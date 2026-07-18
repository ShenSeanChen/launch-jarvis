# Dashboard-configurable episodic store (sqlite | notion)

## Goal

Let users switch the episodic-memory backend from the dashboard Settings page.
Default stays SQLite; opting into Notion requires only picking "notion" and
filling in the integration token + database id — no manual `.env` editing.

Builds on the `notion-episodic-adapter` branch, which added
`waku/memory/episodic/notion_store.py` (`NotionEpisodeStore`) but deliberately
did not wire it into `waku.memory.Memory`.

## Existing pattern to mirror

Semantic memory already does exactly this:

- `Settings.semantic_store` reads `WAKU_SEMANTIC_STORE` (`"sqlite"` default,
  `"supabase"` opt-in) — `waku/config.py:50`.
- `Memory._make_fact_store(conn, settings)` instantiates the right class —
  `waku/memory/__init__.py:37-43`.
- Dashboard `apply_settings` writes whitelisted env vars to `.env`, updates
  `os.environ`, and rebuilds the agent so the switch is live —
  `waku/ops/dashboard.py:968`. On rebuild failure it returns `{"error": ...}`
  and keeps the old agent.

This spec applies the same pattern to episodic memory.

## Design

### Config

`waku/config.py`:

```python
# 'sqlite' (default, zero setup) or 'notion' (episodes live in a Notion database).
episodic_store: str = field(default_factory=lambda: os.getenv("WAKU_EPISODIC_STORE", "sqlite"))
```

`.env.example` gains a documented block:

```
# Optional episodic-memory backend: Notion database (default: local sqlite)
# WAKU_EPISODIC_STORE=notion
# NOTION_TOKEN=ntn_...
# NOTION_EPISODES_DATABASE_ID=...
```

### Memory wiring

`waku/memory/__init__.py` — replace the hardcoded store with a factory that
mirrors `_make_fact_store`:

```python
self.episodes = self._make_episode_store(conn, settings)

@staticmethod
def _make_episode_store(conn, settings):
    if settings.episodic_store == "notion":
        from waku.memory.episodic.notion_store import NotionEpisodeStore

        return NotionEpisodeStore()
    return SqliteEpisodeStore(conn)
```

`NotionEpisodeStore()` reads `NOTION_TOKEN` / `NOTION_EPISODES_DATABASE_ID`
from the environment and raises `ValueError` when they are missing; the
`apply_settings` rebuild path already catches exceptions, reports the error in
the UI, and keeps the previous agent — so a bad switch fails loudly and safely.

### Dashboard backend (`waku/ops/dashboard.py`)

- `apply_settings`:
  - Extend the `writable` whitelist with `WAKU_EPISODIC_STORE`,
    `NOTION_TOKEN`, `NOTION_EPISODES_DATABASE_ID`.
  - Accept `episodic_store` in the payload; reject values outside
    `{"sqlite", "notion"}` with `{"error": ...}`.
  - Write `WAKU_EPISODIC_STORE` like the other updates.
- `settings_info()`: expose `episodic_store`, plus set/not-set status and last4
  for `NOTION_TOKEN` and `NOTION_EPISODES_DATABASE_ID` (same treatment as the
  provider keys — values never leave the server).
- `snapshot()`: the `episodes` list follows the active backend.
  - `sqlite` → existing SQL query.
  - `notion` → `NotionEpisodeStore().list()` inside try/except: on any error
    return `[]` and set `episodes_error` so the UI can show a warning without
    taking down the whole snapshot.
  - Add `episodes_source: "sqlite" | "notion"` to the payload.
- `memory_action` `delete_episode`: route by active backend — sqlite keeps the
  existing int-rowid path; notion passes the string page id to
  `NotionEpisodeStore.delete`. The int coercion of `payload["id"]` must be
  skipped for notion (page ids are UUID strings).

### Dashboard frontend (`waku/ops/static/js/views.js`, `models.js`)

- Settings page: new **Episodic memory** card below Provider & keys:
  - A select (`#set-episodic-store`) with `sqlite` / `notion`, current value
    pre-selected.
  - When `notion` is selected: password input for `NOTION_TOKEN` and a text
    input for `NOTION_EPISODES_DATABASE_ID`, each with a set····last4 /
    not-set status pill, matching the existing key fields. Both use
    `data-key` so the existing `saveSettings()` collection picks them up.
  - `saveSettings()` (models.js) additionally sends the select's value as
    `episodic_store` in the same `/api/settings` POST — one save path, no new
    endpoint.
- Memory ▸ Episodic tab: a small source badge (`sqlite` / `notion`) next to
  the tab heading; when `episodes_error` is set, show the error message above
  the (empty) table.
- Database page: stays a `state.db` viewer. When `episodic_store == "notion"`,
  the episodes tab there gets a one-line note: episodes currently live in
  Notion; see Memory ▸ Episodic.

### Failure handling

- Switch to notion with missing/invalid token → agent rebuild raises →
  `apply_settings` returns the error and keeps the old agent (existing path).
- Notion unreachable at snapshot time → `episodes: []` + `episodes_error`;
  every other section of the dashboard renders normally.
- Delete against a notion page id → routed to the notion store; sqlite ids
  unaffected.

### Out of scope

- Migrating existing sqlite episodes into Notion.
- Database page rendering Notion rows directly.
- Manual "add episode" UI in the dashboard.
- Making the Notion property names (`Name`, `Summary`) configurable.

## Verification

Deterministic tests (extend `evals/deterministic/`):

1. `Settings` parses `WAKU_EPISODIC_STORE` (default sqlite; notion when set).
2. `Memory._make_episode_store` returns `SqliteEpisodeStore` by default and
   `NotionEpisodeStore` when `episodic_store == "notion"` (with the fake
   `notion_client` module installed, same stub as the notion tests).
3. `apply_settings` rejects an unknown `episodic_store` value.
4. Existing `test_notion_episodes.py` keeps passing unchanged.

Manual check: dashboard → Settings → pick notion, paste credentials → Save &
switch → Memory ▸ Episodic shows Notion rows with the notion badge; deleting a
row archives the Notion page; switch back to sqlite and the local rows return.

## Trade-offs

- `snapshot()` instantiates a `NotionEpisodeStore` per refresh when notion is
  active (one extra `databases.retrieve` call per load). Simple and stateless;
  caching can come later if it ever shows up in latency.
- The Notion database id rides the same `data-key` mechanism as secrets even
  though it is not one — reuses the existing save path instead of inventing a
  second one.
