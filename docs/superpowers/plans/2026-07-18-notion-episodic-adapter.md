# Notion episodic-memory adapter implementation plan

> **For agentic workers:** REQUIRED SUB-_SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `waku/memory/episodic/notion_store.py` with the same `add`/`search`/`recent` interface as `SqliteEpisodeStore`, plus a deterministic eval that stubs the Notion client.

**Architecture:** A thin adapter around `notion-client` that stores each episode as a page in a Notion database (`Name` title = `happened_at`, `Summary` rich_text = `summary`). `search` tokenizes the query with the existing `_fts_query` helper and filters results locally; `recent` returns the latest episodes sorted by `happened_at`. The SDK is imported lazily so the default install stays dependency-free.

**Tech Stack:** Python 3.11+, `notion-client` (behind `[notion]` extra), `pytest`.

---

## File structure

- **Create** `waku/memory/episodic/notion_store.py` — `NotionEpisodeStore` adapter.
- **Modify** `pyproject.toml` — add `[notion]` optional dependency.
- **Create** `evals/deterministic/test_notion_episodes.py` — deterministic eval with stubbed client.

---

### Task 1: Add `[notion]` optional dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the `notion` extra after the `supabase` extra**

Insert the following block after the `supabase` optional-dependency entry:

```toml
# Optional episodic-memory backend: Notion database
notion = [
    "notion-client>=2.0",
]
```

The relevant section should look like:

```toml
[project.optional-dependencies]
# Eval pillar: LLM-as-judge (deterministic evals need only pytest)
eval = [
    "pytest>=8.0",
    "deepeval>=2.0",
]
# LLM-Ops pillar: local trace dashboard (traces also always land in traces/*.jsonl)
tracing = [
    "arize-phoenix>=7.0",
    "opentelemetry-sdk>=1.27",
    "opentelemetry-exporter-otlp>=1.27",
]
# Optional gateway: message your laptop from your phone
telegram = [
    "python-telegram-bot>=21.0",
]
# Optional gateway: talk to your laptop. TTS uses macOS `say` by default;
# for the neural British voice: pip install kokoro soundfile (pulls torch).
voice = [
    "faster-whisper>=1.0",
    "sounddevice>=0.4",
]
# The beautiful neural voice (Kokoro-82M, Apache-2.0): British butler, fully
# local/offline. Heavier — pulls torch (~2GB). `uv pip install '.[voice-neural]'`
# and Waku auto-detects it; no env var needed.
voice-neural = [
    "kokoro>=0.9",
    "soundfile>=0.12",
]
# Optional semantic-memory upgrade path: Supabase pgvector (see launch-rag)
supabase = [
    "supabase>=2.0",
]
# Optional episodic-memory backend: Notion database
notion = [
    "notion-client>=2.0",
]
# Optional: connect MCP servers (.waku/mcp.json)
mcp = [
    "mcp>=1.0",
]
dev = [
    "pytest>=8.0",
    "ruff>=0.6",
]
```

- [ ] **Step 2: Verify pyproject.toml is valid TOML**

Run:

```bash
python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb'))"
```

Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add [notion] extra for Notion episodic adapter"
```

---

### Task 2: Implement `NotionEpisodeStore`

**Files:**
- Create: `waku/memory/episodic/notion_store.py`

- [ ] **Step 1: Write the adapter module**

Create `waku/memory/episodic/notion_store.py` with the following content:

```python
"""Episodic-memory adapter backed by a Notion database.

Each episode becomes a page in a database with two properties:
- Name (title): the ISO-8601 timestamp string (happened_at)
- Summary (rich_text): the episode summary

Install with the [notion] extra:
    pip install 'waku-agent[notion]'

Set environment variables:
    NOTION_TOKEN=<integration token>
    NOTION_EPISODES_DATABASE_ID=<database id>
"""

from __future__ import annotations

import os

from waku.memory.semantic.store import _fts_query


