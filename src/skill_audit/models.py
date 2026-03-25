"""Data models for skill-lint scoring."""

from pathlib import Path

from pydantic import BaseModel, Field


class ScoreDimension(BaseModel):
    """A single scoring dimension with score and feedback."""

    name: str
    score: float = Field(ge=0.0, le=1.0)
    max_score: float = 1.0
    weight: float = 0.2
    details: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class ScoreCard(BaseModel):
    """Complete scoring result for a skill or role."""

    entity_type: str  # "skill" or "role"
    entity_name: str
    format: str  # "dotai-skill", "dotai-role", "claude-native", "unknown"
    dimensions: list[ScoreDimension] = Field(default_factory=list)
    overall_score: float = 0.0
    grade: str = "F"
    summary: str = ""
    file_path: Path | None = None

    def compute_overall(self) -> None:
        """Compute weighted overall score and grade from dimensions."""
        if not self.dimensions:
            self.overall_score = 0.0
            self.grade = "F"
            return

        total_weight = sum(d.weight for d in self.dimensions)
        if total_weight == 0:
            self.overall_score = 0.0
        else:
            self.overall_score = sum(d.score * d.weight for d in self.dimensions) / total_weight

        self.grade = _score_to_grade(self.overall_score)

    def to_dict(self) -> dict:
        """Serialize to dict for JSON output."""
        return {
            "entity_type": self.entity_type,
            "entity_name": self.entity_name,
            "format": self.format,
            "overall_score": round(self.overall_score, 3),
            "grade": self.grade,
            "summary": self.summary,
            "file_path": str(self.file_path) if self.file_path else None,
            "dimensions": [
                {
                    "name": d.name,
                    "score": round(d.score, 3),
                    "weight": d.weight,
                    "details": d.details,
                    "suggestions": d.suggestions,
                }
                for d in self.dimensions
            ],
        }


def _score_to_grade(score: float) -> str:
    """Convert a 0-1 score to a letter grade."""
    if score >= 0.9:
        return "A"
    elif score >= 0.8:
        return "B"
    elif score >= 0.65:
        return "C"
    elif score >= 0.5:
        return "D"
    else:
        return "F"
