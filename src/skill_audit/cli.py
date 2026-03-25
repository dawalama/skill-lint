"""CLI for skill-audit."""

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from . import __version__

_HELP = """\
Audit AI skill and role files for quality and trust.

Vet community skills before installing them. Catch prompt injection,
hardcoded secrets, destructive commands, and data exfiltration. Get
actionable feedback on your own skills and roles.

How to use:

  Audit a file:           skill-audit audit SKILL.md
  See what's wrong:       skill-audit audit SKILL.md -v
  Audit a directory:      skill-audit audit ~/.ai/skills/
  Audit a GitHub repo:    skill-audit audit https://github.com/user/skills
  Audit a GitHub file:    skill-audit audit https://github.com/user/repo/blob/main/SKILL.md
  Add LLM deep review:   skill-audit audit SKILL.md --llm
  Fail CI below grade B: skill-audit audit skills/ --min-grade B
  Inspect without scoring: skill-audit info SKILL.md
  Check LLM providers:   skill-audit providers

Skills are graded A-F across 6 dimensions: completeness, clarity,
actionability, safety, testability, and trust. Trust scans for 7 threat
categories including prompt injection, secrets, and exfiltration.

Static analysis by default (fast, free, offline). Add --llm for deeper
review using claude CLI, OpenRouter, or Ollama — no LLM SDK needed.

Works with dotai skills, Claude-native SKILL.md, and plain markdown.

A passing audit does not guarantee safety. Always review skills manually
before granting them access to your systems.
"""

app = typer.Typer(help=_HELP, no_args_is_help=True)
console = Console()


def _version_callback(value: bool):
    if value:
        print(f"skill-audit {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version and exit"),
):
    pass


def _build_llm_content(artifact) -> str:
    """Build clean content for LLM review from a parsed artifact.

    Strips noise (embedded role definitions, HTML comments, wrapper boilerplate)
    and reconstructs only the meaningful content the LLM should review.
    """
    import re

    parts = []
    parts.append(f"Name: {artifact.name}")
    if artifact.description:
        parts.append(f"Description: {artifact.description}")
    if artifact.trigger:
        parts.append(f"Trigger: {artifact.trigger}")
    if artifact.category:
        parts.append(f"Category: {artifact.category}")
    parts.append("")

    if artifact.entity_type == "skill":
        if artifact.steps:
            parts.append("## Steps")
            for i, step in enumerate(artifact.steps, 1):
                parts.append(f"{i}. {step}")
            parts.append("")
        if artifact.inputs:
            parts.append("## Inputs")
            for inp in artifact.inputs:
                req = "(required)" if inp.get("required") else "(optional)"
                parts.append(f"- {inp['name']} {req}: {inp.get('description', '')}")
            parts.append("")
        if artifact.gotchas:
            parts.append("## Gotchas")
            for g in artifact.gotchas:
                parts.append(f"- {g}")
            parts.append("")
        if artifact.examples:
            parts.append("## Examples")
            for ex in artifact.examples:
                parts.append(f"- {ex}")
            parts.append("")
        # Only include raw_body if we didn't extract structured sections
        # (avoids sending the same content twice)
        if artifact.raw_body and not artifact.steps:
            # Strip wrapper noise (Role Composition section, Available roles list)
            body = artifact.raw_body
            body = re.sub(r"## Role Composition.*?(?=^## |\Z)", "", body, flags=re.DOTALL | re.MULTILINE)
            body = re.sub(r"Available roles:.*?\n", "", body)
            body = re.sub(r"Arguments received:.*?\n", "", body)
            body = body.strip()
            if body:
                parts.append("## Body")
                parts.append(body)
    elif artifact.entity_type == "role":
        if artifact.persona:
            parts.append(artifact.persona)
            parts.append("")
        if artifact.principles:
            parts.append("## Principles")
            for p in artifact.principles:
                parts.append(f"- {p}")
            parts.append("")
        if artifact.anti_patterns:
            parts.append("## Anti-patterns")
            for a in artifact.anti_patterns:
                parts.append(f"- {a}")

    return "\n".join(parts)


