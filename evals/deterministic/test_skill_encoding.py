"""DETERMINISTIC EVAL — procedural skills use a portable text encoding."""

from pathlib import Path

from waku.memory.procedural.loader import SkillLoader


def test_skill_loader_reads_utf8_when_platform_default_cannot(tmp_path, monkeypatch):
    skill_path = tmp_path / "demo" / "SKILL.md"
    skill_path.parent.mkdir()
    skill_path.write_text(
        "---\nname: demo\ndescription: portable skill\n---\nUse an em dash \u2014 safely.\n",
        encoding="utf-8",
    )

    original_read_text = Path.read_text

    def reject_implicit_encoding(path, encoding=None, *args, **kwargs):
        if encoding is None:
            raise UnicodeDecodeError("gbk", b"\x94", 0, 1, "illegal multibyte sequence")
        return original_read_text(path, encoding=encoding, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", reject_implicit_encoding)

    loader = SkillLoader([tmp_path])

    assert [skill.name for skill in loader.skills] == ["demo"]
    assert "em dash \u2014 safely" in loader.skills[0].body