class NotionEpisodeStore:
    def __init__(self, token: str | None = None, database_id: str | None = None) -> None:
        from notion_client import Client

        self.token = token or os.environ.get("NOTION_TOKEN")
        self.database_id = database_id or os.environ.get("NOTION_EPISODES_DATABASE_ID")
        if not self.token:
            raise ValueError(
                "Notion token required: pass token= or set NOTION_TOKEN environment variable"
            )
        if not self.database_id:
            raise ValueError(
                "Notion database_id required: pass database_id= or set "
                "NOTION_EPISODES_DATABASE_ID environment variable"
            )
        self.client = Client(auth=self.token)

    def add(self, summary: str, happened_at: str) -> None:
        """Create a new episode page in the configured Notion database."""
        self.client.pages.create(
            parent={"database_id": self.database_id},
            properties={
                "Name": {"title": [{"text": {"content": happened_at}}]},
                "Summary": {"rich_text": [{"text": {"content": summary}}]},
            },
        )

    def recent(self, top_k: int = 3) -> list[str]:
        """Return the latest N episodes, most recent happened_at first."""
        pages = self._query_all()
        pages.sort(
            key=lambda p: self._extract_title(p.get("properties", {}).get("Name", {})),
            reverse=True,
        )
        return [self._format(p) for p in pages[:top_k]]

    def search(self, query: str, top_k: int = 3) -> list[str]:
        """Keyword search over episode summaries; falls back to recent if query is empty."""
        fts = _fts_query(query)
        if not fts:
            return self.recent(top_k)

        keywords = [word.lower() for word in fts.split(" OR ")]
        matches = []
        for page in self._query_all():
            summary = self._extract_rich_text(
                page.get("properties", {}).get("Summary", {})
            )
            if any(keyword in summary.lower() for keyword in keywords):
                matches.append(page)

        matches.sort(
            key=lambda p: self._extract_title(p.get("properties", {}).get("Name", {})),
            reverse=True,
        )
        return [self._format(p) for p in matches[:top_k]]

    def _query_all(self) -> list[dict]:
        """Fetch all pages from the database, following pagination."""
        results: list[dict] = []
        response = self.client.databases.query(database_id=self.database_id)
        results.extend(response.get("results", []))
        while response.get("has_more"):
            response = self.client.databases.query(
                database_id=self.database_id,
                start_cursor=response.get("next_cursor"),
            )
            results.extend(response.get("results", []))
        return results

    def _format(self, page: dict) -> str:
        props = page.get("properties", {})
        happened_at = self._extract_title(props.get("Name", {}))
        summary = self._extract_rich_text(props.get("Summary", {}))
        return f"({happened_at}) {summary}"

    @staticmethod
    def _extract_title(prop: dict) -> str:
        return "".join(
            part.get("text", {}).get("content", "") for part in prop.get("title", [])
        )

    @staticmethod
    def _extract_rich_text(prop: dict) -> str:
        return "".join(
            part.get("text", {}).get("content", "")
            for part in prop.get("rich_text", [])
        )
