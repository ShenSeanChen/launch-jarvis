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
                     picked: null, running: false, results: null, order: null };
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

function toggleCompareModel(spec){
  const s = compareState.picked;
  s.has(spec) ? s.delete(spec) : s.add(spec);
  render();
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
}

// One contestant's column. While the model runs (res.streaming) it plays out
// live like the chat dock — gate badge, tool chips light up, reply types in with
// a caret. When it finishes (res.result) it flips to the full receipts card.
// Reuses the shared formatters (renderMarkdown/secs/money).
function compareCol(res){
  if (res.error) return `<div class="cmp-col err"><div class="cmp-h"><code>${esc(res.model)}</code>
    <span class="srcpill apple">error</span></div><div class="meta">${esc(res.error)}</div></div>`;
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
      <span class="chip">${secs(res.latency_ms)}</span>
      <span class="chip">${res.iterations??"?"} iter</span>
      <span class="chip money">${money(res.cost_usd||0)}</span>
      <span class="chip">${(res.tokens_in||0)+(res.tokens_out||0)} tok</span>
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
    const summary = done.length
      ? `Isolated temp runs — nothing saved to your data.
         Fastest: <b>${secs(Math.min(...done.map(r=>r.latency_ms)))}</b> ·
         Cheapest: <b>${money(Math.min(...done.map(r=>r.cost_usd||0)))}</b>
         · ${done.length}/${order.length} done`
      : `Racing ${order.length} models in isolated sandboxes — watch each column think and act live.`;
    // Rank the fastest finished model to the front, then still-running, then
    // errors — so as the race resolves, the winner rises to the top-left.
    const rank = s => {
      const r = results[s];
      if (!r) return [2, 0];                       // not started
      if (r.error) return [3, 0];                  // failed -> end
      if (r.streaming) return [1, 0];              // running -> middle
      return [0, r.latency_ms || 0];               // done -> front, fastest first
    };
    const shown = [...order].sort((a, b) => { const ra = rank(a), rb = rank(b); return ra[0] - rb[0] || ra[1] - rb[1]; });
    const cols = shown.map(s => {
      const r = results[s];
      if (r) return compareCol(r);
      return `<div class="cmp-col"><div class="cmp-h"><span class="mm-prov">${esc(s.split(":")[0])}</span> <code>${esc(s.split(":").slice(1).join(":"))}</code></div>
        <div class="meta">racing… <span class="caret"></span></div></div>`;
    }).join("");
    grid = `<div class="meta" style="margin:2px 0 8px">${summary}</div><div class="cmp-grid">${cols}</div>`
      + (compareState.raceError ? `<div class="meta" style="color:var(--bad)">${esc(compareState.raceError)}</div>` : "");
  }

  return `<div class="card">
    <div class="meta" style="margin-bottom:6px">One message, every brain at once — same harness, isolated homes, real receipts (gate · latency · cost · tools). Compare, don't guess.</div>
    <textarea id="cmp-msg" class="cmp-input" rows="2" onfocus="markEditing()"
      oninput="compareState.message=this.value">${esc(compareState.message)}</textarea>
    <div class="cmp-picks">${chips}</div>
    <div style="margin-top:10px">
      <button class="save" onclick="runCompare()" ${(!n||compareState.running)?"disabled":""}>
        ${compareState.running?"Racing…":`Race ${n} model${n===1?"":"s"}`}</button>
    </div>
  </div>${grid}`;
};
