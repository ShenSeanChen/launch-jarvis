"""DETERMINISTIC EVAL — the shootout's scoring contract, offline.

The shootout's value is its honesty: check_case is the same deterministic
contract as the live eval tier. These pin it (and the report math) without any
network or model."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "shootout", Path(__file__).resolve().parents[2] / "scripts" / "shootout.py")
shootout = importlib.util.module_from_spec(spec)
sys.modules["shootout"] = shootout
spec.loader.exec_module(shootout)


def calls(*pairs):
    return [{"tool": t, "args": a} for t, a in pairs]


def test_right_tool_and_args_pass():
    case = {"expect_tool": "create_event", "expect_in_args": {"title": "alex"}}
    ok, why = shootout.check_case(case, calls(("create_event", {"title": "Coffee with Alex"})))
    assert ok, why


def test_wrong_tool_fails():
    case = {"expect_tool": "create_event"}
    ok, why = shootout.check_case(case, calls(("save_note", {})))
    assert not ok and "expected create_event" in why


def test_no_tool_case():
    case = {"expect_tool": None}
    assert shootout.check_case(case, [])[0]
    assert not shootout.check_case(case, calls(("save_note", {})))[0]


def test_multi_tool_minimum_enforced():
    """pokemon-team style: right tool fired but the loop barely looped → fail."""
    case = {"expect_tool": "save_note", "expect_in_args": {"content": "pikachu"},
            "expect_min_tool_calls": 3}
    only_one = calls(("save_note", {"content": "Pikachu is the starter"}))
    ok, why = shootout.check_case(case, only_one)
    assert not ok and "wanted >= 3" in why
    full = calls(("search_web", {"query": "kanto team"}),
                 ("save_note", {"content": "Pikachu is the starter"}),
                 ("create_event", {"title": "training"}))
    assert shootout.check_case(case, full)[0]


def test_markdown_report_math():
    results = [{"provider": "kimi", "model": "kimi-k3", "passed": 6, "total": 7,
                "cost_usd": 0.1234, "avg_latency_s": 9.5,
                "cases": [{"tokens_in": 100, "tokens_out": 50, "passed": True}]}]
    table = shootout.markdown(results)
    assert "| kimi:kimi-k3 | 6/7 | $0.1234 | 9.5s | 100/50 |" in table
    assert "re-run" in table  # the reproducibility line is part of the contract


def test_dataset_has_the_demo_beats():
    ids = [c["id"] for c in shootout.DATASET]
    assert "pokemon-team" in ids and "worldcup-final" in ids