```

- [ ] **Step 2: Verify the module imports without `notion-client` installed**

Run:

```bash
python -c "from waku.memory.episodic.notion_store import NotionEpisodeStore; print('ok')"
```

Expected output: `ok`

If `notion-client` is installed in your environment, uninstall it first to confirm the lazy import works:

```bash
pip uninstall -y notion-client
python -c "from waku.memory.episodic.notion_store import NotionEpisodeStore; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git add waku/memory/episodic/notion_store.py
git commit -m "feat: add NotionEpisodeStore adapter for episodic memory"
```

---

### Task 3: Write deterministic eval with stubbed Notion client

**Files:**
- Create: `evals/deterministic/test_notion_episodes.py`

- [ ] **Step 1: Write the eval file**

Create `evals/deterministic/test_notion_episodes.py` with the following content:

```python
"""Deterministic eval for NotionEpisodeStore.

Stubs `notion_client.Client` so no real network requests are made.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock


class _FakeNotionClient:
    """In-memory fake for notion_client.Client."""

    def __init__(self, auth: str | None = None) -> None:
        self.auth = auth
        self.databases = types.SimpleNamespace(query=self._query)
        self.pages = types.SimpleNamespace(create=self._create)
        self._pages: list[dict] = []

    def _create(self, *, parent: dict, properties: dict) -> dict:
        page = {
            "id": f"page-{len(self._pages) + 1}",
            "parent": parent,
            "properties": properties,
        }
        self._pages.append(page)
        return page

    def _query(self, *, database_id: str, start_cursor: str | None = None) -> dict:
        assert database_id == "test-db-id"
        return {"results": list(self._pages), "has_more": False}


def _install_fake_notion_client() -> None:
    fake_module = types.ModuleType("notion_client")
    fake_module.Client = _FakeNotionClient
    sys.modules["notion_client"] = fake_module


# Install the fake module before importing the adapter under test.
_install_fake_notion_client()

from waku.memory.episodic.notion_store import NotionEpisodeStore


def test_add_creates_page_with_correct_properties():
    store = NotionEpisodeStore(token="test-token", database_id="test-db-id")
    store.add("planned the demo with Alex", "2026-07-10")

    created = store.client._pages[0]
    assert created["parent"]["database_id"] == "test-db-id"
    title_parts = created["properties"]["Name"]["title"]
    assert title_parts[0]["text"]["content"] == "2026-07-10"
    summary_parts = created["properties"]["Summary"]["rich_text"]
    assert summary_parts[0]["text"]["content"] == "planned the demo with Alex"


def test_recent_returns_latest_episodes_sorted_by_happened_at():
    store = NotionEpisodeStore(token="test-token", database_id="test-db-id")
    store.add("first episode", "2026-07-08")
    store.add("second episode", "2026-07-10")
    store.add("third episode", "2026-07-09")

    recent = store.recent(top_k=2)
    assert recent == [
        "(2026-07-10) second episode",
        "(2026-07-09) third episode",
    ]


def test_search_filters_by_keyword_and_returns_matching_episodes():
    store = NotionEpisodeStore(token="test-token", database_id="test-db-id")
    store.add("planned the demo with Alex", "2026-07-10")
    store.add("wrote the quarterly report", "2026-07-09")
    store.add("demo follow-up with team", "2026-07-08")

    results = store.search("demo", top_k=2)
    assert results == [
        "(2026-07-10) planned the demo with Alex",
        "(2026-07-08) demo follow-up with team",
    ]


def test_search_falls_back_to_recent_when_query_has_no_keywords():
    store = NotionEpisodeStore(token="test-token", database_id="test-db-id")
    store.add("only episode", "2026-07-10")

    results = store.search("!!!", top_k=1)
    assert results == ["(2026-07-10) only episode"]


def test_constructor_requires_token_and_database_id():
    store = NotionEpisodeStore(token="test-token", database_id="test-db-id")
    assert store.token == "test-token"
    assert store.database_id == "test-db-id"

    try:
        NotionEpisodeStore(token=None, database_id="test-db-id")
        raise AssertionError("expected ValueError for missing token")
    except ValueError as e:
        assert "NOTION_TOKEN" in str(e)

    try:
        NotionEpisodeStore(token="test-token", database_id=None)
        raise AssertionError("expected ValueError for missing database_id")
    except ValueError as e:
        assert "NOTION_EPISODES_DATABASE_ID" in str(e)
```

- [ ] **Step 2: Run the eval without `notion-client` installed**

```bash
pytest evals/deterministic/test_notion_episodes.py -v
```

Expected: all tests pass.

If `notion-client` is installed, uninstall it first:

```bash
pip uninstall -y notion-client
pytest evals/deterministic/test_notion_episodes.py -v
```

- [ ] **Step 3: Commit**

```bash
git add evals/deterministic/test_notion_episodes.py
git commit -m "test: deterministic eval for NotionEpisodeStore with stubbed client"
```

---

### Task 4: Run lint and the deterministic gate

**Files:**
- None (verification only)

- [ ] **Step 1: Run lint**

```bash
make lint
```

Expected: no errors. If ruff reports formatting issues, run `ruff format waku/memory/episodic/notion_store.py evals/deterministic/test_notion_episodes.py` and re-run.

- [ ] **Step 2: Run deterministic evals**

```bash
pytest evals/deterministic/ -q
```

Expected: all deterministic tests pass.

- [ ] **Step 3: Commit any formatting fixes**

```bash
git add -u
git commit -m "style: lint fixes for Notion episodic adapter" || true
```

---

## Self-review

**1. Spec coverage:**
- `waku/memory/episodic/notion_store.py` with `add`/`search`/`recent` interface — Task 2.
- Same return format as `SqliteEpisodeStore` — implemented in `_format`.
- Optional `[notion]` extra — Task 1.
- Deterministic eval against stubbed Notion client, no network in CI — Task 3.

**2. Placeholder scan:**
- No TBD/TODO/"implement later".
- All code blocks contain complete code.
- All commands include expected output.

**3. Type consistency:**
- Method signatures match `SqliteEpisodeStore`: `add(self, summary, happened_at)`, `search(self, query, top_k=3)`, `recent(self, top_k=3)`.
- Property names `Name` (title) and `Summary` (rich_text) are consistent across the adapter and tests.
- `_fts_query` usage matches the helper's output format (`word OR word OR ...`).
