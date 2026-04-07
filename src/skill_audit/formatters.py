"""Output formatters for skill-audit results."""

import json
import html as html_mod

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .models import ScoreCard
from . import __version__


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

    if card.entity_type == "mcp-config":
        _format_mcp_summary(card, console)
    elif card.summary:
        console.print(f"\n  {card.summary}")

    console.print()


def _format_mcp_summary(card: ScoreCard, console: Console) -> None:
    """Print enhanced summary for MCP config scorecards."""
    # Extract risk level from summary (e.g. "risk: CRITICAL")
    import re
    risk_match = re.search(r"risk:\s*(\w+)", card.summary)
    risk = risk_match.group(1) if risk_match else "UNKNOWN"

    risk_colors = {"CRITICAL": "red bold", "HIGH": "red", "MEDIUM": "yellow", "LOW": "green"}
    risk_color = risk_colors.get(risk, "white")

    # Find weakest dimension
    weakest = min(card.dimensions, key=lambda d: d.score) if card.dimensions else None
    weakest_detail = ""
    if weakest and weakest.score < 1.0:
        finding_count = len(weakest.suggestions)
        weakest_detail = f" — Weakest: {weakest.name}"
        if finding_count:
            weakest_detail += f" ({finding_count} finding{'s' if finding_count != 1 else ''})"

    # Count servers from summary
    server_match = re.search(r"(\d+) server", card.summary)
    servers = server_match.group(1) if server_match else "?"
    total_findings = sum(len(d.suggestions) for d in card.dimensions)

    console.print(f"\n  [bold]Overall Risk: [{risk_color}]{risk}[/{risk_color}][/bold]{weakest_detail}")
    console.print(f"  [dim]{servers} server(s) configured, {total_findings} finding(s)[/dim]")

    # Show recommendation for anything below A
    if card.grade not in ("A",):
        has_secrets = any(d.name == "secret_hygiene" and d.score < 1.0 for d in card.dimensions)
        has_access = any(d.name in ("command_safety", "filesystem_scope") and d.score < 1.0 for d in card.dimensions)

        rec_parts = []
        if has_secrets:
            rec_parts.append("move all secrets to a .env file or credential manager")
        if has_access:
            rec_parts.append("apply least-privilege rules for filesystem and shell access")
        if not rec_parts:
            rec_parts.append("review findings and address flagged issues")

        console.print(f"\n  [yellow bold]Recommendation:[/yellow bold] {'; '.join(rec_parts).capitalize()}.")


def format_llm_findings(findings: list, entity_name: str, model: str,
                        verbose: bool = False, error: str = "") -> None:
    """Print LLM review findings grouped by severity with deduplication."""
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

    # Top Risks summary — show critical+high as a quick glance box
    top_risks = [f for f in ordered if f.severity in ("critical", "high")]
    if top_risks:
        console.print(f"    [bold]Top Risks[/bold]")
        for f in top_risks:
            label = severity_labels[f.severity]
            console.print(f"      {label}  {f.message}")
        console.print()

    # Group findings by severity
    groups: dict[str, list] = {}
    for f in ordered:
        groups.setdefault(f.severity, []).append(f)

    # Print each severity group with details (skip critical/high if already shown above without verbose)
    for severity in ("critical", "high", "medium", "low"):
        group = groups.get(severity, [])
        if not group:
            continue

        # In non-verbose mode, critical/high details already shown in Top Risks
        if severity in ("critical", "high") and not verbose:
            # Just show the fixes inline under Top Risks
            for finding in group:
                if finding.recommendation:
                    console.print(f"      [green]Fix:[/green] {finding.recommendation}")
            if group:
                console.print()
            continue

        label = severity_labels[severity]
        header = {
            "critical": "Immediate action recommended",
            "high": "Should be addressed",
            "medium": "Worth reviewing",
            "low": "Minor concerns",
        }[severity]
        console.print(f"    {label} — {header}")

        for finding in group:
            console.print(f"      - {finding.message}")
            if finding.recommendation:
                console.print(f"        [green]Fix:[/green] {finding.recommendation}")
            if verbose and finding.evidence:
                evidence = finding.evidence.replace("\n", " ").strip()[:150]
                console.print(f"        [dim]Evidence: {evidence}[/dim]")

        console.print()

    console.print(f"    [dim]{len(findings)} finding(s) via {model}[/dim]")


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


