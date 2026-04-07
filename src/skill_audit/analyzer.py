"""Scoring engine: ties parser + rubrics together to produce ScoreCards."""

from __future__ import annotations

from pathlib import Path

from .config import WeightsConfig
from .ignore import IgnoreConfig
from .models import ScoreCard, ScoreDimension
from .parser import ParsedArtifact, parse_file, detect_format
from .rubrics.skill_rubrics import score_skill
from .rubrics.role_rubrics import score_role


def analyze_file(
    path: Path,
    force_format: str | None = None,
    ignore_config: IgnoreConfig | None = None,
    custom_patterns: list[tuple[str, str, str]] | None = None,
    weights: WeightsConfig | None = None,
    trust_inline: bool = True,
) -> ScoreCard:
    """Analyze a single skill or role file and return a ScoreCard."""
    fmt = force_format or detect_format(path)
    if fmt == "mcp-config":
        return analyze_mcp_config(path)
    artifact = parse_file(path, force_format)
    return analyze_artifact(artifact, ignore_config=ignore_config, custom_patterns=custom_patterns, weights=weights, trust_inline=trust_inline)


def analyze_artifact(
    artifact: ParsedArtifact,
    ignore_config: IgnoreConfig | None = None,
    custom_patterns: list[tuple[str, str, str]] | None = None,
    weights: WeightsConfig | None = None,
    trust_inline: bool = True,
) -> ScoreCard:
    """Score a parsed artifact and return a ScoreCard.

    When trust_inline=False, inline suppression comments in the file are
    ignored entirely. This is used for remote/untrusted targets where the
    file author should not be able to influence their own audit score.
    """
    # Collect ignored categories from config file (operator-controlled)
    ignore_categories: set[str] = set()
    if ignore_config is not None:
        file_path = artifact.file_path if hasattr(artifact, "file_path") else None
        ignore_categories |= ignore_config.ignored_categories(file_path)
    # Parse inline ignores from raw content — only if the file is trusted
    if trust_inline:
        raw_content = artifact.raw_body or ""
        inline_ignored = IgnoreConfig.parse_inline_ignores(raw_content)
        ignore_categories |= inline_ignored

    w = weights or WeightsConfig()

    if artifact.entity_type == "role":
        dimensions = score_role(artifact, weights=w)
    else:
        dimensions = score_skill(artifact, ignore_categories=ignore_categories, custom_patterns=custom_patterns, weights=w, trust_inline=trust_inline)

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


_DOC_FILES = {
    # Standard repo docs
    "readme.md", "changelog.md", "license.md", "licence.md",
    # Contribution / governance docs
    "contributing.md", "contributors.md", "code_of_conduct.md",
    "security.md", "governance.md",
    # Project management docs
    "installation.md", "setup.md", "getting-started.md",
    "architecture.md", "design.md", "roadmap.md",
    # Claude/AI config files (not skills)
    "claude.md", "gemini.md", "conventions.md",
    # Audit / pipeline docs
    "audit_report.md", "skill_pipeline.md", "store.md",
    # Project structure / meta docs
    "agents.md", "ethos.md", "todos.md", "browser.md",
    "todos.md", "vision.md", "philosophy.md",
}


def analyze_directory(
    dir_path: Path,
    force_format: str | None = None,
    ignore_config: IgnoreConfig | None = None,
    custom_patterns: list[tuple[str, str, str]] | None = None,
    weights: WeightsConfig | None = None,
    include_docs: bool = False,
    trust_inline: bool = True,
) -> tuple[list[ScoreCard], int]:
    """Analyze all skill/role files in a directory.

    Scans top-level .md files and folder-based skills (dirs with main.md or
    SKILL.md). If nothing is found at the top level, checks common container
    directories (skills/, roles/, src/) one level deeper.

    Returns (cards, skipped_count) where skipped_count is the number of
    documentation files that were skipped.
    """
    results, skipped = _scan_level(dir_path, force_format, ignore_config, custom_patterns, weights, include_docs, trust_inline)

    # If nothing found, try common container directories
    if not results:
        for subdir_name in ("skills", "roles", "src"):
            subdir = dir_path / subdir_name
            if subdir.is_dir():
                sub_results, sub_skipped = _scan_level(subdir, force_format, ignore_config, custom_patterns, weights, include_docs, trust_inline)
                results.extend(sub_results)
                skipped += sub_skipped

    return results, skipped


