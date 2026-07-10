"""Dashboard — every pillar on one local page. Zero new dependencies.

    make dashboard        # → http://localhost:7777

One stdlib HTTP server reading the files Jarvis already writes:
  loop + harness   traces/*.jsonl   (turns, gate decisions, tool calls, tokens)
  memory           state.db         (facts, episodes, chat log, consolidation)
  tools            state.db + calendar.ics + outbox/
  eval             eval_report.json (written by `make gate`)

The overview mirrors the architecture diagram — every box is clickable and
opens that section's live data. It reads and displays; it never mutates.
For deep trace waterfalls use Phoenix (`make trace`).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jarvis.config import load_settings
from jarvis.db import connect

PORT = 7777


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
        turns.append(current)

    from jarvis.memory.procedural.loader import SkillLoader
    from jarvis.memory import REPO_SKILLS

    skills = [{"name": s.name, "description": s.description, "path": str(s.path)}
              for s in SkillLoader([REPO_SKILLS, home / "skills"]).skills]

    eval_report = None
    report_path = home / "eval_report.json"
    if report_path.exists():
        eval_report = json.loads(report_path.read_text())

    outbox = [{"name": p.name, "text": p.read_text()[:400]}
              for p in sorted((home / "outbox").glob("*.txt"), reverse=True)[:20]]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "home": str(home.resolve()),
        "provider": settings.provider,
        "model": settings.model or "(provider default)",
        "stats": {
            "turns": len(turns),
            "tool_calls": sum(len(t["tools"]) for t in turns),
            "gate_skips": sum(1 for t in turns if t["gate"] and t["gate"].get("decision") == "skip"),
            "gate_retrieves": sum(1 for t in turns if t["gate"] and t["gate"].get("decision") == "retrieve"),
            "tokens_in": sum(c.get("usage", {}).get("in", 0) for t in turns for c in t["llm_calls"]),
            "tokens_out": sum(c.get("usage", {}).get("out", 0) for t in turns for c in t["llm_calls"]),
            "trace_files": len(trace_files),
        },
        "turns": turns[::-1][:50],
        "wake_scans": wake_scans[::-1][:25],
        "facts": rows("SELECT subject, content, source, created_at FROM facts ORDER BY id DESC"),
        "episodes": rows("SELECT happened_at, summary FROM episodes ORDER BY happened_at DESC"),
        "chat_pending": conn.execute("SELECT COUNT(*) FROM chat_log WHERE consolidated=0").fetchone()[0],
        "consolidate_every": settings.consolidate_every,
        "calendar": rows('SELECT title, start, "end", attendees, created_at FROM calendar_events ORDER BY start'),
        "outbox": outbox,
        "skills": skills,
        "eval_report": eval_report,
    }


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
  body{background:var(--bg);color:var(--ink);
       font:14px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       display:flex;min-height:100vh}
  nav{width:208px;flex-shrink:0;border-right:1px solid var(--line);padding:20px 12px;
      position:sticky;top:0;height:100vh}
  .brand{font-weight:650;font-size:15px;padding:0 10px 4px}
  .brand small{display:block;color:var(--ink3);font-weight:400;font-size:11px;margin-top:2px}
  nav a{display:flex;justify-content:space-between;align-items:center;color:var(--ink2);
        text-decoration:none;padding:6px 10px;border-radius:6px;font-size:13.5px;margin-top:2px}
  nav a:hover{background:var(--panel);color:var(--ink)}
  nav a.on{background:var(--accent-soft);color:var(--accent);font-weight:550}
  nav .n{font-size:11px;color:var(--ink3);font-variant-numeric:tabular-nums}
  nav .grp{font-size:10.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--ink3);
           padding:16px 10px 4px}
  main{flex:1;padding:32px 40px;max-width:960px}
  h1{font-size:17px;font-weight:600;margin-bottom:2px}
  .sub{color:var(--ink3);font-size:12px;margin-bottom:24px;font-family:var(--mono)}
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
  .tool{font-family:var(--mono);font-size:11.5px;background:var(--bg);border:1px solid var(--line);
        border-radius:6px;padding:6px 9px;margin-top:8px;white-space:pre-wrap;word-break:break-all;color:var(--ink2)}
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
  <div class="grp">System</div>
  <a href="#overview" data-v="overview">Overview</a>
  <a href="#loop" data-v="loop">Loop <span class="n" id="n-loop"></span></a>
  <a href="#memory" data-v="memory">Memory <span class="n" id="n-mem"></span></a>
  <a href="#tools" data-v="tools">Tools <span class="n" id="n-tools"></span></a>
  <a href="#ops" data-v="ops">Ops <span class="n" id="n-ops"></span></a>
</nav>
<main>
  <h1 id="title">Overview</h1>
  <div class="sub" id="sub"></div>
  <div id="view"></div>
</main>
<script>
const esc = s => (s??"").toString().replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
let D = null;

const gateBadge = g => !g ? "" :
  `<span class="badge ${g.decision==="retrieve"?"retrieve":""}">gate · ${esc(g.decision)}</span><span class="meta" style="margin:0">${esc(g.reason||"")}</span>`;

const turnCard = t => `<div class="card">
  <div class="u">${esc(t.user_message)}</div>
  <div class="meta" style="margin-top:4px">${gateBadge(t.gate)}</div>
  ${(t.tools||[]).map(x=>`<div class="tool">${esc(x.tool)}(${esc(JSON.stringify(x.args))})\\n→ ${esc(x.output)}</div>`).join("")}
  <div class="r">${esc(t.reply)}</div>
  <div class="meta">${esc((t.ts||"").replace("T"," ").slice(0,19))} · ${t.iterations??"?"} iteration(s) · ${(t.llm_calls||[]).map(c=>`${c.usage?.in??0}→${c.usage?.out??0} tok`).join(", ")}${t.consolidation?` · consolidated ${t.consolidation.new_facts} fact(s)`:""}</div>
</div>`;

const table = (heads, rows) => rows.length
  ? `<div class="card" style="padding:4px 8px"><table><tr>${heads.map(h=>`<th>${h}</th>`).join("")}</tr>${rows.join("")}</table></div>`
  : `<div class="card empty">nothing here yet</div>`;

const VIEWS = {
  overview(d){
    const s = d.stats;
    return `<div class="tiles">${[
        [s.turns,"turns"],[s.tool_calls,"tool calls"],
        [`${s.gate_skips} / ${s.gate_retrieves}`,"gate skip / retrieve"],
        [s.tokens_in.toLocaleString(),"tokens in"],[s.tokens_out.toLocaleString(),"tokens out"],
        [d.facts.length,"facts"],[d.calendar.length,"events"]
      ].map(([v,l])=>`<div class="tile"><b>${v}</b><span>${l}</span></div>`).join("")}</div>
    <h2>Architecture — click any box</h2>
    <div class="map">
      <div class="lane"><div class="lane-label">One turn</div>
        <div class="box" onclick="location.hash='ops'"><b>Gateway</b><span>cli · voice · telegram</span></div>
        <div class="arrow">→</div>
        <div class="box" onclick="location.hash='memory'"><b>Working memory</b><span>soul + memory + history</span></div>
        <div class="arrow">→</div>
        <div class="box" onclick="location.hash='loop'"><b>Loop</b><span>${s.turns} turns</span></div>
        <div class="arrow">⇄</div>
        <div class="box" onclick="location.hash='tools'"><b>Tools</b><span>${s.tool_calls} calls</span></div>
      </div>
      <div class="lane"><div class="lane-label">Memory</div>
        <div class="box" onclick="location.hash='memory'"><b>Retrieval gate</b><span>${s.gate_skips} skipped · ${s.gate_retrieves} retrieved</span></div>
        <div class="box" style="margin-left:10px" onclick="location.hash='memory'"><b>Procedural</b><span>${d.skills.length} skills</span></div>
        <div class="box" style="margin-left:10px" onclick="location.hash='memory'"><b>Semantic</b><span>${d.facts.length} facts</span></div>
        <div class="box" style="margin-left:10px" onclick="location.hash='memory'"><b>Episodic</b><span>${d.episodes.length} episodes</span></div>
        <div class="box" style="margin-left:10px" onclick="location.hash='memory'"><b>Consolidation</b><span>${d.chat_pending}/${d.consolidate_every*2} queued</span></div>
      </div>
      <div class="lane"><div class="lane-label">LLM ops</div>
        <div class="box" onclick="location.hash='ops'"><b>Trace</b><span>${s.trace_files} file(s) · always on</span></div>
        <div class="box" style="margin-left:10px" onclick="location.hash='ops'"><b>Eval</b><span>${d.eval_report?`det ${d.eval_report.deterministic} · judge ${d.eval_report.judge}`:"not run yet"}</span></div>
        <div class="box" style="margin-left:10px" onclick="location.hash='ops'"><b>Release gate</b><span>make gate</span></div>
      </div>
    </div>
    <h2>Latest turn</h2>${d.turns.length?turnCard(d.turns[0]):'<div class="card empty">no turns yet — talk to Jarvis first</div>'}`;
  },
  loop(d){
    return d.turns.length ? d.turns.map(turnCard).join("") : `<div class="card empty">no turns yet</div>`;
  },
  memory(d){
    let h = `<h2>Semantic — durable facts</h2>`;
    h += table(["subject","fact","source","when"], d.facts.map(f =>
      `<tr><td><code>${esc(f.subject)}</code></td><td>${esc(f.content)}</td><td>${esc(f.source)}</td><td class="meta">${esc(f.created_at)}</td></tr>`));
    h += `<h2>Episodic — what happened, when</h2>`;
    h += table(["date","episode"], d.episodes.map(e =>
      `<tr><td class="meta">${esc(e.happened_at)}</td><td>${esc(e.summary)}</td></tr>`));
    h += `<h2>Consolidation</h2><div class="card">${d.chat_pending} unconsolidated message(s).
          The summarizer distills chats into facts + an episode every ${d.consolidate_every} exchanges.</div>`;
    h += `<h2>Procedural — loaded skills</h2>`;
    h += table(["skill","when it triggers"], d.skills.map(s =>
      `<tr><td><code>${esc(s.name)}</code></td><td>${esc(s.description)}</td></tr>`));
    return h;
  },
  tools(d){
    let h = `<h2>Calendar events</h2>`;
    h += table(["event","start","end","with"], d.calendar.map(e =>
      `<tr><td>${esc(e.title)}</td><td class="meta">${esc(e.start)}</td><td class="meta">${esc(e.end)}</td><td>${esc(e.attendees)}</td></tr>`));
    h += `<div class="meta" style="margin-bottom:16px">also written to <code>calendar.ics</code> — import with <code>open .jarvis/calendar.ics</code></div>`;
    h += `<h2>Outbox — drafted messages</h2>`;
    h += d.outbox.length ? d.outbox.map(o=>`<div class="card"><span class="u">${esc(o.name)}</span><div class="r">${esc(o.text)}</div></div>`).join("")
                         : `<div class="card empty">no drafted messages</div>`;
    return h;
  },
  ops(d){
    let h = `<h2>Release gate</h2>`;
    h += d.eval_report ? `<div class="card">
        <span class="pill ${d.eval_report.deterministic}">deterministic · ${d.eval_report.deterministic}</span>
        <span class="pill ${d.eval_report.judge==="pass"?"pass":d.eval_report.judge==="fail"?"fail":"skip"}" style="margin-left:8px">llm-judge · ${d.eval_report.judge}</span>
        <div class="meta">last run ${esc(d.eval_report.ran_at)} — refresh with <code>make gate</code></div></div>`
      : `<div class="card empty">no eval report yet — run <code>make gate</code></div>`;
    h += `<h2>Tracing</h2><div class="card">${d.stats.trace_files} trace file(s) in <code>traces/</code>.
          Every turn is recorded as JSONL. For span waterfalls: <code>make trace</code> +
          <code>OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317</code>.</div>`;
    if (d.wake_scans.length){
      h += `<h2>Voice — wake near-misses</h2>`;
      h += table(["heard","when"], d.wake_scans.map(w =>
        `<tr><td>${esc(w.heard)}</td><td class="meta">${esc(w.ts)}</td></tr>`));
    }
    return h;
  },
};

function render(){
  if (!D) return;
  const v = (location.hash||"#overview").slice(1);
  const view = VIEWS[v] ? v : "overview";
  document.querySelectorAll("nav a").forEach(a=>a.classList.toggle("on", a.dataset.v===view));
  document.getElementById("title").textContent = view==="ops" ? "LLM Ops" : view[0].toUpperCase()+view.slice(1);
  document.getElementById("view").innerHTML = VIEWS[view](D);
  document.getElementById("model").textContent = `${D.provider} · ${D.model}`;
  document.getElementById("sub").textContent = `${D.home} · refreshed ${D.generated_at}`;
  document.getElementById("n-loop").textContent = D.stats.turns;
  document.getElementById("n-mem").textContent = D.facts.length + D.episodes.length;
  document.getElementById("n-tools").textContent = D.calendar.length + D.outbox.length;
  document.getElementById("n-ops").textContent = D.eval_report ? "" : "!";
}
async function refresh(){ D = await (await fetch("/api/data")).json(); render(); }
window.addEventListener("hashchange", render);
refresh(); setInterval(refresh, 5000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — http.server API
        if self.path == "/api/data":
            body = json.dumps(collect(), default=str).encode()
            ctype = "application/json"
        else:
            body = PAGE.encode()
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the terminal quiet
        pass


def main() -> None:
    import os

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
