"""Deterministic eval for NotionEpisodeStore.

Stubs `notion_client.Client` so no real network requests are made.
"""

from __future__ import annotations

import sys
import types


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

from waku.memory.episodic.notion_store import (  # noqa: E402
    NotionEpisodeStore,
)


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
