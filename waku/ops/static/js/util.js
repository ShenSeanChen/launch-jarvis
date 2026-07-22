// waku dashboard — escaping, markdown, core globals (D/editing), postJSON, reveal.
// Split out of app.js: classic <script>, shared global scope (no build
// step, no modules). Load order + rules: static/README.md.

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
