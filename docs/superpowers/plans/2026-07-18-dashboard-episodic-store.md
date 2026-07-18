# Dashboard-configurable episodic store (sqlite | notion) implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users switch the episodic-memory backend between local SQLite (default) and a Notion database from the dashboard Settings page, persisting via `WAKU_EPISODIC_STORE` + `NOTION_TOKEN` + `NOTION_EPISODES_DATABASE_ID` in `.env`.

**Architecture:** Mirror the existing `semantic_store` (sqlite/supabase) pattern: a `Settings.episodic_store` env-backed field, a `Memory._make_episode_store` factory, and the dashboard's existing `/api/settings` write path (`apply_settings` → `.env` → rebuild agent). Dashboard reads (`collect()`) and deletes (`memory_action`) route episodes through the active backend.

**Tech Stack:** Python 3.11+, `notion-client>=2.5` (data-sources API, behind `[notion]` extra), pytest, vanilla JS dashboard (no build step).

**Spec:** `docs/superpowers/specs/2026-07-18-dashboard-episodic-store-design.md`

---

## File structure

- **Modify** `waku/config.py` — add `episodic_store` field.
- **Modify** `.env.example` — document the three Notion env vars.
- **Modify** `waku/memory/__init__.py` — `_make_episode_store` factory.
- **Modify** `waku/ops/dashboard.py` — `apply_settings` whitelist + validation, `settings_info` exposure, `collect()` episodes routing, `memory_action` delete routing.
- **Modify** `waku/ops/static/js/views.js` — settings card, episodic tab badge/error, database-page note.
- **Modify** `waku/ops/static/js/models.js` — send `episodic_store` in `/api/settings` payload.
- **Create** `evals/deterministic/test_episodic_store_switch.py` — all new deterministic tests.

---

### Task 1: Add `episodic_store` to Settings + document env vars

**Files:**
- Modify: `waku/config.py:49-50`
- Modify: `.env.example:136-141`
- Test: `evals/deterministic/test_episodic_store_switch.py`

- [ ] **Step 1: Write the failing test**

Create `evals/deterministic/test_episodic_store_switch.py`:

```python
"""Deterministic tests for the sqlite|notion episodic-store switch."""

from __future__ import annotations

import sys
import types

import pytest

from waku.config import Settings
from waku.memory import Memory
from waku.memory.episodic.store import SqliteEpisodeStore


class _FakeNotionClient:
    """In-memory fake for notion_client.Client (>= 2.5, data-sources API).

    Pages are class-level so a store created inside dashboard code sees the
    same rows as one created in the test body."""

    _pages: list[dict] = []

    def __init__(self, auth: str | None = None) -> None:
        self.auth = auth
        self.databases = types.SimpleNamespace(retrieve=self._retrieve)
        self.data_sources = types.SimpleNamespace(query=self._query)
        self.pages = types.SimpleNamespace(create=self._create, update=self._update)

    def _retrieve(self, *, database_id: str) -> dict:
        assert database_id == "test-db-id"
        return {"data_sources": [{"id": "test-ds-id"}]}

    def _create(self, *, parent: dict, properties: dict) -> dict:
        cls = type(self)
        page = {
            "id": f"page-{len(cls._pages) + 1}",
            "parent": parent,
            "properties": properties,
            "created_time": "2026-07-18T00:00:00.000Z",
        }
        cls._pages.append(page)
        return page

    def _update(self, *, page_id: str, archived: bool) -> dict:
        for page in type(self)._pages:
            if page["id"] == page_id:
                page["archived"] = archived
                return page
        return {}

    def _query(self, *, data_source_id: str, start_cursor: str | None = None) -> dict:
        assert data_source_id == "test-ds-id"
        return {"results": list(type(self)._pages), "has_more": False}


@pytest.fixture
def fake_notion(monkeypatch):
    _FakeNotionClient._pages = []
    fake_module = types.ModuleType("notion_client")
    fake_module.Client = _FakeNotionClient
    monkeypatch.setitem(sys.modules, "notion_client", fake_module)
    monkeypatch.setenv("NOTION_TOKEN", "test-token")
    monkeypatch.setenv("NOTION_EPISODES_DATABASE_ID", "test-db-id")
    return _FakeNotionClient


def test_settings_defaults_to_sqlite(monkeypatch):
    monkeypatch.delenv("WAKU_EPISODIC_STORE", raising=False)
    assert Settings().episodic_store == "sqlite"


def test_settings_reads_episodic_store_env(monkeypatch):
    monkeypatch.setenv("WAKU_EPISODIC_STORE", "notion")
    assert Settings().episodic_store == "notion"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest evals/deterministic/test_episodic_store_switch.py -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'episodic_store'` (and `ImportError` is NOT expected — `waku.memory` imports fine already).

