// waku dashboard — Model arena: race ONE message through several models at once.
// Split out of app.js: classic <script>, shared global scope (no build step,
// no modules). Loads after views.js so it can hang a page onto VIEWS.
//
// Each contestant runs server-side in its own throwaway home (see
// compare_models in dashboard.py) — this is a benchmark, not a conversation, so
// nothing here touches your real memory or calendar.

// State survives the 5s refresh redraw (the view rebuilds from here) AND — via
// localStorage — tab switches and full reloads, so a finished race isn't lost.
// Kept out of the chat log on purpose: a benchmark isn't a conversation.
let compareState = { message: "Build a Kanto team around Pikachu — search current picks, remember it, and schedule two training sessions this week.",
                     picked: null, running: false, results: null, order: null, sortBy: "latency" };
try {
  const saved = JSON.parse(localStorage.getItem("waku_compare") || "null");
  if (saved){ compareState.message = saved.message ?? compareState.message;
              compareState.results = saved.results || null;
              // only restore columns that actually finished (drop any stale racing… ones)
              compareState.order = (saved.order || []).filter(s => saved.results && saved.results[s]); }
} catch(e){}
function saveCompare(){
  try { localStorage.setItem("waku_compare", JSON.stringify({
    message: compareState.message, order: compareState.order, results: compareState.results})); } catch(e){}
}

// --- Compare history: past races + a cumulative per-model scoreboard, from the
// server's own compare/history.jsonl (never the agent's real state). Loaded once
// when the tab opens and refreshed after each race.
async function loadCompareHistory(){
  try {
    const h = await (await fetch("/api/compare/history")).json();
    compareState.history = h.runs || [];
    compareState.aggregate = h.aggregate || [];
  } catch(e){ compareState.history = []; compareState.aggregate = []; }
  editing = false;   // ensure the scoreboard redraw isn't skipped by the edit-guard
  render();
}
// Sort the scoreboard by a column: same column flips asc<->desc, a new column
// starts ascending (lowest/best first for time/tokens/cost).
function setBoardSort(key){
  const b = compareState.boardSort || {key: "total_cost_usd", dir: "asc"};
  compareState.boardSort = (b.key === key) ? {key, dir: b.dir === "asc" ? "desc" : "asc"} : {key, dir: "asc"};
  editing = false; render();
}
async function clearCompareHistory(){
  if (!confirm("Clear the compare scoreboard and race history? (Only the arena's own log — your real data is untouched.)")) return;
  const r = await postJSON("/api/compare/clear", {});
  compareState.history = r.runs || []; compareState.aggregate = r.aggregate || [];
  editing = false; render();
}
// A stored (slimmed) result -> the shape compareCol expects (gate object, tool
// objects), so a past race renders identically to a live one.
function adaptHistResult(r){
  return {...r, gate: r.gate ? {decision: r.gate} : null,
          tools: (r.tools || []).map(t => ({tool: t}))};
}
// Reopen a past race into the columns (read-only view of that run).
function openCompareRun(idx){
  const run = (compareState.history || [])[idx];
  if (!run) return;
  compareState.order = run.results.map(r => r.spec);
  compareState.results = {}; run.results.forEach(r => { compareState.results[r.spec] = adaptHistResult(r); });
  compareState.message = run.message;
  render();
}

// Which models are offered: your pinned shortlist (models.json). Default-pick
// the first (flagship) of each provider so the race is one brain per lab.
function compareModels(d){
  const pinned = ((d.settings && d.settings.pinned) || []);
  if (compareState.picked === null){
    const seen = new Set();
    compareState.picked = new Set(pinned.filter(p => {
      const first = !seen.has(p.provider); seen.add(p.provider); return first;
    }).map(p => `${p.provider}:${p.model}`));
  }
  return pinned;
}

function setCompareSort(key){
  compareState.sortBy = key;
  editing = false;   // release the textarea lock so the re-sort redraw shows
  render();
}
function toggleCompareModel(spec){
  const s = compareState.picked;
  s.has(spec) ? s.delete(spec) : s.add(spec);
  editing = false;   // release the textarea edit-lock so this redraw isn't
  render();          // skipped by the guard (else the count/chips go stale)
}

