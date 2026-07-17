from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Final

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
TraceEvent = dict[str, JsonValue]

INDENT: Final = "  "


@dataclass(frozen=True, slots=True)
class TraceParseError(Exception):
    path: Path
    line_number: int
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line_number}: {self.detail}"


def read_events(path: Path) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    with path.open(encoding="utf-8") as trace:
        for line_number, line in enumerate(trace, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except JSONDecodeError as exc:
                raise TraceParseError(path, line_number, exc.msg) from exc
            if not isinstance(record, dict):
                raise TraceParseError(path, line_number, "trace line must be a JSON object")
            events.append(record)
    return events


def format_events(events: list[TraceEvent]) -> list[str]:
    lines: list[str] = []
    for event in events:
        lines.extend(_format_event(event))
    return lines


def _format_event(event: TraceEvent) -> list[str]:
    timestamp = _text(event.get("ts"))
    prefix = f"{timestamp} " if timestamp else ""
    event_type = _text(event.get("type"))
    match event_type:
        case "turn_start":
            return [f"{prefix}turn", f"{INDENT}user: {_text(event.get('user_message'))}"]
        case "gate":
            return [f"{prefix}gate: {_text(event.get('decision'))} - {_text(event.get('reason'))}"]
        case "llm":
            return [f"{prefix}llm: {_llm_summary(event)}"]
        case "tool":
            return [
                f"{prefix}tool: {_text(event.get('tool'))}",
                f"{INDENT}args: {_json_summary(event.get('args'))}",
                f"{INDENT}output: {_text(event.get('output'))}",
            ]
        case "turn_end":
            return [
                f"{prefix}reply: {_text(event.get('reply'))} "
                f"({_text(event.get('iterations'))} iterations)"
            ]
        case "consolidation":
            return [f"{prefix}consolidation: {_text(event.get('status'))}"]
        case "wake_scan":
            return [f"{prefix}wake_scan: heard {_text(event.get('heard'))}"]
        case _:
            return [f"{prefix}{event_type or 'event'}: {_json_summary(event)}"]


def _llm_summary(event: TraceEvent) -> str:
    usage = event.get("usage")
    tokens = "0 in / 0 out"
    if isinstance(usage, dict):
        tokens = f"{_text(usage.get('in', 0))} in / {_text(usage.get('out', 0))} out"
    return (
        f"iteration {_text(event.get('iteration'))}, "
        f"stop {_text(event.get('stop_reason'))}, tokens {tokens}"
    )


def _text(value: JsonValue | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _json_summary(value: JsonValue | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _default_trace_path() -> Path:
    traces = Path.home() / ".waku" / "traces"
    trace_files = sorted(traces.glob("*.jsonl"))
    if trace_files:
        return trace_files[-1]
    return traces / "missing.jsonl"


def main(argv: list[str] | None = None) -> int:
    from rich.console import Console

    parser = argparse.ArgumentParser(description="Render a Waku JSONL trace as a timeline.")
    parser.add_argument("trace", nargs="?", type=Path, default=_default_trace_path())
    args = parser.parse_args(argv)
    console = Console()
    try:
        events = read_events(args.trace)
    except FileNotFoundError:
        console.print(f"trace file not found: {args.trace}", style="red")
        return 1
    except TraceParseError as exc:
        console.print(str(exc), style="red")
        return 1
    for line in format_events(events):
        console.print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