- [ ] **Step 3: Add the Settings field**

In `waku/config.py`, directly after the `semantic_store` field (line 50), add:

```python
    # 'sqlite' (default, zero setup) or 'notion' (episodes live in a Notion database).
    episodic_store: str = field(default_factory=lambda: os.getenv("WAKU_EPISODIC_STORE", "sqlite"))
```

- [ ] **Step 4: Document the env vars**

Append to `.env.example` (after the Supabase block at the end of the file):

```
# ── Notion episodic memory (optional): pip install -e '.[notion]' ───────────
# Store episodes (dated memory summaries) in a Notion database instead of the
# local state.db. Create an integration at https://www.notion.so/my-integrations,
# share a database with it (properties: Name = title, Summary = rich text), and
# copy the database id from its URL (the 32-char segment before "?v="):
# WAKU_EPISODIC_STORE=notion
# NOTION_TOKEN=ntn_...
# NOTION_EPISODES_DATABASE_ID=...
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest evals/deterministic/test_episodic_store_switch.py -q`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add waku/config.py .env.example evals/deterministic/test_episodic_store_switch.py
git commit -m "feat: WAKU_EPISODIC_STORE setting for episodic backend selection"
```

---

### Task 2: `Memory._make_episode_store` factory

**Files:**
- Modify: `waku/memory/__init__.py:33-43`
- Test: `evals/deterministic/test_episodic_store_switch.py`

- [ ] **Step 1: Write the failing tests**

Append to `evals/deterministic/test_episodic_store_switch.py`:

```python
def test_factory_returns_sqlite_store_by_default(monkeypatch):
    monkeypatch.delenv("WAKU_EPISODIC_STORE", raising=False)
    store = Memory._make_episode_store(conn=None, settings=Settings())
    assert isinstance(store, SqliteEpisodeStore)


def test_factory_returns_notion_store_when_configured(monkeypatch, fake_notion):
    monkeypatch.setenv("WAKU_EPISODIC_STORE", "notion")
    store = Memory._make_episode_store(conn=None, settings=Settings())
    from waku.memory.episodic.notion_store import NotionEpisodeStore

    assert isinstance(store, NotionEpisodeStore)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest evals/deterministic/test_episodic_store_switch.py -q`
Expected: FAIL — `AttributeError: type object 'Memory' has no attribute '_make_episode_store'`.

- [ ] **Step 3: Implement the factory**

In `waku/memory/__init__.py`, replace line 34:

```python
        self.episodes = SqliteEpisodeStore(conn)
```

with:

```python
        self.episodes = self._make_episode_store(conn, settings)
```

and add this method directly after `_make_fact_store` (after line 43):

```python
    @staticmethod
    def _make_episode_store(conn, settings):
        if settings.episodic_store == "notion":
            from waku.memory.episodic.notion_store import NotionEpisodeStore

            return NotionEpisodeStore()
        return SqliteEpisodeStore(conn)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest evals/deterministic/test_episodic_store_switch.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add waku/memory/__init__.py evals/deterministic/test_episodic_store_switch.py