def _scan_level(
    dir_path: Path,
    force_format: str | None = None,
    ignore_config: IgnoreConfig | None = None,
    custom_patterns: list[tuple[str, str, str]] | None = None,
    weights: WeightsConfig | None = None,
    include_docs: bool = False,
    trust_inline: bool = True,
) -> tuple[list[ScoreCard], int]:
    """Scan a single directory level for skill/role files."""
    results: list[ScoreCard] = []
    skipped = 0

    if not dir_path.exists():
        return results, skipped

    # MCP config files at this level
    _MCP_FILES = {"mcp.json", "claude_desktop_config.json"}
    for mcp_name in sorted(_MCP_FILES):
        mcp_file = dir_path / mcp_name
        if mcp_file.exists():
            card = analyze_mcp_config(mcp_file)
            results.append(card)

    # .md files at this level
    for md_file in sorted(dir_path.glob("*.md")):
        if not include_docs and md_file.name.lower() in _DOC_FILES:
            skipped += 1
            continue
        card = analyze_file(md_file, force_format, ignore_config=ignore_config, custom_patterns=custom_patterns, weights=weights, trust_inline=trust_inline)
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
            card = analyze_file(skill_file, force_format, ignore_config=ignore_config, custom_patterns=custom_patterns, weights=weights, trust_inline=trust_inline)
            results.append(card)

    return results, skipped


def analyze_mcp_config(path: Path) -> ScoreCard:
    """Analyze an MCP config file and return a ScoreCard."""
    from .mcp_scanner import scan_mcp_config

    result = scan_mcp_config(path)

    dimensions: list[ScoreDimension] = []

    # --- Command safety dimension ---
    cmd_findings = [f for f in result.servers if f.category == "risky-command"]
    cmd_score = 1.0
    cmd_details: list[str] = []
    cmd_suggestions: list[str] = []
    if cmd_findings:
        for f in cmd_findings:
            deduction = 0.5 if f.severity == "critical" else 0.3
            cmd_score = max(0.0, cmd_score - deduction)
            cmd_suggestions.append(f"[{f.server_name}] {f.message}")
    else:
        cmd_details.append("No risky command patterns detected")
    dimensions.append(ScoreDimension(
        name="command_safety",
        score=cmd_score,
        weight=0.30,
        details=cmd_details,
        suggestions=cmd_suggestions,
    ))

    # --- Filesystem scope dimension ---
    fs_findings = [f for f in result.servers if f.category == "broad-filesystem"]
    fs_score = 1.0
    fs_details: list[str] = []
    fs_suggestions: list[str] = []
    if fs_findings:
        for f in fs_findings:
            fs_score = max(0.0, fs_score - 0.3)
            fs_suggestions.append(f"[{f.server_name}] {f.message}")
    else:
        fs_details.append("No overly broad filesystem access detected")
    dimensions.append(ScoreDimension(
        name="filesystem_scope",
        score=fs_score,
        weight=0.25,
        details=fs_details,
        suggestions=fs_suggestions,
    ))

    # --- Secrets / env leaks dimension ---
    env_findings = [f for f in result.servers if f.category == "env-leak"]
    env_score = 1.0
    env_details: list[str] = []
    env_suggestions: list[str] = []
    if env_findings:
        for f in env_findings:
            deduction = 0.4 if f.severity == "high" else 0.2
            env_score = max(0.0, env_score - deduction)
            env_suggestions.append(f"[{f.server_name}] {f.message}")
    else:
        env_details.append("No hardcoded secrets in environment variables")
    dimensions.append(ScoreDimension(
        name="secret_hygiene",
        score=env_score,
        weight=0.20,
        details=env_details,
        suggestions=env_suggestions,
    ))

    # --- Network / auth / URL dimension ---
    net_categories = {"network-exposure", "suspicious-url", "no-auth", "overly-permissive"}
    net_findings = [f for f in result.servers if f.category in net_categories]
    net_score = 1.0
    net_details: list[str] = []
    net_suggestions: list[str] = []
    if net_findings:
        for f in net_findings:
            deduction = {"critical": 0.5, "high": 0.3, "medium": 0.15}.get(f.severity, 0.1)
            net_score = max(0.0, net_score - deduction)
            net_suggestions.append(f"[{f.server_name}] {f.message}")
    else:
        net_details.append("No network exposure or suspicious URL issues")
    dimensions.append(ScoreDimension(
        name="network_trust",
        score=net_score,
        weight=0.25,
        details=net_details,
        suggestions=net_suggestions,
    ))

    card = ScoreCard(
        entity_type="mcp-config",
        entity_name=path.name,
        format="mcp-config",
        dimensions=dimensions,
        file_path=path,
    )
    card.compute_overall()
    card.summary = _generate_mcp_summary(card, result)
    return card


def _generate_mcp_summary(card: ScoreCard, result) -> str:
    """Generate a human-readable summary for an MCP config scorecard."""
    risk_label = result.overall_risk.upper()
    total_findings = len(result.servers)

    if card.grade in ("A", "B"):
        prefix = "Clean" if card.grade == "A" else "Mostly safe"
    elif card.grade == "C":
        prefix = "Some concerns"
    else:
        prefix = "Risky"

    parts = [f"{prefix} MCP config"]
    parts.append(f"({result.server_count} server(s), {total_findings} finding(s), risk: {risk_label})")

    weakest = min(card.dimensions, key=lambda d: d.score) if card.dimensions else None
    if weakest and weakest.score < 0.5:
        parts.append(f"(weakest: {weakest.name})")

    return " ".join(parts)


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
