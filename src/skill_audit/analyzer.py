"""Scoring engine: ties parser + rubrics together to produce ScoreCards."""

from pathlib import Path

from .models import ScoreCard
from .parser import ParsedArtifact, parse_file
from .rubrics.skill_rubrics import score_skill
from .rubrics.role_rubrics import score_role


def analyze_file(path: Path, force_format: str | None = None) -> ScoreCard:
    """Analyze a single skill or role file and return a ScoreCard."""
    artifact = parse_file(path, force_format)
    return analyze_artifact(artifact)


def analyze_artifact(artifact: ParsedArtifact) -> ScoreCard:
    """Score a parsed artifact and return a ScoreCard."""
    if artifact.entity_type == "role":
        dimensions = score_role(artifact)
    else:
        dimensions = score_skill(artifact)

    card = ScoreCard(
        entity_type=artifact.entity_type,
        entity_name=artifact.name,
        format=artifact.format,
        dimensions=dimensions,
        file_path=artifact.file_path,
    )

    card.compute_overall()
    card.summary = _generate_summary(card)
    return card


def analyze_directory(dir_path: Path, force_format: str | None = None) -> list[ScoreCard]:
    """Analyze all skill/role files in a directory.

    Scans top-level .md files and folder-based skills (dirs with main.md or
    SKILL.md). If nothing is found at the top level, checks common container
    directories (skills/, roles/, src/) one level deeper.
    """
    results = _scan_level(dir_path, force_format)

    # If nothing found, try common container directories
    if not results:
        for subdir_name in ("skills", "roles", "src"):
            subdir = dir_path / subdir_name
            if subdir.is_dir():
                results.extend(_scan_level(subdir, force_format))

    return results


def _scan_level(dir_path: Path, force_format: str | None = None) -> list[ScoreCard]:
    """Scan a single directory level for skill/role files."""
    results: list[ScoreCard] = []

    if not dir_path.exists():
        return results

    _SKIP_FILES = {"readme.md", "changelog.md", "license.md"}

    # .md files at this level
    for md_file in sorted(dir_path.glob("*.md")):
        if md_file.name.lower() in _SKIP_FILES:
            continue
        card = analyze_file(md_file, force_format)
        results.append(card)

    # Folder-based skills (dirs with main.md or SKILL.md)
    for item in sorted(dir_path.iterdir()):
        if not item.is_dir():
            continue
        skill_file = None
        if (item / "main.md").exists():
            skill_file = item / "main.md"
        elif (item / "SKILL.md").exists():
            skill_file = item / "SKILL.md"
        if skill_file:
            card = analyze_file(skill_file, force_format)
            results.append(card)

    return results


def _generate_summary(card: ScoreCard) -> str:
    """Generate a human-readable summary of the scorecard."""
    total_suggestions = sum(len(d.suggestions) for d in card.dimensions)

    if card.grade == "A":
        prefix = "Excellent"
    elif card.grade == "B":
        prefix = "Good"
    elif card.grade == "C":
        prefix = "Acceptable"
    elif card.grade == "D":
        prefix = "Needs work"
    else:
        prefix = "Poor"

    parts = [f"{prefix} {card.entity_type}"]
    if total_suggestions > 0:
        parts.append(f"with {total_suggestions} suggestions for improvement")

    # Highlight weakest dimension
    if card.dimensions:
        weakest = min(card.dimensions, key=lambda d: d.score)
        if weakest.score < 0.5:
            parts.append(f"(weakest: {weakest.name})")

    return " ".join(parts)
