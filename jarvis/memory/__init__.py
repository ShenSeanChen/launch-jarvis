"""Memory facade — the three pillars behind one small interface.

    procedural  SKILL.md files      how to act
    semantic    facts table (FTS5)  what is durably true
    episodic    episodes table      what happened, when

Plus the two agents that manage them:
    retrieval_gate   decides IF a turn needs memory   (hero moment #1)
    consolidation    distills chats into facts, every N exchanges
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import anthropic

from jarvis.config import Settings
from jarvis.memory import consolidation, retrieval_gate
from jarvis.memory.episodic.store import SqliteEpisodeStore
from jarvis.memory.procedural.loader import SkillLoader
from jarvis.memory.semantic.store import SqliteFactStore

REPO_SKILLS = Path(__file__).resolve().parents[2] / "skills"


class Memory:
    def __init__(self, conn: sqlite3.Connection, settings: Settings, client: anthropic.Anthropic):
        self.conn = conn
        self.settings = settings
        self.client = client
        self.facts = self._make_fact_store(conn, settings)
        self.episodes = SqliteEpisodeStore(conn)
        self.skills = SkillLoader([REPO_SKILLS, settings.home / "skills"])

    @staticmethod
    def _make_fact_store(conn, settings):
        if settings.semantic_store == "supabase":
            from jarvis.memory.semantic.supabase_store import SupabaseFactStore

            return SupabaseFactStore(settings)
        return SqliteFactStore(conn)

    # ---- retrieval (gated — see retrieval_gate.py for why)
    def gated_retrieve(self, message: str, notify=None) -> str:
        retrieve, query, reason = retrieval_gate.should_retrieve(
            self.client, self.settings.small_model, message
        )
        if notify:
            notify("gate", {"decision": "retrieve" if retrieve else "skip", "reason": reason})
        if not retrieve:
            return ""
        found = self.facts.search(query, self.settings.retrieval_top_k)
        found += self.episodes.search(query, top_k=3)
        return "\n".join(found)

    # ---- procedural
    def matching_skills(self, message: str) -> str:
        matched = self.skills.match(message)
        return "\n\n".join(f"### {s.name}\n{s.body}" for s in matched)

    # ---- write paths
    def log_chat(self, user_message: str, reply: str) -> None:
        self.conn.execute("INSERT INTO chat_log (role, content) VALUES ('user', ?)", (user_message,))
        self.conn.execute("INSERT INTO chat_log (role, content) VALUES ('assistant', ?)", (reply,))
        self.conn.commit()

    def maybe_consolidate(self, notify=None) -> None:
        new_facts = consolidation.consolidate_if_due(
            self.conn,
            self.client,
            self.settings.small_model,
            self.settings.consolidate_every,
            self.facts,
            self.episodes,
        )
        if new_facts and notify:
            notify("consolidation", {"new_facts": new_facts})
