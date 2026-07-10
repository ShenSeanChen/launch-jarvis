"""Flagship-task tools only (see brief §9: no scope creep)."""

from __future__ import annotations

import sqlite3

from jarvis.config import Settings
from jarvis.tools import calendar, messages, notes
from jarvis.tools.registry import ToolRegistry


def build_registry(conn: sqlite3.Connection, settings: Settings) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(calendar.make_tool(conn, settings.home, apple_calendar=settings.apple_calendar))
    registry.register(notes.make_tool(conn))
    registry.register(messages.make_tool(settings.home))
    return registry