@app.command()
def audit(
    path: str = typer.Argument(..., help="File, directory, or URL to audit"),
    format: Optional[str] = typer.Option(None, "--format", "-f", help="Force format: dotai-skill, dotai-role, claude-native"),
    output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, markdown"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show per-dimension details and suggestions"),
    min_grade: Optional[str] = typer.Option(None, "--min-grade", help="Exit 1 if below grade (A/B/C/D) — useful for CI"),
    summary: bool = typer.Option(False, "--summary", help="Summary table only (for directories)"),
    llm: bool = typer.Option(False, "--llm", help="Enable LLM review for deeper analysis (uses claude CLI, OpenRouter, or Ollama)"),
    llm_provider: Optional[str] = typer.Option(None, "--llm-provider", help="Force LLM provider: claude, openrouter, ollama"),
    llm_model: Optional[str] = typer.Option(None, "--llm-model", help="Override LLM model (e.g. anthropic/claude-sonnet-4-5)"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Skip LLM cache and force fresh review"),
):
    """Audit a skill or role file for quality and trust.

    Scores files across quality dimensions (completeness, clarity, actionability,
    safety, testability) and a trust dimension that scans for:

    - Prompt injection (instruction overrides, hidden tags, zero-width chars)
    - Hardcoded secrets (API keys, tokens, private keys, wallet seeds)
    - Destructive commands (rm -rf, DROP TABLE, force push)
    - Data exfiltration (curl POST, credential file access, netcat)
    - Code obfuscation (eval, base64 decode to shell, dynamic imports)
    - Suspicious URLs (curl|bash, IP addresses, URL shorteners)
    - Privilege escalation (sudo, service modification, privileged containers)

    Use --llm for deeper analysis: intent mismatch detection, sophisticated
    prompt injection, and semantic quality review. Uses claude CLI (zero config),
    OpenRouter (OPENROUTER_API_KEY), or Ollama (local). No LLM SDK required.

    Accepts local files/directories or remote URLs:
      skill-audit audit SKILL.md                              Local file
      skill-audit audit ~/.ai/skills/                         Local directory
      skill-audit audit https://github.com/user/skills        GitHub repo
      skill-audit audit https://github.com/user/repo/blob/main/SKILL.md
    """
    from .analyzer import analyze_file, analyze_directory
    from .fetcher import is_remote, fetch_remote, cleanup_temp
    from .formatters import format_table, format_json, format_markdown, format_summary_table

    # Handle remote URLs
    temp_path = None
    if is_remote(path):
        try:
            console.print(f"  [dim]Fetching {path}...[/dim]")
            target, is_temp = fetch_remote(path)
            if is_temp:
                temp_path = target
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
    else:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            console.print(f"[red]Not found: {target}[/red]")
            raise typer.Exit(1)

    if target.is_dir():
        cards = analyze_directory(target, format)
        if not cards:
            console.print(f"[yellow]No skill/role files found in {target}[/yellow]")
            raise typer.Exit(0)
        if output == "json":
            print(format_json(cards))
        elif summary:
            format_summary_table(cards)
        else:
            for card in cards:
                format_table(card, verbose=verbose)
            if len(cards) > 1:
                format_summary_table(cards)
    else:
        cards = [analyze_file(target, format)]
        if output == "json":
            print(format_json(cards))
        elif output == "markdown":
            for card in cards:
                print(format_markdown(card))
        else:
            for card in cards:
                format_table(card, verbose=verbose)

    # LLM review (optional — runs after static analysis)
    if llm:
        from .llm_reviewer import review_skill, detect_provider
        from .formatters import format_llm_findings
        from .parser import parse_file as parse_for_llm

        provider = llm_provider or detect_provider()
        if provider is None:
            console.print("\n  [yellow]No LLM provider found.[/yellow]")
            console.print("  [dim]Run `skill-audit providers` to check availability.[/dim]\n")
        else:
            # Collect cleaned content for LLM review (strips <details>, noise)
            files_to_review: list[tuple[str, str]] = []
            for card in cards:
                if card.file_path and card.file_path.exists():
                    artifact = parse_for_llm(card.file_path)
                    # Build clean content from parsed artifact
                    clean = _build_llm_content(artifact)
                    files_to_review.append((card.entity_name, clean))

            if files_to_review:
                label = f"{len(files_to_review)} file(s)" if len(files_to_review) > 1 else files_to_review[0][0]
                console.print(f"  [bold]LLM Review[/bold] via {provider} — {label}\n")

                for fname, content in files_to_review:
                    if len(files_to_review) > 1:
                        console.print(f"  [bold]{fname}[/bold]")
                    review = review_skill(content, provider=provider, model=llm_model, no_cache=no_cache)
                    format_llm_findings(
                        review.findings, fname, review.model,
                        verbose=verbose, error=review.error,
                    )
                    if len(files_to_review) > 1:
                        console.print()

                console.print()

    # Check minimum grade
    if min_grade:
        grade_order = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
        min_val = grade_order.get(min_grade.upper(), 0)
        failures = [c for c in cards if grade_order.get(c.grade, 0) < min_val]
        if failures:
            console.print(f"[red]{len(failures)} file(s) below minimum grade {min_grade}[/red]")
            if temp_path:
                cleanup_temp(temp_path)
            raise typer.Exit(1)

    # Clean up temp files from remote fetch
    if temp_path:
        cleanup_temp(temp_path)


