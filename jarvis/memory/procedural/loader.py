"""Procedural memory — SKILL.md files: how to act, loaded only when relevant.

Official Anthropic Agent Skills format: YAML frontmatter with `name` and
`description` (the description doubles as the trigger — no custom `triggers:`
field, which launch-agent-skills used before the spec settled).

Progressive disclosure, the part that matters:
  1. frontmatter of every skill is always scanned (cheap)
  2. a skill's BODY is loaded into the prompt only when it matches the message
  3. files a skill references are only read if the model asks
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path


def _parse(path: Path) -> Skill | None:
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        return None
    front, body = match.groups()
    fields = dict(
        (k.strip(), v.strip().strip("'\""))
        for k, _, v in (line.partition(":") for line in front.splitlines() if ":" in line)
    )
    if "name" not in fields or "description" not in fields:
        return None
    return Skill(fields["name"], fields["description"], body.strip(), path)


class SkillLoader:
    """Scans skill directories: the repo's skills/ (built-in + community) and
    JARVIS_HOME/skills (installed via `python -m jarvis skill install <url>`)."""

    def __init__(self, dirs: list[Path]):
        self.skills: list[Skill] = []
        for d in dirs:
            if not d.is_dir():
                continue
            for f in sorted(d.rglob("SKILL.md")):
                skill = _parse(f)
                if skill:
                    self.skills.append(skill)

    def match(self, message: str, max_skills: int = 2) -> list[Skill]:
        """Transparent trigger: keyword overlap between the message and each
        skill's name+description. No embeddings, no magic — you can compute
        the score in your head."""
        msg_words = set(re.findall(r"[a-z0-9]{3,}", message.lower()))
        scored = []
        for skill in self.skills:
            skill_words = set(re.findall(r"[a-z0-9]{3,}", (skill.name + " " + skill.description).lower()))
            overlap = len(msg_words & skill_words)
            if overlap >= 2:
                scored.append((overlap, skill))
        scored.sort(key=lambda pair: -pair[0])
        return [skill for _, skill in scored[:max_skills]]