git commit -m "feat: Memory selects episodic store via _make_episode_store"
```

---

### Task 3: Dashboard settings plumbing (`apply_settings` + `settings_info`)

**Files:**
- Modify: `waku/ops/dashboard.py:930-965` (`settings_info`), `968-1006` (`apply_settings`)
- Test: `evals/deterministic/test_episodic_store_switch.py`

- [ ] **Step 1: Write the failing test**

Append to `evals/deterministic/test_episodic_store_switch.py`:

```python
def test_apply_settings_rejects_unknown_episodic_store():
    from waku.ops.dashboard import apply_settings

    result = apply_settings({"provider": "anthropic", "episodic_store": "bogus"})
    assert "error" in result
    assert "episodic_store" in result["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest evals/deterministic/test_episodic_store_switch.py -q`
Expected: FAIL — `result` is `{"ok": True, ...}` (the bogus value is silently ignored today), so `"error" in result` fails.

- [ ] **Step 3: Validate `episodic_store` and extend the whitelist**

In `waku/ops/dashboard.py` `apply_settings`, directly after the provider guard
(`if provider not in PROVIDERS: return {"error": ...}`, lines 976-978), add:

```python
    episodic_store = payload.get("episodic_store")
    if episodic_store is not None and episodic_store not in ("sqlite", "notion"):
        return {"error": f"unknown episodic_store {episodic_store}"}
```

Extend the `writable` set (lines 982-983) to:

```python
    writable = ({"WAKU_PROVIDER", "WAKU_MODEL", "WAKU_SMALL_MODEL", "TAVILY_API_KEY",
                 "WAKU_EPISODIC_STORE", "NOTION_TOKEN", "NOTION_EPISODES_DATABASE_ID"}
                | {p.key_env for p in PROVIDERS.values()})
```

After the `updates = {...}` block (lines 986-988), add:

```python
    if episodic_store:
        updates["WAKU_EPISODIC_STORE"] = episodic_store
```

- [ ] **Step 4: Expose the backend + Notion status in `settings_info`**

In `settings_info` (line 930), add these keys to the returned dict, directly
after the `"search_key_last4"` line (line 964):

```python
        # episodic-memory backend: sqlite (default) or notion
        "episodic_store": s.episodic_store,
        "notion_token_set": bool(os.getenv("NOTION_TOKEN")),
        "notion_token_last4": (os.getenv("NOTION_TOKEN") or "")[-4:],
        "notion_db_set": bool(os.getenv("NOTION_EPISODES_DATABASE_ID")),
        "notion_db_last4": (os.getenv("NOTION_EPISODES_DATABASE_ID") or "")[-4:],
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest evals/deterministic/test_episodic_store_switch.py -q`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add waku/ops/dashboard.py evals/deterministic/test_episodic_store_switch.py
git commit -m "feat: apply_settings accepts and validates episodic_store"
```

---

### Task 4: `collect()` episodes routing + `memory_action` delete routing

**Files:**
- Modify: `waku/ops/dashboard.py:289-297` (`collect` helpers), `434-435` (episodes row), `757-770` (`memory_action`)
- Test: `evals/deterministic/test_episodic_store_switch.py`

- [ ] **Step 1: Write the failing tests**

Append to `evals/deterministic/test_episodic_store_switch.py`:

```python
def _isolated_home(monkeypatch, tmp_path):
    """Point collect()/memory_action() at a throwaway WAKU_HOME with no network
    warm-up (provider anthropic, no base_url)."""
    monkeypatch.setenv("WAKU_HOME", str(tmp_path))
    monkeypatch.setenv("WAKU_PROVIDER", "anthropic")
    monkeypatch.delenv("WAKU_BASE_URL", raising=False)


def test_collect_reads_episodes_from_notion_when_active(monkeypatch, fake_notion, tmp_path):
    _isolated_home(monkeypatch, tmp_path)
    monkeypatch.setenv("WAKU_EPISODIC_STORE", "notion")

    from waku.memory.episodic.notion_store import NotionEpisodeStore

    NotionEpisodeStore().add("episode from notion", "2026-07-18")

    from waku.ops.dashboard import collect

    data = collect()
    assert data["episodes_source"] == "notion"
    assert data["episodes_error"] == ""
    assert [e["summary"] for e in data["episodes"]] == ["episode from notion"]


def test_collect_episodes_default_to_sqlite(monkeypatch, tmp_path):
    _isolated_home(monkeypatch, tmp_path)
    monkeypatch.delenv("WAKU_EPISODIC_STORE", raising=False)

    from waku.ops.dashboard import collect

    data = collect()
    assert data["episodes_source"] == "sqlite"
    assert data["episodes_error"] == ""
    assert data["episodes"] == []


def test_memory_action_delete_episode_routes_to_notion(monkeypatch, fake_notion, tmp_path):
    _isolated_home(monkeypatch, tmp_path)
    monkeypatch.setenv("WAKU_EPISODIC_STORE", "notion")

    from waku.memory.episodic.notion_store import NotionEpisodeStore

    NotionEpisodeStore().add("to delete", "2026-07-18")
    page_id = _FakeNotionClient._pages[0]["id"]

    from waku.ops.dashboard import memory_action

    assert memory_action({"action": "delete_episode", "id": page_id}) == {"ok": True}
    assert _FakeNotionClient._pages[0]["archived"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest evals/deterministic/test_episodic_store_switch.py -q`
Expected: FAIL — `KeyError: 'episodes_source'` on the collect tests; the delete test fails because `int("page-1")` raises inside `memory_action` (returns `{"error": "bad id"}`).

- [ ] **Step 3: Route `collect()` episodes through the active backend**

In `waku/ops/dashboard.py` `collect()`, directly after the `rows()` helper
(lines 296-297), add:

```python
    def episodes_payload() -> dict:
        """Episodes from the active backend: sqlite (default) or notion.
        A Notion outage must not take down the whole dashboard payload."""
        if settings.episodic_store != "notion":
            return {
                "source": "sqlite",
                "error": "",
                "items": rows(
                    "SELECT id, happened_at, summary FROM episodes ORDER BY happened_at DESC"
                ),
            }
        try:
            from waku.memory.episodic.notion_store import NotionEpisodeStore

            return {"source": "notion", "error": "", "items": NotionEpisodeStore().list()}
        except Exception as exc:
            return {"source": "notion", "error": str(exc), "items": []}

    episodes_data = episodes_payload()
```

Then replace line 435:

```python
        "episodes": rows("SELECT id, happened_at, summary FROM episodes ORDER BY happened_at DESC"),
```

with:

```python
        "episodes": episodes_data["items"],
        "episodes_source": episodes_data["source"],
        "episodes_error": episodes_data["error"],
```

- [ ] **Step 4: Route `memory_action` delete through the active backend**

In `memory_action` (`waku/ops/dashboard.py`), replace the block from
`conn = connect(settings.home)` (line 758) through the end of the function
(line 770) with:

```python
    conn = connect(settings.home)
    facts, episodes = SqliteFactStore(conn), SqliteEpisodeStore(conn)
    if action == "delete_episode" and settings.episodic_store == "notion":
        from waku.memory.episodic.notion_store import NotionEpisodeStore

        return {"ok": NotionEpisodeStore().delete(str(payload.get("id", "")))}
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
```

(The only semantic change: the notion branch is checked before the int
coercion, because Notion page ids are UUID strings.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest evals/deterministic/test_episodic_store_switch.py -q`
Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add waku/ops/dashboard.py evals/deterministic/test_episodic_store_switch.py
git commit -m "feat: dashboard reads and deletes episodes via the active backend"
```

> **Amendment (added during execution, post code review):**
> 1. Added `test_collect_episodes_notion_outage_degrades_gracefully` — the spec's
>    failure-handling requirement had no test. It asserts `episodes == []`,
>    `episodes_source == "notion"`, `"NOTION_TOKEN" in episodes_error`, and
>    `"facts" in data`.
> 2. That test exposed a second unguarded construction site: `tools_info()`'s
>    display-only branch (`_agent is None`) eagerly builds `Memory(...)`, which
>    raises on notion misconfiguration and kills the whole payload. Fixed by
>    wrapping the construction in try/except (`mem = None`) and appending the
>    two mem-dependent tools only on success. `Memory._make_episode_store`
>    deliberately unchanged — the agent runtime still fails loudly.

---

### Task 5: Frontend — settings card, episodic tab badge, database note

**Files:**
- Modify: `waku/ops/static/js/views.js:102-112` (`memEpisodic`), `255-291` (`settings`), `337-341` (`database`)
- Modify: `waku/ops/static/js/models.js:10-24` (`applyModel`, `saveSettings`)

No JS test harness exists; verification is manual (Task 6) plus the existing
`test_static_assets.py` sanity checks.

- [ ] **Step 1: Send `episodic_store` from the settings form**

In `waku/ops/static/js/models.js`, replace `applyModel` and `saveSettings`
(lines 10-24) with:

```javascript
async function applyModel({provider, model, small_model, episodic_store, keys = {}}){
  const r = await postJSON("/api/settings", {provider, model, small_model, episodic_store, keys});
  if (!r.error){ editing = false; modelCatalog = null; await refresh(); }
  return r;
}
async function saveSettings(){
  const provider = document.getElementById("set-provider").value;
  const model = document.getElementById("set-model").value.trim();
  const small_model = (document.getElementById("set-small-model")?.value || "").trim();
  const episodic_store = document.getElementById("set-episodic-store")?.value;
  const keys = {};
  document.querySelectorAll("[data-key]").forEach(i => { if(i.value.trim()) keys[i.dataset.key] = i.value.trim(); });
  document.getElementById("set-msg").textContent = "switching…";
  const r = await applyModel({provider, model, small_model, episodic_store, keys});
  document.getElementById("set-msg").textContent = r.error ? ("Error: "+r.error) : "Switched to "+r.provider+" — live now.";
}
```

(Other `applyModel` callers — catalog one-click, chat pill — omit
`episodic_store`; `JSON.stringify` drops `undefined`, so the backend never
sees it from those paths.)

- [ ] **Step 2: Add the Episodic memory card to the Settings view**

In `waku/ops/static/js/views.js` `settings(d)`, insert the following directly
after the Provider & keys card's closing `</div>` on line 277 (i.e. between the
first `Save & switch` block and `<h2 id="catalog-h"...>`):

```javascript
    h += `<h2>Episodic memory</h2><div class="card">
      <div class="meta" style="margin-bottom:8px">Where dated episode summaries live. Default is the local
        <code>state.db</code> (zero setup). Pick <code>notion</code> to store them in a Notion database instead
        (requires <code>pip install -e '.[notion]'</code>).</div>
      <label class="fld">Backend
        <select id="set-episodic-store" onfocus="markEditing()">
          <option value="sqlite" ${st.episodic_store!=="notion"?"selected":""}>sqlite — local state.db (default)</option>
          <option value="notion" ${st.episodic_store==="notion"?"selected":""}>notion — a Notion database</option>
        </select></label>
      <label class="fld"><span>Notion token <span class="meta">(NOTION_TOKEN)</span>
        ${st.notion_token_set?`<span class="srcpill" style="background:var(--good-soft);color:var(--good)">set ····${esc(st.notion_token_last4)}</span>`
                             :`<span class="srcpill apple">not set</span>`}</span>
        <input type="password" data-key="NOTION_TOKEN" placeholder="${st.notion_token_set?"key on file — blank keeps it":"paste integration token"}"></label>
      <label class="fld"><span>Notion database id <span class="meta">(NOTION_EPISODES_DATABASE_ID)</span>
        ${st.notion_db_set?`<span class="srcpill" style="background:var(--good-soft);color:var(--good)">set ····${esc(st.notion_db_last4)}</span>`
                          :`<span class="srcpill apple">not set</span>`}</span>
        <input data-key="NOTION_EPISODES_DATABASE_ID" placeholder="${st.notion_db_set?"id on file — blank keeps it":"32-char id from the database URL"}"></label>
      <div style="margin-top:12px"><button class="save" onclick="saveSettings()">Save &amp; switch</button>
        <span class="meta" style="margin-left:10px">rebuilds the agent in-process — a bad token surfaces the error here and keeps the old backend</span></div>
    </div>`;
```

- [ ] **Step 3: Source badge + error state on Memory ▸ Episodic**

In `waku/ops/static/js/views.js`, replace `memEpisodic` (lines 102-112) with:

```javascript
function memEpisodic(d){
  const src = d.episodes_source || "sqlite";
  let h = `<div class="meta" style="margin-bottom:8px">backend: <span class="srcpill">${esc(src)}</span></div>`;
  if (d.episodes_error) h += `<div class="card empty">Could not read episodes from Notion: ${esc(d.episodes_error)}</div>`;
  h += `<div class="card" style="background:var(--accent-soft);border-color:var(--line2)">
    <b>Why is this small?</b> <span class="r">Episodic memory holds one <i>distilled</i> summary per
    consolidation, not every message. The raw, blow-by-blow conversation lives in the
    <a class="reveal" onclick="location.hash='database/chat_log'"><code>chat_log</code> table</a>
    (the big one) on the Database tab — episodes are its highlights.</span></div>`;
  h += `<div class="card" style="padding:4px 8px"><table><tr><th>date</th><th>episode</th><th></th></tr>${
    d.episodes.map(e => `<tr><td class="meta">${esc(e.happened_at)}</td><td>${esc(e.summary)}</td>
      <td><a class="reveal del" onclick="delMem('delete_episode','${e.id}')">delete</a></td></tr>`).join("")}</table></div>`;
  return h;
}
```

(The delete id is now quoted — sqlite int ids work the same after the
backend's `int()` coercion, and Notion UUID strings survive.)

- [ ] **Step 4: Database-page note when notion is active**

In `waku/ops/static/js/views.js` `database(d, sub)`, replace line 340:

```javascript
      return h + `<div class="meta" style="margin-bottom:10px">${DB_DESC[t.name]||""}</div>` + dbTable(t);
```

with:

```javascript
      const notionNote = (t.name === "episodes" && d.episodes_source === "notion")
        ? `<div class="meta" style="margin-bottom:10px">Episodes currently live in Notion — see
            <a class="reveal" onclick="location.hash='memory/episodic'">Memory ▸ Episodic</a>.
            The rows below are the old local copy in state.db.</div>` : "";
      return h + notionNote + `<div class="meta" style="margin-bottom:10px">${DB_DESC[t.name]||""}</div>` + dbTable(t);
```

- [ ] **Step 5: Static-asset sanity checks**

Run: `.venv/bin/python -m pytest evals/deterministic/test_static_assets.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add waku/ops/static/js/views.js waku/ops/static/js/models.js
git commit -m "feat: settings UI for episodic backend selection + notion status"
```

---

### Task 6: Lint, full deterministic gate, manual E2E

**Files:**
- None (verification only)

- [ ] **Step 1: Lint**

Run: `.venv/bin/python -m ruff check waku/ evals/`
Expected: no errors.

- [ ] **Step 2: Full deterministic suite**

Run: `.venv/bin/python -m pytest evals/deterministic/ -q`
Expected: all pass, including the pre-existing `test_notion_episodes.py` (9 tests).

- [ ] **Step 3: Manual E2E — sqlite default untouched**

Run: `.venv/bin/waku dashboard` (or `make dashboard`), open
`http://localhost:7777/#memory/episodic`.
Expected: backend badge shows `sqlite`; episodes table shows local rows;
Settings page shows the Episodic memory card with `sqlite` selected.

- [ ] **Step 4: Manual E2E — switch to notion**

On the Settings page: pick `notion`, paste a real integration token + database
id, Save & switch.
Expected: success message; `#memory/episodic` now shows `notion` badge and the
Notion database rows; deleting a row archives the Notion page (check Notion
UI); `#database/episodes` shows the "Episodes currently live in Notion" note.
Then switch back to `sqlite` and confirm the local rows return.

- [ ] **Step 5: Commit any fixes**

```bash
git add -u
git commit -m "style: lint fixes for episodic store switch" || true
```

---

## Self-review

**1. Spec coverage:**
- `Settings.episodic_store` + `.env.example` docs — Task 1.
- `Memory._make_episode_store` factory — Task 2.
- `apply_settings` whitelist + validation, `settings_info` exposure — Task 3.
- `collect()` routing with `episodes_source`/`episodes_error`, `memory_action` delete routing — Task 4.
- Settings card, episodic badge/error, database note, `saveSettings` payload — Task 5.
- Failure handling: bad-token switch → rebuild exception path (spec; existing `apply_settings` try/except, unchanged); Notion-down at snapshot → `episodes_error` (Task 4); UUID delete ids (Tasks 4-5).
- Verification items 1-4 from the spec — Tasks 1-4 tests; manual check — Task 6.

**2. Placeholder scan:** no TBD/TODO; every code step shows complete code; commands carry expected output.

**3. Type consistency:**
- `Settings.episodic_store` (Task 1) is the field read in `Memory._make_episode_store` (Task 2), `apply_settings` payload key `episodic_store` (Task 3), `collect()` (Task 4), and the JS `st.episodic_store` / `#set-episodic-store` (Task 5).
- `settings_info` keys `episodic_store`, `notion_token_set/last4`, `notion_db_set/last4` (Task 3) match the JS card (Task 5).
- `collect()` payload keys `episodes`, `episodes_source`, `episodes_error` (Task 4) match `memEpisodic`/`database` readers (Task 5).
- Fake client in the new test file mirrors the one in `test_notion_episodes.py` (same `data_sources` API shape), with class-level `_pages` so dashboard-instantiated stores share state.
