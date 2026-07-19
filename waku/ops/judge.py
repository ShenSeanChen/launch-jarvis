"""K3-as-referee quality scoring for the Compare arena.

Completion (waku.ops.scoring) is deterministic — did the right tool fire. Quality
is the other half: *how good was the answer*, for the open-ended part a checklist
can't see. There's no single right answer, so we do what the market does for that
axis (MT-Bench / Chatbot-Arena style): an LLM grades the transcript against a
rubric, 0-10 + a one-line reason.

The referee is **kimi-k3** by default — for the sponsor video the hook is that
K3 grades the whole field, itself included, out loud. That's a bias we surface,
not hide: for unbiased internal numbers, point WAKU_JUDGE_* at a model that isn't
racing. The judge speaks the anthropic wire (kimi's endpoint is anthropic-compat),
so it reuses Waku's own client — no extra dependency.
"""

from __future__ import annotations

import json
import os
import time

from waku.config import Settings, load_settings
from waku.loop.models import get_client

JUDGE_PROVIDER = os.getenv("WAKU_JUDGE_PROVIDER", "kimi")
JUDGE_MODEL = os.getenv("WAKU_JUDGE_MODEL", "kimi-k3")

_RUBRIC = """You are a strict, fair judge scoring an AI assistant's reply.

The user asked:
{task}

The assistant replied:
{reply}

Score how well the reply serves the user's request on a 0-10 scale:
- 9-10: fully addresses the request, correct, concise, honest about any limits.
- 5-8: mostly addresses it, minor gaps, padding, or small errors.
- 1-4: partial, vague, or partly wrong.
- 0: ignores the request, hallucinates, or claims actions it didn't take.

Reply with ONLY a JSON object, no prose:
{{"score": <int 0-10>, "reason": "<one short sentence>"}}"""


def judge_reply(task: str, reply: str, provider: str | None = None,
                model: str | None = None) -> dict | None:
    """Grade one reply. Returns {"score": 0-10, "reason": str, "judge": model} or
    None if there's nothing to grade or the judge is unreachable (a judge hiccup
    must never fail a race)."""
    if not (reply or "").strip():
        return None
    provider = provider or JUDGE_PROVIDER
    model = model or JUDGE_MODEL
    prompt = _RUBRIC.format(task=task[:2000], reply=reply[:4000])
    # Races judge every column at once, so the judge endpoint sees a burst of
    # concurrent calls and may 429. One retry turns most of those transient
    # failures into a score; a persistent failure still degrades to None.
    for attempt in range(2):
        try:
            settings = Settings(provider=provider, model=model, small_model="",
                                home=load_settings().home, apple_calendar=False)
            client = get_client(settings)   # fills the provider default id
            resp = client.messages.create(
                model=settings.model, max_tokens=300,
                messages=[{"role": "user", "content": prompt}])
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            obj = json.loads(text[text.index("{"): text.rindex("}") + 1])
            score = max(0, min(10, int(obj["score"])))
            return {"score": score, "reason": str(obj.get("reason", ""))[:200],
                    "judge": settings.model}
        except Exception:
            if attempt == 0:
                time.sleep(1.5)   # brief backoff, then one more try
    return None
