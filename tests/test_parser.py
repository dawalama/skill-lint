"""Tests for skill-lint parser."""

import pytest
from pathlib import Path

from skill_audit.parser import parse_file, detect_format, ParsedArtifact


@pytest.fixture
def dotai_skill(tmp_path):
    content = """\
---
name: Code Review
trigger: /run_review
role: reviewer
category: code-quality
allowed-tools: Read, Grep, Glob
tags: review, quality
---

Analyze code for structural issues.

## Inputs

- `target` (optional): Files to review
- `depth` (required): Review depth

## Gotchas

- Large diffs should be split
- Check base branch first

## Steps

1. Detect the base branch
2. Run git diff to see changes
3. Review each changed file
4. Generate findings report

## Examples

- Review branch: "/run_review"
- Review file: "/run_review target=src/api.py depth=thorough"
"""
    path = tmp_path / "review.md"
    path.write_text(content)
    return path


@pytest.fixture
def dotai_role(tmp_path):
    content = """\
---
name: Debugger
description: Root cause analyst
tags: debug, investigation
---

You are a systematic debugger. Your job is to isolate problems methodically.

## Principles

- Reproduce first. If you can't reproduce it, you can't fix it.
- Binary search the problem space
- Read the actual error message carefully

## Anti-patterns (avoid these)

- Changing things randomly until it works
- Fixing the symptom without understanding the cause
"""
    path = tmp_path / "debugger.md"
    path.write_text(content)
    return path


@pytest.fixture
def claude_native_skill(tmp_path):
    content = """\
---
name: PDF Summarizer
description: Summarize PDF documents
compatibility: claude-3, claude-4
license: MIT
---

Summarize a PDF document into key takeaways.

## Parameters

- `file_path` (required): Path to the PDF
- `length` (optional): Summary length

## Usage

- Summarize: pdf-summarizer doc.pdf
- Short: pdf-summarizer doc.pdf --length short

## Caveats

- Large PDFs may hit token limits
"""
    path = tmp_path / "SKILL.md"
    path.write_text(content)
    return path


@pytest.fixture
def plain_md(tmp_path):
    content = "# Just a readme\n\nNothing to see.\n"
    path = tmp_path / "notes.md"
    path.write_text(content)
    return path


class TestDetectFormat:
    def test_dotai_skill(self, dotai_skill):
        assert detect_format(dotai_skill) == "dotai-skill"

    def test_dotai_role(self, dotai_role):
        assert detect_format(dotai_role) == "dotai-role"

    def test_claude_native(self, claude_native_skill):
        assert detect_format(claude_native_skill) == "claude-native"

    def test_unknown(self, plain_md):
        assert detect_format(plain_md) == "unknown"

    def test_nonexistent(self, tmp_path):
        assert detect_format(tmp_path / "nope.md") == "unknown"

    def test_directory_with_skill_md(self, tmp_path):
        d = tmp_path / "skill"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: X\n---\nDo stuff.\n")
        assert detect_format(d) == "claude-native"

    def test_directory_with_main_md(self, tmp_path):
        d = tmp_path / "skill"
        d.mkdir()
        (d / "main.md").write_text("---\ntrigger: /x\n---\nDo stuff.\n")
        assert detect_format(d) == "dotai-skill"


class TestParseFile:
    def test_parses_dotai_skill(self, dotai_skill):
        result = parse_file(dotai_skill)
        assert result.entity_type == "skill"
        assert result.name == "Code Review"
        assert result.trigger == "/run_review"
        assert result.category == "code-quality"
        assert len(result.steps) == 4
        assert len(result.inputs) == 2
        assert len(result.examples) == 2
        assert len(result.gotchas) == 2
        assert result.inputs[0]["name"] == "target"
        assert result.inputs[1]["required"] is True

    def test_parses_dotai_role(self, dotai_role):
        result = parse_file(dotai_role)
        assert result.entity_type == "role"
        assert result.name == "Debugger"
        assert "systematic debugger" in result.persona
        assert len(result.principles) == 3
        assert len(result.anti_patterns) == 2

    def test_parses_claude_native(self, claude_native_skill):
        result = parse_file(claude_native_skill)
        assert result.entity_type == "skill"
        assert result.name == "PDF Summarizer"
        assert len(result.inputs) == 2
        assert len(result.examples) == 2
        assert len(result.gotchas) == 1

    def test_parses_unknown(self, plain_md):
        result = parse_file(plain_md)
        assert result.format == "unknown"

    def test_force_format(self, dotai_skill):
        result = parse_file(dotai_skill, force_format="claude-native")
        assert result.format == "claude-native"

    def test_parses_directory(self, tmp_path):
        d = tmp_path / "skill"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: Test\ncompatibility: claude-3\n---\n\nA test.\n")
        result = parse_file(d)
        assert result.name == "Test"

    def test_extracts_description_from_body(self, dotai_skill):
        result = parse_file(dotai_skill)
        assert "structural issues" in result.description

    def test_extracts_tags(self, dotai_skill):
        result = parse_file(dotai_skill)
        assert "review" in result.tags
        assert "quality" in result.tags

    def test_extracts_allowed_tools(self, dotai_skill):
        result = parse_file(dotai_skill)
        assert "Read" in result.allowed_tools
        assert "Grep" in result.allowed_tools