def format_html(cards: list[ScoreCard], llm_findings: dict[str, list] | None = None, audit_source: str = "", audit_command: str = "") -> str:
    """Generate a self-contained HTML report for scorecards.

    Args:
        cards: ScoreCards to render
        llm_findings: Optional dict mapping entity_name -> list of LLMFinding objects
        audit_source: The path/URL that was audited
        audit_command: The full CLI command used
    """
    grade_colors = {
        "A": "#22c55e",
        "B": "#3b82f6",
        "C": "#eab308",
        "D": "#ef4444",
        "F": "#dc2626",
    }

    def _score_color_css(score: float) -> str:
        if score >= 0.8:
            return grade_colors["A"]
        elif score >= 0.6:
            return grade_colors["B"]
        elif score >= 0.4:
            return grade_colors["C"]
        else:
            return grade_colors["D"]

    def _esc(text: str) -> str:
        return html_mod.escape(text)

    def _slug(name: str) -> str:
        """Convert a name to a URL-safe anchor slug."""
        import re as _re
        return _re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')

    def _render_card(card: ScoreCard) -> str:
        gc = grade_colors.get(card.grade, "#888")
        slug = _slug(card.entity_name)
        sections = []

        # Header
        sections.append(f'''<div class="card" id="{slug}">
  <div class="card-header">
    <div class="card-title">
      <h2>{_esc(card.entity_name)}</h2>
      <span class="badge" style="background:{gc}">{_esc(card.grade)}</span>
    </div>
    <div class="card-meta">
      <span class="tag">{_esc(card.entity_type)}</span>
      <span class="tag">{_esc(card.format)}</span>
      <span class="score-label">Score: {card.overall_score:.0%}</span>
    </div>
  </div>''')

        # Dimensions
        sections.append('  <div class="dimensions">')
        for dim in card.dimensions:
            sc = _score_color_css(dim.score)
            pct = dim.score * 100
            sections.append(f'''    <div class="dim-row">
      <div class="dim-info">
        <span class="dim-name">{_esc(dim.name)}</span>
        <span class="dim-score" style="color:{sc}">{dim.score:.0%}</span>
        <span class="dim-weight">weight {dim.weight:.0%}</span>
      </div>
      <div class="bar-track">
        <div class="bar-fill" style="width:{pct:.1f}%;background:{sc}"></div>
      </div>
    </div>''')
        sections.append('  </div>')

        # Details / suggestions (collapsible)
        has_details = any(dim.details or dim.suggestions for dim in card.dimensions)
        if has_details:
            sections.append('  <details class="detail-section"><summary>Details &amp; Suggestions</summary>')
            for dim in card.dimensions:
                if not dim.details and not dim.suggestions:
                    continue
                sections.append(f'    <h4>{_esc(dim.name)} ({dim.score:.0%})</h4>')
                if dim.details:
                    sections.append('    <ul class="detail-list">')
                    for d in dim.details:
                        sections.append(f'      <li>{_esc(d)}</li>')
                    sections.append('    </ul>')
                if dim.suggestions:
                    sections.append('    <ul class="suggestion-list">')
                    for s in dim.suggestions:
                        sections.append(f'      <li>{_esc(s)}</li>')
                    sections.append('    </ul>')
            sections.append('  </details>')

        # LLM findings
        card_llm = (llm_findings or {}).get(card.entity_name, [])
        if card_llm:
            severity_colors = {
                "critical": "#dc2626", "high": "#ef4444",
                "medium": "#ca8a04", "low": "#94a3b8",
            }
            sections.append('  <div class="llm-section">')
            sections.append('    <h3>LLM Security Review</h3>')
            for sev in ("critical", "high", "medium", "low"):
                group = [f for f in card_llm if f.severity == sev]
                if not group:
                    continue
                color = severity_colors.get(sev, "#888")
                label = sev.upper()
                sections.append(f'    <div class="llm-group"><span class="llm-sev" style="color:{color}">{label}</span>')
                sections.append('    <ul>')
                for f in group:
                    sections.append(f'      <li>{_esc(f.message)}')
                    if f.recommendation:
                        sections.append(f'        <br><span class="llm-fix">Fix: {_esc(f.recommendation)}</span>')
                    sections.append('      </li>')
                sections.append('    </ul></div>')
            sections.append('  </div>')

        # Summary
        if card.summary:
            sections.append(f'  <p class="summary">{_esc(card.summary)}</p>')

        sections.append('</div>')
        return "\n".join(sections)

    # Build summary table if multiple cards
    summary_html = ""
    if len(cards) > 1:
        sorted_cards = sorted(cards, key=lambda c: c.overall_score, reverse=True)
        avg = sum(c.overall_score for c in cards) / len(cards)
        rows = []
        for card in sorted_cards:
            gc = grade_colors.get(card.grade, "#888")
            fname = card.file_path.name if card.file_path else "?"
            suggestions = sum(len(d.suggestions) for d in card.dimensions)
            issue_str = str(suggestions) if suggestions else "-"
            slug = _slug(card.entity_name)
            rows.append(f'''      <tr>
        <td><a href="#{slug}">{_esc(fname)}</a></td>
        <td class="hide-mobile">{_esc(card.entity_type)}</td>
        <td><a href="#{slug}">{_esc(card.entity_name)}</a></td>
        <td style="text-align:center"><span class="badge-sm" style="background:{gc}">{_esc(card.grade)}</span></td>
        <td style="text-align:right">{card.overall_score:.0%}</td>
        <td class="hide-mobile" style="text-align:right">{issue_str}</td>
      </tr>''')
        summary_html = f'''<div class="summary-section">
  <h2>Summary</h2>
  <table class="summary-table">
    <thead>
      <tr><th>File</th><th class="hide-mobile">Type</th><th>Name</th><th>Grade</th><th>Score</th><th class="hide-mobile">Issues</th></tr>
    </thead>
    <tbody>
{"".join(rows)}
    </tbody>
  </table>
  <p class="avg-score">{len(cards)} files analyzed &mdash; average score: {avg:.0%}</p>
</div>'''

    card_html = "\n".join(_render_card(c) for c in cards)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Skill Audit Report</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: #f8f9fa; color: #1a1a2e; margin: 0; padding: 2rem;
    line-height: 1.5;
  }}
  .container {{ max-width: 860px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 0.5rem; color: #1a1a2e; }}
  .audit-meta {{
    background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 6px;
    padding: 0.5rem 0.75rem; margin-bottom: 0.5rem; font-size: 0.85rem;
    overflow-x: auto;
  }}
  .audit-meta code {{ background: none; padding: 0; color: #334155; }}
  .audit-source {{ font-size: 0.85rem; color: #64748b; margin-bottom: 1.5rem; }}
  .audit-source code {{ font-size: 0.85rem; }}
  .card {{
    background: #fff; border: 1px solid #e2e8f0; border-radius: 8px;
    padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }}
  .card-header {{ margin-bottom: 1rem; }}
  .card-title {{ display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem; }}
  .card-title h2 {{ margin: 0; font-size: 1.25rem; }}
  .badge {{
    display: inline-flex; align-items: center; justify-content: center;
    color: #fff; font-weight: 700; font-size: 0.9rem;
    width: 2rem; height: 2rem; border-radius: 6px;
  }}
  .badge-sm {{
    display: inline-flex; align-items: center; justify-content: center;
    color: #fff; font-weight: 700; font-size: 0.75rem;
    width: 1.5rem; height: 1.5rem; border-radius: 4px;
  }}
  .card-meta {{ display: flex; align-items: center; gap: 0.5rem; }}
  .tag {{
    background: #f1f5f9; color: #64748b; padding: 0.15rem 0.5rem;
    border-radius: 4px; font-size: 0.8rem;
  }}
  .score-label {{ font-size: 0.85rem; color: #64748b; margin-left: auto; }}
  .dimensions {{ display: flex; flex-direction: column; gap: 0.6rem; }}
  .dim-row {{ }}
  .dim-info {{
    display: flex; align-items: baseline; gap: 0.5rem; margin-bottom: 0.2rem;
  }}
  .dim-name {{ font-weight: 600; font-size: 0.85rem; min-width: 120px; }}
  .dim-score {{ font-weight: 600; font-size: 0.85rem; min-width: 36px; text-align: right; }}
  .dim-weight {{ font-size: 0.75rem; color: #94a3b8; }}
  .bar-track {{
    height: 8px; background: #e2e8f0; border-radius: 4px; overflow: hidden;
  }}
  .bar-fill {{
    height: 100%; border-radius: 4px; transition: width 0.3s ease;
  }}
  .detail-section {{
    margin-top: 1rem; border-top: 1px solid #e2e8f0; padding-top: 0.75rem;
  }}
  .detail-section summary {{
    cursor: pointer; font-weight: 600; font-size: 0.9rem; color: #475569;
  }}
  .detail-section h4 {{ margin: 0.75rem 0 0.25rem; font-size: 0.85rem; color: #334155; }}
  .detail-list {{ margin: 0.25rem 0; padding-left: 1.25rem; }}
  .detail-list li {{ font-size: 0.82rem; color: #16a34a; margin-bottom: 0.15rem; }}
  .suggestion-list {{ margin: 0.25rem 0; padding-left: 1.25rem; }}
  .suggestion-list li {{ font-size: 0.82rem; color: #ca8a04; margin-bottom: 0.15rem; }}
  .summary {{ font-size: 0.85rem; color: #475569; margin-top: 0.75rem; }}
  .llm-section {{
    margin-top: 1rem; border-top: 1px solid #e2e8f0; padding-top: 0.75rem;
  }}
  .llm-section h3 {{ font-size: 0.95rem; color: #334155; margin-bottom: 0.5rem; }}
  .llm-group {{ margin-bottom: 0.5rem; }}
  .llm-sev {{ font-weight: 700; font-size: 0.8rem; text-transform: uppercase; }}
  .llm-group ul {{ margin: 0.25rem 0 0.5rem; padding-left: 1.25rem; }}
  .llm-group li {{ font-size: 0.82rem; color: #334155; margin-bottom: 0.3rem; }}
  .llm-fix {{ color: #16a34a; font-size: 0.8rem; }}
  .summary-section {{
    background: #fff; border: 1px solid #e2e8f0; border-radius: 8px;
    padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }}
  .summary-section h2 {{ margin: 0 0 1rem; font-size: 1.1rem; }}
  .summary-table {{
    width: 100%; border-collapse: collapse; font-size: 0.85rem;
  }}
  .summary-table th {{
    text-align: left; padding: 0.5rem 0.75rem; border-bottom: 2px solid #e2e8f0;
    font-weight: 600; color: #475569; font-size: 0.8rem; text-transform: uppercase;
    letter-spacing: 0.03em;
  }}
  .summary-table td {{
    padding: 0.5rem 0.75rem; border-bottom: 1px solid #f1f5f9;
  }}
  .avg-score {{ font-size: 0.85rem; color: #64748b; margin-top: 0.75rem; }}
  .summary-table a {{ color: #2563eb; text-decoration: none; }}
  .summary-table a:hover {{ text-decoration: underline; }}
  footer {{
    text-align: center; color: #94a3b8; font-size: 0.75rem;
    margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #e2e8f0;
  }}
  /* Mobile responsive */
  @media (max-width: 640px) {{
    body {{ padding: 0.75rem; }}
    .hide-mobile {{ display: none; }}
    h1 {{ font-size: 1.2rem; }}
    .card {{ padding: 1rem; }}
    .card-title {{ flex-wrap: wrap; gap: 0.5rem; }}
    .card-title h2 {{ font-size: 1.05rem; }}
    .card-meta {{ flex-wrap: wrap; gap: 0.4rem; }}
    .score-label {{ margin-left: 0; }}
    .dim-info {{ flex-wrap: wrap; gap: 0.25rem; }}
    .dim-name {{ min-width: auto; font-size: 0.8rem; }}
    .dim-score {{ min-width: auto; font-size: 0.8rem; }}
    .dim-weight {{ font-size: 0.7rem; }}
    .bar-track {{ height: 6px; }}
    .audit-meta {{ font-size: 0.75rem; word-break: break-all; }}
    .audit-source {{ font-size: 0.75rem; }}
    .summary-section {{ padding: 1rem; overflow-x: auto; }}
    .summary-table {{ font-size: 0.75rem; }}
    .summary-table th, .summary-table td {{ padding: 0.35rem 0.4rem; }}
    .detail-list li, .suggestion-list li {{ font-size: 0.78rem; }}
    .llm-group li {{ font-size: 0.78rem; }}
    .llm-fix {{ font-size: 0.75rem; }}
  }}
  .nav {{ display: flex; align-items: center; gap: 1.5rem; margin-bottom: 1.5rem; padding-bottom: 1rem; border-bottom: 1px solid #e2e8f0; font-size: 0.85rem; }}
  .nav a {{ color: #2563eb; text-decoration: none; }}
  .nav a:hover {{ text-decoration: underline; }}
  .nav .sep {{ color: #cbd5e1; }}
  @media print {{
    body {{ background: #fff; padding: 0.5rem; }}
    .card {{ box-shadow: none; break-inside: avoid; }}
    .detail-section {{ open: true; }}
    details[open] summary {{ display: none; }}
    .nav {{ display: none; }}
  }}
</style>
</head>
<body>
<div class="container">
  <nav class="nav">
    <a href="https://dawalama.github.io/skill-audit/">All Reports</a>
    <span class="sep">|</span>
    <a href="https://github.com/dawalama/skill-audit">GitHub</a>
    <span class="sep">|</span>
    <a href="https://pypi.org/project/ai-skill-audit/">PyPI</a>
  </nav>
  <h1>Skill Audit Report</h1>
{f'  <div class="audit-meta"><code>{_esc(audit_command)}</code></div>' if audit_command else ''}
{f'  <p class="audit-source">Source: <code>{_esc(audit_source)}</code></p>' if audit_source else ''}
{summary_html}
{card_html}
  <footer>Generated by ai-skill-audit v{__version__}</footer>
</div>
</body>
</html>'''


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
