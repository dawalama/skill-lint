"""CLI for skill-audit."""

import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from . import __version__
from .config import load_config, format_config

_HELP = """\
Audit AI skill and role files for quality and trust.

Vet community skills before installing them. Catch prompt injection,
hardcoded secrets, destructive commands, and data exfiltration. Get
actionable feedback on your own skills and roles.

How to use:

  Audit a file:           ai-skill-audit audit SKILL.md
  See what's wrong:       ai-skill-audit audit SKILL.md -v
  Audit a directory:      ai-skill-audit audit ~/.ai/skills/
  Audit a GitHub repo:    ai-skill-audit audit https://github.com/user/skills
  Audit a GitHub file:    ai-skill-audit audit https://github.com/user/repo/blob/main/SKILL.md
  Add LLM deep review:   ai-skill-audit audit SKILL.md --llm
  Fail CI below grade B: ai-skill-audit audit skills/ --min-grade B
  Inspect without scoring: ai-skill-audit info SKILL.md
  Check LLM providers:   ai-skill-audit providers

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
_stderr = Console(stderr=True)  # For status messages that shouldn't pollute stdout


def _version_callback(value: bool):
    if value:
        print(f"ai-skill-audit {__version__}")
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
    output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, markdown, html"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show per-dimension details and suggestions"),
    min_grade: Optional[str] = typer.Option(None, "--min-grade", help="Exit 1 if below grade (A/B/C/D) — useful for CI"),
    summary: bool = typer.Option(False, "--summary", help="Summary table only (for directories)"),
    llm: bool = typer.Option(False, "--llm", help="Enable LLM review for deeper analysis (uses claude CLI, OpenRouter, or Ollama)"),
    llm_provider: Optional[str] = typer.Option(None, "--llm-provider", help="Force LLM provider: claude, openrouter, ollama"),
    llm_model: Optional[str] = typer.Option(None, "--llm-model", help="Override LLM model (e.g. anthropic/claude-sonnet-4-5)"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Skip LLM cache and force fresh review"),
    include_docs: Optional[bool] = typer.Option(None, "--include-docs", help="Include documentation files (README, CONTRIBUTING, etc.) in scan — defaults to True for remote targets"),
    trust_target_ignore: bool = typer.Option(False, "--trust-target-ignore", help="Honor .skill-audit-ignore files inside remote repos (off by default for safety)"),
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
    - Persistence mechanisms (authorized_keys, systemd, shell profiles)
    - Resource hijacking (crypto miners, mining pool connections)

    Use --llm for deeper analysis: intent mismatch detection, sophisticated
    prompt injection, and semantic quality review. Uses claude CLI (zero config),
    OpenRouter (OPENROUTER_API_KEY), or Ollama (local). No LLM SDK required.

    Accepts local files/directories or remote URLs:
      ai-skill-audit audit SKILL.md                           Local file
      ai-skill-audit audit ~/.ai/skills/                      Local directory
      ai-skill-audit audit https://github.com/user/skills     GitHub repo
      ai-skill-audit audit https://github.com/user/repo/blob/main/SKILL.md
    """
    from .analyzer import analyze_file, analyze_directory
    from .fetcher import is_remote, fetch_remote, cleanup_temp
    from .formatters import format_table, format_json, format_markdown, format_html, format_summary_table
    from .ignore import load_ignore_config

    # Load config and apply defaults (CLI flags override config values)
    cfg = load_config()
    if output == "table" and cfg.output != "table":
        output = cfg.output
    if min_grade is None and cfg.min_grade:
        min_grade = cfg.min_grade
    if not llm and cfg.llm.enabled:
        llm = True
    if llm_provider is None and cfg.llm.provider:
        llm_provider = cfg.llm.provider
    if llm_model is None and cfg.llm.model:
        llm_model = cfg.llm.model

    # Handle remote URLs
    temp_path = None
    _is_remote = is_remote(path)
    if _is_remote:
        try:
            _stderr.print(f"  [dim]Fetching {path}...[/dim]")
            target, is_temp = fetch_remote(path)
            if is_temp:
                temp_path = target
        except ValueError as e:
            _stderr.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
    else:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            _stderr.print(f"[red]Not found: {target}[/red]")
            raise typer.Exit(1)

    # For remote targets: default to including docs (they're part of the attack
    # surface), skip the repo's .skill-audit-ignore (attacker-controlled),
    # and ignore inline suppression comments (the file shouldn't influence its own audit)
    if include_docs is None:
        include_docs = _is_remote  # True for remote, False for local
    _trust_ignore = trust_target_ignore if _is_remote else True
    _trust_inline = not _is_remote  # Local files trusted, remote files not

    # Load ignore configuration
    ignore_config = load_ignore_config(target, trust_target_ignore=_trust_ignore)

    skipped = 0
    if target.is_dir():
        cards, skipped = analyze_directory(target, format, ignore_config=ignore_config, custom_patterns=cfg.custom_patterns or None, weights=cfg.weights, include_docs=include_docs, trust_inline=_trust_inline)
        if not cards:
            _stderr.print(f"[yellow]No skill/role files found in {target}[/yellow]")
            raise typer.Exit(0)
    else:
        cards = [analyze_file(target, format, ignore_config=ignore_config, custom_patterns=cfg.custom_patterns or None, weights=cfg.weights, trust_inline=_trust_inline)]

    # LLM review (runs before output so HTML can include findings)
    llm_results: dict[str, list] = {}
    if llm:
        from .llm_reviewer import review_skill, detect_provider
        from .parser import parse_file as parse_for_llm

        provider = llm_provider or detect_provider()
        if provider is None:
            _stderr.print("\n  [yellow]No LLM provider found.[/yellow]")
            _stderr.print("  [dim]Run `ai-skill-audit providers` to check availability.[/dim]\n")
        else:
            files_to_review: list[tuple[str, str, str]] = []  # (name, content, review_type)
            for card in cards:
                if card.file_path and card.file_path.exists():
                    if card.entity_type == "mcp-config":
                        clean = card.file_path.read_text()
                        files_to_review.append((card.entity_name, clean, "mcp"))
                    else:
                        artifact = parse_for_llm(card.file_path)
                        clean = _build_llm_content(artifact)
                        files_to_review.append((card.entity_name, clean, "skill"))

            if files_to_review:
                for fname, content, rtype in files_to_review:
                    review = review_skill(content, provider=provider, model=llm_model, no_cache=no_cache, review_type=rtype)
                    if review.findings:
                        llm_results[fname] = review.findings

    # Output
    if output == "json":
        print(format_json(cards))
    elif output == "html":
        # Build command string for the report header
        cmd_parts = ["ai-skill-audit", "audit", path]
        if format:
            cmd_parts.extend(["--format", format])
        if llm:
            cmd_parts.append("--llm")
        if verbose:
            cmd_parts.append("--verbose")
        cmd_parts.extend(["--output", "html"])
        audit_cmd = " ".join(cmd_parts)
        print(format_html(cards, llm_findings=llm_results or None, audit_source=path, audit_command=audit_cmd))
    elif output == "markdown":
        for card in cards:
            print(format_markdown(card))
    elif target.is_dir() and summary:
        format_summary_table(cards)
    else:
        for card in cards:
            format_table(card, verbose=verbose)
        if target.is_dir() and len(cards) > 1:
            format_summary_table(cards)

    if skipped > 0:
        _stderr.print(f"  [dim]Skipped {skipped} documentation file(s) (README, CONTRIBUTING, etc.). Use --include-docs to scan them.[/dim]\n")

    # Print LLM findings to terminal (for non-HTML output)
    if llm_results and output not in ("html", "json"):
        from .formatters import format_llm_findings
        label = f"{len(llm_results)} file(s)" if len(llm_results) > 1 else list(llm_results.keys())[0]
        has_mcp = any(c.entity_type == "mcp-config" for c in cards)
        review_label = "LLM Security Review" if has_mcp else "LLM Review"
        console.print(f"  [bold]{review_label}[/bold] — {label}\n")
        for fname, findings in llm_results.items():
            if len(llm_results) > 1:
                console.print(f"  [bold]{fname}[/bold]")
            format_llm_findings(findings, fname, "LLM", verbose=verbose)
            if len(llm_results) > 1:
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
    from .parser import parse_file, detect_format

    target = Path(path).expanduser().resolve()
    if not target.exists():
        console.print(f"[red]Not found: {target}[/red]")
        raise typer.Exit(1)

    # Handle MCP config files specially
    fmt = detect_format(target)
    if fmt == "mcp-config":
        from .mcp_scanner import scan_mcp_config
        result = scan_mcp_config(target)
        console.print(f"\n  [bold]File:[/bold]        {target.name}")
        console.print(f"  [bold]Format:[/bold]      mcp-config")
        console.print(f"  [bold]Type:[/bold]        mcp-config")
        console.print(f"  [bold]Servers:[/bold]     {result.server_count}")
        console.print(f"  [bold]Risk:[/bold]        {result.overall_risk}")
        console.print(f"  [bold]Findings:[/bold]    {len(result.servers)}")
        if result.servers:
            for f in result.servers:
                sev_color = {"critical": "red bold", "high": "red", "medium": "yellow", "low": "dim"}.get(f.severity, "white")
                console.print(f"    [{sev_color}]{f.severity.upper()}[/{sev_color}] [{f.server_name}] {f.message}")
        console.print()
        return

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
    console.print(f"\n  Run [bold]ai-skill-audit cache --clear[/bold] to delete.\n")


@app.command()
def config():
    """Show the current effective configuration.

    Displays merged config from skill-audit.toml in the current directory
    and ~/.config/skill-audit/config.toml. CWD config takes precedence
    over home config. CLI flags always override config values.
    """
    from .config import _CWD_FILE, _HOME_FILE

    cfg = load_config()

    cwd_path = Path.cwd() / _CWD_FILE
    home_path = _HOME_FILE

    console.print("\n  [bold]Effective Configuration[/bold]\n")

    sources = []
    if cwd_path.exists():
        sources.append(f"  [green]{cwd_path}[/green] (project)")
    if home_path.exists():
        sources.append(f"  [green]{home_path}[/green] (user)")
    if not sources:
        sources.append("  [dim](no config files found — using defaults)[/dim]")

    console.print("  [bold]Sources:[/bold]")
    for s in sources:
        console.print(f"    {s}")
    console.print()

    console.print(format_config(cfg))
    console.print()


if __name__ == "__main__":
    app()
