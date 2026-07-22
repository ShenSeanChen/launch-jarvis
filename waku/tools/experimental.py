"""Roadmap tools — the whiteboard boxes beyond the flagship task.

One of them is now ALIVE: `delegate_task` (the Sub-Agents box) hands a coding
job to pi (https://github.com/earendil-works/pi) — a minimal open-source coding
agent by Mario Zechner — through its headless print mode (`pi -p "task"`).
The division of labor is the teaching point: Waku is the orchestrator (memory,
working-memory assembly, evals, the human's context) and pi is the specialist
contractor (read/bash/edit/write, pure coding craft). Waku hires; pi codes;
Waku's release gate can then inspect the work. v2 idea: run `pi --mode json`
and stream its per-turn events into the dashboard's Loop tab.

The other three boxes are still SKELETONS on purpose: each shows the *shape* of
a capability and returns an honest "coming soon" (terminal/browser tools need a
real sandbox + safety surface first). Everything here is OFF by default; set
`WAKU_EXPERIMENTAL=1` to register these tools.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from waku.config import Settings
from waku.tools.registry import Tool

PI_INSTALL_HINT = "npm install -g --ignore-scripts @earendil-works/pi-coding-agent"

# Still-skeleton boxes: name → what it will do, and its box on the whiteboard.
PLANNED = [
    {"name": "run_command", "box": "Terminal tool",
     "description": "Run a shell command in a sandbox and read the output — Hermes's 'Terminal' "
                    "tool. Needs a real sandbox + safety surface first."},
    {"name": "browse_web", "box": "Browser tool",
     "description": "Open a page and read/click it — Hermes's 'Browser' tool. (search_web already "
                    "covers read-only web lookups.)"},
    {"name": "schedule_task", "box": "Cron Job",
     "description": "Let the agent schedule its own recurring runs. Today `make brief` + a system "
                    "cron line already does scheduled runs; this would move it in-app."},
]


def make_delegate_tool(settings: Settings) -> Tool:
    """The Sub-Agents box, wired for real: delegate a coding task to pi.

    Same honesty contract as every Waku tool — the return string says exactly
    what happened (done / failed / timed out / pi not installed), short enough
    for the voice gateway to speak. The full pi transcript goes to the outbox.
    """

    def delegate_task(task: str = "", cwd: str = "", timeout_seconds: int = 0) -> str:
        if not task.strip():
            return ("delegate_task needs a 'task' — a plain-English description of the "
                    "coding job, e.g. 'fix the failing test in this repo'.")
        pi_bin = shutil.which("pi")
        if not pi_bin:
            return f"pi isn't installed, so I can't delegate. Install it with: {PI_INSTALL_HINT}"

        from waku.tools import workspace
        if cwd:
            workdir = Path(cwd).expanduser()
            if not workdir.is_dir():
                return f"delegate_task: the working directory '{cwd}' doesn't exist."
            in_workspace = False   # working in the user's own project; don't relocate/auto-run
        else:
            # Repo-less task: land it in a dated, documented workspace folder so
            # the scripts survive and are traceable (not a temp dir), then auto-run.
            workdir = workspace.new_run_folder(settings.model or settings.provider, task)
            in_workspace = True

        timeout = int(timeout_seconds) or int(os.getenv("WAKU_DELEGATE_TIMEOUT", "300"))
        # Run pi on the SAME brain the loop is using, so the sub-agent's coding is
        # this model's coding (that's the point of a per-model comparison). pi
        # natively speaks every provider we pin; fall back to pi's own default if
        # this provider isn't mappable. -a/--no-session = headless; stdin=DEVNULL
        # so pi never blocks on a TTY it doesn't have under the server.
        from waku.ops.coding_eval import PI_PROVIDER, _key_for
        cmd = [pi_bin]
        pi_prov = PI_PROVIDER.get(settings.provider)
        if pi_prov and settings.model:
            cmd += ["--provider", pi_prov, "--model", settings.model]
            key = _key_for(settings.provider)
            if key:
                cmd += ["--api-key", key]
        cmd += ["-p", task, "-a", "--no-session"]
        try:
            result = subprocess.run(cmd, cwd=workdir, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return (f"pi was still working after {timeout}s so I stopped it — try a smaller "
                    f"task, or raise WAKU_DELEGATE_TIMEOUT.")
        except OSError as exc:
            return f"Couldn't launch pi: {exc}"

        # Full pi transcript alongside the work (workspace) or in the outbox.
        transcript = (workdir / "pi-transcript.log") if in_workspace else (
            settings.home / "outbox" / f"delegate-{datetime.now():%Y%m%d-%H%M%S}.log")
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(f"$ {' '.join(cmd[:-4])} -p {task!r}   (cwd: {workdir})\n\n"
                              f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}",
                              encoding="utf-8")

        if result.returncode != 0:
            err = (result.stderr or result.stdout).strip()[-200:] or "no output"
            return f"pi hit an error: {err} (full log: {transcript})"
        summary = result.stdout.strip()[-500:] or "(pi finished but printed nothing)"

        if not in_workspace:
            return f"pi finished the delegated task in {workdir}.\n{summary}\n(full log: {transcript})"

        # Scratch task: document the run (dated MANIFEST) and auto-run the script,
        # feeding the run result back into the loop so the model can react to it.
        files = workspace.created_files(workdir)
        run = workspace.autorun(workdir)
        workspace.write_manifest(workdir, settings.provider, settings.model or "(default)", task, files, run)
        made = ", ".join(p.name for p in files[:6]) or "no files"
        lines = [f"pi finished. Files saved to {workdir} ({made}).", summary]
        if run is not None:
            entry, code, out, secs = run
            verdict = "still running (interactive)" if code is None else ("ran clean" if code == 0 else f"exited {code}")
            lines.append(f"\nAuto-ran {entry}: {verdict} in {secs}s.\n{out[-400:]}")
        return "\n".join(lines)

    return Tool(
        name="delegate_task",
        description=("Delegate a CODING task (fixing tests, multi-file edits, writing "
                     "programs) to pi, a specialist coding agent running locally on this "
                     "machine. Give it a self-contained task and, when the work targets an "
                     "existing project, that project's absolute path as cwd. Use this for "
                     "real programming work instead of describing code in chat."),
        input_schema={
            "type": "object",
            "properties": {
                "task": {"type": "string",
                         "description": "Plain-English description of the coding job, self-contained"},
                "cwd": {"type": "string",
                        "description": "Absolute path of the repo/directory to work in; omit for a scratch sandbox"},
                "timeout_seconds": {"type": "integer",
                                    "description": "Max seconds to let pi work (default 300)"},
            },
            "required": ["task"],
        },
        fn=delegate_task,
    )


def _stub(name: str, description: str, box: str) -> Tool:
    def fn(**kwargs) -> str:
        return (f"'{name}' maps to the '{box}' box on the architecture chart and isn't wired "
                f"in yet — it's on the roadmap (coming soon). Tell the user honestly.")

    return Tool(name=name, description=f"[coming soon] {description}",
                input_schema={"type": "object", "properties": {}}, fn=fn)


def make_tools(settings: Settings) -> list[Tool]:
    """Experimental tools, registered only when WAKU_EXPERIMENTAL=1: the live
    pi delegation plus the remaining skeletons."""
    return [make_delegate_tool(settings)] + [
        _stub(p["name"], p["description"], p["box"]) for p in PLANNED
    ]
