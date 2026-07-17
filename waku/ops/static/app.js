const esc = s => (s??"").toString().replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));

// --- tiny markdown renderer for chat replies (no dependency, XSS-safe: we
// escape first, then apply a small set of transforms the LLM actually uses:
// bold/italic/code, links, ordered/unordered lists, and tables).
function mdInline(s){   // s is already HTML-escaped
  return s
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+|message:\/\/[^\s)]+)\)/g,
             (m, text, url) => `<a href="${url}" target="_blank" rel="noopener">${text}</a>`)
    .replace(/\*\*([^*]+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*_`])[*_]([^*_`\s][^*_`]*?)[*_](?![\w*])/g, "$1<em>$2</em>")
    .replace(/`([^`]+?)`/g, "<code>$1</code>");
}
function renderMarkdown(text){
  const lines = esc(text).split(/\r?\n/);
  const row = l => /^\s*\|.*\|\s*$/.test(l);
  const sep = l => /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(l);
  const cells = l => l.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
  const out = [];
  let i = 0;
  while (i < lines.length){
    const l = lines[i];
    if (row(l) && i+1 < lines.length && sep(lines[i+1])){          // table
      const head = cells(l); i += 2; const body = [];
      while (i < lines.length && row(lines[i])){ body.push(cells(lines[i])); i++; }
      out.push(`<table class="mdtable"><thead><tr>${head.map(h=>`<th>${mdInline(h)}</th>`).join("")}</tr></thead><tbody>${
        body.map(r=>`<tr>${r.map(c=>`<td>${mdInline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      continue;
    }
    const h = l.match(/^\s*#{1,6}\s+(.*)$/);
    if (h){ out.push(`<div class="mdh">${mdInline(h[1])}</div>`); i++; continue; }
    if (/^\s*[-*]\s+/.test(l)){                                     // unordered list
      const items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])){ items.push(mdInline(lines[i].replace(/^\s*[-*]\s+/,""))); i++; }
      out.push(`<ul class="mdlist">${items.map(x=>`<li>${x}</li>`).join("")}</ul>`); continue;
    }
    if (/^\s*\d+\.\s+/.test(l)){                                    // ordered list
      const items = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])){ items.push(mdInline(lines[i].replace(/^\s*\d+\.\s+/,""))); i++; }
      out.push(`<ol class="mdlist">${items.map(x=>`<li>${x}</li>`).join("")}</ol>`); continue;
    }
    if (/^\s*$/.test(l)){ i++; continue; }
    const para = [];                                                // paragraph
    while (i < lines.length && lines[i].trim() && !/^\s*[-*]\s|^\s*\d+\.\s|^\s*#{1,6}\s/.test(lines[i])
           && !(row(lines[i]) && i+1<lines.length && sep(lines[i+1]))){
      para.push(mdInline(lines[i])); i++;
    }
    out.push(`<div class="mdp">${para.join("<br>")}</div>`);
  }
  return out.join("");
}
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
  const r = await postJSON("/api/memory", {action:"save_skill", path:ta.dataset.path, content:ta.value});
  document.getElementById("skmsg-"+i).textContent = r.error ? ("Error: "+r.error) : "Saved — live next turn.";
  if (!r.error){ const b=document.getElementById("sksave-"+i); if(b) b.disabled=true; editing=false; }
}
async function saveSettings(){
  const provider = document.getElementById("set-provider").value;
  const model = document.getElementById("set-model").value.trim();
  const small_model = (document.getElementById("set-small-model")?.value || "").trim();
  const keys = {};
  document.querySelectorAll("[data-key]").forEach(i => { if(i.value.trim()) keys[i.dataset.key] = i.value.trim(); });
  document.getElementById("set-msg").textContent = "switching…";
  const r = await postJSON("/api/settings", {provider, model, small_model, keys});
  document.getElementById("set-msg").textContent = r.error ? ("Error: "+r.error) : "Switched to "+r.provider+" — live now.";
  // release the editing lock or the render guard keeps showing the OLD state
  // (live bug: "Current:" card stayed on kimi after switching provider)
  if(!r.error){ editing = false; modelCatalog = null; await refresh(); }
}
function markEditing(){ editing = true; }

// Model picker: fill the settings datalist from /api/models (the active
// endpoint's live catalog; on OpenRouter each entry says free / tool support).
// Waku's loop needs tool calling, so tool-less models are labelled as such.
let modelCatalog = null;
async function loadModelList(){
  const dl = document.getElementById("model-list");
  if (!dl) return;
  if (modelCatalog === null){
    try { modelCatalog = await (await fetch("/api/models")).json(); }
    catch(e){ modelCatalog = {models:[], listed:false}; }
  }
  const ms = modelCatalog.models || [];
  dl.innerHTML = ms.map(m => {
    const price = m.free ? "free" : (m.price_out != null ? `$${m.price_in}/$${m.price_out} per M` : "");
    const tags = [price, m.tools === false ? "chat-only" : "", m.reasoning ? "reasoning" : "",
                  m.context ? Math.round(m.context/1000) + "k ctx" : ""].filter(Boolean).join(" · ");
    return `<option value="${esc(m.id)}">${esc(tags)}</option>`;
  }).join("");
  const msg = document.getElementById("model-list-msg");
  if (!msg) return;
  if (modelCatalog.listed){
    const free = ms.filter(m=>m.free), freeTools = free.filter(m=>m.tools);
    msg.textContent = `${ms.length} models on ${modelCatalog.endpoint}` +
      (free.length ? ` · ${free.length} free, ${freeTools.length} of those tool-capable (Waku needs tool calling)` : "") +
      ` · type in the field above to search`;
  } else {
    msg.textContent = modelCatalog.error ? `model list unavailable: ${modelCatalog.error}` : "";
  }
  renderCatalog();
}

// The catalog browser (shown when the endpoint lists models, i.e. OpenRouter):
// suggested picks per SLOT, a search + free/tools filter, and the full list
// grouped by vendor. Every row can go to either slot: "use" is the loop model
// (needs tool calling), "gate" is the small model (needs terse JSON, so
// reasoning models are steered away from it).
let catFilter = {q: "", free: false, tools: false};

function modelRow(m, st){
  const cur = m.id === st.model, curGate = m.id === st.small_model;
  const price = m.free ? "free" : (m.price_out != null ? `$${m.price_in}/$${m.price_out} per M` : "");
  const tags = [price, m.context ? Math.round(m.context/1000) + "k ctx" : ""]
               .filter(Boolean).join(" · ");
  return `<div class="tool" style="display:flex;align-items:center;gap:8px;padding:6px 8px">
    <code style="flex:1;word-break:break-all">${esc(m.id)}</code>
    <span class="meta" style="margin:0;white-space:nowrap">${esc(tags)}</span>
    ${m.reasoning ? `<span class="srcpill apple" title="thinks out loud before answering: fine for the loop, a poor fit for the gate's tiny token budget">reasoning</span>` : ""}
    ${curGate ? `<span class="srcpill">GATE</span>`
              : `<a class="reveal" data-id="${esc(m.id)}" onclick="switchModel(this.dataset.id,true)" title="use as the gate/summary model">gate</a>`}
    ${cur ? `<span class="srcpill" style="background:var(--good-soft);color:var(--good)">CURRENT</span>`
          : (m.tools === false ? `<span class="meta" style="margin:0" title="the loop needs tool calling">chat-only</span>`
                               : `<button class="save" data-id="${esc(m.id)}" onclick="switchModel(this.dataset.id)">use</button>`)}
  </div>`;
}

// Slot suggestions are transparent heuristics over catalog metadata (tools,
// price, context, reasoning), NOT a quality leaderboard. Loop: tool-capable,
// free first, then biggest context. Gate: cheap non-reasoning instruct-style.
const GATE_HINT = /instruct|gemma|haiku|flash|mini|nano|lite|small/;
function loopPicks(ms){
  return ms.filter(m => m.tools)
           .sort((a,b) => (b.free - a.free) || ((b.context||0) - (a.context||0))).slice(0, 4);
}
function gatePicks(ms){
  return ms.filter(m => m.tools !== false && m.reasoning !== true
                        && (m.free || (m.price_out != null && m.price_out <= 1.5)))
           .sort((a,b) => (GATE_HINT.test(b.id) - GATE_HINT.test(a.id))
                        || (b.free - a.free) || ((a.price_out||99) - (b.price_out||99))).slice(0, 4);
}

function renderCatalog(){
  const box = document.getElementById("catalog");
  if (!box || !modelCatalog) return;
  const all = modelCatalog.models || [];
  const head = document.getElementById("catalog-h");
  if (!modelCatalog.listed || !all.length){
    box.style.display = "none"; if (head) head.style.display = "none"; return;
  }
  box.style.display = ""; if (head) head.style.display = "";
  box.innerHTML = `
    <div class="cat-controls">
      <input id="cat-q" type="text" placeholder="filter models…" value="${esc(catFilter.q)}"
        onfocus="markEditing()" oninput="catFilter.q=this.value;renderCatalogList()">
      <label class="meta" style="margin:0"><input type="checkbox" id="cat-free" ${catFilter.free?"checked":""}
        onchange="catFilter.free=this.checked;renderCatalogList()"> free only</label>
      <label class="meta" style="margin:0"><input type="checkbox" id="cat-tools" ${catFilter.tools?"checked":""}
        onchange="catFilter.tools=this.checked;renderCatalogList()"> tool-capable only</label>
    </div>
    <div id="cat-list"></div>
    <div class="meta" id="free-switch-msg" style="margin-top:6px"></div>`;
  renderCatalogList();
}

function renderCatalogList(){
  const list = document.getElementById("cat-list");
  if (!list || !modelCatalog) return;
  const st = (D && D.settings) || {};
  const all = modelCatalog.models || [];
  const q = catFilter.q.trim().toLowerCase();
  const shown = all.filter(m => (!q || m.id.toLowerCase().includes(q))
                             && (!catFilter.free || m.free)
                             && (!catFilter.tools || m.tools));
  let h = "";
  if (!q && !catFilter.free && !catFilter.tools){
    h += `<div class="meta" style="margin:4px 0">Suggested picks: transparent heuristics from catalog metadata (tools, price, context), not a quality leaderboard</div>`;
    h += `<div class="meta" style="margin:6px 0 2px"><b>For the loop</b> (needs tool calling; free first, biggest context)</div>`;
    h += loopPicks(all).map(m => modelRow(m, st)).join("");
    h += `<div class="meta" style="margin:10px 0 2px"><b>For the gate</b> (cheap, terse, non-reasoning)</div>`;
    h += gatePicks(all).map(m => modelRow(m, st)).join("");
    h += `<div class="meta" style="margin:12px 0 2px"><b>Everything</b> (${all.length} models, by vendor)</div>`;
  } else {
    h += `<div class="meta" style="margin:4px 0">${shown.length} of ${all.length} models</div>`;
  }
  const vendors = {};
  shown.forEach(m => (vendors[m.id.split("/")[0]] ??= []).push(m));
  const expand = q || catFilter.free || catFilter.tools;
  h += Object.keys(vendors).sort().map(v => `
    <details ${expand ? "open" : ""}><summary><code>${esc(v)}</code>
      <span class="meta" style="margin-left:6px">${vendors[v].length}${vendors[v].some(m=>m.free) ? " · has free" : ""}</span></summary>
      ${vendors[v].map(m => modelRow(m, st)).join("")}
    </details>`).join("");
  list.innerHTML = h;
}

// One-click model switch: same /api/settings path as the Save button, keeping
// the other slot (main vs gate) as-is. Live for the next turn.
async function switchModel(id, asGate){
  const st = (D && D.settings) || {};
  const msg = document.getElementById("free-switch-msg");
  if (msg) msg.textContent = "switching…";
  const r = await postJSON("/api/settings", {
    provider: st.provider,
    model: asGate ? st.model : id,
    small_model: asGate ? id : st.small_model,
    keys: {},
  });
  if (msg) msg.textContent = r.error ? ("Error: " + r.error)
                                     : (asGate ? "Gate model is now " : "Model is now ") + id + ". Applies from your next message.";
  if (!r.error){ editing = false; await refresh(); }
}

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
    <pre>${esc(x.tool)}(${esc(JSON.stringify(x.args,null,1))})\n\n${esc(x.output)}</pre>
  </details>
</div>`;

const turnCard = t => `<div class="card">
  <div class="u">${esc(t.user_message)}</div>
  <div class="meta" style="margin-top:4px">${gateBadge(t.gate)}</div>
  ${(t.tools||[]).map(toolRow).join("")}
  <div class="r">${renderMarkdown(t.reply)}</div>
  <div class="meta">${esc((t.ts||"").replace("T"," ").slice(0,19))} · ${secs(t.latency_ms)} · ${t.iterations??"?"} iter · ${money(t.cost||0)}${t.consolidation?` · consolidated ${t.consolidation.new_facts} fact(s)`:""}</div>
</div>`;

const table = (heads, rows) => rows.length
  ? `<div class="card" style="padding:4px 8px"><table><tr>${heads.map(h=>`<th>${h}</th>`).join("")}</tr>${rows.join("")}</table></div>`
  : `<div class="card empty">nothing here yet</div>`;

const gateSplit = s => {
  if (!(s.gate_skips + s.gate_retrieves))
    return `<div class="splitbar"><div class="seg-skip" style="width:100%;opacity:.35"></div></div>
      <div class="meta" style="margin-top:6px">no turns yet — send a message and the gate starts deciding</div>`;
  const tot = s.gate_skips + s.gate_retrieves;
  const skipPct = Math.round(s.gate_skips/tot*100), retPct = 100-skipPct;
  // only label a segment when it's wide enough to fit the text — otherwise a
  // 0%/tiny segment spills its label past the bar (the "0 retri" bug).
  const seg = (cls, n, label, pct) =>
    `<div class="${cls}" style="width:${pct}%">${pct>=14?`${n} ${label}`:""}</div>`;
  return `<div class="splitbar">
    ${seg("seg-skip", s.gate_skips, "skipped", skipPct)}
    ${seg("seg-ret", s.gate_retrieves, "retrieved", retPct)}
  </div><div class="meta" style="margin-top:6px">the retrieval gate skipped memory on ${skipPct}% of turns — that's latency and bias saved</div>`;
};

// --- Chat gateway: type here, watch the harness run (turns kept in memory)
const CHAT = [];
const chatTurnCard = t => `<div class="card">
  ${t.gate?`<div class="stages"><span class="stage done">gate · ${esc(t.gate.decision)}</span>${(t.tools||[]).map(x=>`<span class="stage done">tool · ${esc(x.tool)}</span>`).join("")}<span class="stage done">reply</span></div>
    <div class="meta" style="margin:0 0 6px">${esc(t.gate.reason||"")}</div>`:""}
  ${(t.tools||[]).map(toolRow).join("")}
  <div class="r" style="margin-top:8px">${renderMarkdown(t.reply)}</div>
  <div class="meta">${secs(t.latency_ms)} · ${t.iterations??"?"} iter${t.consolidation?` · consolidated ${t.consolidation.new_facts} fact(s)`:""}</div>
</div>`;

// While a turn runs we stream it live: stages light up as the harness reaches
// them, and the reply text appears token by token (with a blinking caret).
const streamingCard = m => `<div class="card">
  <div class="stages">
    <span class="stage ${m.gate?"done":"on"}">gate${m.gate?` · ${esc(m.gate.decision)}`:""}</span>
    ${(m.tools||[]).map(x=>`<span class="stage done">tool · ${esc(x.tool)}</span>`).join("")}
    <span class="stage ${m.stream?"on":""}">reply</span>
  </div>
  ${m.gate&&m.gate.reason?`<div class="meta" style="margin:0 0 6px">${esc(m.gate.reason)}</div>`:""}
  ${(m.tools||[]).map(toolRow).join("")}
  ${m.stream
     ? `<div class="r" style="margin-top:8px">${renderMarkdown(m.stream)}<span class="caret"></span></div>`
     : `<div class="meta" style="margin:0">thinking&hellip;${m.started?` ${Math.round((Date.now()-m.started)/1000)}s`:""}${
         m.started && Date.now()-m.started > 20000
         ? `<br>still waiting: slow models (free tiers especially) can queue for a while; this errors out at the WAKU_LLM_TIMEOUT limit instead of hanging forever`
         : ""}</div>`}
</div>`;

// Messages loaded from history (a switched/opened conversation) have no live
// latency/iteration data, and their stored form carries an internal
// "[tools used: ...]" annotation — strip both so the thread reads cleanly.
const stripTools = t => (t || "").replace(/\s*\[tools used:[\s\S]*\]\s*$/, "").trim();
const historicalCard = m => `<div class="card"><div class="r">${renderMarkdown(stripTools(m.reply))}</div></div>`;

function renderChatLog(){
  if (!CHAT.length)
    return `<div class="empty" style="padding:6px 2px">Message Waku here from any tab. Open Overview to watch it flow through the harness, or the Gateway tab to see every channel's messages together.</div>`;
  return CHAT.map(m => m.role==="user"
      ? `<div class="bubble">${esc(m.text)}</div>`
      : m.pending ? streamingCard(m)
      : m.historical ? historicalCard(m)
      : chatTurnCard(m)).join("");
}

function syncChatLogs(){
  // one conversation, two surfaces: the Chat & watch tab and the side dock
  document.querySelectorAll(".chatlog").forEach(el => {
    el.innerHTML = renderChatLog();
    el.scrollTop = el.scrollHeight;      // dock scrolls its own container
  });
}

// One streamed harness event updates the live card in place.
function applyStreamEvent(pending, ev){
  if (ev.kind === "gate") pending.gate = {decision: ev.decision, reason: ev.reason};
  else if (ev.kind === "text") pending.stream = (pending.stream || "") + (ev.delta || "");
  else if (ev.kind === "tool"){
    (pending.tools = pending.tools || []).push({
      tool: ev.tool, args: ev.args, output: ev.output,
      status: (ev.output||"").toLowerCase().startsWith("error") ? "error" : "ok",
      summary: (ev.output || "").split(". ")[0].slice(0,120)});
    pending.stream = "";   // a new assistant turn begins after the tool result
  } else if (ev.kind === "done"){
    pending.pending = false; pending.stream = "";
    if (ev.error) pending.reply = "Error: " + ev.error;
    else Object.assign(pending, ev);   // reply, tools, gate, iterations, latency_ms, consolidation
  }
}

async function sendChat(fromInput){
  const input = fromInput || document.getElementById("msg") || document.getElementById("dmsg");
  const text = (input && input.value || "").trim();
  if (!text) return;
  input.value = "";
  CHAT.push({role:"user", text});
  const pending = {role:"waku", pending:true, stream:"", started: Date.now()};
  CHAT.push(pending);
  syncChatLogs();
  // tick the elapsed counter while we wait for the first token
  const ticker = setInterval(() => { if (pending.pending && !pending.stream) syncChatLogs(); }, 1000);
  try {
    const res = await fetch("/api/chat/stream", {method:"POST",
      headers:{"Content-Type":"application/json"}, body:JSON.stringify({message:text})});
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;){
      const {value, done} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream:true});
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0){
        const line = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!line.startsWith("data:")) continue;
        try { applyStreamEvent(pending, JSON.parse(line.slice(5).trim())); } catch(e){}
        syncChatLogs();
      }
    }
  } catch(e){ Object.assign(pending, {pending:false, reply:"Error: "+e}); }
  clearInterval(ticker);
  if (pending.pending) pending.pending = false;   // stream ended without a 'done'
  syncChatLogs();
  input.focus();
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
    <!-- The gateway is the door IN and OUT: the reply leaves through the very
         gateway it arrived at (Telegram sends it, the CLI prints it, voice
         speaks it, the dashboard streams it). A clean over-the-top arc. -->
    <path class="flow" data-edge="e-reply-gw" d="M604 82 C548 40 172 40 100 70" marker-end="url(#arr)"/>
    ${flowLbl(352,32,"reply, out the same gateway","middle")}
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
    <textarea class="sqlbox" id="sqlbox" spellcheck="false" onfocus="markEditing()" oninput="markEditing()">${esc(QUERY_EXAMPLES[0])}</textarea>
    <div style="margin:8px 0"><button class="save" onclick="runQuery()">Run</button>
      <span class="meta" style="margin-left:12px">try: ${QUERY_EXAMPLES.map(q=>`<span class="qexample" onclick="qFill(this.textContent)">${esc(q)}</span>`).join(" &nbsp; ")}</span></div>
    <div id="qout"></div>`;
}

// --- chat sessions (the "New chat" + history picker, like a chat app)
let SESSION = "default";
async function newChat(){
  const r = await postJSON("/api/session", {action:"new"});
  if (r.session_id){ liveView = null; SESSION = r.session_id; CHAT.length = 0; syncChatLogs(); }
  closeSessMenu();
}
async function switchSession(id){
  const r = await postJSON("/api/session", {action:"switch", id});
  if (r.ok){
    SESSION = r.session_id; CHAT.length = 0;
    (r.history||[]).forEach(m => CHAT.push(m.role==="user"
      ? {role:"user", text:m.content} : {role:"waku", reply:m.content, historical:true}));
    syncChatLogs();
  }
  closeSessMenu();
}
// Open a conversation from the Gateway inbox: load it into the dock (the active
// thread), keep it live-synced (so new Telegram/voice messages appear), and make
// sure the dock is visible.
let liveView = null;   // a conversation opened from the inbox, kept live-updated
async function openConversation(id){
  document.body.classList.remove("dock-closed");
  localStorage.setItem("dockClosed", "0");
  liveView = id;
  await switchSession(id);   // switch the agent so a reply continues this thread
  render();                  // reflect the active-session highlight in the inbox
}
// Re-pull the opened conversation each refresh so incoming messages from another
// gateway (your phone) show up live — unless a turn is mid-stream in the dock.
async function syncLiveView(){
  if (!liveView || CHAT.some(m => m.pending)) return;
  const r = await postJSON("/api/session", {action:"history", id:liveView});
  if (!r.ok) return;
  const fresh = (r.history||[]).map(m => m.role==="user"
    ? {role:"user", text:m.content} : {role:"waku", reply:m.content, historical:true});
  if (fresh.length !== CHAT.length){   // only redraw when it actually changed
    CHAT.length = 0; fresh.forEach(m => CHAT.push(m)); syncChatLogs();
  }
}
function closeSessMenu(){ const m=document.getElementById("sessmenu"); if(m) m.remove(); }
function toggleSessMenu(ev){
  ev.stopPropagation();
  if (document.getElementById("sessmenu")){ closeSessMenu(); return; }
  const sessions = (D && D.sessions) || [];
  const menu = document.createElement("div");
  menu.className = "sessmenu"; menu.id = "sessmenu";
  menu.innerHTML = sessions.length ? sessions.map(s => {
    const tags = (s.sources||[]).map(src => `<span class="gwtag ${esc(src)}">${esc(src)}</span>`).join("");
    return `<div class="sessitem ${s.id===SESSION?"on":""}" onclick="openConversation('${esc(s.id)}')">
      <div>${esc(s.title||s.id)} ${tags}</div>
      <div class="sm">${s.messages} msg · ${esc((s.last_at||"").slice(0,16).replace("T"," "))}</div>
    </div>`;
  }).join("") : `<div class="sessitem">no past conversations yet</div>`;
  const r = ev.currentTarget.getBoundingClientRect();
  menu.style.top = (r.bottom+6)+"px";
  menu.style.left = Math.max(8, r.right-300)+"px";
  document.body.appendChild(menu);
}
document.addEventListener("click", e => {
  const m = document.getElementById("sessmenu");
  if (m && !m.contains(e.target)) closeSessMenu();
});
// --- read-only SQL console (item: "a simple query editor like Supabase")
function qFill(sql){ const b=document.getElementById("sqlbox"); if(b){ b.value=sql; runQuery(); } }
async function runQuery(){
  editing = true;   // keep the 5s refresh from wiping the query + results
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
      <b>Memory vs Database — two views of one file.</b>
      <div class="r">This tab is the curated, per-pillar view of what Waku remembers. The
      <a class="reveal" onclick="location.hash='database'">Database tab</a> shows the exact same
      thing as raw SQLite tables (plus the FTS5 keyword index). Same
      <code>.waku/state.db</code> — different altitude.
      <br><br>Some assistants (Hermes) keep memory as a single <code>MEMORY.md</code> file. Waku keeps
      the queryable source in <code>state.db</code> (facts + episodes, FTS5-searchable) <b>and</b> writes a
      human-readable ${reveal("MEMORY.md","MEMORY.md")} mirror after every turn — so you get both: a real file
      you can open, backed by a sturdy database.</div></div>
    <h2>The three pillars</h2>
    <div class="tiles" style="grid-template-columns:repeat(auto-fill,minmax(220px,1fr))">${pillars}</div>
    <h2>Retrieval gate — does this turn even need memory?</h2>${gateSplit(s)}
    <div class="meta" style="margin-top:8px">A cheap model decides <b>if</b> a turn needs memory at all, before any lookup —
      this is memory <i>retrieval</i>, the hero decision. (The Ops tab charts the same skip/retrieve
      numbers as an operational metric; the decision itself is memory's.)</div>
    <div class="meta" style="margin-top:14px">Files: ${reveal("state.db","state.db")} · ${reveal("MEMORY.md","MEMORY.md")} · ${reveal("SOUL.md","SOUL.md")} · ${reveal("skills","skills/")}</div>`;
}
function memSemantic(d){
  let h = `<div class="meta" style="margin-bottom:12px">Durable facts distilled from what you tell Waku —
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
    (the big one) on the Database tab — episodes are its highlights.</span></div>`;
  h += `<div class="card" style="padding:4px 8px"><table><tr><th>date</th><th>episode</th><th></th></tr>${
    d.episodes.map(e => `<tr><td class="meta">${esc(e.happened_at)}</td><td>${esc(e.summary)}</td>
      <td><a class="reveal del" onclick="delMem('delete_episode',${e.id})">delete</a></td></tr>`).join("")}</table></div>`;
  return h;
}
function memSkills(d){
  let h = `<div class="meta" style="margin-bottom:12px">Procedural memory — markdown instructions loaded
    only when a message matches. Add your own three ways: teach Waku in chat (it calls
    <code>create_skill</code>), edit a skill below, or drop a <code>SKILL.md</code> into ${reveal("skills","the skills folder")}.</div>`;
  h += d.skills.map((sk,i) => {
    const full = `---
name: ${sk.name}
description: ${sk.description}
---

${sk.body}`;
    return `<div class="card">
      <div class="u"><code>${esc(sk.name)}</code> <span class="meta" style="font-weight:400">· ${esc(sk.description)}</span>
        <span class="srcpill ${sk.editable?"":"apple"}" style="margin-left:6px">${sk.editable?"home":"built-in"}</span></div>
      <textarea class="editor" id="sk-${i}" style="min-height:150px;margin-top:8px" data-path="${esc(sk.path)}"
        oninput="dirty('sksave-${i}')" onfocus="markEditing()">${esc(full)}</textarea>
      <div style="margin-top:8px"><button class="save" id="sksave-${i}" disabled onclick="saveSkill(${i})">Save SKILL.md</button>
        <span class="meta" id="skmsg-${i}" style="margin-left:10px">${esc(sk.rel)}</span></div></div>`;
  }).join("") || `<div class="card empty">no skills loaded</div>`;
  return h;
}
function memSoul(d){
  return `<div class="meta" style="margin-bottom:12px">SOUL.md is Waku's persona — the system prompt it
    loads every turn. Editing it changes who your Waku is. Changes are live next turn.</div>
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
    <div class="r">MCP lets Waku borrow tools from any external server (files, GitHub, a database, …),
    namespaced <code>&lt;server&gt;_&lt;tool&gt;</code>. ${m.configured
      ? `Configured servers: ${m.servers.map(s=>`<code>${esc(s)}</code>`).join(" ")}${m.live?"":" — start a chat to connect them."}`
      : "None configured yet."}</div></div>`;
  h += `<h2>Connect one (30 seconds)</h2><div class="card">
    <div class="meta">1 — install the extra: <code>pip install -e '.[mcp]'</code></div>
    <div class="meta" style="margin-top:6px">2 — create ${reveal("","the .waku folder")}<code>/mcp.json</code>:</div>
    <pre style="font-family:var(--mono);font-size:11.5px;color:var(--ink2);white-space:pre-wrap;margin-top:8px">{"servers": [
  {"name": "fs", "command": "npx",
   "args": ["-y", "@modelcontextprotocol/server-filesystem", "${esc(D&&D.home||"")}"]}
]}</pre>
    <div class="meta" style="margin-top:8px">3 — restart the dashboard. The server's tools appear above under
      <a class="reveal" onclick="location.hash='tools/available'">Available ▸ MCP servers</a>, callable in chat.</div></div>`;
  h += `<div class="meta" style="margin-top:12px">The same pattern scales: any MCP server (yours or a vendor's)
    plugs in the same way — no code changes to Waku. Skills work the same way — drop a <code>SKILL.md</code>
    in ${reveal("skills","skills/")}.</div>`;
  return h;
}

const VIEWS = {
  // Gateway: ONE unified conversation across every channel (dashboard, telegram,
  // voice, cli) — the same loop + memory answer all of them. Each message is
  // tagged with where it came in, Hermes-style. You type in the dock on the right.
  // Gateway = an INBOX of conversations (like Slack/Intercom): one row per
  // conversation, tagged with its channel(s). Click one to open it in the chat
  // dock (the active thread). No longer a flat stream that duplicates the dock.
  gateway(d){
    const sessions = d.sessions || [];
    let h = `<div class="meta" style="margin-bottom:14px">Every conversation across every channel —
      web, phone (Telegram), voice, terminal — answered by the same brain. Click one to open it in the
      chat dock &rarr;. This is the inbox; the dock is the open thread.</div>`;
    if (!sessions.length)
      return h + `<div class="card empty">no conversations yet — say something in the chat dock &rarr;</div>`;
    h += sessions.map(s => {
      const tags = (s.sources||[]).map(src => `<span class="gwtag ${esc(src)}">${esc(src)}</span>`).join("");
      const on = s.id === SESSION;
      return `<div class="toolcard" style="cursor:pointer${on?';border-color:var(--accent)':''}" onclick="openConversation('${esc(s.id)}')">
        <div class="tn" style="display:flex;justify-content:space-between;align-items:baseline;gap:10px">
          <span>${esc(s.title||s.id)} ${tags}</span>
          <span class="meta" style="font-weight:400;white-space:nowrap">${s.messages} msg · ${esc((s.last_at||"").slice(0,16).replace("T"," "))}</span></div>
        <div class="td">${esc(s.last||"")}</div></div>`;
    }).join("");
    return h;
  },
  overview(d){
    const s = d.stats;
    const u = d.usage || {total_cost:0};
    const tiles = [
        [money(u.total_cost),"spent · all-time","money"],[secs(s.latency_avg),"avg turn",""],
        [s.turns,"turns",""],[s.tool_calls,"tool calls",""],
        [d.facts.length,"facts",""],[d.calendar.length,"events",""],
      ].map(([v,l,c])=>`<div class="tile"><b class="${c}">${v}</b><span>${l}</span></div>`).join("");
    return `<div class="tiles">${tiles}</div>
    <h2>Retrieval gate — the hero decision</h2>${gateSplit(s)}
    <h2 style="margin-top:26px">Architecture — click any box <span class="arch-status"></span></h2>
    ${archSVG(d)}
    <h2>Latest turn</h2>${d.turns.length?turnCard(d.turns[0]):'<div class="card empty">no turns yet — talk to Waku first</div>'}`;
  },
  loop(d){
    return d.turns.length ? d.turns.map(turnCard).join("") : `<div class="card empty">no turns yet</div>`;
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
    let h = `<div class="card">Current: <b>${esc(st.provider)}</b> · loop brain <code>${esc(st.model)}</code> · gate &amp; summarizer <code>${esc(st.small_model)}</code><div class="meta" style="margin:4px 0 0">two jobs, two brains: the loop brain answers you; the small gate model decides memory retrieval and distills chats</div></div>`;
    h += `<h2>Provider &amp; keys (BYOK)</h2><div class="card">
      <label class="fld">Provider
        <select id="set-provider" onfocus="markEditing()">${st.providers.map(p=>`<option value="${p.name}" ${p.name===st.provider?"selected":""}>${p.name}${p.name===st.provider?` — now: ${esc(st.model)}`:` — provider default: ${esc(p.default_model)}`}</option>`).join("")}</select></label>
      ${st.base_url?`<div class="meta" style="margin:4px 0 8px">Custom endpoint active: <code>${esc(st.base_url)}</code> (WAKU_BASE_URL${st.custom_key_set?" + WAKU_API_KEY":""}). The model list below comes from it.</div>`:""}
      <details class="adv"><summary>Type a model id manually (advanced; the catalog below switches in one click)</summary>
      <label class="fld">Model (runs the loop; needs tool calling) <input id="set-model" list="model-list" onfocus="markEditing()" placeholder="blank = provider default" value="${st.model===st.providers.find(p=>p.name===st.provider)?.default_model?"":esc(st.model)}"></label>
      <label class="fld">Gate / summary model (the small model that decides whether a message needs memory, and distills chats into facts; pick something cheap and terse) <input id="set-small-model" list="model-list" onfocus="markEditing()" placeholder="blank = provider default" value="${st.small_model===st.providers.find(p=>p.name===st.provider)?.default_small_model?"":esc(st.small_model)}"></label>
      <datalist id="model-list"></datalist>
      <div class="meta" id="model-list-msg" style="margin:4px 0 8px"></div></details>${(setTimeout(loadModelList,0),"")}
      <details class="adv" ${st.providers.find(p=>p.name===st.provider)?.key_set?"":"open"}><summary>API keys (${st.providers.find(p=>p.name===st.provider)?.key_set?`${esc(st.provider)} key set`:`${esc(st.provider)} key needed`})</summary>
      <div class="meta" style="margin:10px 0 4px">Keys stay in your local <code>.env</code> — never sent back to this page (only a set/not-set status and the last 4 digits). Leave a field blank to keep the current key.</div>
      ${st.providers.map(p=>`<label class="fld"><span>${p.name} key <span class="meta">(${p.key_env})</span>
        ${p.key_set?`<span class="srcpill" style="background:var(--good-soft);color:var(--good)">set ····${esc(p.key_last4)}</span>`
                   :`<span class="srcpill apple">not set</span>`}</span>
        <input type="password" data-key="${p.key_env}" placeholder="${p.key_set?"key on file — blank keeps it":"paste key"}"></label>`).join("")}
      </details>
      <div style="margin-top:12px"><button class="save" onclick="saveSettings()">Save &amp; switch</button>
        <span class="meta" id="set-msg" style="margin-left:10px"></span></div>
    </div>
    <h2 id="catalog-h" style="display:none">Model catalog: click to switch</h2>
    <div class="card" id="catalog" style="display:none"></div>
    <h2>Web search key (optional)</h2><div class="card">
      <div class="meta" style="margin-bottom:8px">A free <a class="reveal" onclick="window.open('https://tavily.com','_blank')">Tavily</a> key makes the <code>search_web</code> tool reliable (the World Cup demo). Stored in your local <code>.env</code>, same as above.</div>
      <label class="fld"><span>Tavily key <span class="meta">(${esc(st.search_key_env||"TAVILY_API_KEY")})</span>
        ${st.search_key_set?`<span class="srcpill" style="background:var(--good-soft);color:var(--good)">set ····${esc(st.search_key_last4)}</span>`
                          :`<span class="srcpill apple">not set</span>`}</span>
        <input type="password" data-key="TAVILY_API_KEY" placeholder="${st.search_key_set?"key on file — blank keeps it":"paste key"}"></label>
      <div style="margin-top:12px"><button class="save" onclick="saveSettings()">Save</button>
        <span class="meta" style="margin-left:10px">reads live — no restart needed for search</span></div>
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
      ${t.apple_on?"":"Apple tools are off (set <code>WAKU_APPLE_TOOLS=1</code>). "}Connect more via
      <a class="reveal" onclick="location.hash='tools/mcp'">MCP</a>.</div>`;
    const SRC = [["flagship","Flagship task — scheduling"],["web","Web search"],
      ["self-management","Self-management — it edits its own memory"],
      ["apple","Apple ecosystem"],["mcp","MCP servers"],["other","Other"]];
    SRC.forEach(([key,label]) => {
      const items = t.catalog.filter(c => c.source === key);
      if (!items.length) return;
      h += `<h2>${label}</h2>`;
      h += items.map(c => `<div class="toolcard">
        <div class="tn">${esc(c.name)}<span class="srcpill ${key==="mcp"?"mcp":key==="apple"?"apple":""}">${esc(key)}</span></div>
        <div class="td">${esc(c.description)}</div></div>`).join("");
    });
    // Roadmap: whiteboard boxes not wired in yet — set expectations, don't over-promise.
    if ((t.planned||[]).length){
      h += `<h2>Coming soon <span class="meta" style="font-weight:400">· on the architecture chart, not wired in yet (opt in with <code>WAKU_EXPERIMENTAL=1</code>)</span></h2>`;
      h += t.planned.map(p => `<div class="toolcard" style="opacity:.7">
        <div class="tn">${esc(p.name)}<span class="srcpill apple">soon · ${esc(p.box)}</span></div>
        <div class="td">${esc(p.description)}</div></div>`).join("");
    }
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
      <b>Database vs Memory.</b> <span class="r">This is the raw persistence layer — the literal SQLite
      tables. The <a class="reveal" onclick="location.hash='memory'">Memory tab</a> is the friendly
      view of the same rows (facts, episodes, skills, persona). One file, two altitudes. Where Hermes
      uses a <code>MEMORY.md</code> file, Waku uses these queryable tables — and mirrors them to a
      readable <code>MEMORY.md</code> too.</span></div>`;
    h += `<div class="card">
      <div class="u" style="font-family:var(--mono);font-size:12.5px;word-break:break-all">${esc(db.path)}</div>
      <div class="meta">${kb} KB on disk · SQLite + FTS5 · open it yourself: <code>sqlite3 .waku/state.db</code></div>
      <div class="meta" style="margin-top:8px">${reveal("state.db","reveal state.db in Finder")} &nbsp;·&nbsp; ${reveal("","open the .waku folder")}</div></div>`;
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
    const u = d.usage || {calls:0,total_in:0,total_out:0,total_cost:0,by_day:[],by_provider:[]};
    let h = `<div class="tiles">${[
        [money(u.total_cost),"spent · all-time","money"],[u.total_in.toLocaleString(),"tokens in · all-time",""],
        [u.total_out.toLocaleString(),"tokens out · all-time",""],[u.calls.toLocaleString(),"LLM calls",""],
        [secs(s.latency_avg),"avg turn",""],[`${s.tool_errors}`,"tool errors",""],
      ].map(([v,l,c])=>`<div class="tile"><b class="${c}">${v}</b><span>${l}</span></div>`).join("")}</div>`;

    h += `<h2>Spend <span class="meta" style="font-weight:400">· permanent ledger — survives a demo reset</span></h2>`;
    h += `<div class="card"><span class="r">Every LLM call's tokens are logged to
      <code>.waku/usage.jsonl</code> (append-only, never wiped). Dollar cost is estimated from tokens
      × current pricing — the tokens are the ground truth. ${reveal("usage.jsonl","open usage.jsonl")}</span></div>`;
    if ((u.by_provider||[]).length){
      h += table(["provider","LLM calls","tokens in","tokens out","cost (est)"], u.by_provider.map(p =>
        `<tr><td><code>${esc(p.provider)}</code></td><td class="meta">${p.calls}</td>
          <td class="meta">${p.in.toLocaleString()}</td><td class="meta">${p.out.toLocaleString()}</td>
          <td class="meta">${money(p.cost)}</td></tr>`));
    }
    if ((u.by_day||[]).length){
      h += `<h2>Spend per day</h2>`;
      h += table(["day","LLM calls","tokens in","tokens out","cost (est)"], u.by_day.map(r =>
        `<tr><td class="meta">${esc(r.date)}</td><td class="meta">${r.calls}</td>
          <td class="meta">${r.in.toLocaleString()}</td><td class="meta">${r.out.toLocaleString()}</td>
          <td class="meta">${money(r.cost)}</td></tr>`));
    }

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
      : `<div class="card empty">no trace lines yet — talk to Waku</div>`;
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
                database:"Database — everything Waku stores (state.db)"};
function render(){
  if (!D) return;
  const [v, subRaw] = (location.hash||"#overview").slice(1).split("/");
  const sub = subRaw || null;
  const view = VIEWS[v] ? v : "overview";
  const subChanged = sub !== activeSub || view !== activeView;
  document.querySelectorAll("nav a").forEach(a=>a.classList.toggle("on", a.dataset.v===view));
  document.getElementById("title").textContent = TITLES[view] || view[0].toUpperCase()+view.slice(1);
  if (view === "overview"){
    // don't rebuild mid-animation or the glowing SVG gets wiped
    if (activeView !== "overview" || !animating){ document.getElementById("view").innerHTML = VIEWS.overview(D); }
  } else if ((view === "memory" || view === "settings" || view === "database") && editing && !subChanged){
    // don't wipe an in-progress edit on the 5s refresh — but DO switch sub-tabs
  } else {
    editing = false;
    document.getElementById("view").innerHTML = VIEWS[view](D, sub);
  }
  activeView = view; activeSub = sub;
  document.getElementById("model").textContent = `${D.provider} · ${D.model}`;
  document.getElementById("n-gw").textContent = (D.chat_log||[]).length;
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
let dockRestored = false;
async function restoreDock(){
  // On page load the dock is empty even though the current thread has messages
  // — restore them so a refresh never looks like it lost the chat.
  dockRestored = true;
  const sid = D && D.current_session;
  if (!sid || CHAT.length) return;
  SESSION = sid;
  const r = await postJSON("/api/session", {action:"history", id:sid});
  if (r.history && r.history.length && !CHAT.length){
    r.history.forEach(m => CHAT.push(m.role==="user"
      ? {role:"user", text:m.content}
      : {role:"assistant", reply:m.content, historical:true}));
    syncChatLogs();
  }
}
async function refresh(){
  try {
    D = await (await fetch("/api/data")).json(); lastFetch = Date.now();
    render(); tickLive();
    syncLiveView();   // live-update an opened conversation (e.g. new phone messages)
    if (!dockRestored) restoreDock();
  } catch(e){ /* server restarting — keep showing last data */ }
}
// --- resizable columns: drag the thin handle between nav|main and main|dock.
// Width lives in a CSS var + localStorage, so it survives refreshes.
function wireResizer(id, cssVar, key, fromRight, min, max){
  const el = document.getElementById(id);
  if (!el) return;
  el.onmousedown = e => {
    e.preventDefault();
    document.body.classList.add("resizing");
    const move = ev => {
      let w = fromRight ? (window.innerWidth - ev.clientX) : ev.clientX;
      w = Math.max(min, Math.min(max, w));
      document.documentElement.style.setProperty(cssVar, w + "px");
      localStorage.setItem(key, w);
    };
    const up = () => { document.body.classList.remove("resizing");
      document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  };
}
function wireChrome(){
  // restore saved widths
  const nw = localStorage.getItem("navW"); if (nw) document.documentElement.style.setProperty("--nav-w", nw+"px");
  const dw = localStorage.getItem("dockW"); if (dw) document.documentElement.style.setProperty("--dock-w", dw+"px");
  wireResizer("nav-resizer", "--nav-w", "navW", false, 150, 380);
  wireResizer("dock-resizer", "--dock-w", "dockW", true, 260, 680);
  // hide / show the sidebar
  const setNav = v => { document.body.classList.toggle("nav-hidden", v); localStorage.setItem("navHidden", v?"1":"0"); };
  const nt = document.getElementById("nav-toggle"), nr = document.getElementById("nav-reopen");
  if (nt) nt.onclick = () => setNav(true);
  if (nr) nr.onclick = () => setNav(false);
  setNav(localStorage.getItem("navHidden") === "1");
}

// --- voice on the dashboard: record in the browser, transcribe on the server
// with the SAME local Whisper `make voice` uses. Text lands in the input for
// you to review, then Send — nothing leaves the machine.
// Voice capture records WAV (uncompressed PCM) via the Web Audio API — NOT
// MediaRecorder's WebM/Opus, which faster-whisper/PyAV often can't decode
// ("transcription failed [Errno …]"). WAV is trivially decodable server-side.
let micCtx = null, micStream = null, micNode = null, micBuf = [], micOn = false;
const micHint = (msg) => { const i = document.getElementById("dmsg");
  if (i){ i.placeholder = msg; setTimeout(()=>{ i.placeholder = "Message Waku…"; }, 8000); } };

async function toggleMic(){
  const btn = document.getElementById("mic");
  if (micOn){ await stopMic(); return; }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){
    micHint("voice needs a normal browser tab at localhost:7777 — not the IDE preview pane");
    return;
  }
  try {
    micStream = await navigator.mediaDevices.getUserMedia({audio:true});
    micCtx = new (window.AudioContext || window.webkitAudioContext)();
    const source = micCtx.createMediaStreamSource(micStream);
    micNode = micCtx.createScriptProcessor(4096, 1, 1);
    micBuf = [];
    micNode.onaudioprocess = e => micBuf.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    source.connect(micNode); micNode.connect(micCtx.destination);
    micOn = true; btn.classList.add("rec");
  } catch(e){
    console.warn("mic error:", e);
    micHint(e && e.name === "NotAllowedError"
      ? "mic blocked — click the lock icon in the address bar → allow Microphone → reload (macOS: also System Settings ▸ Privacy ▸ Microphone ▸ your browser)"
      : "mic unavailable: " + (e && e.message || e));
  }
}

async function stopMic(){
  const btn = document.getElementById("mic"), input = document.getElementById("dmsg");
  micOn = false; btn.classList.remove("rec");
  try { micNode.disconnect(); } catch(e){}
  micStream.getTracks().forEach(t => t.stop());
  const rate = micCtx.sampleRate;
  micCtx.close();
  const wav = encodeWAV(micBuf, rate);
  const hold = input.placeholder; input.placeholder = "transcribing…";
  let r; try { r = await (await fetch("/api/voice", {method:"POST", body:wav})).json(); }
  catch(e){ r = {error:String(e)}; }
  input.placeholder = hold;
  if (r.error){ input.value = ""; micHint("voice: " + r.error); return; }
  if (r.text){ input.value = r.text; input.focus(); }
}

// float32 chunks → 16-bit PCM mono WAV blob
function encodeWAV(chunks, rate){
  let n = 0; chunks.forEach(c => n += c.length);
  const pcm = new Float32Array(n); let off = 0; chunks.forEach(c => { pcm.set(c, off); off += c.length; });
  const buf = new ArrayBuffer(44 + pcm.length * 2), view = new DataView(buf);
  const str = (o, s) => { for (let i=0;i<s.length;i++) view.setUint8(o+i, s.charCodeAt(i)); };
  str(0,"RIFF"); view.setUint32(4, 36 + pcm.length*2, true); str(8,"WAVE"); str(12,"fmt ");
  view.setUint32(16,16,true); view.setUint16(20,1,true); view.setUint16(22,1,true);
  view.setUint32(24,rate,true); view.setUint32(28,rate*2,true); view.setUint16(32,2,true); view.setUint16(34,16,true);
  str(36,"data"); view.setUint32(40, pcm.length*2, true);
  let o = 44; for (let i=0;i<pcm.length;i++){ const s = Math.max(-1, Math.min(1, pcm[i])); view.setInt16(o, s<0 ? s*0x8000 : s*0x7FFF, true); o += 2; }
  return new Blob([view], {type:"audio/wav"});
}
function wireMic(){ const b = document.getElementById("mic"); if (b) b.onclick = toggleMic; }

window.addEventListener("hashchange", render);
window.__hold = (v)=>{ animating = v; };   // test hook: freeze the diagram
wireDock(); wireChrome(); wireMic();
refresh(); setInterval(refresh, 5000); setInterval(tickLive, 1000);
pollEvents(); setInterval(pollEvents, 450);   // live harness animation
