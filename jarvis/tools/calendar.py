"""create_event — the flagship tool. "Did the meeting trigger?" is THE
deterministic eval: it either wrote the right row or it didn't.

Where events land:
  always      state.db (the eval asserts here) + calendar.ics (importable file)
  opt-in      Apple Calendar, in a dedicated "Jarvis" calendar, via AppleScript —
              set JARVIS_APPLE_CALENDAR=1. First use makes macOS ask permission
              for your terminal to control Calendar; approve once.

The tool's return string always says exactly where the event went — the model
relays it, so Jarvis never over-claims what happened.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from jarvis.tools.registry import Tool

APPLE_CALENDAR_NAME = "Jarvis"


def _write_ics(home: Path, title: str, start: str, end: str, attendees: str) -> None:
    """Append a minimal VEVENT. ISO timestamps like 2026-07-14T09:00 become
    ICS's compact 20260714T090000 form."""
    ics_path = home / "calendar.ics"

    def dt(s: str) -> str:
        return s.replace("-", "").replace(":", "") + ("00" if len(s) == 16 else "")

    event = (
        "BEGIN:VEVENT\n"
        f"SUMMARY:{title}\n"
        f"DTSTART:{dt(start)}\n"
        f"DTEND:{dt(end)}\n"
        f"DESCRIPTION:attendees: {attendees}\n"
        "END:VEVENT\n"
    )
    if ics_path.exists():
        body = ics_path.read_text().replace("END:VCALENDAR\n", "")
    else:
        body = "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//launch-jarvis//EN\n"
    ics_path.write_text(body + event + "END:VCALENDAR\n")


def _applescript_date(var: str, iso: str) -> str:
    """Build an AppleScript date from ISO parts — immune to system locale
    (never feed AppleScript a formatted date string; parsing is locale-bound)."""
    d = datetime.fromisoformat(iso)
    # set day to 1 BEFORE month/year: prevents the classic AppleScript overflow
    # (if today is the 31st, setting month to a 30-day month rolls into next month)
    return (
        f"set {var} to current date\nset day of {var} to 1\n"
        f"set year of {var} to {d.year}\nset month of {var} to {d.month}\n"
        f"set day of {var} to {d.day}\nset hours of {var} to {d.hour}\n"
        f"set minutes of {var} to {d.minute}\nset seconds of {var} to 0\n"
    )


def sync_to_apple_calendar(title: str, start: str, end: str, notes: str = "") -> str:
    """Create the event in Calendar.app under the 'Jarvis' calendar (created on
    first use). Returns a short human-readable outcome for the tool output."""
    if sys.platform != "darwin":
        return "Apple Calendar sync skipped (not macOS)."
    safe_title = title.replace("\\", "").replace('"', "'")
    safe_notes = notes.replace("\\", "").replace('"', "'")
    script = (
        _applescript_date("startDate", start)
        + _applescript_date("endDate", end)
        + f'''
tell application "Calendar"
  if not (exists calendar "{APPLE_CALENDAR_NAME}") then
    make new calendar with properties {{name:"{APPLE_CALENDAR_NAME}"}}
  end if
  tell calendar "{APPLE_CALENDAR_NAME}"
    make new event with properties {{summary:"{safe_title}", start date:startDate, end date:endDate, description:"{safe_notes}"}}
  end tell
end tell'''
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Apple Calendar sync FAILED ({exc}) — the event is still in the local calendar."
    if result.returncode != 0:
        detail = (result.stderr or "").strip()[:120]
        return (
            f"Apple Calendar sync FAILED ({detail}) — the event is still in the local "
            "calendar. If this is a permissions error, allow your terminal to control "
            "Calendar in System Settings > Privacy & Security > Automation."
        )
    return f"Also added to Apple Calendar (calendar '{APPLE_CALENDAR_NAME}')."


def make_tool(conn: sqlite3.Connection, home: Path, apple_calendar: bool = False) -> Tool:
    def create_event(title: str, start: str, end: str = "", attendees: str = "", notes: str = "") -> str:
        if not end:
            # default: one hour
            from datetime import timedelta
            end = (datetime.fromisoformat(start) + timedelta(hours=1)).isoformat(timespec="minutes")

        # idempotence guard: same title+start = same event. A confused model
        # (or an impatient user) must not be able to triple-book a meeting.
        start = start[:16]  # normalize 2026-07-11T17:00:00 → 2026-07-11T17:00
        end = end[:16]
        existing = conn.execute(
            "SELECT id FROM calendar_events WHERE title = ? AND start = ?", (title, start)
        ).fetchone()
        if existing:
            return f"Event '{title}' at {start} already exists (not duplicated)."

        conn.execute(
            'INSERT INTO calendar_events (title, start, "end", attendees, notes) VALUES (?,?,?,?,?)',
            (title, start, end, attendees, notes),
        )
        conn.commit()
        _write_ics(home, title, start, end, attendees)

        where = f"Saved to the local calendar ({home / 'calendar.ics'})."
        if apple_calendar:
            where += " " + sync_to_apple_calendar(title, start, end, notes)
        else:
            where += (
                " Not synced to any calendar app (enable with JARVIS_APPLE_CALENDAR=1, "
                f"or import manually: open {home / 'calendar.ics'})."
            )
        return (
            f"Event created: '{title}' {start} → {end}"
            + (f" with {attendees}" if attendees else "")
            + f". {where}"
        )

    return Tool(
        name="create_event",
        description=(
            "Create a calendar event on the user's local calendar. Use whenever the user "
            "wants to schedule, book, or plan something at a specific time."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short event title"},
                "start": {"type": "string", "description": "Start time, ISO 8601, e.g. 2026-07-14T09:00"},
                "end": {"type": "string", "description": "End time, ISO 8601. Defaults to start + 1h."},
                "attendees": {"type": "string", "description": "Comma-separated names/emails"},
                "notes": {"type": "string", "description": "Optional context for the event"},
            },
            "required": ["title", "start"],
        },
        fn=create_event,
    )
