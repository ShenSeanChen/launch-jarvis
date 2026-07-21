"""DETERMINISTIC EVAL — delegate_task hands coding work to pi, honestly.

Hermetic: pi is NEVER actually spawned. subprocess.run and shutil.which are
monkeypatched, so these run everywhere (CI included) with no node, no network.
What's pinned: pi runs headless on the loop's OWN model, the outbox paper trail,
and the honest strings for every failure mode (not installed / timeout / bad cwd)."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

from evals.helpers import ScriptedClient, make_waku, response, text_block, tool_block
from waku.config import Settings
from waku.tools import experimental


import pytest


@pytest.fixture(autouse=True)
def _tmp_workspace(tmp_path, monkeypatch):
    """Never let a delegate test write into the repo's ./waku_workspace."""
    monkeypatch.setenv("WAKU_WORKSPACE", str(tmp_path / "ws"))


def fake_run(record, stdout="Done. Created hello.py.", returncode=0):
    def run(argv, **kwargs):
        record["argv"] = argv
        record["kwargs"] = kwargs
        return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)
    return run


def test_delegate_task_invokes_pi_print_mode(tmp_path, monkeypatch):
    """Full-loop wiring: the model calls delegate_task → pi fires → a scratch task
    lands in the dated workspace with a MANIFEST + pi transcript, and pi's answer
    comes back in the tool result."""
    record = {}
    monkeypatch.setenv("WAKU_EXPERIMENTAL", "1")
    monkeypatch.setenv("WAKU_WORKSPACE", str(tmp_path / "ws"))   # keep it out of the repo
    monkeypatch.setattr(experimental.shutil, "which", lambda _: "/fake/bin/pi")
    monkeypatch.setattr(experimental.subprocess, "run", fake_run(record))

    gate = response([text_block('{"retrieve": false, "query": "", "reason": "test"}')])
    script = [gate] + [
        response([tool_block("delegate_task", {"task": "create hello.py"})], "tool_use"),
        response([text_block("pi handled it.")]),
    ]
    app = make_waku(tmp_path / "home", client=ScriptedClient(script))
    result = app.respond("have pi create hello.py")

    assert [c["tool"] for c in result.tool_calls] == ["delegate_task"]
    argv = record["argv"]
    assert argv[0] == "/fake/bin/pi"
    assert "-p" in argv and "create hello.py" in argv
    assert "-a" in argv and "--no-session" in argv          # headless, non-interactive
    output = result.tool_calls[0]["output"]
    assert "Done. Created hello.py." in output and "saved to" in output.lower()
    # the run landed in the dated workspace with a manifest + transcript
    manifests = list((tmp_path / "ws").rglob("MANIFEST.md"))
    assert len(manifests) == 1 and "create hello.py" in manifests[0].read_text()
    assert list((tmp_path / "ws").rglob("pi-transcript.log"))


def test_delegate_runs_pi_on_the_calling_model(tmp_path, monkeypatch):
    """The sub-agent codes with the loop's OWN brain — delegate_task passes this
    model's provider/model/key to pi, so a per-model race actually compares
    models (kimi's pi uses kimi, opus's pi uses opus)."""
    record = {}
    monkeypatch.setattr(experimental.shutil, "which", lambda _: "/fake/bin/pi")
    monkeypatch.setattr(experimental.subprocess, "run", fake_run(record))
    monkeypatch.setenv("MOONSHOT_API_KEY", "k")
    tool = experimental.make_delegate_tool(Settings(home=tmp_path, provider="kimi", model="kimi-k3"))
    tool.fn(task="write fizzbuzz")
    argv = record["argv"]
    assert "--provider" in argv and "moonshotai" in argv    # kimi -> pi's moonshotai
    assert "--model" in argv and "kimi-k3" in argv
    assert "--api-key" in argv


def test_delegate_without_pi_returns_install_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(experimental.shutil, "which", lambda _: None)
    tool = experimental.make_delegate_tool(Settings(home=tmp_path))
    out = tool.fn(task="anything")
    assert experimental.PI_INSTALL_HINT in out
    assert "isn't installed" in out


def test_delegate_timeout_is_honest(tmp_path, monkeypatch):
    monkeypatch.setattr(experimental.shutil, "which", lambda _: "/fake/bin/pi")

    def run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 300))

    monkeypatch.setattr(experimental.subprocess, "run", run)
    tool = experimental.make_delegate_tool(Settings(home=tmp_path))
    out = tool.fn(task="huge refactor", timeout_seconds=7)
    assert "7s" in out and "WAKU_DELEGATE_TIMEOUT" in out


def test_delegate_rejects_missing_cwd_and_empty_task(tmp_path, monkeypatch):
    monkeypatch.setattr(experimental.shutil, "which", lambda _: "/fake/bin/pi")
    tool = experimental.make_delegate_tool(Settings(home=tmp_path))
    assert "doesn't exist" in tool.fn(task="fix tests", cwd=str(tmp_path / "nope"))
    assert "needs a 'task'" in tool.fn()   # empty model call → recovery text, no raise


def test_delegate_failure_surfaces_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr(experimental.shutil, "which", lambda _: "/fake/bin/pi")

    def run(argv, **kwargs):
        return SimpleNamespace(stdout="", stderr="No API key found", returncode=1)

    monkeypatch.setattr(experimental.subprocess, "run", run)
    tool = experimental.make_delegate_tool(Settings(home=tmp_path))
    out = tool.fn(task="anything")
    assert "pi hit an error" in out and "No API key found" in out


def test_experimental_flag_gates_registration(tmp_path, monkeypatch):
    """The demo depends on this: flag off → no delegate_task; flag on → present."""
    monkeypatch.delenv("WAKU_EXPERIMENTAL", raising=False)
    app_off = make_waku(tmp_path / "off", client=ScriptedClient([]))
    assert "delegate_task" not in app_off.tools._tools

    monkeypatch.setenv("WAKU_EXPERIMENTAL", "1")
    app_on = make_waku(tmp_path / "on", client=ScriptedClient([]))
    assert "delegate_task" in app_on.tools._tools
    assert "run_command" in app_on.tools._tools   # skeletons still registered
