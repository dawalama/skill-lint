"""Role scoring rubrics.

4 dimensions: persona_clarity, principles_quality, anti_patterns, scope.
"""

from ..models import ScoreDimension
from ..parser import ParsedArtifact


def score_role(artifact: ParsedArtifact) -> list[ScoreDimension]:
    """Score a role across 4 dimensions. Returns list of ScoreDimension."""
    return [
        _score_persona_clarity(artifact),
        _score_principles_quality(artifact),
        _score_anti_patterns(artifact),
        _score_scope(artifact),
    ]


def _score_persona_clarity(a: ParsedArtifact) -> ScoreDimension:
    """Has persona, starts with 'You are...', describes mission."""
    score = 0.0
    details: list[str] = []
    suggestions: list[str] = []

    # Has persona (0.35)
    if a.persona:
        score += 0.35
        details.append("Has persona text")
    else:
        suggestions.append("Add a persona paragraph describing who this role is")

    # Starts with "You are..." (0.30)
    if a.persona and a.persona.lower().startswith("you are"):
        score += 0.30
        details.append("Persona starts with 'You are...'")
    elif a.persona:
        score += 0.10
        suggestions.append("Start persona with 'You are a...' for clear identity")

    # Describes mission/purpose (0.35) — check for mission-oriented language
    if a.persona:
        mission_words = {"job", "goal", "purpose", "mission", "responsible", "focus", "task"}
        persona_lower = a.persona.lower()
        found = any(w in persona_lower for w in mission_words)
        if found:
            score += 0.35
            details.append("Persona describes mission/purpose")
        else:
            score += 0.10
            suggestions.append("Describe the role's mission (e.g. 'Your job is to...')")

    return ScoreDimension(
        name="persona_clarity",
        score=min(score, 1.0),
        weight=0.30,
        details=details,
        suggestions=suggestions,
    )


def _score_principles_quality(a: ParsedArtifact) -> ScoreDimension:
    """Has 3+ principles, specific (>30 chars, concrete nouns)."""
    score = 0.0
    details: list[str] = []
    suggestions: list[str] = []

    # Has principles (0.35)
    if a.principles:
        score += 0.35
        details.append(f"Has {len(a.principles)} principles")
    else:
        suggestions.append("Add a ## Principles section with guiding rules")
        return ScoreDimension(
            name="principles_quality",
            score=0.0,
            weight=0.30,
            details=details,
            suggestions=suggestions,
        )

    # Has 3+ principles (0.30)
    if len(a.principles) >= 3:
        score += 0.30
        details.append("Has 3+ principles (good coverage)")
    else:
        score += 0.10
        suggestions.append(f"Add more principles (have {len(a.principles)}, recommend 3+)")

    # Principles are specific (0.35) — >30 chars with concrete content
    specific = sum(1 for p in a.principles if len(p) > 30)
    if a.principles:
        ratio = specific / len(a.principles)
        score += 0.35 * ratio
        if ratio >= 0.8:
            details.append("Principles are specific and detailed")
        else:
            suggestions.append("Make principles more specific (>30 chars each, with concrete guidance)")

    return ScoreDimension(
        name="principles_quality",
        score=min(score, 1.0),
        weight=0.30,
        details=details,
        suggestions=suggestions,
    )


def _score_anti_patterns(a: ParsedArtifact) -> ScoreDimension:
    """Present, 2+ items, specific."""
    score = 0.0
    details: list[str] = []
    suggestions: list[str] = []

    # Present (0.40)
    if a.anti_patterns:
        score += 0.40
        details.append(f"Has {len(a.anti_patterns)} anti-patterns")
    else:
        suggestions.append("Add an ## Anti-patterns section listing what to avoid")
        return ScoreDimension(
            name="anti_patterns",
            score=0.0,
            weight=0.20,
            details=details,
            suggestions=suggestions,
        )

    # 2+ items (0.30)
    if len(a.anti_patterns) >= 2:
        score += 0.30
        details.append("Has 2+ anti-patterns")
    else:
        score += 0.10
        suggestions.append("Add more anti-patterns (recommend 2+)")

    # Specific (0.30) — >30 chars
    specific = sum(1 for ap in a.anti_patterns if len(ap) > 30)
    if a.anti_patterns:
        ratio = specific / len(a.anti_patterns)
        score += 0.30 * ratio
        if ratio >= 0.8:
            details.append("Anti-patterns are specific and detailed")
        else:
            suggestions.append("Make anti-patterns more specific (explain why they're bad)")

    return ScoreDimension(
        name="anti_patterns",
        score=min(score, 1.0),
        weight=0.20,
        details=details,
        suggestions=suggestions,
    )


def _score_scope(a: ParsedArtifact) -> ScoreDimension:
    """Has description, focused (<120 chars), has tags."""
    score = 0.0
    details: list[str] = []
    suggestions: list[str] = []

    # Has description (0.40)
    if a.description:
        score += 0.40
        details.append("Has description")
    else:
        suggestions.append("Add a description in frontmatter or first line of persona")

    # Focused description (<120 chars) (0.30)
    if a.description:
        if len(a.description) <= 120:
            score += 0.30
            details.append(f"Description is focused ({len(a.description)} chars)")
        else:
            score += 0.10
            suggestions.append(f"Shorten description to under 120 chars (currently {len(a.description)})")

    # Has tags (0.30)
    if a.tags:
        score += 0.30
        details.append(f"Has {len(a.tags)} tags")
    else:
        suggestions.append("Add tags in frontmatter for discoverability")

    return ScoreDimension(
        name="scope",
        score=min(score, 1.0),
        weight=0.20,
        details=details,
        suggestions=suggestions,
    )
