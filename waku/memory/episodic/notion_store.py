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
import re


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
        keywords = re.findall(r"[a-zA-Z0-9]{2,}", query.lower())
        if not keywords:
            return self.recent(top_k)

        # Deduplicate while preserving order.
        keywords = list(dict.fromkeys(keywords))
        matches = []
        for page in self._query_all():
            summary_lower = self._extract_rich_text(
                page.get("properties", {}).get("Summary", {})
            ).lower()
            if any(
                re.search(rf"\b{re.escape(keyword)}\b", summary_lower)
                for keyword in keywords
            ):
                matches.append(page)

        matches.sort(
            key=lambda p: self._extract_title(p.get("properties", {}).get("Name", {})),
            reverse=True,
        )
        return [self._format(p) for p in matches[:top_k]]

    def list(self, limit: int = 200) -> list[dict]:
        """Return all episodes as dicts, sorted by happened_at descending."""
        pages = self._query_all()
        pages.sort(
            key=lambda p: self._extract_title(p.get("properties", {}).get("Name", {})),
            reverse=True,
        )
        return [
            {
                "id": page.get("id", ""),
                "happened_at": self._extract_title(
                    page.get("properties", {}).get("Name", {})
                ),
                "summary": self._extract_rich_text(
                    page.get("properties", {}).get("Summary", {})
                ),
                "created_at": page.get("created_time", ""),
            }
            for page in pages[:limit]
        ]

    def delete(self, episode_id: int | str) -> bool:
        """Archive the Notion page for the given episode id."""
        self.client.pages.update(page_id=str(episode_id), archived=True)
        return True

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
