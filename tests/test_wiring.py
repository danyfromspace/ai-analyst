"""Agents, skills and eval cases are wired together."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ["games-portfolio-performance", "games-portfolio-validator"]
SKILLS = ["games-portfolio", "games-portfolio-monitor", "games-portfolio-validation"]


def fm(path: Path) -> dict:
    t = path.read_text(encoding="utf-8")
    return yaml.safe_load(t[3:t.index("\n---", 3)])


def test_agents_preload_existing_skills_and_cannot_delegate():
    for a in AGENTS:
        d = fm(ROOT / ".claude" / "agents" / f"{a}.md")
        assert d["name"] == a and "Agent" in d["disallowedTools"]
        for s in d["skills"]:
            assert (ROOT / ".claude" / "skills" / s / "SKILL.md").exists()


def test_validator_has_no_edit_tools():
    d = fm(ROOT / ".claude" / "agents" / "games-portfolio-validator.md")
    assert "Edit" not in d["tools"] and "Write" not in d["tools"]


def test_skill_names_and_description_budget():
    for s in SKILLS:
        d = fm(ROOT / ".claude" / "skills" / s / "SKILL.md")
        assert d["name"] == s and len(d["description"]) // 4 <= 220


def test_orchestrator_names_both_agents():
    body = (ROOT / ".claude" / "skills" / "games-portfolio" / "SKILL.md").read_text(encoding="utf-8")
    assert all(a in body for a in AGENTS)


def test_agent_cases_well_formed():
    cases = yaml.safe_load((ROOT / "evals" / "agent_cases.yaml").read_text(encoding="utf-8"))["cases"]
    assert len({c["id"] for c in cases}) == len(cases) >= 8
    assert all(c["command"].startswith("/games-portfolio") and c["expect"] for c in cases)
