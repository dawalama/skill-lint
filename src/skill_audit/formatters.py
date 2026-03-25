"""Output formatters for skill-audit results."""

import json

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .models import ScoreCard


def format_table(card: ScoreCard, verbose: bool = False) -> None:
    """Print a scorecard as a Rich table."""
    console = Console()

    grade_color = _grade_color(card.grade)
    title = f"[bold]{card.entity_name}[/bold] ({card.entity_type}) — Grade: [{grade_color}]{card.grade}[/{grade_color}] ({card.overall_score:.0%})"

    console.print()
    console.print(Panel(title, subtitle=f"Format: {card.format}"))

    table = Table(show_header=True)
    table.add_column("Dimension", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Weight", justify="right", style="dim")
    table.add_column("Status")

    for dim in card.dimensions:
        score_color = _grade_color(_score_to_quick_grade(dim.score))
        status = _score_bar(dim.score)
        table.add_row(
            dim.name,
            f"[{score_color}]{dim.score:.0%}[/{score_color}]",
            f"{dim.weight:.0%}",
            status,
        )

    console.print(table)

    if verbose:
        # In verbose mode, show suggestions (what to fix) prominently,
        # and details (what's good) only for imperfect dimensions
        has_suggestions = any(dim.suggestions for dim in card.dimensions)
        has_imperfect = any(dim.score < 1.0 for dim in card.dimensions)

        if has_suggestions or has_imperfect:
            console.print()
            for dim in card.dimensions:
                # Skip perfect dimensions in verbose — no news is good news
                if dim.score >= 1.0 and not dim.suggestions:
                    continue

                console.print(f"  [bold]{dim.name}[/bold] ({dim.score:.0%})")

                # Show details for imperfect or interesting dimensions
                for detail in dim.details:
                    console.print(f"    [green]+[/green] {detail}")
                for suggestion in dim.suggestions:
                    console.print(f"    [yellow]![/yellow] {suggestion}")

    if card.summary:
        console.print(f"\n  {card.summary}")
    console.print()


def format_llm_findings(findings: list, entity_name: str, model: str,
                        verbose: bool = False, error: str = "") -> None:
    """Print LLM review findings with clear structure."""
    console = Console()

    if error:
        console.print(f"    [red]Error: {error}[/red]")
        return

    if not findings:
        console.print(f"    [green]Clean — no issues found[/green] [dim]({model})[/dim]")
        return

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    ordered = sorted(findings, key=lambda f: severity_order.get(f.severity, 4))

    severity_labels = {
        "critical": "[red bold]CRITICAL[/red bold]",
        "high": "[red]HIGH[/red]",
        "medium": "[yellow]MEDIUM[/yellow]",
        "low": "[dim]LOW[/dim]",
    }

    for i, finding in enumerate(ordered):
        num = i + 1
        label = severity_labels.get(finding.severity, finding.severity.upper())

        # Numbered finding with severity
        console.print(f"    {num}. {label}  {finding.message}")

        # Recommendation (always shown if present — this is the actionable part)
        if finding.recommendation:
            console.print(f"       [green]Fix:[/green] {finding.recommendation}")

        # Evidence only in verbose
        if verbose and finding.evidence:
            evidence = finding.evidence.replace("\n", " ").strip()[:150]
            console.print(f"       [dim]Evidence: {evidence}[/dim]")

        # Space between findings
        if i < len(ordered) - 1:
            console.print()

    console.print(f"\n    [dim]{len(findings)} finding(s) via {model}[/dim]")


def format_json(cards: list[ScoreCard]) -> str:
    """Format scorecards as JSON."""
    return json.dumps([c.to_dict() for c in cards], indent=2)


def format_markdown(card: ScoreCard) -> str:
    """Format a scorecard as markdown."""
    lines = [
        f"# {card.entity_name} ({card.entity_type})",
        "",
        f"**Grade:** {card.grade} ({card.overall_score:.0%})  ",
        f"**Format:** {card.format}  ",
        "",
        "## Dimensions",
        "",
        "| Dimension | Score | Weight |",
        "|-----------|-------|--------|",
    ]

    for dim in card.dimensions:
        lines.append(f"| {dim.name} | {dim.score:.0%} | {dim.weight:.0%} |")

    lines.append("")

    for dim in card.dimensions:
        if dim.suggestions:
            lines.append(f"### {dim.name}")
            lines.append("")
            for detail in dim.details:
                lines.append(f"- {detail}")
            for suggestion in dim.suggestions:
                lines.append(f"- **Fix:** {suggestion}")
            lines.append("")

    if card.summary:
        lines.append(f"**Summary:** {card.summary}")

    return "\n".join(lines)


def format_summary_table(cards: list[ScoreCard]) -> None:
    """Print a summary table of multiple scorecards."""
    console = Console()

    table = Table(title="Skill Audit Summary", show_header=True)
    table.add_column("File", style="bold")
    table.add_column("Type")
    table.add_column("Name")
    table.add_column("Grade", justify="center")
    table.add_column("Score", justify="right")
    table.add_column("Issues", justify="right")

    for card in sorted(cards, key=lambda c: c.overall_score, reverse=True):
        grade_color = _grade_color(card.grade)
        suggestions = sum(len(d.suggestions) for d in card.dimensions)
        file_name = card.file_path.name if card.file_path else "?"
        table.add_row(
            file_name,
            card.entity_type,
            card.entity_name,
            f"[{grade_color}]{card.grade}[/{grade_color}]",
            f"{card.overall_score:.0%}",
            str(suggestions) if suggestions else "-",
        )

    console.print()
    console.print(table)

    if cards:
        avg = sum(c.overall_score for c in cards) / len(cards)
        console.print(f"\n  {len(cards)} files analyzed, average score: {avg:.0%}")
    console.print()


def _grade_color(grade: str) -> str:
    return {
        "A": "green",
        "B": "blue",
        "C": "yellow",
        "D": "red",
        "F": "red bold",
    }.get(grade, "white")


def _score_bar(score: float, width: int = 10) -> str:
    filled = int(score * width)
    empty = width - filled
    return f"[green]{'█' * filled}[/green][dim]{'░' * empty}[/dim]"


def _score_to_quick_grade(score: float) -> str:
    if score >= 0.8:
        return "A"
    elif score >= 0.6:
        return "B"
    elif score >= 0.4:
        return "C"
    else:
        return "D"
