import json

from waku.ops.show_trace import format_events, read_events


def test_format_events_renders_indented_timeline():
    events = [
        {"type": "turn_start", "ts": "2026-07-17T13:00:00Z", "user_message": "Book swim"},
        {
            "type": "gate",
            "ts": "2026-07-17T13:00:01Z",
            "decision": "retrieve",
            "reason": "calendar context",
        },
        {
            "type": "llm",
            "ts": "2026-07-17T13:00:02Z",
            "iteration": 1,
            "stop_reason": "tool_use",
            "usage": {"in": 12, "out": 5},
        },
        {
            "type": "tool",
            "ts": "2026-07-17T13:00:03Z",
            "tool": "create_event",
            "args": {"title": "Swim", "start": "2026-07-18T17:00"},
            "output": "Created Swim.",
        },
        {"type": "turn_end", "ts": "2026-07-17T13:00:04Z", "reply": "Done.", "iterations": 1},
    ]

    lines = format_events(events)

    assert lines == [
        "2026-07-17T13:00:00Z turn",
        "  user: Book swim",
        "2026-07-17T13:00:01Z gate: retrieve - calendar context",
        "2026-07-17T13:00:02Z llm: iteration 1, stop tool_use, tokens 12 in / 5 out",
        "2026-07-17T13:00:03Z tool: create_event",
        '  args: {"start": "2026-07-18T17:00", "title": "Swim"}',
        "  output: Created Swim.",
        "2026-07-17T13:00:04Z reply: Done. (1 iterations)",
    ]


def test_read_events_ignores_blank_lines(tmp_path):
    trace_file = tmp_path / "trace.jsonl"
    trace_file.write_text(
        "\n".join(
            [
                json.dumps({"type": "turn_start", "user_message": "hello"}),
                "",
                json.dumps({"type": "turn_end", "reply": "hi", "iterations": 1}),
            ]
        ),
        encoding="utf-8",
    )

    events = read_events(trace_file)

    assert [event["type"] for event in events] == ["turn_start", "turn_end"]