// Race over SSE so each column fills the MOMENT its model finishes — a slow or
// broken contestant (e.g. a keyless provider) never blocks the others. Results
// are keyed by spec into compareState.results; the grid redraws per event.
async function runCompare(){
  const specs = [...compareState.picked];
  if (!compareState.message.trim() || !specs.length || compareState.running) return;
  editing = false;   // release the typing lock so the racing/results redraws show
  compareState.running = true;
  compareState.order = specs;      // columns to show, in picked order
  compareState.results = {};       // spec -> result, filled as they land
  compareState.raceError = null;
  render();
  const R = compareState.results;
  try {
    const res = await fetch("/api/compare/stream", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({message: compareState.message, models: specs})});
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for(;;){
      const {value, done} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream:true});
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0){
        const line = buf.slice(0, i); buf = buf.slice(i+2);
        if (!line.startsWith("data:")) continue;
        let ev; try { ev = JSON.parse(line.slice(5).trim()); } catch(e){ continue; }
        const s = ev.spec;
        // The harness plays out live: start -> gate -> tools, then the final
        // result with receipts. (We don't token-stream the reply — see
        // compare_stream in dashboard.py for why.)
        if (ev.kind === "start"){ R[s] = {spec:s, provider:ev.provider, model:ev.model, streaming:true, tools:[], gate:null}; render(); }
        else if (ev.kind === "gate" && R[s]){ R[s].gate = {decision:ev.decision, reason:ev.reason}; render(); }
        else if (ev.kind === "tool" && R[s]){ (R[s].tools = R[s].tools||[]).push({tool:ev.tool}); render(); }
        else if (ev.kind === "result" && s){ R[s] = ev; saveCompare(); render(); }
        else if (ev.kind === "done"){ if (ev.error) compareState.raceError = ev.error; }
      }
    }
  } catch(e){ compareState.raceError = String(e); }
  compareState.running = false; saveCompare(); render();
  loadCompareHistory();   // the server just logged this race — refresh the scoreboard
}

// One contestant's column. While the model runs (res.streaming) it plays out
// live like the chat dock — gate badge, tool chips light up, reply types in with
// a caret. When it finishes (res.result) it flips to the full receipts card.
// Reuses the shared formatters (renderMarkdown/secs/money).
// Plain-English reason for the common, expected failure modes — so the arena
// reads honestly on camera (the raw error stays below, muted).
function compareErrorReason(err){
  const e = (err || "").toLowerCase();
  if (e.includes("reasoning_effort") || e.includes("/v1/responses")) return "can't call tools — reasoning model, needs the /v1/responses API";
  if (e.includes("thought_signature")) return "can't call tools — missing thought_signature echo";
  if (e.includes("credit") || e.includes("permission-denied") || e.includes("license")) return "no credits/licenses on this provider";
  if (e.includes("max_tokens")) return "token-parameter mismatch";
  if (e.includes("not found") || e.includes("no longer available")) return "model id not available";
  return null;
}
function compareCol(res){
  if (res.error){
    const why = compareErrorReason(res.error);
    return `<div class="cmp-col err"><div class="cmp-h"><span class="mm-prov">${esc(res.provider)}</span> <code>${esc(res.model)}</code>
      <span class="srcpill apple">error</span></div>
      ${why?`<div class="meta" style="color:var(--bad)"><b>${esc(why)}</b></div>`:""}
      <div class="meta" style="opacity:.7">${esc(res.error)}</div></div>`;
  }
  const tools = (res.tools||[]).map(t => `<span class="stage done">tool · ${esc(t.tool)}</span>`).join("");
  const gateBadgeHtml = `<span class="badge ${res.gate&&res.gate.decision==="retrieve"?"retrieve":""}">gate · ${esc(res.gate?res.gate.decision:"…")}</span>`;
  if (res.streaming){
    return `<div class="cmp-col">
      <div class="cmp-h"><span class="mm-prov">${esc(res.provider)}</span> <code>${esc(res.model)}</code>
        <span class="live-dot"></span></div>
      <div class="cmp-stats">${gateBadgeHtml}</div>
      ${tools?`<div class="stages" style="flex-wrap:wrap">${tools}</div>`:""}
      <div class="meta">${(res.tools||[]).length?"running tools…":"thinking…"} <span class="caret"></span></div>
    </div>`;
  }
  return `<div class="cmp-col">
    <div class="cmp-h"><span class="mm-prov">${esc(res.provider)}</span> <code>${esc(res.model)}</code></div>
    <div class="cmp-stats">
      ${gateBadgeHtml}
      <span class="chip ${compareState.sortBy==="latency"?"sorted":""}">${secs(res.latency_ms)}</span>
      <span class="chip">${res.iterations??"?"} iter</span>
      <span class="chip ${compareState.sortBy==="cost"?"money":""}">${money(res.cost_usd||0)}</span>
      <span class="chip ${compareState.sortBy==="tokens"?"sorted":""}">${(res.tokens_in||0)+(res.tokens_out||0)} tok</span>
    </div>
    ${tools?`<div class="stages" style="flex-wrap:wrap">${tools}</div>`:""}
    <div class="r cmp-reply">${renderMarkdown(res.reply||"")}</div>
  </div>`;
}