@app.command()
def info(
    path: str = typer.Argument(..., help="File to inspect"),
):
    """Inspect a file without scoring — show detected format and parsed structure.

    Useful for understanding how a file will be audited. Shows the detected
    format, entity type, parsed name, description, and what sections were
    found.
    """
    from .parser import parse_file

    target = Path(path).expanduser().resolve()
    if not target.exists():
        console.print(f"[red]Not found: {target}[/red]")
        raise typer.Exit(1)

    artifact = parse_file(target)

    console.print(f"\n  [bold]File:[/bold]        {target.name}")
    console.print(f"  [bold]Format:[/bold]      {artifact.format}")
    console.print(f"  [bold]Type:[/bold]        {artifact.entity_type}")
    console.print(f"  [bold]Name:[/bold]        {artifact.name}")

    if artifact.description:
        desc = artifact.description[:120] + "..." if len(artifact.description) > 120 else artifact.description
        console.print(f"  [bold]Description:[/bold] {desc}")

    if artifact.entity_type == "skill":
        console.print(f"  [bold]Trigger:[/bold]     {artifact.trigger or '(none)'}")
        console.print(f"  [bold]Category:[/bold]    {artifact.category or '(none)'}")
        console.print(f"  [bold]Steps:[/bold]       {len(artifact.steps)}")
        console.print(f"  [bold]Inputs:[/bold]      {len(artifact.inputs)}")
        console.print(f"  [bold]Examples:[/bold]    {len(artifact.examples)}")
        console.print(f"  [bold]Gotchas:[/bold]     {len(artifact.gotchas)}")
        if artifact.allowed_tools:
            console.print(f"  [bold]Tools:[/bold]       {', '.join(artifact.allowed_tools)}")
    elif artifact.entity_type == "role":
        console.print(f"  [bold]Persona:[/bold]     {'yes' if artifact.persona else 'no'} ({len(artifact.persona)} chars)")
        console.print(f"  [bold]Principles:[/bold]  {len(artifact.principles)}")
        console.print(f"  [bold]Anti-patterns:[/bold] {len(artifact.anti_patterns)}")

    if artifact.tags:
        console.print(f"  [bold]Tags:[/bold]        {', '.join(artifact.tags)}")

    if artifact.sections:
        console.print(f"  [bold]Sections:[/bold]    {', '.join(artifact.sections.keys())}")

    body_words = len(artifact.raw_body.split()) if artifact.raw_body else 0
    console.print(f"  [bold]Body:[/bold]        {body_words} words")
    console.print()


@app.command()
def providers():
    """Show available LLM providers for --llm review.

    skill-audit uses already-installed tools for LLM review — no SDK needed.
    Checks for: claude CLI (zero config), OpenRouter (API key), Ollama (local).
    """
    from .llm_reviewer import _claude_available, _ollama_available

    console.print("\n  [bold]LLM Providers for --llm review:[/bold]\n")

    # Claude CLI
    if _claude_available():
        console.print("  [green]claude CLI[/green]     installed (zero config — already authenticated)")
    else:
        console.print("  [dim]claude CLI[/dim]     not found (install from https://claude.ai/code)")

    # OpenRouter
    if os.environ.get("OPENROUTER_API_KEY"):
        console.print("  [green]OpenRouter[/green]     OPENROUTER_API_KEY set")
    else:
        console.print("  [dim]OpenRouter[/dim]     OPENROUTER_API_KEY not set (get key at https://openrouter.ai)")

    # Ollama
    if _ollama_available():
        console.print("  [green]Ollama[/green]        running at localhost:11434")
    else:
        console.print("  [dim]Ollama[/dim]        not running (install from https://ollama.com)")

    console.print()


@app.command()
def cache(
    clear: bool = typer.Option(False, "--clear", help="Delete all cached LLM reviews"),
):
    """Show or clear the LLM review cache.

    LLM results are cached by content hash so repeated audits are instant.
    Cache auto-invalidates when skill content changes.
    Stored at ~/.cache/skill-audit/llm/
    """
    from .llm_reviewer import _CACHE_DIR
    import shutil

    if not _CACHE_DIR.exists():
        console.print("  No cache found.")
        return

    entries = list(_CACHE_DIR.glob("*.json"))

    if clear:
        shutil.rmtree(_CACHE_DIR)
        console.print(f"  [green]Cleared {len(entries)} cached review(s).[/green]")
        return

    if not entries:
        console.print("  Cache is empty.")
        return

    total_size = sum(f.stat().st_size for f in entries)
    console.print(f"\n  [bold]LLM Review Cache[/bold]")
    console.print(f"  Location: {_CACHE_DIR}")
    console.print(f"  Entries:  {len(entries)}")
    console.print(f"  Size:     {total_size / 1024:.1f} KB")
    console.print(f"\n  Run [bold]skill-audit cache --clear[/bold] to delete.\n")


if __name__ == "__main__":
    app()
