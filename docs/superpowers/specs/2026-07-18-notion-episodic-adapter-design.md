# Notion episodic-memory adapter

## Goal

Implement `waku/memory/episodic/notion_store.py` so episodes can be stored in a Notion database instead of SQLite, while keeping the same public interface as `SqliteEpisodeStore`.

Issue: https://github.com/ShenSeanChen/waku-agent/issues/10

## Reference interface

`SqliteEpisodeStore` in `waku/memory/episodic/store.py` exposes:

```python
class SqliteEpisodeStore:
    def add(self, summary: str, happened_at: str) -> None: ...
    def search(self, query: str, top_k: int = 3) -> list[str]: ...
    def recent(self, top_k: int = 3) -> list[str]: ...
```

Return format for `search` and `recent` is `f"({happened_at}) {summary}"`.

## Design

### Adapter class

```python
class NotionEpisodeStore:
    def __init__(self, token: str | None = None, database_id: str | None = None) -> None: ...
    def add(self, summary: str, happened_at: str) -> None: ...
    def search(self, query: str, top_k: int = 3) -> list[str]: ...
    def recent(self, top_k: int = 3) -> list[str]: ...
```

- `token` defaults to `os.environ["NOTION_TOKEN"]`.
- `database_id` defaults to `os.environ["NOTION_EPISODES_DATABASE_ID"]`.
- The Notion database is expected to have two properties:
  - `Name` / `title` — stores `happened_at`.
  - `Summary` / `rich_text` — stores `summary`.

### Dependency

Add a new optional extra in `pyproject.toml`, matching the existing `supabase` pattern:

```toml
notion = ["notion-client>=2.0"]
```

The SDK is imported inside `__init__` so the default install stays free of the dependency.

### Behavior

#### `add(summary, happened_at)`

Create a new page in the configured database with:

```json
{
  "parent": {"database_id": "<database_id>"},
  "properties": {
    "Name": {"title": [{"text": {"content": happened_at}}]},
    "Summary": {"rich_text": [{"text": {"content": summary}}]}
  }
}
```

#### `recent(top_k=3)`

Query the database sorted by `happened_at` descending and return up to `top_k` formatted strings. Because Notion database sorts work on property types, sort by the `Name` title property or by `created_time` as a practical proxy. For consistency with SQLite, use `happened_at` lexicographic descending (ISO-8601 strings sort correctly).

#### `search(query, top_k=3)`

Reuse `waku.memory.semantic.store._fts_query` to tokenize `query` into alphanumeric keywords. Query the database for recent pages, then filter results locally by checking whether any keyword appears in the `summary` string (case-insensitive). Return up to `top_k` formatted strings.

If `_fts_query` returns no tokens, fall back to `recent(top_k)` — identical to `SqliteEpisodeStore.search`.

### Integration scope

Keep this PR self-contained:

- Add `waku/memory/episodic/notion_store.py`.
- Add `notion` extra in `pyproject.toml`.
- Add `evals/deterministic/test_notion_episodes.py`.

Do **not** wire `NotionEpisodeStore` into `waku.memory.Memory` by default. Users can instantiate it directly; a future PR can add an env-gated switch (`WAKU_EPISODIC_STORE=notion`) if desired.

## Verification

`evals/deterministic/test_notion_episodes.py` stubs `notion_client.Client` methods and asserts:

1. `add` calls `pages.create` with the correct `parent.database_id` and properties.
2. `recent` returns the latest N episodes formatted as `(happened_at) summary`.
3. `search` filters stubbed pages by keywords and returns matching episodes.
4. `search` with no valid keywords falls back to `recent`.
5. No real network requests are made.

## Trade-offs

- Local keyword filtering instead of Notion's search API keeps the implementation deterministic and simple, but may return less relevant matches for large databases than true full-text search.
- Sorting by `happened_at` relies on ISO-8601 lexicographic order, which is correct for the existing SQLite store's string format.
- Hard-coded property names (`Name`, `Summary`) keep the adapter simple; a future iteration can make them configurable if users need custom schemas.