VIEWS.compare = function(d){
  const pinned = compareModels(d);
  const chips = pinned.length ? pinned.map(p => {
    const spec = `${p.provider}:${p.model}`, on = compareState.picked.has(spec);
    return `<label class="cmp-pick ${on?"on":""}"><input type="checkbox" ${on?"checked":""}
      onchange="toggleCompareModel('${esc(spec)}')"> <span class="mm-prov">${esc(p.provider)}</span> ${esc(p.model)}</label>`;
  }).join("") : `<div class="meta">No models pinned yet — add some in Settings.</div>`;
  const n = compareState.picked ? compareState.picked.size : 0;

  // One column per raced model, in order. Each shows "racing…" until its result
  // arrives over the stream, then flips to the receipts card.
  let grid = "";
  const order = compareState.order || [];
  if (order.length){
    const results = compareState.results || {};
    // "done" = finished successfully (not streaming, not errored) — only these
    // have latency/cost for the fastest/cheapest summary.
    const done = order.map(s => results[s]).filter(Boolean).filter(r => !r.error && !r.streaming);
    // Sort key: the finished cards rank ascending by the chosen metric (least is
    // best — fastest / cheapest / fewest tokens), winner to the top-left.
    const metric = { latency: r => r.latency_ms || 0,
                     cost:    r => r.cost_usd || 0,
                     tokens:  r => (r.tokens_in || 0) + (r.tokens_out || 0) };
    const key = metric[compareState.sortBy] || metric.latency;
    const sorters = [["latency", "seconds"], ["tokens", "tokens"], ["cost", "money"]];
    // Prominent, tab-like sort buttons — the selected one is highlighted.
    const sortBar = done.length ? `<div class="cmp-sortbar">sort by ${sorters.map(([k, label]) =>
      `<button class="cmp-sortbtn ${compareState.sortBy === k ? "on" : ""}" onclick="setCompareSort('${k}')">${label}</button>`).join("")}</div>` : "";
    // Only a progress line while the race is still running; once every column is
    // in, the sort tabs + cards + scoreboard say it all (no redundant summary).
    const summary = done.length < order.length
      ? `Racing ${order.length} models — ${done.length}/${order.length} done`
      : "";
    // Rank finished models first (by the chosen metric), then still-running,
    // then errors — so as the race resolves, the best rises to the top-left.
    const rank = s => {
      const r = results[s];
      if (!r) return [2, 0];                       // not started
      if (r.error) return [3, 0];                  // failed -> end
      if (r.streaming) return [1, 0];              // running -> middle
      return [0, key(r)];                          // done -> front, best-of-metric first
    };
    const shown = [...order].sort((a, b) => { const ra = rank(a), rb = rank(b); return ra[0] - rb[0] || ra[1] - rb[1]; });
    const cols = shown.map(s => {
      const r = results[s];
      if (r) return compareCol(r);
      return `<div class="cmp-col"><div class="cmp-h"><span class="mm-prov">${esc(s.split(":")[0])}</span> <code>${esc(s.split(":").slice(1).join(":"))}</code></div>
        <div class="meta">racing… <span class="caret"></span></div></div>`;
    }).join("");
    grid = `${summary ? `<div class="meta" style="margin:2px 0 6px">${summary}</div>` : ""}${sortBar}<div class="cmp-grid">${cols}</div>`
      + (compareState.raceError ? `<div class="meta" style="color:var(--bad)">${esc(compareState.raceError)}</div>` : "");
  }

  // Load the history once when the tab first opens (setting [] first stops the
  // 5s refresh from re-triggering); loadCompareHistory re-renders when it lands.
  if (compareState.history === undefined){ compareState.history = []; setTimeout(loadCompareHistory, 0); }

  return `<div class="card">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:6px">
      <span class="meta">One message, every brain at once — same harness, isolated homes, real receipts (gate · latency · cost · tools). Compare, don't guess.</span>
      <button class="save cmp-race" style="margin-left:auto" onclick="runCompare()" ${(!n||compareState.running)?"disabled":""}>
        ${compareState.running?"Racing…":`Race ${n} model${n===1?"":"s"}`}</button>
    </div>
    <textarea id="cmp-msg" class="cmp-input" rows="2" onfocus="markEditing()"
      oninput="compareState.message=this.value">${esc(compareState.message)}</textarea>
    <div class="cmp-picks">${chips}</div>
  </div>${grid}${compareHistoryHtml()}`;
};

