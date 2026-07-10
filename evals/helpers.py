"""Shared eval plumbing: a scripted fake LLM client for offline tests, and a
real-Jarvis factory for live ones."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

HAS_KEY = bool(os.getenv("ANTHROPIC_API_KEY"))


def text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def tool_block(name: str, args: dict, call_id: str = "tu_1"):
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input=args)


def response(blocks, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=0, output_tokens=0),
        content=blocks,
    )


class ScriptedClient:
    """Plays back a fixed list of responses — the 'model' for offline tests."""

    def __init__(self, script: list):
        self._script = list(script)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        return self._script.pop(0)


def make_jarvis(home: Path, client=None, **settings_overrides):
    """Build a Jarvis with an isolated home dir; optionally swap in a fake client."""
    from jarvis.app import Jarvis
    from jarvis.config import Settings

    # evals must NEVER touch the real Apple Calendar, whatever .env says
    settings_overrides.setdefault("apple_calendar", False)
    settings = Settings(home=home, **settings_overrides)
    if client is not None and not settings.api_key:
        settings.api_key = "offline"  # never read the real key for scripted runs
    return Jarvis(settings=settings, client=client)
