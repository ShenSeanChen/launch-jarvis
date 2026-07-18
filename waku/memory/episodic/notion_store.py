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
            summary = self._extract_rich_text(page.get("properties", {}).get("Summary", {}))
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
        return "".join(part.get("text", {}).get("content", "") for part in prop.get("title", []))

    @staticmethod
    def _extract_rich_text(prop: dict) -> str:
        return "".join(
            part.get("text", {}).get("content", "") for part in prop.get("rich_text", [])
        )
