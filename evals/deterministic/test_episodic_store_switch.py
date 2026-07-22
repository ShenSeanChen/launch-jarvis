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


def test_factory_returns_sqlite_store_by_default(monkeypatch):
    monkeypatch.delenv("WAKU_EPISODIC_STORE", raising=False)
    store = Memory._make_episode_store(conn=None, settings=Settings())
    assert isinstance(store, SqliteEpisodeStore)


def test_factory_returns_notion_store_when_configured(monkeypatch, fake_notion):
    monkeypatch.setenv("WAKU_EPISODIC_STORE", "notion")
    store = Memory._make_episode_store(conn=None, settings=Settings())
    from waku.memory.episodic.notion_store import NotionEpisodeStore

    assert isinstance(store, NotionEpisodeStore)


def test_apply_settings_rejects_unknown_episodic_store(monkeypatch, tmp_path):
    # chdir so a regression of the guard can't write into the real project .env
    monkeypatch.chdir(tmp_path)
    from waku.ops.dashboard import apply_settings

    result = apply_settings({"provider": "anthropic", "episodic_store": "bogus"})
    assert "error" in result
    assert "episodic_store" in result["error"]


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


def test_collect_episodes_notion_outage_degrades_gracefully(monkeypatch, fake_notion, tmp_path):
    _isolated_home(monkeypatch, tmp_path)
    monkeypatch.setenv("WAKU_EPISODIC_STORE", "notion")
    monkeypatch.delenv("NOTION_TOKEN", raising=False)  # constructor raises ValueError

    from waku.ops.dashboard import collect

    data = collect()
    assert data["episodes"] == []
    assert data["episodes_source"] == "notion"
    assert "NOTION_TOKEN" in data["episodes_error"]
    assert "facts" in data  # the rest of the payload still rendered


def test_manage_memory_delete_episode_accepts_notion_string_id(fake_notion):
    from waku.memory.episodic.notion_store import NotionEpisodeStore
    from waku.tools.memory_admin import make_manage_memory_tool

    store = NotionEpisodeStore()
    store.add("via tool", "2026-07-18")
    page_id = _FakeNotionClient._pages[0]["id"]

    memory = types.SimpleNamespace(episodes=store, facts=None)
    tool = make_manage_memory_tool(memory)
    assert tool.fn("delete", kind="episode", id=page_id) == f"Deleted episode #{page_id}."
    assert _FakeNotionClient._pages[0]["archived"] is True


def test_manage_memory_delete_episode_sqlite_accepts_string_id(tmp_path):
    from waku.db import connect
    from waku.memory.episodic.store import SqliteEpisodeStore
    from waku.tools.memory_admin import make_manage_memory_tool

    conn = connect(tmp_path)
    store = SqliteEpisodeStore(conn)
    store.add("sqlite ep", "2026-07-18")

    memory = types.SimpleNamespace(episodes=store, facts=None)
    tool = make_manage_memory_tool(memory)
    assert tool.fn("delete", kind="episode", id="1") == "Deleted episode #1."
    assert store.recent(top_k=1) == []
