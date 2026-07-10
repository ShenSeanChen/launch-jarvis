"""Model access — five providers, one loop, zero framework.

The loop speaks one dialect: Anthropic's Messages shape (system/messages/tools
in, content blocks out). Providers plug in two ways:

  anthropic wire format (native)     → Anthropic, Kimi/Moonshot, GLM/Z.ai
  openai wire format (thin adapter)  → OpenAI, Google Gemini

Pick with JARVIS_PROVIDER=anthropic|openai|gemini|kimi|glm and set that
provider's API key in .env. Override the model ids with JARVIS_MODEL /
JARVIS_SMALL_MODEL if the defaults below age out — they're just strings.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from types import SimpleNamespace

from jarvis.config import Settings


@dataclass(frozen=True)
class Provider:
    kind: str        # 'anthropic' or 'openai' — the wire format
    key_env: str     # which env var holds the key
    base_url: str | None
    model: str       # default main model (the loop)
    small_model: str  # default cheap model (retrieval gate + consolidation)


PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider("anthropic", "ANTHROPIC_API_KEY", None,
                          "claude-sonnet-5", "claude-haiku-4-5-20251001"),
    "openai":    Provider("openai", "OPENAI_API_KEY", None,
                          "gpt-5.6", "gpt-5.6-luna"),
    "gemini":    Provider("openai", "GEMINI_API_KEY",
                          "https://generativelanguage.googleapis.com/v1beta/openai/",
                          "gemini-3.5-flash", "gemini-3.1-flash-lite"),
    "kimi":      Provider("anthropic", "MOONSHOT_API_KEY", "https://api.moonshot.ai/anthropic",
                          "kimi-k2.7", "kimi-k2.7"),
    "glm":       Provider("anthropic", "ZHIPU_API_KEY", "https://api.z.ai/api/anthropic",
                          "glm-5.2", "glm-5-turbo"),
}


def get_client(settings: Settings):
    """Build the client for settings.provider and fill in default model ids.
    Returns anything with .messages.create(...) in the Anthropic shape."""
    provider = PROVIDERS.get(settings.provider)
    if provider is None:
        raise SystemExit(f"Unknown JARVIS_PROVIDER '{settings.provider}'. "
                         f"Pick one of: {', '.join(PROVIDERS)}")

    api_key = settings.api_key or os.getenv(provider.key_env, "")
    if not api_key:
        raise SystemExit(
            f"No API key for provider '{settings.provider}'. "
            f"Set {provider.key_env} in .env (see .env.example)."
        )

    settings.model = settings.model or provider.model
    settings.small_model = settings.small_model or provider.small_model
    base_url = settings.base_url or provider.base_url

    if provider.kind == "anthropic":
        import anthropic

        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        return anthropic.Anthropic(**kwargs)
    return OpenAICompatClient(api_key=api_key, base_url=base_url)


class OpenAICompatClient:
    """Speaks the Anthropic Messages shape the loop expects, backed by an
    OpenAI-style chat.completions API. ~60 lines is the entire difference
    between the two wire formats — worth reading once.
    """

    def __init__(self, api_key: str, base_url: str | None = None):
        import openai

        self._client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, *, model, messages, max_tokens, system=None, tools=None):
        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        for message in messages:
            content = message["content"]
            if isinstance(content, str):
                oai_messages.append({"role": message["role"], "content": content})
            elif message["role"] == "assistant":
                # anthropic content blocks → assistant text + tool_calls
                text = "".join(b.text for b in content if getattr(b, "type", "") == "text")
                calls = [
                    {"id": b.id, "type": "function",
                     "function": {"name": b.name, "arguments": json.dumps(b.input)}}
                    for b in content if getattr(b, "type", "") == "tool_use"
                ]
                entry: dict = {"role": "assistant", "content": text or None}
                if calls:
                    entry["tool_calls"] = calls
                oai_messages.append(entry)
            else:
                # anthropic tool_result blocks → one 'tool' message each
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        oai_messages.append({
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": block["content"],
                        })

        kwargs: dict = {"model": model, "messages": oai_messages,
                        "max_completion_tokens": max_tokens}
        if tools:
            kwargs["tools"] = [
                {"type": "function",
                 "function": {"name": t["name"], "description": t["description"],
                              "parameters": t["input_schema"]}}
                for t in tools
            ]
        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception:
            # older OpenAI-compatible endpoints only know max_tokens
            kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
            response = self._client.chat.completions.create(**kwargs)

        choice = response.choices[0].message
        blocks = []
        if choice.content:
            blocks.append(SimpleNamespace(type="text", text=choice.content))
        for call in choice.tool_calls or []:
            blocks.append(SimpleNamespace(
                type="tool_use", id=call.id, name=call.function.name,
                input=json.loads(call.function.arguments or "{}"),
            ))
        usage = getattr(response, "usage", None)
        return SimpleNamespace(
            stop_reason="tool_use" if choice.tool_calls else "end_turn",
            usage=SimpleNamespace(
                input_tokens=getattr(usage, "prompt_tokens", 0),
                output_tokens=getattr(usage, "completion_tokens", 0),
            ),
            content=blocks,
        )
