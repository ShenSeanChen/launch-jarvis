"""Dashboard — every pillar on one local page. Zero new dependencies.

    make dashboard        # → http://localhost:7777

One stdlib HTTP server reading the files Jarvis already writes:
  loop + harness   traces/*.jsonl   (turns, gate decisions, tool calls, tokens)
  memory           state.db         (facts, episodes, chat log, consolidation)
  tools            state.db + calendar.ics + outbox/
  eval             eval_report.json (written by `make gate`)

The overview mirrors the architecture diagram — every box is clickable and
opens that section's live data. The Chat tab is a real gateway: type a message
and watch the same harness (gate, loop, tools, memory) that the CLI/voice/
telegram gateways drive — the pipeline lights up in the browser as it runs.
Bound to 127.0.0.1 only. For deep trace waterfalls use Phoenix (`make trace`).
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jarvis.config import load_settings
from jarvis.db import connect

PORT = 7777

# One shared agent for the browser gateway. Built lazily (first chat), reused
# across the threaded server's workers via a cross-thread connection + a lock
# so chats run one at a time — correct for a single-user local tool.
_agent = None
_agent_lock = threading.Lock()


def _get_agent():
    global _agent
    if _agent is None:
        from jarvis.app import Jarvis

        settings = load_settings()
        settings.ensure_home()
        conn = connect(settings.home, check_same_thread=False)
        _agent = Jarvis(settings=settings, conn=conn)
    return _agent


def chat(message: str) -> dict:
    """Run one real turn through the harness and return the structured result —
    gate decision, tool calls, reply, latency — so the browser can render the
    pipeline as it happened. Writes traces + memory like any other gateway."""
    events: list[dict] = []
    with _agent_lock:
        agent = _get_agent()
        start = datetime.now(timezone.utc)
        result = agent.respond(message, observer=lambda kind, ev: events.append({"kind": kind, **ev}))
        latency_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)

    gate = next((e for e in events if e["kind"] == "gate"), None)
    cons = next((e for e in events if e["kind"] == "consolidation"), None)
    return {
        "reply": result.reply,
        "gate": {"decision": gate["decision"], "reason": gate.get("reason")} if gate else None,
        "tools": [
            {"tool": c["tool"], "args": c["args"], "output": c["output"],
             "status": _tool_status(c["output"]), "summary": (c["output"] or "").split(". ")[0][:120]}
            for c in result.tool_calls
        ],
        "consolidation": {"new_facts": cons["new_facts"]} if cons else None,
        "iterations": result.iterations,
        "latency_ms": latency_ms,
    }

# Rough $/million tokens (in, out) for a dollar ESTIMATE — the number humans
# actually feel. Keyed by provider; deliberately approximate and labelled "est".
PRICING = {
    "anthropic": (3.0, 15.0), "openai": (2.5, 15.0), "gemini": (0.3, 2.5),
    "kimi": (0.6, 2.5), "glm": (0.6, 2.2),
}


def _parse_ts(ts: str):
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _tool_status(output: str) -> str:
    """Classify a tool result for the UI: ok / warn / error — from the output
    string alone (tools already report honestly, so trust their words)."""
    low = (output or "").lower()
    if "failed" in low or "timed out" in low or low.startswith("error"):
        return "error"
    if "already exists" in low or "not synced" in low or "skipped" in low:
        return "warn"
    return "ok"


def collect() -> dict:
    """Everything the page shows, in one JSON blob."""
    settings = load_settings()
    settings.ensure_home()
    home = settings.home
    conn = connect(home)

    def rows(sql: str) -> list[dict]:
        return [dict(r) for r in conn.execute(sql).fetchall()]

    # --- traces → turns (group events between turn_start and turn_end)
    events = []
    trace_files = sorted((home / "traces").glob("*.jsonl"))
    for path in trace_files:
        for line in path.read_text().splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    turns, current, wake_scans = [], None, []
    for ev in events:
        kind = ev.get("type")
        if kind == "turn_start":
            current = {"user_message": ev.get("user_message"), "ts": ev.get("ts"),
                       "gate": None, "llm_calls": [], "tools": [], "reply": None}
        elif kind == "wake_scan":
            wake_scans.append(ev)
        elif current is not None:
            if kind == "gate":
                current["gate"] = ev
            elif kind == "llm":
                current["llm_calls"].append(ev)
            elif kind == "tool":
                current["tools"].append(ev)
            elif kind == "consolidation":
                current["consolidation"] = ev
            elif kind == "turn_end":
                current["reply"] = ev.get("reply")
                current["iterations"] = ev.get("iterations")
                turns.append(current)
                current = None
    if current is not None:  # a turn that never ended = the smoking gun for hangs
        current["reply"] = "TURN NEVER FINISHED — check for a hang after this point"
        current["unfinished"] = True
        turns.append(current)

    # --- derive per-turn latency + dollar cost (the ops numbers humans feel)
    price_in, price_out = PRICING.get(settings.provider, (3.0, 15.0))
    for t in turns:
        start, end = _parse_ts(t["ts"]), None
        last = t["llm_calls"][-1]["ts"] if t["llm_calls"] else None
        end = _parse_ts(last)
        t["latency_ms"] = int((end - start).total_seconds() * 1000) if start and end else None
        tin = sum(c.get("usage", {}).get("in", 0) for c in t["llm_calls"])
        tout = sum(c.get("usage", {}).get("out", 0) for c in t["llm_calls"])
        t["cost"] = tin / 1e6 * price_in + tout / 1e6 * price_out
        for x in t["tools"]:
            x["status"] = _tool_status(x.get("output", ""))
            x["summary"] = (x.get("output", "") or "").split(". ")[0][:120]

    latencies = sorted(t["latency_ms"] for t in turns if t["latency_ms"] is not None)
    total_cost = sum(t["cost"] for t in turns)

    def pct(p: float) -> int:
        return latencies[min(len(latencies) - 1, int(len(latencies) * p))] if latencies else 0

    from jarvis.memory.procedural.loader import SkillLoader
    from jarvis.memory import REPO_SKILLS

    skills = [{"name": s.name, "description": s.description, "body": s.body,
               "path": str(s.path),
               # relative path (for reveal) + whether it lives in the editable home dir
               "rel": _rel_to_home(s.path, home),
               "editable": str((home / "skills").resolve()) in str(s.path.resolve())}
              for s in SkillLoader([REPO_SKILLS, home / "skills"]).skills]

    eval_report = None
    report_path = home / "eval_report.json"
    if report_path.exists():
        eval_report = json.loads(report_path.read_text())

    eval_history = []
    hist_path = home / "eval_runs.jsonl"
    if hist_path.exists():
        for line in hist_path.read_text().splitlines()[-20:]:
            try:
                eval_history.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    eval_history.reverse()

    outbox = [{"name": p.name, "text": p.read_text()[:400]}
              for p in sorted((home / "outbox").glob("*.txt"), reverse=True)[:20]]

    # --- state.db introspection: the actual SQLite tables, so the persistence
    # layer is visible (not just its contents). Table names are hard-coded, so
    # the f-string SQL is safe.
    def table_info(name):
        info = conn.execute(f"PRAGMA table_info({name})").fetchall()
        cols = [r["name"] for r in info]
        types = {r["name"]: r["type"] for r in info}
        count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        # up to 200 newest rows so each table has its own scrollable tab
        sample = [dict(r) for r in conn.execute(f"SELECT * FROM {name} ORDER BY rowid DESC LIMIT 200").fetchall()]
        return {"name": name, "columns": cols, "types": types, "count": count, "sample": sample}

    db_path = home / "state.db"
    all_tables = [r["name"] for r in
                  conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
    db_info = {
        "path": str(db_path.resolve()),
        "size": db_path.stat().st_size if db_path.exists() else 0,
        "tables": [table_info(n) for n in ("calendar_events", "facts", "episodes", "chat_log")],
        "fts": [t for t in all_tables if t.endswith("_fts")],
        "all_tables": all_tables,
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "home": str(home.resolve()),
        "provider": settings.provider,
        "model": settings.model or "(provider default)",
        "stats": {
            "turns": len(turns),
            "tool_calls": sum(len(t["tools"]) for t in turns),
            "tool_errors": sum(1 for t in turns for x in t["tools"] if x["status"] == "error"),
            "gate_skips": sum(1 for t in turns if t["gate"] and t["gate"].get("decision") == "skip"),
            "gate_retrieves": sum(1 for t in turns if t["gate"] and t["gate"].get("decision") == "retrieve"),
            "tokens_in": sum(c.get("usage", {}).get("in", 0) for t in turns for c in t["llm_calls"]),
            "tokens_out": sum(c.get("usage", {}).get("out", 0) for t in turns for c in t["llm_calls"]),
            "cost": round(total_cost, 4),
            "latency_avg": int(sum(latencies) / len(latencies)) if latencies else 0,
            "latency_p95": pct(0.95),
            "trace_files": len(trace_files),
        },
        "turns": turns[::-1][:50],
        "wake_scans": wake_scans[::-1][:25],
        # last raw trace lines, so Ops shows traces inline (no folder needed)
        "trace_tail": [{"type": e.get("type"), "ts": e.get("ts"),
                        "detail": (e.get("user_message") or e.get("decision") or e.get("tool")
                                   or e.get("reply") or "")}
                       for e in events[-18:]][::-1],
        "trace_file": (trace_files[-1].name if trace_files else None),
        "facts": rows("SELECT id, subject, content, source, created_at FROM facts ORDER BY id DESC"),
        "episodes": rows("SELECT id, happened_at, summary FROM episodes ORDER BY happened_at DESC"),
        "soul": (home / "SOUL.md").read_text() if (home / "SOUL.md").exists() else "",
        "chat_pending": conn.execute("SELECT COUNT(*) FROM chat_log WHERE consolidated=0").fetchone()[0],
        "chat_log": rows("SELECT role, content, consolidated, created_at FROM chat_log ORDER BY id DESC LIMIT 60")[::-1],
        "sessions": session_list(conn),
        "current_session": (_agent.session.session_id if _agent is not None else "default"),
        "consolidate_every": settings.consolidate_every,
        "calendar": rows('SELECT title, start, "end", attendees, created_at FROM calendar_events ORDER BY start'),
        "outbox": outbox,
        "skills": skills,
        "eval_report": eval_report,
        "eval_history": eval_history,
        "db": db_info,
        "settings": settings_info(),
        "tools": tools_info(),
    }


def _rel_to_home(path, home) -> str:
    """Path relative to JARVIS_HOME if it lives there, else the repo-relative
    'skills/...' path — either way something reveal_path can open."""
    try:
        return str(path.resolve().relative_to(home.resolve()))
    except ValueError:
        return str(path)


def session_list(conn) -> list[dict]:
    """One row per conversation for the chat-history picker: id, its first user
    message (the title), message count, newest first. Sessions are just a
    session_id label on chat_log rows — the same table, no new storage."""
    groups = conn.execute(
        """SELECT session_id, COUNT(*) AS messages, MAX(created_at) AS last_at
           FROM chat_log GROUP BY session_id ORDER BY last_at DESC"""
    ).fetchall()
    out = []
    for g in groups:
        first = conn.execute(
            "SELECT content FROM chat_log WHERE session_id=? AND role='user' ORDER BY id LIMIT 1",
            (g["session_id"],),
        ).fetchone()
        out.append({"id": g["session_id"],
                    "title": (first["content"][:60] if first else "(empty)"),
                    "messages": g["messages"],
                    "last_at": g["last_at"]})
    return out


# A tool's origin, for grouping in the Tools tab (name → category).
_FLAGSHIP = {"create_event", "save_note", "send_message"}
_SELFMGMT = {"manage_memory", "update_soul", "create_skill"}
_APPLE = {"read_apple_calendar", "read_apple_mail", "create_reminder", "create_note"}


def _tool_source(name: str, mcp_servers: list[str]) -> str:
    if name in _FLAGSHIP:
        return "flagship"
    if name in _SELFMGMT:
        return "self-management"
    if name in _APPLE:
        return "apple"
    if any(name.startswith(f"{s}_") for s in mcp_servers):
        return "mcp"
    return "other"


def tools_info() -> dict:
    """The agent's available tools + any configured MCP servers — so the Tools
    tab shows CAPABILITIES, not just the artifacts tool calls produced. Reflects
    the live agent's registry when one exists (exact), else builds a display-only
    catalog (no MCP subprocess is spawned just to render the page)."""
    settings = load_settings()
    settings.ensure_home()
    mcp = {"configured": False, "servers": [], "live": False}
    mcp_path = settings.home / "mcp.json"
    if mcp_path.exists():
        mcp["configured"] = True
        try:
            mcp["servers"] = [s.get("name", "?") for s in json.loads(mcp_path.read_text()).get("servers", [])]
        except (json.JSONDecodeError, OSError):
            pass

    catalog = []
    if _agent is not None:
        mcp["live"] = getattr(_agent, "mcp_bridge", None) is not None
        tools = list(_agent.tools._tools.values())
    else:
        # Display-only: same tools minus MCP (building the real registry would
        # start MCP servers, which we don't want on a 5-second poll).
        from jarvis.memory import Memory
        from jarvis.tools import calendar, memory_admin, messages, notes

        conn = connect(settings.home)
        mem = Memory(conn, settings, None)
        tools = [calendar.make_tool(conn, settings.home, apple_calendar=settings.apple_calendar),
                 notes.make_tool(conn), messages.make_tool(settings.home),
                 memory_admin.make_manage_memory_tool(mem),
                 memory_admin.make_update_soul_tool(settings),
                 memory_admin.make_create_skill_tool(settings, mem)]
        if settings.apple_tools:
            from jarvis.tools import apple

            tools += apple.make_tools()
    for t in tools:
        catalog.append({"name": t.name, "description": t.description,
                        "source": _tool_source(t.name, mcp["servers"])})
    catalog.sort(key=lambda c: (c["source"], c["name"]))
    return {"catalog": catalog, "mcp": mcp, "apple_on": settings.apple_tools}


def run_query(payload: dict) -> dict:
    """A tiny read-only SQL console (the Supabase-editor idea, scoped down).
    Opens state.db in read-only mode so a write can't slip through, and only
    accepts a single SELECT/WITH statement. Caps at 200 rows."""
    sql = (payload.get("sql") or "").strip().rstrip(";").strip()
    if not sql:
        return {"error": "Type a SELECT query."}
    low = sql.lower()
    if not (low.startswith("select") or low.startswith("with")):
        return {"error": "Only SELECT (or WITH … SELECT) queries are allowed."}
    if ";" in sql:
        return {"error": "One statement at a time (no semicolons)."}
    import sqlite3

    settings = load_settings()
    settings.ensure_home()
    db = (settings.home / "state.db").resolve()
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        cur = c.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        data = [[str(r[i]) if r[i] is not None else "" for i in range(len(cols))]
                for r in cur.fetchmany(200)]
        c.close()
        return {"columns": cols, "rows": data}
    except sqlite3.Error as exc:
        return {"error": str(exc)}


def session_action(payload: dict) -> dict:
    """Chat history control: start a new conversation, or switch to a past one
    (reloading its history so replies keep context). Sessions live in chat_log."""
    action = payload.get("action")
    with _agent_lock:
        agent = _get_agent()
        if action == "new":
            sid = datetime.now().strftime("s-%Y%m%d-%H%M%S")
            agent.session.start_new(sid)
            return {"ok": True, "session_id": sid, "history": []}
        if action == "switch":
            sid = payload.get("id") or "default"
            agent.session.switch(sid)
            hist = [{"role": r, "content": c}
                    for u, a in agent.memory.session_history(sid)
                    for r, c in (("user", u), ("assistant", a))]
            return {"ok": True, "session_id": sid, "history": hist}
    return {"error": f"unknown action {action}"}


def _editor_cmd() -> list[str] | None:
    """The user's code editor CLI: $JARVIS_EDITOR, then cursor, then code."""
    import shutil

    custom = os.getenv("JARVIS_EDITOR")
    if custom and shutil.which(custom):
        return [custom]
    for cli in ("cursor", "code"):
        if shutil.which(cli):
            return [cli]
    return None


