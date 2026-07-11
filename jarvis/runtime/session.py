"""Ephemeral Agent Run — assembles working memory for each turn.

The inner box on the whiteboard: everything here is rebuilt per run and thrown
away. What persists lives in jarvis/memory. Working memory =

    system prompt (SOUL.md)            ← who Jarvis is
  + durable facts & episodes           ← what Jarvis remembers (gated!)
  + current chat history               ← this conversation
  + the user's new message
"""

from __future__ import annotations


from jarvis.config import Settings

DEFAULT_SOUL = """\
You are Jarvis, a personal assistant running locally on your user's laptop.
You are concise, warm, and proactive. You remember what your user tells you.

Rules:
- When the user wants to schedule something, use create_event. Resolve relative
  dates and times ("next Tuesday", "in 30 minutes") to ISO timestamps yourself;
  the current date and time are given below — trust them, never ask the user
  what time it is.
- When the user shares something durable about a person, project, or preference,
  use save_note to remember it.
- When asked to message someone, use send_message (it drafts to a local outbox).
- If memory context is provided below, trust it — it came from your own store.
- Call each tool at most once per request. Your history shows [tools used: ...]
  lines for past turns — if a tool already ran, do NOT run it again; answer
  from that record instead.
- Be honest about where things live. Every tool's output states exactly where
  its artifact landed (local calendar file, Apple Calendar, memory database at
  .jarvis/state.db) — relay that truthfully, and never claim something synced
  anywhere the tool output doesn't say.
- You can manage your own memory: use manage_memory to correct or forget facts,
  update_soul to save a standing preference the user gives you, and create_skill
  to save a repeatable workflow the user teaches you (only after they say yes).
"""


def load_soul(settings: Settings) -> str:
    """SOUL.md is the editable persona file, created on first run. Changing it
    changes who your Jarvis is — that's procedural memory at its simplest."""
    soul_path = settings.home / "SOUL.md"
    if not soul_path.exists():
        soul_path.write_text(DEFAULT_SOUL)
    return soul_path.read_text()


class Session:
    """Holds one conversation: the chat history plus the recipe for the
    system prompt. One Session per gateway connection."""

    def __init__(self, settings: Settings, memory=None, session_id: str = "default"):
        self.settings = settings
        self.memory = memory  # jarvis.memory.Memory (None until Phase-2 wiring)
        self.session_id = session_id
        self.history: list[dict] = []

    def build_system(self, user_message: str, notify=None) -> str:
        from datetime import datetime

        # The agent runs on your laptop, so it should know your laptop's clock.
        # Local time WITH the timezone name — enough to resolve "in 30 minutes".
        now = datetime.now().astimezone()
        parts = [load_soul(self.settings),
                 f"\nRight now it is {now:%A, %Y-%m-%d %H:%M} ({now:%Z}, UTC{now:%z})."]

        if self.memory is not None:
            # Hero moment #1: a cheap judge decides IF we retrieve at all —
            # default-on retrieval is slow and biases answers (see
            # memory/retrieval_gate.py for the why).
            retrieved = self.memory.gated_retrieve(user_message, notify=notify)
            if retrieved:
                parts.append("\nRelevant memory:\n" + retrieved)
            skills = self.memory.matching_skills(user_message)
            if skills:
                parts.append("\nRelevant skill instructions:\n" + skills)

        return "\n".join(parts)

    def add_exchange(self, user_message: str, reply: str, tool_calls: list | None = None) -> None:
        """Record the turn in history (working memory) and, if memory is wired,
        in the chat log (so consolidation can distill it later).

        Tool activity is folded into the assistant's history entry as a compact
        [tools used: ...] line. Without it, the model forgets it already acted
        and happily re-runs the same tool next turn (the triple-booked-meeting
        bug from the first live test)."""
        record = reply
        if tool_calls:
            summary = "; ".join(f"{c['tool']}({c['args']}) -> {c['output']}" for c in tool_calls)
            record = f"{reply}\n[tools used: {summary}]"
        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": record})
        if self.memory is not None:
            self.memory.log_chat(user_message, record, session_id=self.session_id)

    # ---- session lifecycle (the "New chat" / history feature)
    # A session is just a tag on chat_log rows. Starting a new one clears working
    # memory; switching reloads a past conversation's history so replies have
    # context. Consolidation still reads ALL unconsolidated rows regardless.
    def start_new(self, session_id: str) -> None:
        self.session_id = session_id
        self.history = []

    def switch(self, session_id: str) -> None:
        self.session_id = session_id
        self.history = []
        if self.memory is None:
            return
        for user_msg, reply in self.memory.session_history(session_id):
            self.history.append({"role": "user", "content": user_msg})
            self.history.append({"role": "assistant", "content": reply})
