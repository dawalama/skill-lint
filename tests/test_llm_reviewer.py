"""Tests for LLM reviewer — tests parsing logic without making real LLM calls."""

import pytest

from skill_audit.llm_reviewer import (
    _parse_response,
    LLMReview,
    LLMFinding,
)


class TestParseResponse:
    def test_parses_clean_json_array(self):
        response = '[]'
        review = _parse_response(response, "test", "test-model")
        assert review.findings == []
        assert review.provider == "test"
        assert review.model == "test-model"

    def test_parses_findings(self):
        response = '''[
            {"category": "INJECTION", "severity": "critical", "message": "Hidden override", "evidence": "ignore previous"},
            {"category": "QUALITY", "severity": "low", "message": "Steps could be clearer"}
        ]'''
        review = _parse_response(response, "test", "model")
        assert len(review.findings) == 2
        assert review.findings[0].category == "INJECTION"
        assert review.findings[0].severity == "critical"
        assert review.findings[1].category == "QUALITY"

    def test_extracts_json_from_markdown_wrapper(self):
        response = '''Here is my analysis:

```json
[{"category": "INTENT_MISMATCH", "severity": "high", "message": "Says review but deletes files", "evidence": "rm -rf"}]
```

That's all I found.'''
        review = _parse_response(response, "test", "model")
        assert len(review.findings) == 1
        assert review.findings[0].category == "INTENT_MISMATCH"

    def test_handles_empty_array_in_text(self):
        response = "I reviewed the skill and found no issues. []"
        review = _parse_response(response, "test", "model")
        assert review.findings == []
        assert review.error == ""

    def test_handles_unparseable_response(self):
        response = "I couldn't analyze this properly, sorry."
        review = _parse_response(response, "test", "model")
        assert review.findings == []
        assert review.error  # Should have an error

    def test_handles_missing_fields(self):
        response = '[{"category": "QUALITY", "message": "Something vague"}]'
        review = _parse_response(response, "test", "model")
        assert len(review.findings) == 1
        assert review.findings[0].severity == "medium"  # default
        assert review.findings[0].evidence == ""  # default

    def test_passed_property(self):
        clean = LLMReview(provider="test", model="m", findings=[])
        assert clean.passed is True

        low_risk = LLMReview(provider="test", model="m", findings=[
            LLMFinding(category="QUALITY", severity="low", message="minor"),
        ])
        assert low_risk.passed is True

        critical = LLMReview(provider="test", model="m", findings=[
            LLMFinding(category="INJECTION", severity="critical", message="bad"),
        ])
        assert critical.passed is False

        high = LLMReview(provider="test", model="m", findings=[
            LLMFinding(category="INTENT_MISMATCH", severity="high", message="mismatch"),
        ])
        assert high.passed is False