def reveal_path(rel: str) -> dict:
    """Open a file/folder under JARVIS_HOME — in the user's code editor if one
    is on PATH (cursor/code/$JARVIS_EDITOR), otherwise reveal in Finder.
    Restricted to paths inside JARVIS_HOME."""
    import subprocess
    import sys

    settings = load_settings()
    settings.ensure_home()
    home = settings.home.resolve()
    target = (home / (rel or ".")).resolve()
    if target != home and home not in target.parents:
        return {"error": "path is outside the Jarvis home"}
    if not target.exists():
        return {"error": f"not found: {target}"}

    editor = _editor_cmd()
    if editor and target.is_file() and target.suffix != ".db":  # editors choke on sqlite
        subprocess.run([*editor, str(target)], check=False)
        return {"ok": True, "opened_in": editor[0], "path": str(target)}
    if sys.platform != "darwin":
        return {"error": f"no editor found and reveal is macOS-only — the path is {target}"}
    subprocess.run(
        ["open", "-R", str(target)] if target.is_file() else ["open", str(target)],
        check=False,
    )
    return {"ok": True, "revealed": str(target)}


def memory_action(payload: dict) -> dict:
    """Human CRUD on memory from the dashboard: update/delete facts & episodes,
    rewrite SOUL.md. Writes the same sqlite file the agent uses (busy_timeout
    covers contention); changes are live for the next agent turn."""
    from jarvis.memory.episodic.store import SqliteEpisodeStore
    from jarvis.memory.semantic.store import SqliteFactStore

    settings = load_settings()
    settings.ensure_home()
    action = payload.get("action")
    if action == "save_soul":
        text = (payload.get("content") or "").strip()
        if not text:
            return {"error": "SOUL cannot be empty"}
        (settings.home / "SOUL.md").write_text(text + "\n")
        return {"ok": True}
    if action == "save_skill":
        # Edit an existing home skill's SKILL.md by hand (same file the agent's
        # create_skill writes). Validates frontmatter; only home skills are
        # writable (built-in repo skills stay read-only).
        from jarvis.memory.procedural.loader import _parse_text

        rel = (payload.get("rel") or "").strip()
        text = (payload.get("content") or "").strip()
        if not rel or not rel.startswith("skills/") or ".." in rel:
            return {"error": "can only edit skills under the home skills/ folder"}
        dest = (settings.home / rel).resolve()
        if settings.home.resolve() not in dest.parents:
            return {"error": "path is outside the Jarvis home"}
        if _parse_text(text, dest) is None:
            return {"error": "invalid SKILL.md — needs a name and description in the frontmatter"}
        dest.write_text(text.rstrip() + "\n")
        return {"ok": True}

    conn = connect(settings.home)
    facts, episodes = SqliteFactStore(conn), SqliteEpisodeStore(conn)
    try:
        rid = int(payload.get("id", 0))
    except (TypeError, ValueError):
        return {"error": "bad id"}
    if action == "update_fact":
        return {"ok": facts.update(rid, payload.get("content", ""), payload.get("subject") or None)}
    if action == "delete_fact":
        return {"ok": facts.delete(rid)}
    if action == "delete_episode":
        return {"ok": episodes.delete(rid)}
    return {"error": f"unknown action {action}"}


def settings_info() -> dict:
    """Current provider/model + which keys are set — masked to last-4, never
    the full key."""
    from jarvis.loop.models import PROVIDERS

    s = load_settings()
    prov = PROVIDERS.get(s.provider)
    return {
        "provider": s.provider,
        "model": s.model or (prov.model if prov else ""),
        "small_model": s.small_model or (prov.small_model if prov else ""),
        "providers": [
            {"name": name, "key_env": p.key_env,
             "key_set": bool(os.getenv(p.key_env)),
             "key_last4": (os.getenv(p.key_env) or "")[-4:],
             "default_model": p.model}
            for name, p in PROVIDERS.items()
        ],
    }


def apply_settings(payload: dict) -> dict:
    """Write .env + os.environ, then rebuild the agent so the switch is live.
    Never logs keys; only whitelisted env names are writable."""
    global _agent
    from dotenv import find_dotenv, set_key

    from jarvis.loop.models import PROVIDERS

    provider = payload.get("provider")
    if provider not in PROVIDERS:
        return {"error": f"unknown provider {provider}"}
    writable = {"JARVIS_PROVIDER", "JARVIS_MODEL", "JARVIS_SMALL_MODEL"} | {p.key_env for p in PROVIDERS.values()}
    env_path = find_dotenv(usecwd=True) or ".env"

    updates = {"JARVIS_PROVIDER": provider,
               "JARVIS_MODEL": payload.get("model", "") or "",
               "JARVIS_SMALL_MODEL": payload.get("small_model", "") or ""}
    for k, v in (payload.get("keys") or {}).items():
        if k in writable and v:  # only non-empty keys overwrite
            updates[k] = v
    for k, v in updates.items():
        if k in writable:
            set_key(env_path, k, v)
            os.environ[k] = v

    with _agent_lock:
        old = _agent
        try:
            new_settings = load_settings()
            new_settings.ensure_home()
            conn = connect(new_settings.home, check_same_thread=False)
            from jarvis.app import Jarvis

            _agent = Jarvis(settings=new_settings, conn=conn)
        except (Exception, SystemExit) as exc:  # get_client raises SystemExit
            _agent = old
            return {"error": str(exc)}
    if old is not None:
        old.close()
    return {"ok": True, **settings_info()}


