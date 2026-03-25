"""Tests for skill-lint analyzer."""

import pytest
from pathlib import Path

from skill_audit.analyzer import analyze_file, analyze_artifact, analyze_directory
from skill_audit.parser import parse_file


@pytest.fixture
def high_quality_skill(tmp_path):
    content = """\
---
name: Code Review
trigger: /run_review
role: reviewer
category: code-quality
allowed-tools: Read, Grep, Glob, Bash
tags: review, quality
---

Analyze the current branch's diff against the base branch for structural issues.

## Inputs

- `target` (optional): Specific files or staged changes
- `depth` (required): Review depth (quick, standard, thorough)

## Gotchas

- Large diffs (>500 lines) should be split into per-file reviews to avoid missed issues
- Always verify the base branch before diffing to prevent stale comparisons
- Renamed files show as delete+add in diffs, don't flag these as missing code

## Steps

1. Detect the base branch using `gh pr view` or fall back to main
2. Run `git fetch origin <base>` and `git diff origin/<base> --stat`
3. Read the full diff with `git diff origin/<base>`
4. Check each changed file for issues
5. Search for leftover TODOs in changed files
6. Generate a structured report with CRITICAL/HIGH/MEDIUM findings

## Examples

- Review current branch: "/run_review"
- Review specific file: "/run_review target=src/api/auth.py depth=thorough"
- Quick review: "/run_review depth=quick"
"""
    path = tmp_path / "review.md"
    path.write_text(content)
    return path


@pytest.fixture
def low_quality_skill(tmp_path):
    content = """\
---
name: Do Stuff
---

Does things and stuff.
"""
    path = tmp_path / "bad.md"
    path.write_text(content)
    return path


@pytest.fixture
def high_quality_role(tmp_path):
    content = """\
---
name: Debugger
description: Root cause analyst who isolates problems
tags: debug, investigation
---

You are a systematic debugger. Your job is to isolate problems methodically and find root causes.

## Principles

- Reproduce first. If you can't reproduce it, you can't fix it.
- Binary search the problem space: is it frontend or backend? This commit or older?
- Read the actual error message. Then read it again. Most errors tell you exactly what's wrong.
- Check the logs, network tab, database state, and environment variables.

## Anti-patterns (avoid these)

- Changing things randomly until it works ("shotgun debugging")
- Fixing the symptom without understanding the root cause
- Blaming infrastructure before checking your own code
"""
    path = tmp_path / "debugger.md"
    path.write_text(content)
    return path


@pytest.fixture
def low_quality_role(tmp_path):
    content = """\
---
name: Helper
---

Help people.
"""
    path = tmp_path / "helper.md"
    path.write_text(content)
    return path


class TestAnalyzeFile:
    def test_high_quality_skill_gets_good_grade(self, high_quality_skill):
        card = analyze_file(high_quality_skill)
        assert card.entity_type == "skill"
        assert card.grade in ("A", "B")
        assert card.overall_score >= 0.7

    def test_low_quality_skill_gets_bad_grade(self, low_quality_skill):
        card = analyze_file(low_quality_skill)
        assert card.grade in ("D", "F")
        assert card.overall_score < 0.5

    def test_high_quality_role_gets_good_grade(self, high_quality_role):
        card = analyze_file(high_quality_role)
        assert card.entity_type == "role"
        assert card.grade in ("A", "B")
        assert card.overall_score >= 0.7

    def test_low_quality_role_gets_bad_grade(self, low_quality_role):
        card = analyze_file(low_quality_role)
        assert card.grade in ("D", "F")

    def test_scorecard_has_dimensions(self, high_quality_skill):
        card = analyze_file(high_quality_skill)
        assert len(card.dimensions) == 6
        dim_names = [d.name for d in card.dimensions]
        assert "completeness" in dim_names
        assert "clarity" in dim_names
        assert "actionability" in dim_names
        assert "safety" in dim_names
        assert "testability" in dim_names
        assert "trust" in dim_names

    def test_role_has_4_dimensions(self, high_quality_role):
        card = analyze_file(high_quality_role)
        assert len(card.dimensions) == 4
        dim_names = [d.name for d in card.dimensions]
        assert "persona_clarity" in dim_names
        assert "principles_quality" in dim_names
        assert "anti_patterns" in dim_names
        assert "scope" in dim_names

    def test_summary_generated(self, high_quality_skill):
        card = analyze_file(high_quality_skill)
        assert card.summary
        assert "skill" in card.summary.lower()

    def test_to_dict(self, high_quality_skill):
        card = analyze_file(high_quality_skill)
        d = card.to_dict()
        assert "grade" in d
        assert "dimensions" in d
        assert isinstance(d["dimensions"], list)


class TestAnalyzeDirectory:
    def test_analyzes_all_files(self, tmp_path):
        (tmp_path / "a.md").write_text("---\nname: A\ntrigger: /a\n---\n\nSkill A.\n\n## Steps\n\n1. Do A\n")
        (tmp_path / "b.md").write_text("---\nname: B\ntrigger: /b\n---\n\nSkill B.\n\n## Steps\n\n1. Do B\n")
        cards = analyze_directory(tmp_path)
        assert len(cards) == 2

    def test_skips_readme(self, tmp_path):
        (tmp_path / "README.md").write_text("# Readme\n")
        (tmp_path / "skill.md").write_text("---\nname: X\ntrigger: /x\n---\n\nDo X.\n")
        cards = analyze_directory(tmp_path)
        assert len(cards) == 1

    def test_empty_directory(self, tmp_path):
        cards = analyze_directory(tmp_path)
        assert cards == []

    def test_nonexistent_directory(self, tmp_path):
        cards = analyze_directory(tmp_path / "nope")
        assert cards == []


class TestScoreCard:
    def test_compute_overall_empty(self):
        from skill_audit.models import ScoreCard
        card = ScoreCard(entity_type="skill", entity_name="x", format="unknown")
        card.compute_overall()
        assert card.overall_score == 0.0
        assert card.grade == "F"

    def test_grade_thresholds(self):
        from skill_audit.models import _score_to_grade
        assert _score_to_grade(0.95) == "A"
        assert _score_to_grade(0.9) == "A"
        assert _score_to_grade(0.85) == "B"
        assert _score_to_grade(0.8) == "B"
        assert _score_to_grade(0.7) == "C"
        assert _score_to_grade(0.65) == "C"
        assert _score_to_grade(0.55) == "D"
        assert _score_to_grade(0.5) == "D"
        assert _score_to_grade(0.4) == "F"
        assert _score_to_grade(0.0) == "F"