// The cumulative view under the current race: a per-model scoreboard averaged
// across every logged race, then the list of recent races (click to reopen).
// Data comes from GET /api/compare/history (the arena's own JSONL, never the
// agent's real state).
function compareHistoryHtml(){
  const agg = compareState.aggregate || [];
  const hist = compareState.history || [];
  if (!agg.length && !hist.length) return "";
  // Cumulative totals across all races. Click a column header to sort by it —
  // ascending first, click again to flip (arrow shows the active column + dir).
  const bs = compareState.boardSort || (compareState.boardSort = {key: "total_cost_usd", dir: "asc"});
  const arrow = k => bs.key === k ? (bs.dir === "asc" ? " ▲" : " ▼") : "";
  const th = (k, label) => `<th class="cmp-th ${bs.key===k?"on":""}" onclick="setBoardSort('${k}')">${label}${arrow(k)}</th>`;
  const rows = [...agg].sort((x, y) => ((x[bs.key] ?? 0) - (y[bs.key] ?? 0)) * (bs.dir === "asc" ? 1 : -1));
  const scoreboard = agg.length ? `
    <h2 style="margin-top:22px;display:flex;align-items:center;gap:10px">Scoreboard
      <span class="meta" style="font-weight:400">— totals across ${hist.length} race${hist.length===1?"":"s"}</span>
      <a class="reveal" style="margin-left:auto;font-size:12px" onclick="clearCompareHistory()">clear</a></h2>
    <div class="card" style="padding:4px 8px"><table>
      <tr><th>model</th>${th("runs","races")}<th>ok</th>${th("total_latency_ms","total time")}${th("total_tokens","total tokens")}${th("total_cost_usd","total cost")}</tr>
      ${rows.map(a=>`<tr>
        <td><span class="mm-prov">${esc(a.provider)}</span> <code>${esc(a.model)}</code></td>
        <td class="meta">${a.runs}</td><td class="meta">${a.ok}/${a.runs}</td>
        <td class="meta">${secs(a.total_latency_ms)}</td><td class="meta">${a.total_tokens}</td>
        <td class="meta" style="color:var(--good)">${money(a.total_cost_usd)}</td></tr>`).join("")}
    </table></div>` : "";
  const recent = hist.length ? `
    <h2 style="margin-top:18px">Recent races <span class="meta" style="font-weight:400">— click to reopen</span></h2>
    <div class="card">${hist.map((run,i)=>`
      <div class="pinrow" style="cursor:pointer" onclick="openCompareRun(${i})">
        <code style="flex:1;word-break:break-all">${esc((run.message||"").slice(0,90))}</code>
        <span class="meta" style="white-space:nowrap">${(run.results||[]).length} models · ${esc((run.ts||"").slice(0,16).replace("T"," "))}</span>
      </div>`).join("")}</div>` : "";
  return scoreboard + recent;
}