def events_since(cursor):
    """New trace events past `cursor` (a line count in today's trace file).
    Any gateway — browser, CLI, voice, Telegram — appends to this same file,
    so the live diagram lights up for all of them. cursor=None returns just
    the current tail so the browser starts fresh instead of replaying history."""
    settings = load_settings()
    settings.ensure_home()
    path = settings.home / "traces" / (datetime.now().strftime("%Y-%m-%d") + ".jsonl")
    if not path.exists():
        return {"events": [], "cursor": 0}
    lines = path.read_text().splitlines()
    if cursor is None or cursor < 0 or cursor > len(lines):
        return {"events": [], "cursor": len(lines)}
    out = []
    for ln in lines[cursor:]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return {"events": out, "cursor": len(lines)}


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jarvis</title>
<style>
  :root{
    --bg:#fafaf9;--panel:#ffffff;--line:#e7e6e4;--line2:#d9d8d5;
    --ink:#21201d;--ink2:#6f6e69;--ink3:#a3a29d;
    --accent:#5e6ad2;--accent-soft:#eef0fb;
    --good:#1f7a4d;--good-soft:#e8f4ee;--bad:#c0392b;--bad-soft:#faeceb;
    --mono:ui-monospace,'SF Mono',Menlo,monospace;
  }
  @media (prefers-color-scheme:dark){:root{
    --bg:#101012;--panel:#18181b;--line:#26262a;--line2:#333338;
    --ink:#ececea;--ink2:#96959f;--ink3:#5f5e66;
    --accent:#7c8aec;--accent-soft:#20223a;
    --good:#4cc38a;--good-soft:#12291d;--bad:#e5655a;--bad-soft:#331714;
  }}
  *{box-sizing:border-box;margin:0}
  /* three fixed-height columns, each scrolling independently: the main
     content's scrollbar sits at its own right edge (the "middle"), never over
     the chat dock. */
  body{background:var(--bg);color:var(--ink);
       font:14px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       display:flex;height:100vh;overflow:hidden}
  nav{width:208px;flex-shrink:0;border-right:1px solid var(--line);padding:20px 12px;
      height:100vh;overflow-y:auto}
  .brand{font-weight:650;font-size:15px;padding:0 10px 4px}
  .brand small{display:block;color:var(--ink3);font-weight:400;font-size:11px;margin-top:2px}
  nav a{display:flex;justify-content:space-between;align-items:center;color:var(--ink2);
        text-decoration:none;padding:6px 10px;border-radius:6px;font-size:13.5px;margin-top:2px}
  nav a:hover{background:var(--panel);color:var(--ink)}
  nav a.on{background:var(--accent-soft);color:var(--accent);font-weight:550}
  nav .n{font-size:11px;color:var(--ink3);font-variant-numeric:tabular-nums}
  nav .grp{font-size:10.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--ink3);
           padding:16px 10px 4px}
  main{flex:1;min-width:0;height:100vh;overflow-y:auto;padding:0 40px 32px}
  .pagehead{position:sticky;top:0;z-index:6;background:var(--bg);padding:28px 0 10px;
            border-bottom:1px solid var(--line);margin-bottom:18px}
  /* in-page sub-tabs (Memory pillars, Data tables) — keep each section short */
  .subtabs{display:flex;gap:2px;flex-wrap:wrap;margin:0 0 18px;border-bottom:1px solid var(--line)}
  .subtab{padding:8px 14px;font-size:13px;color:var(--ink2);cursor:pointer;text-decoration:none;
          border-bottom:2px solid transparent;white-space:nowrap}
  .subtab:hover{color:var(--ink)}
  .subtab.on{color:var(--accent);border-bottom-color:var(--accent);font-weight:550}
  .subtab .n{font-size:11px;color:var(--ink3);margin-left:5px}
  /* long tables scroll within their own box, header pinned */
  .scrolly{max-height:62vh;overflow:auto;border:1px solid var(--line);border-radius:8px;background:var(--panel)}
  .scrolly table{border:none}
  .scrolly th{position:sticky;top:0;background:var(--panel);z-index:1}
  /* aligned schema: the column header IS the indigo chip, so labels line up
     over their data (no separate, misaligned chip row). */
  .scrolly th.dbcol{color:var(--accent);background:var(--accent-soft);font-family:var(--mono);
                    font-size:11px;text-transform:none;letter-spacing:0;font-weight:600;border-bottom:1px solid var(--line)}
  .scrolly th.dbcol small{color:var(--ink3);font-weight:400;margin-left:5px}
  h1{font-size:17px;font-weight:600;margin-bottom:2px}
  .sub{color:var(--ink3);font-size:12px;font-family:var(--mono)}
  h2{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--ink2);
     font-weight:600;margin:28px 0 10px}
  .tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(128px,1fr));gap:10px}
  .tile{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
  .tile b{font-size:19px;font-weight:600;font-variant-numeric:tabular-nums;display:block}
  .tile span{color:var(--ink2);font-size:11.5px}
  .map{display:flex;flex-direction:column;gap:10px;margin-top:6px}
  .lane{display:flex;align-items:stretch;gap:0;flex-wrap:wrap}
  .lane-label{width:86px;flex-shrink:0;color:var(--ink3);font-size:11px;text-transform:uppercase;
              letter-spacing:.07em;padding-top:14px}
  .box{background:var(--panel);border:1px solid var(--line);border-radius:8px;
       padding:10px 14px;cursor:pointer;min-width:118px;transition:border-color .1s}
  .box:hover{border-color:var(--accent)}
  .box b{font-size:13px;font-weight:550;display:block}
  .box span{color:var(--ink2);font-size:11.5px}
  .arrow{align-self:center;color:var(--ink3);padding:0 8px;font-size:13px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:8px;
        padding:14px 16px;margin-bottom:10px}
  .badge{display:inline-block;font-size:11px;padding:1px 8px;border-radius:99px;
         border:1px solid var(--line2);color:var(--ink2);margin-right:8px}
  .badge.retrieve{border-color:var(--accent);color:var(--accent)}
  .pill{font-size:11.5px;padding:2px 9px;border-radius:99px;font-weight:600}
  .pill.pass{background:var(--good-soft);color:var(--good)}
  .pill.fail{background:var(--bad-soft);color:var(--bad)}
  .pill.skip{background:var(--accent-soft);color:var(--accent)}
  .u{font-weight:550}
  .r{color:var(--ink2);white-space:pre-wrap;margin-top:6px}
  .meta{color:var(--ink3);font-size:11.5px;margin-top:8px;font-variant-numeric:tabular-nums}
  .tool{border:1px solid var(--line);border-radius:7px;padding:8px 10px;margin-top:8px;background:var(--bg)}
  .tool.error{border-color:var(--bad);background:var(--bad-soft)}
  .tool.warn{border-color:var(--line2)}
  .tool-head{display:flex;align-items:center;gap:8px;font-size:12.5px}
  .dot{width:7px;height:7px;border-radius:99px;flex-shrink:0;background:var(--good)}
  .dot.error{background:var(--bad)} .dot.warn{background:#c8951f}
  .tool code{border:none;background:transparent;padding:0;color:var(--ink)}
  .tool details{margin-top:6px}
  .tool summary{font-size:11px;color:var(--ink3);cursor:pointer;list-style:none}
  .tool pre{font-family:var(--mono);font-size:11px;color:var(--ink2);white-space:pre-wrap;
            word-break:break-all;margin-top:6px;max-height:180px;overflow:auto}
  .live{display:inline-flex;align-items:center;gap:6px}
  .live .dot{animation:pulse 2s ease-in-out infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
  .splitbar{display:flex;height:26px;border-radius:6px;overflow:hidden;border:1px solid var(--line);margin-top:2px}
  .splitbar div{display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;color:#fff;min-width:2px}
  .seg-skip{background:var(--accent)} .seg-ret{background:#c8951f}
  .tile b.money{color:var(--good)}
  .arch{width:100%;min-width:760px;height:auto;font-family:-apple-system,system-ui,sans-serif}
  .arch .container{fill:none;stroke:var(--line2);stroke-dasharray:5 4}
  /* LLM Ops is a SEPARATE system (offline, improves the agent) — a solid
     tinted panel so it never reads as part of the ephemeral Harness. */
  .arch .container.ops{fill:var(--accent-soft);opacity:.5;stroke:var(--accent);stroke-width:1.6;stroke-dasharray:none}
  .arch .bx{fill:var(--panel);stroke:var(--line);stroke-width:1}
  .arch .node{cursor:pointer}
  .arch .node:hover .bx{stroke:var(--accent);stroke-width:1.5}
  .arch .loopbox{fill:none;stroke:var(--accent);stroke-width:1.5}
  .arch .memgroup{fill:var(--accent-soft);opacity:.4;stroke:var(--line2);stroke-width:1;stroke-dasharray:5 4}
  .arch .gate{fill:var(--accent-soft);stroke:var(--accent);stroke-width:1.2}
  .arch .nt{fill:var(--ink);font-size:12.5px;font-weight:600}
  .arch .ns{fill:var(--ink2);font-size:10.5px}
  .arch .grp{fill:var(--ink3);font-size:10px;font-weight:700;letter-spacing:.07em}
  .arch .fl{fill:var(--ink3);font-size:9.5px}
  .arch .flow{fill:none;stroke:var(--ink3);stroke-width:1.3;marker-end:url(#arr)}
  .arch .flow.dash{stroke-dasharray:4 3;opacity:.75}
  .arch .head{fill:var(--ink3)}
  /* live animation: node lights up (fill+stroke) + flowing edge (n8n-style).
     drop-shadow(var()) is unreliable on SVG, so we light the fill instead. */
  .arch .bx{transition:stroke .15s ease, fill .15s ease, stroke-width .15s ease}
  .arch .node.hot .bx{stroke:var(--accent) !important;stroke-width:2.6;fill:var(--accent-soft) !important}
  .arch .gate{transition:stroke .15s ease, stroke-width .15s ease}
  .arch .gate.hot{stroke:var(--accent) !important;stroke-width:4}
  .arch .flow.live{stroke:var(--accent) !important;stroke-width:2.6;opacity:1;stroke-dasharray:6 5;
                   animation:flowdash .5s linear infinite}
  @keyframes flowdash{to{stroke-dashoffset:-22}}
  .arch-status{font-size:11px;font-weight:600;color:var(--accent);text-transform:none;
               letter-spacing:0;margin-left:10px}
  .arch-status .live-dot{display:inline-block;width:7px;height:7px;border-radius:99px;
               background:var(--accent);margin-right:5px;vertical-align:middle;animation:pulse 1s ease-in-out infinite}
  @media (prefers-reduced-motion:reduce){.arch .flow.live{animation:none}.arch-status .live-dot{animation:none}}
  .convo{display:flex;flex-direction:column;gap:8px}
  .msg{border:1px solid var(--line);border-radius:9px;padding:10px 13px;max-width:78%}
  .msg.user{align-self:flex-end;background:var(--accent-soft);border-color:transparent}
  .msg.assistant{align-self:flex-start;background:var(--panel)}
  .msg .who{font-size:11px;color:var(--ink3);font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px}
  .msg .mtext{font-size:13.5px;white-space:pre-wrap;color:var(--ink)}
  .chip-c{display:inline-block;font-size:9.5px;font-weight:600;padding:1px 6px;border-radius:99px;
          background:var(--good-soft);color:var(--good);text-transform:none;letter-spacing:0;vertical-align:middle}
  .cols{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:8px}
  .col-chip{font-family:var(--mono);font-size:11px;padding:2px 8px;border-radius:5px;
            background:var(--accent-soft);color:var(--accent);border:1px solid var(--line)}
  .dbcell{font-family:var(--mono);font-size:11.5px;color:var(--ink2);max-width:240px;overflow:hidden;text-overflow:ellipsis}
  .reveal{color:var(--accent);cursor:pointer;font-weight:500;border-bottom:1px dashed var(--accent);padding-bottom:1px}
  .reveal:hover{border-bottom-style:solid}
  .reveal.del{color:var(--bad);border-color:var(--bad)}
  .editor{width:100%;min-height:120px;background:var(--bg);border:1px solid var(--line2);border-radius:8px;
          padding:10px 12px;color:var(--ink);font:13px/1.5 var(--mono);resize:vertical;outline:none}
  .editor:focus{border-color:var(--accent)}
  tr .editor{min-height:52px}
  .save{background:var(--accent);color:#fff;border:none;border-radius:7px;padding:8px 16px;font-weight:600;font-size:13px;cursor:pointer}
  /* dirty-state: a save button is muted until there's an unsaved change */
  .save:disabled{opacity:.4;cursor:default}
  .save.ghost{background:transparent;color:var(--ink2);border:1px solid var(--line2)}
  /* Tools tab: capability cards grouped by origin */
  .toolcard{border:1px solid var(--line);border-radius:8px;padding:10px 13px;margin-bottom:8px;background:var(--panel)}
  .toolcard .tn{font-family:var(--mono);font-size:12.5px;font-weight:600;color:var(--ink)}
  .toolcard .td{color:var(--ink2);font-size:12px;margin-top:3px}
  .srcpill{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
           padding:1px 7px;border-radius:99px;background:var(--accent-soft);color:var(--accent);margin-left:8px;vertical-align:middle}
  .srcpill.mcp{background:var(--good-soft);color:var(--good)}
  .srcpill.apple{background:#0000;border:1px solid var(--line2);color:var(--ink2)}
  /* read-only SQL console (the Supabase-editor idea, scoped down) */
  .sqlbox{width:100%;min-height:70px;background:#0b0b0d;color:#d6d7de;border:1px solid var(--line2);
          border-radius:8px;padding:11px 13px;font:12.5px/1.5 var(--mono);resize:vertical;outline:none}
  @media (prefers-color-scheme:light){.sqlbox{background:#1c1c20;color:#e6e6ea}}
  .sqlbox:focus{border-color:var(--accent)}
  .qexample{font-family:var(--mono);font-size:11.5px;color:var(--accent);cursor:pointer;border-bottom:1px dashed var(--accent)}
  /* session picker in the chat surfaces */
  .sesshead{display:flex;align-items:center;gap:8px;margin-bottom:10px}
  .sessbtn{background:var(--panel);border:1px solid var(--line2);border-radius:7px;color:var(--ink2);
           padding:5px 11px;font-size:12.5px;cursor:pointer}
  .sessbtn:hover{border-color:var(--accent);color:var(--accent)}
  .sessmenu{position:absolute;z-index:30;background:var(--panel);border:1px solid var(--line2);border-radius:10px;
            box-shadow:0 8px 30px rgba(0,0,0,.28);width:300px;max-height:340px;overflow-y:auto;padding:6px}
  .sessitem{padding:8px 10px;border-radius:7px;cursor:pointer;font-size:12.5px}
  .sessitem:hover{background:var(--accent-soft)}
  .sessitem.on{background:var(--accent-soft);color:var(--accent)}
  .sessitem .sm{color:var(--ink3);font-size:11px;margin-top:2px}
  .fld{display:flex;flex-direction:column;gap:4px;margin-bottom:12px;font-size:12.5px;color:var(--ink2)}
  .fld input,.fld select{background:var(--bg);border:1px solid var(--line2);border-radius:8px;padding:9px 12px;
          color:var(--ink);font-size:13.5px;outline:none}
  .fld input:focus,.fld select:focus{border-color:var(--accent)}
  .watchhead{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--ink2);font-weight:600;margin-bottom:8px}
  .chat-arch{max-width:600px;margin:0 auto 16px;border:1px solid var(--line);border-radius:12px;
             padding:8px;background:var(--panel);position:sticky;top:96px;z-index:3}
  .chat-arch svg{min-width:0;width:100%;height:auto}
  .chatlog{display:flex;flex-direction:column;gap:10px}
  .bubble{align-self:flex-end;background:var(--accent);color:#fff;padding:8px 13px;
          border-radius:14px 14px 3px 14px;max-width:75%;font-size:13.5px}
  .chatbar{display:flex;gap:10px;padding:12px 0;border-top:1px solid var(--line);
           background:var(--bg);position:sticky;bottom:0}
  /* the chat side-dock: chat from any tab, watch the harness in main */
  #dock{width:380px;flex-shrink:0;border-left:1px solid var(--line);position:sticky;top:0;
        height:100vh;display:flex;flex-direction:column;background:var(--bg);padding:0 14px}
  .dockhead{display:flex;align-items:center;gap:10px;padding:18px 2px 10px;
            border-bottom:1px solid var(--line)}
  .dockhead .dt{font-weight:650;font-size:14px}
  .dockhead .arch-status{flex:1}
  #dock-close{background:none;border:1px solid var(--line2);border-radius:6px;color:var(--ink2);
              width:24px;height:24px;cursor:pointer;font-size:14px;line-height:1}
  #dock .chatlog{flex:1;overflow-y:auto;padding:12px 2px}
  #dock .chatbar{padding:12px 0 16px}
  #dock-reopen{display:none;position:fixed;bottom:16px;right:16px;z-index:20;
               background:var(--accent);color:#fff;border:none;border-radius:99px;
               padding:9px 16px;font-weight:600;font-size:13px;cursor:pointer;
               box-shadow:0 2px 10px rgba(0,0,0,.25)}
  body.dock-closed #dock{display:none}
  body.dock-closed #dock-reopen{display:block}
  body.dock-hidden #dock{display:none}
  body.dock-hidden #dock-reopen{display:none}
  .chatbar input{flex:1;background:var(--panel);border:1px solid var(--line2);border-radius:8px;
                 padding:10px 14px;color:var(--ink);font-size:14px;outline:none}
  .chatbar input:focus{border-color:var(--accent)}
  .chatbar button{background:var(--accent);color:#fff;border:none;border-radius:8px;
                  padding:0 18px;font-weight:600;font-size:13.5px;cursor:pointer}
  .chatbar button:disabled{opacity:.5;cursor:default}
  .stages{display:flex;gap:6px;margin:2px 0 4px}
  .stage{font-size:11px;padding:2px 9px;border-radius:99px;border:1px solid var(--line2);color:var(--ink3)}
  .stage.on{border-color:var(--accent);color:var(--accent);background:var(--accent-soft)}
  .stage.done{border-color:var(--good);color:var(--good)}
  table{width:100%;border-collapse:collapse;font-size:13px}
  td,th{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
  tr:last-child td{border-bottom:none}
  th{color:var(--ink3);font-size:10.5px;text-transform:uppercase;letter-spacing:.07em;font-weight:600}
  .empty{color:var(--ink3);font-style:normal;font-size:13px}
  code{font-family:var(--mono);font-size:12px;background:var(--bg);border:1px solid var(--line);
       padding:1px 5px;border-radius:4px}
</style></head><body>
<nav>
  <div class="brand">Jarvis<small id="model"></small></div>
  <div class="grp">Test</div>
  <a href="#chat" data-v="chat">Chat &amp; watch</a>
  <div class="grp">System</div>
  <a href="#overview" data-v="overview">Overview</a>
  <a href="#sessions" data-v="sessions">Sessions <span class="n" id="n-sess"></span></a>
  <a href="#loop" data-v="loop">Loop <span class="n" id="n-loop"></span></a>
  <a href="#memory" data-v="memory">Memory <span class="n" id="n-mem"></span></a>
  <a href="#tools" data-v="tools">Tools <span class="n" id="n-tools"></span></a>
  <a href="#database" data-v="database">Data <span class="n" id="n-db"></span></a>
  <a href="#ops" data-v="ops">Ops <span class="n" id="n-ops"></span></a>
  <a href="#settings" data-v="settings">Settings</a>
</nav>
<main>
  <header class="pagehead">
    <h1 id="title">Overview</h1>
    <div class="sub" id="sub"></div>
  </header>
  <div id="view"></div>
</main>
<aside id="dock">
  <div class="dockhead">
    <span class="dt">Chat</span>
    <span class="arch-status"></span>
    <button id="dock-close" title="Collapse chat">&rsaquo;</button>
  </div>
  <div class="sesshead" style="padding:8px 2px 0">
    <button class="sessbtn" onclick="newChat()">+ New chat</button>
    <button class="sessbtn" onclick="toggleSessMenu(event)">History &#9662;</button>
  </div>
  <div class="chatlog" id="docklog"></div>
  <div class="chatbar">
    <input id="dmsg" placeholder="Message Jarvis&hellip;" autocomplete="off">
    <button id="dsend">Send</button>
  </div>
</aside>
<button id="dock-reopen" title="Open chat">&lsaquo; Chat</button>
<script>
const esc = s => (s??"").toString().replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
let D = null;

// Click a section's data to open the real local file/folder (editor or Finder).
function revealFile(p){ fetch("/api/reveal?path=" + encodeURIComponent(p)); }
const reveal = (path, label) => `<a class="reveal" onclick="revealFile('${path}')">${esc(label)}</a>`;

// --- memory CRUD (dashboard side). `editing` pauses the 5s rebuild so an
// in-progress edit isn't wiped (same idea as the animation guard).
let editing = false;
async function postJSON(url, body){ return (await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})).json(); }
function editFact(id){
  const row = document.getElementById("fact-"+id); if(!row) return;
  editing = true;
  const cell = row.querySelector(".fc"); const cur = cell.textContent;
  cell.innerHTML = `<textarea class="editor" id="ef-${id}">${cur.replace(/</g,"&lt;")}</textarea>`;
  const act = row.lastElementChild;
  act.innerHTML = `<a class="reveal" onclick="saveFact(${id})">save</a> · <a class="reveal" onclick="editing=false;refresh()">cancel</a>`;
  document.getElementById("ef-"+id).focus();
}
async function saveFact(id){
  const v = document.getElementById("ef-"+id).value.trim();
  await postJSON("/api/memory", {action:"update_fact", id, content:v});
  editing = false; refresh();
}
async function delMem(action, id){
  if(!confirm("Delete this from memory?")) return;
  await postJSON("/api/memory", {action, id});
  refresh();
}
// dirty-state: a Save button stays muted until its editor actually changes
function dirty(btnId){ editing = true; const b = document.getElementById(btnId); if (b) b.disabled = false; }
async function saveSoul(){
  const v = document.getElementById("soul").value;
  const r = await postJSON("/api/memory", {action:"save_soul", content:v});
  document.getElementById("soul-msg").textContent = r.error ? ("Error: "+r.error) : "Saved — live next turn.";
  if (!r.error){ const b=document.getElementById("soul-save"); if(b) b.disabled=true; editing=false; }
}
async function saveSkill(i){
  const ta = document.getElementById("sk-"+i);
  const r = await postJSON("/api/memory", {action:"save_skill", rel:ta.dataset.rel, content:ta.value});
  document.getElementById("skmsg-"+i).textContent = r.error ? ("Error: "+r.error) : "Saved — live next turn.";
  if (!r.error){ const b=document.getElementById("sksave-"+i); if(b) b.disabled=true; editing=false; }
}
async function saveSettings(){
  const provider = document.getElementById("set-provider").value;
  const model = document.getElementById("set-model").value.trim();
  const keys = {};
  document.querySelectorAll("[data-key]").forEach(i => { if(i.value.trim()) keys[i.dataset.key] = i.value.trim(); });
  document.getElementById("set-msg").textContent = "switching…";
  const r = await postJSON("/api/settings", {provider, model, keys});
  document.getElementById("set-msg").textContent = r.error ? ("Error: "+r.error) : "Switched to "+r.provider+" — live now.";
  if(!r.error) refresh();
}
function markEditing(){ editing = true; }

const money = n => "$" + (n < 0.01 ? n.toFixed(4) : n.toFixed(2));
const secs = ms => ms==null ? "—" : (ms/1000).toFixed(1)+"s";

const gateBadge = g => !g ? "" :
  `<span class="badge ${g.decision==="retrieve"?"retrieve":""}">gate · ${esc(g.decision)}</span><span class="meta" style="margin:0">${esc(g.reason||"")}</span>`;

// A tool call renders as a status row (dot + one-line summary); the raw output
// hides behind a disclosure so an ugly osascript error never floods the page.
const toolRow = x => `<div class="tool ${x.status}">
  <div class="tool-head"><span class="dot ${x.status}"></span><code>${esc(x.tool)}</code>
    <span style="color:var(--ink2)">${esc(x.summary)}</span></div>
  <details><summary>args &amp; raw output</summary>
    <pre>${esc(x.tool)}(${esc(JSON.stringify(x.args,null,1))})\\n\\n${esc(x.output)}</pre>
  </details>
</div>`;

const turnCard = t => `<div class="card">
  <div class="u">${esc(t.user_message)}</div>
  <div class="meta" style="margin-top:4px">${gateBadge(t.gate)}</div>
  ${(t.tools||[]).map(toolRow).join("")}
  <div class="r">${esc(t.reply)}</div>
  <div class="meta">${esc((t.ts||"").replace("T"," ").slice(0,19))} · ${secs(t.latency_ms)} · ${t.iterations??"?"} iter · ${money(t.cost||0)}${t.consolidation?` · consolidated ${t.consolidation.new_facts} fact(s)`:""}</div>
</div>`;

const table = (heads, rows) => rows.length
  ? `<div class="card" style="padding:4px 8px"><table><tr>${heads.map(h=>`<th>${h}</th>`).join("")}</tr>${rows.join("")}</table></div>`
  : `<div class="card empty">nothing here yet</div>`;

const gateSplit = s => {
  const tot = s.gate_skips + s.gate_retrieves || 1;
  const skipPct = Math.round(s.gate_skips/tot*100), retPct = 100-skipPct;
  return `<div class="splitbar">
    <div class="seg-skip" style="width:${skipPct}%">${s.gate_skips} skipped</div>
    <div class="seg-ret" style="width:${retPct}%">${s.gate_retrieves} retrieved</div>
  </div><div class="meta" style="margin-top:6px">the retrieval gate skipped memory on ${skipPct}% of turns — that's latency and bias saved</div>`;
};

// --- Chat gateway: type here, watch the harness run (turns kept in memory)
const CHAT = [];
const chatTurnCard = t => `<div class="card">
  ${t.gate?`<div class="stages"><span class="stage done">gate · ${esc(t.gate.decision)}</span>${(t.tools||[]).map(x=>`<span class="stage done">tool · ${esc(x.tool)}</span>`).join("")}<span class="stage done">reply</span></div>
    <div class="meta" style="margin:0 0 6px">${esc(t.gate.reason||"")}</div>`:""}
  ${(t.tools||[]).map(toolRow).join("")}
  <div class="r" style="margin-top:8px">${esc(t.reply)}</div>
  <div class="meta">${secs(t.latency_ms)} · ${t.iterations??"?"} iter${t.consolidation?` · consolidated ${t.consolidation.new_facts} fact(s)`:""}</div>
</div>`;

function renderChatLog(){
  if (!CHAT.length)
    return `<div class="empty" style="padding:6px 2px">Send a message below and watch it flow through the harness above — the same pipeline the phone, voice, and CLI gateways drive.</div>`;
  return CHAT.map(m => m.role==="user"
      ? `<div class="bubble">${esc(m.text)}</div>`
      : m.pending ? `<div class="card"><div class="stages"><span class="stage on">gate</span><span class="stage">loop</span><span class="stage">tools</span><span class="stage">reply</span></div><div class="meta" style="margin:0">running the harness…</div></div>`
      : chatTurnCard(m)).join("");
}

function chatView(){
  // The diagram lives IN this tab so you type and watch the harness light up in
  // one place. It's built once; sendChat only re-renders the conversation, so
  // the SVG persists and the trace-event animation plays on it uninterrupted.
  return `
    ${sessBar()}
    <div class="watchhead">Live harness — your message flows through this <span class="arch-status"></span></div>
    <div class="chat-arch">${archSVG(D)}</div>
    <div class="chatlog" id="chatlog">${renderChatLog()}</div>
    <div class="chatbar">
      <input id="msg" placeholder="Message Jarvis — e.g. schedule a swim with Sergey Saturday 5pm" autocomplete="off">
      <button id="send">Send</button>
    </div>`;
}

function syncChatLogs(){
  // one conversation, two surfaces: the Chat & watch tab and the side dock
  document.querySelectorAll(".chatlog").forEach(el => {
    el.innerHTML = renderChatLog();
    el.scrollTop = el.scrollHeight;      // dock scrolls its own container
  });
  if ((location.hash||"#chat").split("/")[0] === "#chat"){
    const m = document.querySelector("main");   // main is the scroll container now
    if (m) m.scrollTo({top:0, behavior:"smooth"});  // tab: keep the diagram in view
  }
}

async function sendChat(fromInput){
  const input = fromInput || document.getElementById("msg") || document.getElementById("dmsg");
  const text = (input && input.value || "").trim();
  if (!text) return;
  input.value = "";
  CHAT.push({role:"user", text});
  const pending = {role:"jarvis", pending:true};
  CHAT.push(pending);
  syncChatLogs();
  try {
    const res = await (await fetch("/api/chat", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({message:text})})).json();
    Object.assign(pending, {pending:false}, res.error ? {reply:"Error: "+res.error} : res);
  } catch(e){ Object.assign(pending, {pending:false, reply:"Error: "+e}); }
  syncChatLogs();
  input.focus();
}
function wireChat(){
  const b = document.getElementById("send"), i = document.getElementById("msg");
  if (b) b.onclick = () => sendChat(i);
  if (i){ i.focus(); i.onkeydown = e => { if (e.key==="Enter") sendChat(i); }; }
  syncChatLogs();
}
function wireDock(){
  const b = document.getElementById("dsend"), i = document.getElementById("dmsg");
  if (b) b.onclick = () => sendChat(i);
  if (i) i.onkeydown = e => { if (e.key==="Enter") sendChat(i); };
  const close = document.getElementById("dock-close"), reopen = document.getElementById("dock-reopen");
  const setClosed = v => { document.body.classList.toggle("dock-closed", v); localStorage.setItem("dockClosed", v?"1":"0"); };
  if (close) close.onclick = () => setClosed(true);
  if (reopen) reopen.onclick = () => setClosed(false);
  const saved = localStorage.getItem("dockClosed");
  setClosed(saved === null ? window.innerWidth < 1180 : saved === "1");
  syncChatLogs();
}

// --- Architecture: a calm live SVG that mirrors the whiteboard's structure
// (Harness wraps the ephemeral run · Loop is a cycle · memory feeds up through
// the gate · LLM Ops is a separate loop). Deliberately few arrows + lots of
// air — the detail lives in each tab. Every node is live and clickable.
function archSVG(d){
  const s = d.stats;
  const box = (x,y,w,h,title,sub,view,cls="",nid="") =>
    `<g class="node ${cls}" ${nid?`data-node="${nid}"`:""} ${view?`onclick="location.hash='${view}'"`:""}>
       <rect class="bx" x="${x}" y="${y}" width="${w}" height="${h}" rx="9"/>
       <text class="nt" x="${x+13}" y="${y+24}">${title}</text>
       ${sub?`<text class="ns" x="${x+13}" y="${y+42}">${sub}</text>`:""}
     </g>`;
  const lbl = (x,y,t) => `<text class="grp" x="${x}" y="${y}">${t}</text>`;
  const flow = (d2,cls="",eid="") => `<path class="flow ${cls}" ${eid?`data-edge="${eid}"`:""} d="${d2}"/>`;
  const flowLbl = (x,y,t,anchor="start") => `<text class="fl" x="${x}" y="${y}" text-anchor="${anchor}">${t}</text>`;

  return `<div style="overflow-x:auto"><svg viewBox="0 0 1044 664" class="arch" role="img">
    <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0 L10 5 L0 10 z" class="head"/></marker></defs>

    <!-- HARNESS container: everything runs on your laptop, including the
         offline LLM Ops loop (tinted sub-panel) -->
    <rect class="container" x="12" y="20" width="1020" height="628" rx="16"/>
    ${lbl(32,48,"HARNESS — runs on your laptop · the turn inside is ephemeral")}

    <!-- the turn: gateway → working memory → loop → reply -->
    ${box(32,72,128,56,"Gateway","cli · voice · web","chat","","gateway")}
    ${flow("M160 100 L192 100","","e-gw-wm")}
    ${box(192,72,144,56,"Working memory","assembled per turn","memory/overview","","wm")}

    <rect class="loopbox" x="370" y="56" width="168" height="166" rx="12"/>
    ${lbl(384,48,"LOOP")}
    ${box(384,72,140,50,"LLM agent","reason","loop","","llm")}
    ${box(384,152,140,52,"Tools","create_event…","tools","","tools")}
    ${flow("M448 122 L448 152")}${flow("M470 152 L470 122")}
    ${flowLbl(456,141,"act")}
    ${flow("M336 100 L370 100","","e-wm-loop")}
    ${flow("M538 100 L558 106")}${flowLbl(542,93,"reply")}
    ${box(558,84,104,52,"Reply","→ back to you","loop","","reply")}
    <!-- reply loops back to the gateway (next turn), arced well clear of the loop -->
    <path class="flow" data-edge="e-reply-gw" d="M610 84 C610 28 360 28 96 66" marker-end="url(#arr)"/>
    ${flowLbl(376,24,"next turn")}
    <!-- every turn is saved for consolidation: down a clear right lane,
         then left into the consolidation box -->
    <path class="flow dash" data-edge="e-reply-save" d="M650 136 C660 150 660 200 660 600 L614 600" marker-end="url(#arr)"/>
    ${flowLbl(668,214,"save chats",'start')}

    <!-- retrieval gate feeding working memory (the hero) -->
    <path class="gate node" data-node="gate" onclick="location.hash='memory/overview'" d="M264 250 L340 296 L264 342 L188 296 Z"/>
    <text class="nt" x="264" y="292" text-anchor="middle" style="pointer-events:none">Retrieval gate</text>
    <text class="ns" x="264" y="310" text-anchor="middle" style="pointer-events:none">${s.gate_skips} skip · ${s.gate_retrieves} retrieve</text>
    ${flow("M264 250 L264 128","dash","e-gate-wm")}${flowLbl(274,196,"only if needed")}

    <!-- MEMORY: grouped section with a direct link from the gate to each pillar -->
    ${lbl(40,404,"MEMORY — three pillars")}
    <rect class="memgroup" x="28" y="414" width="600" height="128" rx="12"/>
    ${flow("M148 452 L246 336","dash","e-gate-proc")}
    ${flow("M340 452 L272 344","dash","e-gate-sem")}
    ${flow("M542 452 L286 338","dash","e-gate-epi")}
    ${flowLbl(356,392,"the gate reads all three",'middle')}
    ${box(44,452,208,72,"Procedural","how to act · SKILL.md · "+d.skills.length+" skill(s)","memory/skills","","procedural")}
    ${box(264,452,204,72,"Semantic · FTS5","durable facts · "+d.facts.length+" facts","memory/semantic","","semantic")}
    ${box(480,452,132,72,"Episodic",d.episodes.length+" episodes","memory/episodic","","episodic")}

    <!-- consolidation writes back into memory -->
    ${box(44,576,568,52,"Consolidation · every "+d.consolidate_every+" exchanges",d.chat_pending+"/"+d.consolidate_every*2+" queued → distilled into facts","memory/consolidation","","consolidation")}
    ${flow("M340 576 L340 528","","e-consol-sem")}${flowLbl(350,560,"distill")}

    <!-- LLM OPS: the offline improvement loop — inside the harness (it all
         runs on the laptop) but a distinct tinted sub-panel -->
    <rect class="container ops" x="736" y="40" width="280" height="372" rx="14"/>
    ${lbl(752,64,"LLM OPS — offline improvement loop")}
    ${flowLbl(752,80,"observes each run · improves the agent",'start')}
    <!-- every turn crosses the gap to feed the trace -->
    <path class="flow" data-edge="e-reply-trace" d="M660 104 C700 100 726 100 752 106" marker-end="url(#arr)"/>
    ${flowLbl(688,96,"each turn")}
    ${box(752,92,250,50,"Trace",s.trace_files+" file(s) · always on","ops","","trace")}
    ${flow("M878 142 L878 156")}
    ${box(752,156,250,50,"Eval","deterministic + judge","ops")}
    ${flow("M878 206 L878 220")}
    ${box(752,220,250,50,"Release gate",d.eval_report?"det "+d.eval_report.deterministic+" · judge "+d.eval_report.judge:"run make gate","ops")}
    ${flow("M878 270 L878 284")}
    ${box(752,284,250,50,"Release","new prompt · model · config","ops")}
    <!-- feedback: Release improves the Harness — a short arrow across the gap,
         so the outer loop closes without a long wrap crowding the margins -->
    <path class="flow dash" d="M752 312 C712 324 698 352 676 358" marker-end="url(#arr)"/>
    ${flowLbl(596,346,"improved prompt + config",'end')}
  </svg></div>`;
}

// --- sub-tabs: keep long pages short by splitting them into hash-routed tabs
// (#memory/semantic, #database/facts). Each tab is a plain link, so it's
// bookmarkable and the architecture cards can deep-link straight to one.
function subtabBar(view, tabs, active){
  return `<div class="subtabs">${tabs.map(([key,label,n]) =>
    `<a class="subtab ${key===active?"on":""}" href="#${view}/${key}">${esc(label)}${
      n!=null?`<span class="n">${n}</span>`:""}</a>`).join("")}</div>`;
}

// A raw SQLite table, scrollable, with the column names AS the (indigo) sticky
// headers so the schema lines up over its data instead of floating above it.
function dbTable(t){
  if (!t.sample.length) return `<div class="card empty">empty — no rows yet</div>`;
  const head = t.columns.map(c => `<th class="dbcol">${esc(c)}${
    t.types&&t.types[c]?`<small>${esc(t.types[c].toLowerCase())}</small>`:""}</th>`).join("");
  const body = t.sample.map(r => `<tr>${t.columns.map(c =>
    `<td class="dbcell">${esc(String(r[c]??"").slice(0,120))}</td>`).join("")}</tr>`).join("");
  return `<div class="scrolly"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>
    <div class="meta" style="margin-top:6px">showing ${t.sample.length} of ${t.count} row${t.count===1?"":"s"} (newest first)</div>`;
}
const DB_DESC = {
  calendar_events: "events the create_event tool wrote (the flagship task)",
  facts: "semantic memory — durable facts (Memory ▸ Semantic)",
  episodes: "episodic memory — dated summaries (Memory ▸ Episodic)",
  chat_log: "every message, tagged by session_id — consolidation reads from here",
};
const QUERY_EXAMPLES = [
  "SELECT role, content FROM chat_log ORDER BY id DESC LIMIT 10",
  "SELECT subject, content FROM facts",
  "SELECT session_id, COUNT(*) FROM chat_log GROUP BY session_id",
];
function dbQueryView(){
  return `<div class="meta" style="margin-bottom:10px">A read-only SQL console over <code>state.db</code>
      (the Supabase-editor idea, scoped down). Only <code>SELECT</code> runs — the file is opened read-only,
      so nothing here can change your data.</div>
    <textarea class="sqlbox" id="sqlbox" spellcheck="false">${esc(QUERY_EXAMPLES[0])}</textarea>
    <div style="margin:8px 0"><button class="save" onclick="runQuery()">Run</button>
      <span class="meta" style="margin-left:12px">try: ${QUERY_EXAMPLES.map(q=>`<span class="qexample" onclick="qFill(this.textContent)">${esc(q)}</span>`).join(" &nbsp; ")}</span></div>
    <div id="qout"></div>`;
}

// --- chat sessions (the "New chat" + history picker, like a chat app)
let SESSION = "default";
async function newChat(){
  const r = await postJSON("/api/session", {action:"new"});
  if (r.session_id){ SESSION = r.session_id; CHAT.length = 0; syncChatLogs(); }
  closeSessMenu();
}
async function switchSession(id){
  const r = await postJSON("/api/session", {action:"switch", id});
  if (r.ok){
    SESSION = r.session_id; CHAT.length = 0;
    (r.history||[]).forEach(m => CHAT.push(m.role==="user"
      ? {role:"user", text:m.content} : {role:"jarvis", reply:m.content, historical:true}));
    syncChatLogs();
  }
  closeSessMenu();
}
function closeSessMenu(){ const m=document.getElementById("sessmenu"); if(m) m.remove(); }
function toggleSessMenu(ev){
  ev.stopPropagation();
  if (document.getElementById("sessmenu")){ closeSessMenu(); return; }
  const sessions = (D && D.sessions) || [];
  const menu = document.createElement("div");
  menu.className = "sessmenu"; menu.id = "sessmenu";
  menu.innerHTML = sessions.length ? sessions.map(s => `
    <div class="sessitem ${s.id===SESSION?"on":""}" onclick="switchSession('${esc(s.id)}')">
      <div>${esc(s.title||s.id)}</div>
      <div class="sm">${s.messages} msg · ${esc((s.last_at||"").slice(0,16))}</div>
    </div>`).join("") : `<div class="sessitem">no past conversations yet</div>`;
  const r = ev.currentTarget.getBoundingClientRect();
  menu.style.top = (r.bottom+6)+"px";
  menu.style.left = Math.max(8, r.right-300)+"px";
  document.body.appendChild(menu);
}
document.addEventListener("click", e => {
  const m = document.getElementById("sessmenu");
  if (m && !m.contains(e.target)) closeSessMenu();
});
const sessBar = () => `<div class="sesshead">
    <button class="sessbtn" onclick="newChat()">+ New chat</button>
    <button class="sessbtn" onclick="toggleSessMenu(event)">History &#9662;</button>
  </div>`;

// --- read-only SQL console (item: "a simple query editor like Supabase")
function qFill(sql){ const b=document.getElementById("sqlbox"); if(b){ b.value=sql; runQuery(); } }
async function runQuery(){
  const sql = (document.getElementById("sqlbox")||{}).value || "";
  const out = document.getElementById("qout");
  out.innerHTML = `<div class="meta">running…</div>`;
  const r = await postJSON("/api/query", {sql});
  if (r.error){ out.innerHTML = `<div class="card empty" style="color:var(--bad)">${esc(r.error)}</div>`; return; }
  if (!r.rows.length){ out.innerHTML = `<div class="card empty">0 rows</div>`; return; }
  out.innerHTML = `<div class="scrolly"><table><thead><tr>${
    r.columns.map(c=>`<th class="dbcol">${esc(c)}</th>`).join("")}</tr></thead><tbody>${
    r.rows.map(row=>`<tr>${row.map(v=>`<td class="dbcell">${esc(String(v).slice(0,120))}</td>`).join("")}</tr>`).join("")
    }</tbody></table></div><div class="meta" style="margin-top:6px">${r.rows.length} row(s)</div>`;
}

// --- Memory sub-tabs. Memory is the friendly, per-pillar view of what persists;
// the Data tab shows the SAME rows as raw SQLite tables (see the explainer).
function memOverview(d){
  const s = d.stats;
  const pillars = [
    ["Semantic","semantic",d.facts.length+" facts","durable, distilled facts about you and your people"],
    ["Episodic","episodic",d.episodes.length+" episodes","one dated summary per consolidation — stays small on purpose"],
    ["Procedural","skills",d.skills.length+" skills","SKILL.md files loaded only when relevant — how to act"],
  ].map(([t,sub,n,desc]) => `<div class="box" style="min-width:0" onclick="location.hash='memory/${sub}'">
      <b>${t} <span class="meta" style="font-weight:400">· ${n}</span></b><span>${desc}</span></div>`).join("");
  return `<div class="card" style="border-color:var(--accent);background:var(--accent-soft)">
      <b>Memory vs Data — two views of one file.</b>
      <div class="r">This tab is the curated, per-pillar view of what Jarvis remembers. The
      <a class="reveal" onclick="location.hash='database'">Data tab</a> shows the exact same
      thing as raw SQLite tables (plus the FTS5 keyword index). Same
      <code>.jarvis/state.db</code> — different altitude.</div></div>
    <h2>The three pillars</h2>
    <div class="tiles" style="grid-template-columns:repeat(auto-fill,minmax(220px,1fr))">${pillars}</div>
    <h2>Retrieval gate — does this turn even need memory?</h2>${gateSplit(s)}
    <div class="meta" style="margin-top:8px">A cheap model decides <b>if</b> a turn needs memory at all, before any lookup —
      this is memory <i>retrieval</i>, the hero decision. (The Ops tab charts the same skip/retrieve
      numbers as an operational metric; the decision itself is memory's.)</div>
    <div class="meta" style="margin-top:14px">Files: ${reveal("state.db","state.db")} · ${reveal("SOUL.md","SOUL.md")} · ${reveal("skills","skills/")}</div>`;
}
function memSemantic(d){
  let h = `<div class="meta" style="margin-bottom:12px">Durable facts distilled from what you tell Jarvis —
    the smallest, most-reused store. Edit or forget any of them; changes are live next turn.</div>`;
  h += `<div class="card" style="padding:4px 8px"><table><tr><th>subject</th><th>fact</th><th>source</th><th></th></tr>${
    d.facts.map(f => `<tr id="fact-${f.id}">
      <td><code>${esc(f.subject)}</code></td>
      <td class="fc">${esc(f.content)}</td>
      <td class="meta">${esc(f.source)}</td>
      <td style="white-space:nowrap"><a class="reveal" onclick="editFact(${f.id})">edit</a> · <a class="reveal del" onclick="delMem('delete_fact',${f.id})">delete</a></td>
    </tr>`).join("")}</table></div>`;
  return h;
}
function memEpisodic(d){
  let h = `<div class="card" style="background:var(--accent-soft);border-color:var(--line2)">
    <b>Why is this small?</b> <span class="r">Episodic memory holds one <i>distilled</i> summary per
    consolidation, not every message. The raw, blow-by-blow conversation lives in the
    <a class="reveal" onclick="location.hash='database/chat_log'"><code>chat_log</code> table</a>
    (the big one) on the Data tab — episodes are its highlights.</span></div>`;
  h += `<div class="card" style="padding:4px 8px"><table><tr><th>date</th><th>episode</th><th></th></tr>${
    d.episodes.map(e => `<tr><td class="meta">${esc(e.happened_at)}</td><td>${esc(e.summary)}</td>
      <td><a class="reveal del" onclick="delMem('delete_episode',${e.id})">delete</a></td></tr>`).join("")}</table></div>`;
  return h;
}
function memSkills(d){
  let h = `<div class="meta" style="margin-bottom:12px">Procedural memory — markdown instructions loaded
    only when a message matches. Add your own three ways: teach Jarvis in chat (it calls
    <code>create_skill</code>), edit a skill below, or drop a <code>SKILL.md</code> into ${reveal("skills","the skills folder")}.</div>`;
  h += d.skills.map((sk,i) => {
    const full = `---\nname: ${sk.name}\ndescription: ${sk.description}\n---\n\n${sk.body}`;
    if (sk.editable) return `<div class="card">
      <div class="u"><code>${esc(sk.name)}</code> <span class="meta" style="font-weight:400">· ${esc(sk.description)}</span></div>
      <textarea class="editor" id="sk-${i}" style="min-height:150px;margin-top:8px" data-rel="${esc(sk.rel)}"
        oninput="dirty('sksave-${i}')" onfocus="markEditing()">${esc(full)}</textarea>
      <div style="margin-top:8px"><button class="save" id="sksave-${i}" disabled onclick="saveSkill(${i})">Save SKILL.md</button>
        <span class="meta" id="skmsg-${i}" style="margin-left:10px"></span></div></div>`;
    return `<div class="card">
      <div class="u"><code>${esc(sk.name)}</code> <span class="meta" style="font-weight:400">· ${esc(sk.description)}</span>
        <span class="srcpill apple" style="margin-left:6px">built-in</span></div>
      <div class="r">${esc(sk.body.slice(0,240))}${sk.body.length>240?"…":""}</div>
      <div class="meta" style="margin-top:6px">read-only — lives in the repo at <code>${esc(sk.rel)}</code>. Copy it into
        ${reveal("skills","your skills folder")} to make it editable.</div></div>`;
  }).join("") || `<div class="card empty">no skills loaded</div>`;
  return h;
}
function memSoul(d){
  return `<div class="meta" style="margin-bottom:12px">SOUL.md is Jarvis's persona — the system prompt it
    loads every turn. Editing it changes who your Jarvis is. Changes are live next turn.</div>
    <div class="card"><textarea id="soul" class="editor" style="min-height:260px"
      oninput="dirty('soul-save')" onfocus="markEditing()">${esc(d.soul||"")}</textarea>
    <div style="margin-top:8px"><button class="save" id="soul-save" disabled onclick="saveSoul()">Save SOUL.md</button>
      <span class="meta" id="soul-msg" style="margin-left:10px"></span></div></div>
    <div class="meta" style="margin-top:10px">${reveal("SOUL.md","open SOUL.md in your editor")}</div>`;
}
function memConsolidation(d){
  const distilled = d.facts.filter(f => f.source==="consolidation");
  let h = `<div class="card"><b>How it works.</b> <span class="r">Every ${d.consolidate_every} exchanges,
    a cheap model reads the unconsolidated ${"<code>chat_log</code>"} and distills it into durable
    <b>facts</b> (semantic) plus one <b>episode</b> (episodic). Batching keeps it cheap and gives the
    summarizer enough context to pick what's worth keeping.</span></div>`;
  h += `<div class="tiles" style="margin-top:12px">
    <div class="tile"><b>${d.chat_pending}</b><span>messages queued</span></div>
    <div class="tile"><b>${d.consolidate_every*2}</b><span>trigger threshold</span></div>
    <div class="tile"><b>${distilled.length}</b><span>facts from consolidation</span></div>
    <div class="tile"><b>${d.episodes.length}</b><span>episodes total</span></div></div>`;
  h += `<h2>Facts it distilled</h2>`;
  h += table(["subject","fact","when"], distilled.map(f =>
    `<tr><td><code>${esc(f.subject)}</code></td><td>${esc(f.content)}</td><td class="meta">${esc((f.created_at||"").slice(0,10))}</td></tr>`));
  h += `<div class="meta" style="margin-top:10px">This is a memory operation, shown here. Each run is also
    <a class="reveal" onclick="location.hash='ops'">traced</a> (Ops) and can be scored by the judge evals.</div>`;
  return h;
}

// Tools ▸ Results: the artifacts tool calls produced (kept distinct from the
// tools themselves — the old tab conflated capability with output).
function toolsResults(d){
  let h = `<div class="meta" style="margin-bottom:10px">What tool calls actually wrote. These are results, not the tools.</div>`;
  h += `<h2>Calendar events <span class="meta" style="font-weight:400">· from create_event</span></h2>`;
  h += table(["event","start","end","with"], d.calendar.map(e =>
    `<tr><td>${esc(e.title)}</td><td class="meta">${esc(e.start)}</td><td class="meta">${esc(e.end)}</td><td>${esc(e.attendees)}</td></tr>`));
  h += `<div class="meta" style="margin-bottom:16px">also written to <code>calendar.ics</code> — ${reveal("calendar.ics","reveal calendar.ics in Finder")} (double-click to import into Calendar.app)</div>`;
  h += `<h2>Outbox — drafted messages <span style="font-weight:400;text-transform:none;letter-spacing:0">· ${reveal("outbox","open the outbox folder")}</span></h2>`;
  h += d.outbox.length ? d.outbox.map(o=>`<div class="card"><span class="u">${esc(o.name)}</span><div class="r">${esc(o.text)}</div></div>`).join("")
                       : `<div class="card empty">no drafted messages</div>`;
  return h;
}
// Tools ▸ MCP: external connectors. Shows live status + a copy-paste config so
// anyone can plug in their own server (scalable, not a one-off).
function toolsMCP(t){
  const m = t.mcp;
  let h = `<div class="card ${m.configured?"":""}" style="border-color:${m.live?"var(--good)":"var(--line2)"}">
    <b>Model Context Protocol${m.live?" — connected":m.configured?" — configured":" — not set up"}.</b>
    <div class="r">MCP lets Jarvis borrow tools from any external server (files, GitHub, a database, …),
    namespaced <code>&lt;server&gt;_&lt;tool&gt;</code>. ${m.configured
      ? `Configured servers: ${m.servers.map(s=>`<code>${esc(s)}</code>`).join(" ")}${m.live?"":" — start a chat to connect them."}`
      : "None configured yet."}</div></div>`;
  h += `<h2>Connect one (30 seconds)</h2><div class="card">
    <div class="meta">1 — install the extra: <code>pip install -e '.[mcp]'</code></div>
    <div class="meta" style="margin-top:6px">2 — create ${reveal("","the .jarvis folder")}<code>/mcp.json</code>:</div>
    <pre style="font-family:var(--mono);font-size:11.5px;color:var(--ink2);white-space:pre-wrap;margin-top:8px">{"servers": [
  {"name": "fs", "command": "npx",
   "args": ["-y", "@modelcontextprotocol/server-filesystem", "${esc(D&&D.home||"")}"]}
]}</pre>
    <div class="meta" style="margin-top:8px">3 — restart the dashboard. The server's tools appear above under
      <a class="reveal" onclick="location.hash='tools/available'">Available ▸ MCP servers</a>, callable in chat.</div></div>`;
  h += `<div class="meta" style="margin-top:12px">The same pattern scales: any MCP server (yours or a vendor's)
    plugs in the same way — no code changes to Jarvis. Skills work the same way — drop a <code>SKILL.md</code>
    in ${reveal("skills","skills/")}.</div>`;
  return h;
}

const VIEWS = {
  chat(){ return chatView(); },
  overview(d){
    const s = d.stats;
    const tiles = [
        [money(s.cost),"spent (est)","money"],[secs(s.latency_avg),"avg turn",""],
        [s.turns,"turns",""],[s.tool_calls,"tool calls",""],
        [d.facts.length,"facts",""],[d.calendar.length,"events",""],
      ].map(([v,l,c])=>`<div class="tile"><b class="${c}">${v}</b><span>${l}</span></div>`).join("");
    return `<div class="tiles">${tiles}</div>
    <h2>Retrieval gate — the hero decision</h2>${gateSplit(s)}
    <h2 style="margin-top:26px">Architecture — click any box <span class="arch-status"></span></h2>
    ${archSVG(d)}
    <h2>Latest turn</h2>${d.turns.length?turnCard(d.turns[0]):'<div class="card empty">no turns yet — talk to Jarvis first</div>'}`;
  },
  loop(d){
    return d.turns.length ? d.turns.map(turnCard).join("") : `<div class="card empty">no turns yet</div>`;
  },
  sessions(d){
    // the persistent conversation (working-memory history) across ALL gateways —
    // the "Current Chat History" box from the whiteboard, made real.
    const log = d.chat_log || [];
    if (!log.length) return `<div class="card empty">no conversation yet — talk to Jarvis and it shows up here</div>`;
    let h = `<div class="meta" style="margin-bottom:12px">The running conversation Jarvis remembers — every gateway (browser, phone, CLI) writes here. Rows marked <span class="chip-c">consolidated</span> have been distilled into semantic + episodic memory.</div>`;
    h += `<div class="convo">` + log.map(m => `
      <div class="msg ${m.role}">
        <div class="who">${m.role==="user"?"you":"jarvis"}${m.consolidated?` <span class="chip-c">consolidated</span>`:""}</div>
        <div class="mtext">${esc(m.content)}</div>
        <div class="meta" style="margin-top:4px">${esc((m.created_at||"").slice(0,19))}</div>
      </div>`).join("") + `</div>`;
    return h;
  },
  memory(d, sub){
    sub = sub || "overview";
    const tabs = [["overview","Overview"],["semantic","Semantic",d.facts.length],
      ["episodic","Episodic",d.episodes.length],["skills","Skills",d.skills.length],
      ["soul","SOUL"],["consolidation","Consolidation",d.chat_pending]];
    let h = subtabBar("memory", tabs, sub);
    if (sub==="semantic") return h + memSemantic(d);
    if (sub==="episodic") return h + memEpisodic(d);
    if (sub==="skills") return h + memSkills(d);
    if (sub==="soul") return h + memSoul(d);
    if (sub==="consolidation") return h + memConsolidation(d);
    return h + memOverview(d);
  },
  settings(d){
    const st = d.settings || {providers:[]};
    let h = `<div class="card">Current: <b>${esc(st.provider)}</b> · model <code>${esc(st.model)}</code> · gate model <code>${esc(st.small_model)}</code></div>`;
    h += `<h2>Provider &amp; keys (BYOK)</h2><div class="card">
      <label class="fld">Provider
        <select id="set-provider" onfocus="markEditing()">${st.providers.map(p=>`<option value="${p.name}" ${p.name===st.provider?"selected":""}>${p.name} (default ${esc(p.default_model)})</option>`).join("")}</select></label>
      <label class="fld">Model override <input id="set-model" placeholder="blank = provider default" value="${st.model===st.providers.find(p=>p.name===st.provider)?.default_model?"":esc(st.model)}"></label>
      <div class="meta" style="margin:10px 0 4px">Keys stay in your local <code>.env</code> — never sent back to this page (only a set/not-set status and the last 4 digits). Leave a field blank to keep the current key.</div>
      ${st.providers.map(p=>`<label class="fld"><span>${p.name} key <span class="meta">(${p.key_env})</span>
        ${p.key_set?`<span class="srcpill" style="background:var(--good-soft);color:var(--good)">set ····${esc(p.key_last4)}</span>`
                   :`<span class="srcpill apple">not set</span>`}</span>
        <input type="password" data-key="${p.key_env}" placeholder="${p.key_set?"key on file — blank keeps it":"paste key"}"></label>`).join("")}
      <div style="margin-top:12px"><button class="save" onclick="saveSettings()">Save &amp; switch</button>
        <span class="meta" id="set-msg" style="margin-left:10px"></span></div>
      <div class="meta" style="margin-top:10px">Note: running terminal / voice / Telegram gateways keep their old provider until restarted.</div>
    </div>`;
    return h;
  },
  tools(d, sub){
    const t = d.tools || {catalog:[], mcp:{configured:false,servers:[],live:false}, apple_on:false};
    sub = sub || "available";
    const tabs = [["available","Available",t.catalog.length],["results","Results"],
      ["mcp","MCP",t.mcp.servers.length||null]];
    let h = subtabBar("tools", tabs, sub);
    if (sub === "results") return h + toolsResults(d);
    if (sub === "mcp") return h + toolsMCP(t);
    // Available: what the agent CAN do (grouped by origin), not just what it did.
    h += `<div class="meta" style="margin-bottom:12px">The capabilities the agent can call this turn.
      A tool is a name + description the model reads, a JSON schema, and a Python function — that's it.
      ${t.apple_on?"":"Apple tools are off (set <code>JARVIS_APPLE_TOOLS=1</code>). "}Connect more via
      <a class="reveal" onclick="location.hash='tools/mcp'">MCP</a>.</div>`;
    const SRC = [["flagship","Flagship task — scheduling"],["self-management","Self-management — it edits its own memory"],
      ["apple","Apple ecosystem"],["mcp","MCP servers"],["other","Other"]];
    SRC.forEach(([key,label]) => {
      const items = t.catalog.filter(c => c.source === key);
      if (!items.length) return;
      h += `<h2>${label}</h2>`;
      h += items.map(c => `<div class="toolcard">
        <div class="tn">${esc(c.name)}<span class="srcpill ${key==="mcp"?"mcp":key==="apple"?"apple":""}">${esc(key)}</span></div>
        <div class="td">${esc(c.description)}</div></div>`).join("");
    });
    return h;
  },
  database(d, sub){
    // The persistence layer itself — one SQLite file, real tables, FTS5 index.
    // "Data" in the nav (plainer than "state.db"), but we keep saying state.db
    // because that's literally the filename you can open.
    const db = d.db || {tables:[], all_tables:[], fts:[], size:0, path:""};
    const tables = db.tables || [];
    sub = sub || "overview";
    const tabs = [["overview","Overview"],
      ...tables.map(t => [t.name, t.name, t.count]),
      ["query","SQL console"]];
    let h = subtabBar("database", tabs, sub);
    if (sub === "query") return h + dbQueryView();
    if (sub !== "overview"){
      const t = tables.find(x => x.name === sub);
      if (!t) return h + `<div class="card empty">no such table</div>`;
      return h + `<div class="meta" style="margin-bottom:10px">${DB_DESC[t.name]||""}</div>` + dbTable(t);
    }
    const kb = (db.size/1024).toFixed(1);
    h += `<div class="card" style="border-color:var(--accent);background:var(--accent-soft)">
      <b>Data vs Memory.</b> <span class="r">This is the raw persistence layer — the literal SQLite
      tables. The <a class="reveal" onclick="location.hash='memory'">Memory tab</a> is the friendly
      view of the same rows (facts, episodes, skills, persona). One file, two altitudes.</span></div>`;
    h += `<div class="card">
      <div class="u" style="font-family:var(--mono);font-size:12.5px;word-break:break-all">${esc(db.path)}</div>
      <div class="meta">${kb} KB on disk · SQLite + FTS5 · open it yourself: <code>sqlite3 .jarvis/state.db</code></div>
      <div class="meta" style="margin-top:8px">${reveal("state.db","reveal state.db in Finder")} &nbsp;·&nbsp; ${reveal("","open the .jarvis folder")}</div></div>`;
    h += `<h2>Tables — click a tab above, or a row here</h2>`;
    h += table(["table","rows","what it holds"], tables.map(t =>
      `<tr><td><a class="reveal" onclick="location.hash='database/${esc(t.name)}'"><code>${esc(t.name)}</code></a></td>
        <td class="meta">${t.count}</td><td class="meta">${DB_DESC[t.name]||""}</td></tr>`));
    h += `<h2>FTS5 — the keyword index</h2><div class="card">The <code>*_fts</code> virtual tables (and their
      <code>*_fts_data</code>/<code>*_fts_idx</code> shadows) make memory searchable by keyword — no embeddings,
      no vector DB. This is the "keyword top-k" the retrieval gate queries.
      <div class="meta" style="margin-top:8px">all ${db.all_tables.length} tables: ${db.all_tables.map(t=>`<code>${esc(t)}</code>`).join(" ")}</div></div>`;
    return h;
  },
  ops(d){
    const s = d.stats;
    let h = `<div class="tiles">${[
        [money(s.cost),"spent (est)","money"],[s.tokens_in.toLocaleString(),"tokens in",""],
        [s.tokens_out.toLocaleString(),"tokens out",""],[secs(s.latency_avg),"avg turn",""],
        [secs(s.latency_p95),"p95 turn",""],[`${s.tool_errors}`,"tool errors",s.tool_errors?"":""],
      ].map(([v,l,c])=>`<div class="tile"><b class="${c}">${v}</b><span>${l}</span></div>`).join("")}</div>`;

    h += `<h2>Retrieval gate — which turns used memory</h2>${gateSplit(s)}`;
    const decided = d.turns.filter(t => t.gate);
    if (decided.length){
      h += `<div class="meta" style="margin:8px 0">The actual decisions (what was skipped vs retrieved), most recent first:</div>`;
      h += table(["turn","decision","why"], decided.slice(0,10).map(t =>
        `<tr><td>${esc((t.user_message||"").slice(0,44))}</td>
          <td><span class="pill ${t.gate.decision==="skip"?"skip":"pass"}">${esc(t.gate.decision)}</span></td>
          <td class="meta">${esc(t.gate.reason||"")}</td></tr>`));
    }

    h += `<h2>Release gate <span class="meta" style="font-weight:400">· the ship/no-ship check</span></h2>`;
    h += `<div class="card"><span class="r">Before you ship a change (new prompt, swapped model, tuned
      retrieval), <code>make gate</code> runs both eval suites: deterministic must pass 100%, the judge must
      clear its threshold. It's manual — you run it — so there's one record per run. The history below grows
      each time you run it.</span></div>`;
    h += d.eval_report ? `<div class="card">
        <span class="pill ${d.eval_report.deterministic}">deterministic · ${d.eval_report.deterministic}</span>
        <span class="pill ${d.eval_report.judge==="pass"?"pass":d.eval_report.judge==="fail"?"fail":"skip"}" style="margin-left:8px">llm-judge · ${d.eval_report.judge}</span>
        <div class="meta">last run ${esc(d.eval_report.ran_at)} — re-run with <code>make gate</code></div></div>`
      : `<div class="card empty">never run yet — run <code>make gate</code> to populate this</div>`;

    if ((d.eval_history||[]).length){
      const cnt = s => s ? `${s.passed||0} pass · ${s.failed||0} fail` : "—";
      h += `<h2>Eval history</h2>`;
      h += table(["when","deterministic","llm-judge","counts"], d.eval_history.map(r =>
        `<tr><td class="meta">${esc((r.ran_at||"").replace("T"," ").slice(0,19))}</td>
         <td><span class="pill ${r.deterministic}">${esc(r.deterministic)}</span></td>
         <td><span class="pill ${r.judge==="pass"?"pass":r.judge==="fail"?"fail":"skip"}">${esc(r.judge)}</span></td>
         <td class="meta">det ${cnt(r.suites&&r.suites.deterministic)} · judge ${cnt(r.suites&&r.suites.judge)}</td></tr>`));
    }

    h += `<h2>Slowest turns</h2>`;
    const slow = [...d.turns].filter(t=>t.latency_ms!=null).sort((a,b)=>b.latency_ms-a.latency_ms).slice(0,6);
    h += table(["turn","latency","cost","tools"], slow.map(t =>
      `<tr><td>${esc((t.user_message||"").slice(0,48))}</td><td class="meta">${secs(t.latency_ms)}</td><td class="meta">${money(t.cost||0)}</td><td class="meta">${(t.tools||[]).map(x=>x.tool).join(", ")||"—"}</td></tr>`));

    h += `<h2>Tracing <span class="meta" style="font-weight:400">· every turn as JSONL, always on</span></h2>`;
    h += `<div class="card"><span class="r">${s.trace_files} trace file(s) in <code>traces/</code>${
      d.trace_file?` (newest: <code>${esc(d.trace_file)}</code>)`:""}. ${reveal("traces","open the traces folder")}.
      A trace is just "what happened, in order" — here are the most recent lines:</span></div>`;
    h += (d.trace_tail||[]).length ? table(["event","detail","when"], d.trace_tail.map(e =>
        `<tr><td><code>${esc(e.type)}</code></td><td class="meta">${esc(String(e.detail).slice(0,60))}</td>
          <td class="meta">${esc((e.ts||"").replace("T"," ").slice(0,19))}</td></tr>`))
      : `<div class="card empty">no trace lines yet — talk to Jarvis</div>`;
    h += `<div class="meta" style="margin-top:8px">Span waterfalls: <code>make trace</code> + <code>OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317</code>.</div>`;

    if (d.wake_scans.length){
      h += `<h2>Voice — wake near-misses</h2>`;
      h += table(["heard","when"], d.wake_scans.map(w =>
        `<tr><td>${esc(w.heard)}</td><td class="meta">${esc((w.ts||"").replace("T"," ").slice(0,19))}</td></tr>`));
    }
    return h;
  },
};

// ---- Live harness animation: light up the diagram as a turn flows through,
// driven by the trace stream so ANY gateway (browser, phone, CLI) triggers it.
const STAGE = {
  turn_start:    {nodes:["gateway","wm"],            edges:["e-gw-wm"],                 label:"message in"},
  gate:          {nodes:["gate"],                    edges:["e-gate-wm"],               label:"retrieval gate"},
  llm:           {nodes:["llm"],                     edges:["e-wm-loop"],               label:"agent reasons"},
  tool:          {nodes:["tools"],                   edges:[],                          label:"tool runs"},
  turn_end:      {nodes:["reply","trace"],           edges:["e-reply-trace","e-reply-save"], label:"reply"},
  consolidation: {nodes:["consolidation","semantic"],edges:["e-consol-sem"],            label:"consolidating memory"},
};
let evCursor = null, evQueue = [], playing = false, animating = false;

function hot(sel, cls, ms){
  document.querySelectorAll(sel).forEach(el => {   // every diagram copy lights up
    el.classList.add(cls);
    setTimeout(()=>el.classList.remove(cls), ms);
  });
}
function animateStage(ev){
  const spec = STAGE[ev.type];
  if (!spec || !document.querySelector(".arch")) return;
  document.querySelectorAll(".arch-status").forEach(st => st.innerHTML = `<span class="live-dot"></span>${spec.label}`);
  spec.nodes.forEach(n => hot(`[data-node="${n}"]`, "hot", 1000));
  spec.edges.forEach(e => hot(`[data-edge="${e}"]`, "live", 1000));
  if (ev.type==="gate" && ev.decision==="retrieve"){
    ["procedural","semantic","episodic"].forEach(n => hot(`[data-node="${n}"]`,"hot",1000));
    ["e-gate-proc","e-gate-sem","e-gate-epi"].forEach(e => hot(`[data-edge="${e}"]`,"live",1000));
  }
}
function playNext(){
  if (!evQueue.length){ playing=false; animating=false;
    document.querySelectorAll(".arch-status").forEach(st => st.innerHTML=""); return; }
  playing = true; animating = true;
  animateStage(evQueue.shift());
  setTimeout(playNext, 620);   // stagger so stages light up in sequence
}
async function pollEvents(){
  try{
    const r = await (await fetch("/api/events" + (evCursor==null?"":"?cursor="+evCursor))).json();
    if (evCursor != null && r.events.length){
      evQueue.push(...r.events);
      if (!playing) playNext();
    }
    evCursor = r.cursor;
  } catch(e){ /* server busy */ }
}

let activeView = null, activeSub = null;
const TITLES = {chat:"Chat & watch", ops:"LLM Ops",
                database:"Data — everything Jarvis stores (state.db)"};
function render(){
  if (!D) return;
  const [v, subRaw] = (location.hash||"#chat").slice(1).split("/");
  const sub = subRaw || null;
  const view = VIEWS[v] ? v : "overview";
  const subChanged = sub !== activeSub || view !== activeView;
  document.body.classList.toggle("dock-hidden", view === "chat");  // never two chat inputs
  document.querySelectorAll("nav a").forEach(a=>a.classList.toggle("on", a.dataset.v===view));
  document.getElementById("title").textContent = TITLES[view] || view[0].toUpperCase()+view.slice(1);
  // Chat owns its DOM (don't wipe the input mid-type on the 5s refresh);
  // (re)build it only when first entering the tab.
  if (view === "chat"){
    if (activeView !== "chat"){ document.getElementById("view").innerHTML = chatView(); wireChat(); }
  } else if (view === "overview"){
    // don't rebuild mid-animation or the glowing SVG gets wiped
    if (activeView !== "overview" || !animating){ document.getElementById("view").innerHTML = VIEWS.overview(D); }
  } else if ((view === "memory" || view === "settings") && editing && !subChanged){
    // don't wipe an in-progress edit on the 5s refresh — but DO switch sub-tabs
  } else {
    editing = false;
    document.getElementById("view").innerHTML = VIEWS[view](D, sub);
  }
  activeView = view; activeSub = sub;
  document.getElementById("model").textContent = `${D.provider} · ${D.model}`;
  document.getElementById("n-sess").textContent = (D.chat_log||[]).length;
  document.getElementById("n-loop").textContent = D.stats.turns;
  document.getElementById("n-mem").textContent = D.facts.length + D.episodes.length;
  document.getElementById("n-tools").textContent = D.calendar.length + D.outbox.length;
  document.getElementById("n-db").textContent = (D.db && D.db.all_tables.length) || "";
  document.getElementById("n-ops").textContent = D.stats.tool_errors || (D.eval_report ? "" : "!");
}
let lastFetch = Date.now();
function tickLive(){
  if (!D) return;
  const ago = Math.round((Date.now()-lastFetch)/1000);
  document.getElementById("sub").innerHTML =
    `<span class="live"><span class="dot"></span>live</span> · updated ${ago}s ago · ${esc(D.home)}`;
}
async function refresh(){
  try { D = await (await fetch("/api/data")).json(); lastFetch = Date.now(); render(); tickLive(); }
  catch(e){ /* server restarting — keep showing last data */ }
}
window.addEventListener("hashchange", render);
window.__hold = (v)=>{ animating = v; };   // test hook: freeze the diagram
wireDock();
refresh(); setInterval(refresh, 5000); setInterval(tickLive, 1000);
pollEvents(); setInterval(pollEvents, 450);   // live harness animation
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 — http.server API
        if self.path == "/api/data":
            self._send(json.dumps(collect(), default=str).encode(), "application/json")
        elif self.path.startswith("/api/events"):
            from urllib.parse import parse_qs, urlparse

            raw = parse_qs(urlparse(self.path).query).get("cursor", [None])[0]
            cursor = int(raw) if raw and raw.lstrip("-").isdigit() else None
            self._send(json.dumps(events_since(cursor)).encode(), "application/json")
        elif self.path.startswith("/api/reveal"):
            from urllib.parse import parse_qs, unquote, urlparse

            rel = unquote(parse_qs(urlparse(self.path).query).get("path", [""])[0])
            self._send(json.dumps(reveal_path(rel)).encode(), "application/json")
        else:
            self._send(PAGE.encode(), "text/html; charset=utf-8")

    def do_POST(self):  # noqa: N802 — local write endpoints
        routes = {"/api/chat": None, "/api/memory": memory_action, "/api/settings": apply_settings,
                  "/api/query": run_query, "/api/session": session_action}
        if self.path not in routes:
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or "{}")
        try:
            if self.path == "/api/chat":
                message = (payload.get("message") or "").strip()
                out = chat(message) if message else {"error": "empty message"}
            else:
                out = routes[self.path](payload)
        except Exception as exc:  # surface, don't 500 — the browser shows it
            out = {"error": f"{type(exc).__name__}: {exc}"}
        self._send(json.dumps(out, default=str).encode(), "application/json")

    def log_message(self, *args):  # keep the terminal quiet
        pass


def main() -> None:

    base = int(os.getenv("JARVIS_DASHBOARD_PORT", str(PORT)))
    for port in range(base, base + 10):  # walk past a busy port instead of crashing
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        except OSError:
            print(f"port {port} busy, trying {port + 1}…")
            continue
        print(f"Jarvis dashboard → http://localhost:{port}  (Ctrl-C to stop)")
        server.serve_forever()
        return
    raise SystemExit(f"no free port in {base}–{base + 9}")


if __name__ == "__main__":
    main()
