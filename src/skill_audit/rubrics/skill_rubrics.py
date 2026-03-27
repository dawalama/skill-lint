"""Skill scoring rubrics.

5 dimensions: completeness, clarity, actionability, safety, testability.
"""

import re

from ..config import WeightsConfig
from ..models import ScoreDimension
from ..parser import ParsedArtifact

# Action verbs that indicate actionable steps
ACTION_VERBS = {
    "run", "check", "verify", "read", "write", "create", "delete", "update",
    "find", "search", "grep", "parse", "detect", "analyze", "generate",
    "build", "test", "deploy", "install", "configure", "set", "add",
    "remove", "fix", "debug", "inspect", "validate", "confirm", "report",
    "output", "compile", "execute", "fetch", "load", "save", "open",
    "close", "start", "stop", "restart", "push", "pull", "merge",
    "clone", "copy", "move", "rename", "list", "show", "print", "log",
    "use", "apply", "resolve", "ensure", "identify", "scan", "review",
}


def _is_runbook(a: ParsedArtifact) -> bool:
    """Detect if this is a runbook-style skill (rich body, no structured sections)."""
    has_structured = bool(a.steps or a.inputs or a.examples)
    has_rich_body = len(a.raw_body) > 200
    return has_rich_body and not has_structured


def _body_richness(body: str) -> dict:
    """Analyze richness of a raw body: sections, bullets, code blocks, length."""
    sections = len(re.findall(r"^##+ .+", body, re.MULTILINE))
    bullets = len(re.findall(r"^[-*] .+", body, re.MULTILINE))
    code_blocks = len(re.findall(r"```", body)) // 2
    numbered = len(re.findall(r"^\d+\. .+", body, re.MULTILINE))
    words = len(body.split())
    return {
        "sections": sections,
        "bullets": bullets,
        "code_blocks": code_blocks,
        "numbered": numbered,
        "words": words,
    }


def score_skill(
    artifact: ParsedArtifact,
    ignore_categories: set[str] | None = None,
    custom_patterns: list[tuple[str, str, str]] | None = None,
    weights: WeightsConfig | None = None,
) -> list[ScoreDimension]:
    """Score a skill across 6 dimensions. Returns list of ScoreDimension.

    custom_patterns: optional list of (regex, description, category) to add
    to the trust scan. Loaded from config file custom patterns section.
    weights: optional WeightsConfig to override default dimension weights.
    """
    w = weights or WeightsConfig()
    return [
        _score_completeness(artifact, weight=w.completeness),
        _score_clarity(artifact, weight=w.clarity),
        _score_actionability(artifact, weight=w.actionability),
        _score_safety(artifact, weight=w.safety),
        _score_testability(artifact, weight=w.testability),
        _score_trust(artifact, ignore_categories=ignore_categories, custom_patterns=custom_patterns, weight=w.trust, entropy_threshold=w.entropy_threshold),
    ]


def _score_completeness(a: ParsedArtifact, weight: float = 0.20) -> ScoreDimension:
    """Has description, steps/body, examples, gotchas, inputs."""
    score = 0.0
    details: list[str] = []
    suggestions: list[str] = []
    runbook = _is_runbook(a)
    richness = _body_richness(a.raw_body) if runbook else {}

    # Description (0.25)
    if a.description:
        score += 0.25
        details.append("Has description")
    else:
        suggestions.append("Add a description explaining what this skill does")

    # Steps or body (0.25)
    if a.steps:
        score += 0.25
        details.append(f"Has {len(a.steps)} steps")
    elif runbook:
        # Rich runbook body is a valid alternative to structured steps
        if richness["sections"] >= 2 or richness["bullets"] >= 3:
            score += 0.25
            details.append(f"Rich runbook body ({richness['words']} words, {richness['sections']} sections, {richness['bullets']} bullets)")
        else:
            score += 0.18
            details.append(f"Has runbook body ({richness['words']} words)")
            suggestions.append("Add more structure (sections or bullet lists) to the body")
    elif a.raw_body and len(a.raw_body) > 50:
        score += 0.15
        details.append("Has body content (but no structured steps)")
        suggestions.append("Break instructions into numbered steps for clarity")
    else:
        suggestions.append("Add steps (numbered list) describing the workflow")

    # Examples (0.20)
    if a.examples:
        score += 0.20
        details.append(f"Has {len(a.examples)} examples")
    elif runbook and richness.get("code_blocks", 0) >= 1:
        score += 0.12
        details.append(f"Has {richness['code_blocks']} code block(s) in body (inline examples)")
        suggestions.append("Add a dedicated ## Examples section for discoverability")
    else:
        suggestions.append("Add usage examples showing how to invoke this skill")

    # Gotchas (0.15)
    if a.gotchas:
        score += 0.15
        details.append(f"Has {len(a.gotchas)} gotchas")
    elif runbook and _body_has_warnings(a.raw_body):
        score += 0.10
        details.append("Body contains warning/caveat language")
        suggestions.append("Extract warnings into a dedicated ## Gotchas section")
    else:
        suggestions.append("Add gotchas/caveats to warn about common failure points")

    # Inputs (0.15)
    if a.inputs:
        score += 0.15
        details.append(f"Has {len(a.inputs)} inputs defined")
    elif runbook:
        # Runbook skills often don't have formal inputs — don't penalize as hard
        score += 0.08
        details.append("Runbook style (no formal inputs)")
    else:
        suggestions.append("Define input parameters if the skill accepts any")

    return ScoreDimension(
        name="completeness",
        score=min(score, 1.0),
        weight=weight,
        details=details,
        suggestions=suggestions,
    )


def _score_clarity(a: ParsedArtifact, weight: float = 0.15) -> ScoreDimension:
    """Description length, step count or body structure, concrete language."""
    score = 0.0
    details: list[str] = []
    suggestions: list[str] = []
    runbook = _is_runbook(a)
    richness = _body_richness(a.raw_body) if runbook else {}

    # Description length (0.35)
    desc_len = len(a.description)
    if 20 <= desc_len <= 200:
        score += 0.35
        details.append(f"Description length ({desc_len} chars) is ideal")
    elif desc_len > 0:
        score += 0.15
        if desc_len < 20:
            suggestions.append("Description is too short — expand to 20-200 characters")
        else:
            suggestions.append("Description is very long — consider trimming to under 200 characters")
    else:
        suggestions.append("Add a clear, concise description (20-200 characters ideal)")

    # Structure (0.35) — steps for structured skills, body richness for runbooks
    step_count = len(a.steps)
    if 3 <= step_count <= 10:
        score += 0.35
        details.append(f"Step count ({step_count}) is ideal")
    elif step_count > 0:
        score += 0.15
        if step_count < 3:
            suggestions.append("Consider adding more steps (3-10 is ideal)")
        else:
            suggestions.append(f"Too many steps ({step_count}) — consider grouping or splitting the skill")
    elif runbook:
        # Score based on body structure instead
        if richness["sections"] >= 3 and richness["bullets"] >= 5:
            score += 0.35
            details.append(f"Well-structured body ({richness['sections']} sections, {richness['bullets']} bullets)")
        elif richness["sections"] >= 2 or richness["bullets"] >= 3:
            score += 0.25
            details.append(f"Structured body ({richness['sections']} sections, {richness['bullets']} bullets)")
        else:
            score += 0.12
            details.append(f"Has body content ({richness['words']} words)")
            suggestions.append("Add section headers (##) and bullet lists to improve scannability")
    elif a.raw_body:
        score += 0.10
        details.append("Has body content but no structured steps")
    else:
        suggestions.append("Add numbered steps (3-10 ideal)")

    # Concrete language (0.30) — check for vague words
    vague_words = {"somehow", "maybe", "possibly", "etc", "stuff", "things", "whatever"}
    text = f"{a.description} {' '.join(a.steps)} {a.raw_body}".lower()
    vague_found = [w for w in vague_words if w in text.split()]
    if not vague_found:
        score += 0.30
        details.append("Language is concrete and specific")
    else:
        score += 0.10
        suggestions.append(f"Replace vague words: {', '.join(vague_found)}")

    return ScoreDimension(
        name="clarity",
        score=min(score, 1.0),
        weight=weight,
        details=details,
        suggestions=suggestions,
    )


def _score_actionability(a: ParsedArtifact, weight: float = 0.20) -> ScoreDimension:
    """Steps start with action verbs, reference tools/commands, inputs have descriptions."""
    score = 0.0
    details: list[str] = []
    suggestions: list[str] = []
    runbook = _is_runbook(a)
    richness = _body_richness(a.raw_body) if runbook else {}

    # Steps start with action verbs (0.40)
    if a.steps:
        action_steps = 0
        for step in a.steps:
            first_word = step.split()[0].lower().rstrip(",:") if step.split() else ""
            if first_word in ACTION_VERBS:
                action_steps += 1
        ratio = action_steps / len(a.steps)
        score += 0.40 * ratio
        if ratio >= 0.8:
            details.append("Steps start with action verbs")
        else:
            suggestions.append("Start each step with an action verb (Run, Check, Verify, etc.)")
    elif runbook:
        # Check if body bullets/numbered items use action language
        action_lines = len(re.findall(
            r"^[-*] (" + "|".join(ACTION_VERBS) + r")\b",
            a.raw_body.lower(),
            re.MULTILINE,
        ))
        numbered_items = richness.get("numbered", 0)
        if action_lines >= 3 or numbered_items >= 3:
            score += 0.35
            details.append(f"Body contains actionable instructions ({action_lines} action items, {numbered_items} numbered)")
        elif action_lines >= 1 or numbered_items >= 1:
            score += 0.20
            details.append("Body has some actionable content")
            suggestions.append("Add more action-oriented bullet points or numbered steps")
        else:
            score += 0.10
            details.append("Runbook body present")
            suggestions.append("Add action-oriented instructions (bullet points starting with verbs)")
    else:
        suggestions.append("Add steps that start with action verbs")

    # Steps reference tools or commands (0.30)
    if a.steps:
        has_tool_ref = any(
            re.search(r"`[^`]+`|Read|Grep|Glob|Bash|git |npm |python |pytest", step)
            for step in a.steps
        )
        if has_tool_ref:
            score += 0.30
            details.append("Steps reference specific tools or commands")
        else:
            score += 0.10
            suggestions.append("Reference specific tools or commands in steps (e.g. `git diff`, Grep)")
    elif runbook:
        # Check body for tool/command references
        has_refs = bool(re.search(r"`[^`]+`|```", a.raw_body))
        if has_refs:
            score += 0.25
            details.append("Body references tools or includes code")
        else:
            score += 0.10
            suggestions.append("Include code examples or tool references in the body")

    # Inputs have descriptions (0.30)
    if a.inputs:
        described = sum(1 for i in a.inputs if i.get("description"))
        ratio = described / len(a.inputs)
        score += 0.30 * ratio
        if ratio >= 1.0:
            details.append("All inputs have descriptions")
        else:
            suggestions.append("Add descriptions to all input parameters")
    else:
        # No inputs isn't necessarily bad — give partial credit
        score += 0.15
        details.append("No inputs defined (not always needed)")

    return ScoreDimension(
        name="actionability",
        score=min(score, 1.0),
        weight=weight,
        details=details,
        suggestions=suggestions,
    )


def _body_has_warnings(body: str) -> bool:
    """Check if body contains warning/caveat language."""
    warning_patterns = [
        r"\bdon'?t\b", r"\bnever\b", r"\bavoid\b", r"\bcareful\b",
        r"\bwarn", r"\bcaveat\b", r"\brisk\b", r"\bdanger",
        r"\bnot to\b", r"\bwithout\b.*\bwill\b", r"\bmust not\b",
    ]
    body_lower = body.lower()
    return any(re.search(p, body_lower) for p in warning_patterns)


def _score_safety(a: ParsedArtifact, weight: float = 0.15) -> ScoreDimension:
    """Has gotchas, gotchas are specific, mentions error handling."""
    score = 0.0
    details: list[str] = []
    suggestions: list[str] = []

    # Has gotchas (0.40)
    if a.gotchas:
        score += 0.40
        details.append(f"Has {len(a.gotchas)} gotchas")
    else:
        suggestions.append("Add gotchas/caveats to warn about common failure points")

    # Gotchas are specific (>30 chars each) (0.30)
    if a.gotchas:
        specific = sum(1 for g in a.gotchas if len(g) > 30)
        ratio = specific / len(a.gotchas)
        score += 0.30 * ratio
        if ratio >= 0.8:
            details.append("Gotchas are specific and detailed")
        else:
            suggestions.append("Make gotchas more specific (>30 chars each with concrete details)")
    else:
        suggestions.append("Add specific gotchas (describe what can go wrong and why)")

    # Mentions error handling (0.30) — anywhere in the content
    all_text = f"{a.description} {' '.join(a.steps)} {' '.join(a.gotchas)} {a.raw_body}".lower()
    error_keywords = {"error", "fail", "exception", "retry", "rollback", "timeout", "invalid", "check"}
    found = error_keywords & set(all_text.split())
    if found:
        score += 0.30
        details.append("Mentions error handling concepts")
    else:
        score += 0.05
        suggestions.append("Address what happens when things go wrong (errors, failures, retries)")

    return ScoreDimension(
        name="safety",
        score=min(score, 1.0),
        weight=weight,
        details=details,
        suggestions=suggestions,
    )


def _score_testability(a: ParsedArtifact, weight: float = 0.10) -> ScoreDimension:
    """Has examples, examples include parameters, show expected behavior."""
    score = 0.0
    details: list[str] = []
    suggestions: list[str] = []
    runbook = _is_runbook(a)
    richness = _body_richness(a.raw_body) if runbook else {}

    # Has examples (0.40)
    if a.examples:
        score += 0.40
        details.append(f"Has {len(a.examples)} examples")
    elif runbook:
        # Check for inline examples in body (code blocks, "Example:" patterns)
        example_markers = len(re.findall(r"(?i)\bexample\b|```|e\.g\.", a.raw_body))
        if example_markers >= 2:
            score += 0.30
            details.append("Body contains inline examples")
        elif example_markers >= 1:
            score += 0.15
            details.append("Body has some example content")
            suggestions.append("Add more concrete examples to the body")
        else:
            suggestions.append("Add examples showing how to use this skill")
    else:
        suggestions.append("Add examples showing how to use this skill")

    # Examples include parameters (0.30)
    if a.examples:
        has_params = sum(1 for ex in a.examples if "=" in ex or "--" in ex or re.search(r"`[^`]+`", ex))
        if has_params:
            ratio = has_params / len(a.examples)
            score += 0.30 * ratio
            details.append("Examples include parameters/flags")
        else:
            score += 0.05
            suggestions.append("Include parameter values in examples (e.g. scope=src/)")
    elif runbook and richness.get("code_blocks", 0) >= 1:
        score += 0.15
        details.append("Body code blocks serve as examples")
    else:
        suggestions.append("Add examples with concrete parameter values")

    # Examples show expected behavior (0.30) — look for output/result descriptions
    if a.examples:
        has_description = sum(
            1 for ex in a.examples
            if len(ex) > 30 or ":" in ex
        )
        if has_description:
            ratio = has_description / len(a.examples)
            score += 0.30 * ratio
            details.append("Examples describe expected behavior")
        else:
            suggestions.append("Add descriptions to examples showing expected behavior")
    elif runbook and richness.get("sections", 0) >= 2:
        # Rich runbook content implicitly describes expected behavior
        score += 0.15
        details.append("Structured body describes expected behavior")
    else:
        suggestions.append("Add examples that describe expected outcomes")

    return ScoreDimension(
        name="testability",
        score=min(score, 1.0),
        weight=weight,
        details=details,
        suggestions=suggestions,
    )


# =============================================================================
# Trust scan pattern categories
# Inspired by real attack campaigns (ClawHavoc, typosquatting, etc.)
# and tools like Snyk agent-scan.
# =============================================================================

# --- Destructive operations ---
# NOTE: These are checked with context awareness — patterns found only in
# description/gotchas prose (documenting dangers, not executing them) are
# excluded via _is_documentation_context().
_DESTRUCTIVE_PATTERNS = [
    (r"\brm\s+-rf\s+[/~]", "Destructive rm -rf on root or home directory"),
    (r"\brm\s+-rf\s+/", "Destructive rm -rf on absolute path"),
    (r"\bgit\s+push\s+--force\b", "Force push can destroy remote history"),
    (r"\bgit\s+reset\s+--hard\b", "Hard reset destroys uncommitted work"),
    (r"\bdrop\s+(table|database)\b", "DROP TABLE/DATABASE is destructive"),
    (r"\btruncate\s+table\b", "TRUNCATE TABLE deletes all data"),
    (r"\bformat\s+[a-z]:", "Disk format command"),
    (r"\bmkfs\b", "Filesystem format command"),
    (r"\bdd\s+if=", "Raw disk write with dd"),
    (r"\b>\s*/dev/sd[a-z]", "Direct write to block device"),
    (r"\bkill\s+-9\b", "Force kill can corrupt state"),
    (r"\bchmod\s+777\b", "World-writable permissions are insecure"),
    (r"\bchmod\s+-R\s+777\b", "Recursive world-writable permissions"),
    (r"\b--no-verify\b", "Skipping git hooks bypasses safety checks"),
]

# --- Data exfiltration ---
_EXFILTRATION_PATTERNS = [
    (r"\bcurl\b.*\b(POST|PUT)\b", "Sends data to external URL via curl"),
    (r"\bcurl\b.*-d\b", "Posts data to external URL"),
    (r"\bwget\b.*--post", "Posts data via wget"),
    (r"\bnc\s+-", "Netcat connection (potential data exfil)"),
    (r"\b(api_key|secret|token|password|credential)\b.*\b(echo|print|log|curl|send)\b", "May leak secrets"),
    (r"\benv\b.*\b(curl|wget|nc|send)\b", "May exfiltrate environment variables"),
    (r"\b(base64|encode)\b.*\b(curl|wget|nc)\b", "Encoded data exfiltration"),
    (r"\b/etc/(passwd|shadow)\b", "Accesses system credential files"),
    (r"~/.ssh/", "Accesses SSH keys"),
    (r"~/.aws/", "Accesses AWS credentials"),
    (r"\bcat\b.*\.(env|pem|key)\b", "Reads secret/key files"),
    (r"~/.gnupg/", "Accesses GPG keys"),
    (r"~/\.(kube|docker)/config", "Accesses cloud/container credentials"),
    (r"\bwallet|seed\s*phrase|mnemonic|private\s*key", "References crypto wallet/keys"),
]

# --- Code obfuscation ---
_OBFUSCATION_PATTERNS = [
    (r"\beval\b.*\$\(.*\b(curl|wget|nc|base64)\b", "eval with network/encoded command (obfuscated execution)"),
    (r"\bbase64\s+-d\b.*\|\s*(sh|bash)\b", "Decodes and executes hidden commands"),
    (r"\bpython\s+-c\b.*exec\(", "Inline Python exec (obfuscated code)"),
    (r"\bpython\s+-c\b.*import\s+os", "Inline Python os access"),
    (r"\$\(\s*echo\s.*\|\s*base64\s+-d\s*\)", "Encoded command execution"),
    (r"\b__import__\s*\(", "Dynamic import (common in obfuscated malware)"),
    (r"\bcodecs\.decode\b", "Codec-based string obfuscation"),
    (r"\bcompile\s*\(.*exec", "Dynamic code compilation and execution"),
    (r"(\\x[0-9a-f]{2}){4,}", "Hex-encoded string (potential obfuscation)"),
    (r"(\\u[0-9a-f]{4}){4,}", "Unicode-encoded string (potential obfuscation)"),
]

# --- Privilege escalation ---
_PRIVILEGE_PATTERNS = [
    (r"\bsudo\b", "Requests elevated privileges"),
    (r"\bchown\s+-R\b.*root", "Recursive ownership change to root"),
    (r"\bdocker\s+run\b.*--privileged", "Privileged Docker container"),
    (r"\bdocker\s+run\b.*-v\s+/:/", "Docker mount of entire filesystem"),
    (r"\bsystemctl\s+(start|stop|enable|disable|restart)\b", "Modifies system services"),
    (r"\blaunchctl\s+(load|unload|bootstrap)\b", "Modifies macOS system services"),
    (r"\bcrontab\b", "Modifies scheduled tasks"),
]

# --- Prompt injection (unique to AI skill files) ---
_INJECTION_PATTERNS = [
    # Direct instruction override
    (r"ignore\s+(all\s+)?previous\s+instructions", "Prompt injection: instruction override attempt"),
    (r"ignore\s+(all\s+)?prior\s+(instructions|rules|guidelines)", "Prompt injection: instruction override attempt"),
    (r"disregard\s+(all\s+)?(previous|prior|above)", "Prompt injection: disregard directive"),
    (r"you\s+are\s+now\s+(a|an|in)\b", "Prompt injection: identity reassignment"),
    (r"\bDAN\b.*\bjailbreak", "Prompt injection: DAN/jailbreak pattern"),
    (r"do\s+anything\s+now", "Prompt injection: DAN pattern"),
    (r"act\s+as\s+(if\s+)?you\s+(have\s+)?no\s+(restrictions|limits|rules)", "Prompt injection: restriction bypass"),
    # Hidden instructions in markdown (patterns must work on lowercased text)
    (r"<\s*important\s*>", "Hidden instruction tag (known injection pattern from ClawHavoc)"),
    (r"<!--.*?(ignore|override|bypass|execute|system\s*prompt).*?-->", "Suspicious HTML comment with directive keywords"),
    # Zero-width / invisible characters used to hide instructions
    (r"[\u200b\u200c\u200d\u2060\ufeff]", "Zero-width characters (may hide instructions)"),
    (r"[\u2062\u2063\u2064]", "Invisible math/separator characters"),
    # Conditional malice
    (r"if\s+.*?(first\s+run|first\s+time|hasn't\s+been\s+run)", "Conditional logic based on first run (rug-pull pattern)"),
]

# --- Hardcoded secrets ---
_SECRET_PATTERNS = [
    # API keys with common prefixes (case-sensitive scan — originals matter)
    (r"\b(?:sk|pk|api|key|token|secret|access)[-_][a-zA-Z0-9-_]{20,}", "Possible hardcoded API key or token"),
    (r"\bAIza[0-9A-Za-z_-]{35}\b", "Google API key"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key ID"),
    (r"\bghp_[a-zA-Z0-9]{36}\b", "GitHub personal access token"),
    (r"\bglpat-[a-zA-Z0-9_-]{20,}\b", "GitLab personal access token"),
    (r"\bxox[bporas]-[a-zA-Z0-9-]+", "Slack token"),
    (r"\bsk-[a-zA-Z0-9]{32,}\b", "OpenAI/Stripe-style secret key"),
    (r"\bey[A-Za-z0-9_-]{20,}\.ey[A-Za-z0-9_-]{20,}\.", "JWT token (may contain secrets)"),
    # Private keys
    (r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----", "Embedded private key"),
    (r"-----BEGIN\s+EC\s+PRIVATE\s+KEY-----", "Embedded EC private key"),
    # Crypto wallet seeds
    (r"\b(abandon|ability|able|about|above)\b.*\b(zoo|zone|zero)\b", "Possible BIP39 mnemonic seed phrase"),
]

# --- Suspicious URLs & downloads ---
_SUSPICIOUS_URL_PATTERNS = [
    (r"\bcurl\b.*\|\s*(sh|bash|zsh)\b", "Pipe from URL to shell (remote code execution)"),
    (r"\bwget\b.*&&\s*(sh|bash|chmod)", "Download and execute pattern"),
    (r"\b(bit\.ly|tinyurl|t\.co|rb\.gy|is\.gd)/", "URL shortener (hides true destination)"),
    (r"\bgist\.github\.com/", "Gist URL (unreviewed code source)"),
    (r"\bpastebin\.com/", "Pastebin URL (common malware hosting)"),
    (r"\bngrok\.io\b", "Ngrok tunnel (potential C2 or exfil endpoint)"),
    (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}[:/]", "Direct IP address (no DNS = suspicious)"),
]


_EXEC_LANGUAGES = {"bash", "sh", "zsh", "shell", "python", "python3", "py",
                    "ruby", "rb", "perl", "node", "javascript", "js", "powershell", "ps1", "cmd"}


def _extract_code_blocks_ast(text: str) -> list[tuple[str, str]]:
    """Extract fenced code blocks from markdown using mistletoe AST.

    Returns list of (language, code_content) tuples.
    Handles edge cases like nested blocks and unusual indentation
    more reliably than regex.
    """
    import mistletoe
    from mistletoe.block_token import CodeFence, BlockCode

    doc = mistletoe.Document(text)
    blocks: list[tuple[str, str]] = []

    def _walk(token):
        if isinstance(token, (CodeFence, BlockCode)):
            lang = getattr(token, 'language', '') or ''
            content = (getattr(token, 'content', '') or
                       (token.children[0].content if token.children else ''))
            blocks.append((lang.lower().strip(), content.strip()))
        if hasattr(token, 'children') and token.children:
            for child in token.children:
                _walk(child)

    _walk(doc)
    return blocks


def _extract_code_blocks_regex(text: str) -> list[tuple[str, str]]:
    """Extract fenced code blocks from markdown using regex (fallback).

    Returns list of (language, code_content) tuples.
    """
    blocks: list[tuple[str, str]] = []
    for match in re.finditer(r"```(\w*)\n(.*?)```", text, re.DOTALL):
        lang = match.group(1).lower()
        code = match.group(2).strip()
        blocks.append((lang, code))
    return blocks


def _extract_code_blocks(text: str) -> list[tuple[str, str]]:
    """Extract fenced code blocks from markdown.

    Returns list of (language, code_content) tuples.
    Uses mistletoe AST for reliable extraction, falling back to regex.
    """
    try:
        return _extract_code_blocks_ast(text)
    except Exception:
        return _extract_code_blocks_regex(text)


def _extract_inline_commands(text: str) -> list[str]:
    """Extract backtick-wrapped commands that look executable.

    Matches `command arg arg` patterns where the command is a known executable.
    """
    executables = {"curl", "wget", "rm", "sudo", "chmod", "chown", "dd", "mkfs",
                   "git", "docker", "nc", "python", "node", "bash", "sh", "eval",
                   "kill", "pip", "npm", "npx", "brew", "apt", "yum"}
    commands: list[str] = []
    for match in re.finditer(r"`([^`]{5,})`", text):
        cmd = match.group(1).strip()
        first_word = cmd.split()[0].lower() if cmd.split() else ""
        if first_word in executables:
            commands.append(cmd)
    return commands


def _scan_companion_scripts(file_path) -> list[tuple[str, str]]:
    """Read script files from a companion scripts/ directory.

    Returns list of (filename, content) tuples.
    """
    if file_path is None:
        return []
    from pathlib import Path
    path = Path(file_path)
    # Check for scripts/ sibling (folder-based skill) or parent scripts/
    scripts_dirs = [
        path.parent / "scripts",         # SKILL.md or main.md in skill dir
        path.parent.parent / "scripts",  # main.md inside nested dir
    ]
    results: list[tuple[str, str]] = []
    for scripts_dir in scripts_dirs:
        if scripts_dir.is_dir():
            for script in sorted(scripts_dir.iterdir()):
                if script.is_file() and not script.name.startswith("."):
                    try:
                        results.append((script.name, script.read_text()))
                    except (OSError, UnicodeDecodeError):
                        results.append((script.name, ""))
            break  # Only use the first found
    return results


def _score_trust(
    a: ParsedArtifact,
    ignore_categories: set[str] | None = None,
    custom_patterns: list[tuple[str, str, str]] | None = None,
    weight: float = 0.20,
    entropy_threshold: float = 4.8,
) -> ScoreDimension:
    """Scan for destructive commands, data exfiltration, obfuscation, and privilege escalation.

    Checks three layers:
    1. Prose text (steps, body, gotchas, examples)
    2. Executable code blocks (```bash, ```python, etc.)
    3. Companion script files (scripts/ directory)

    If ignore_categories is provided, findings in those categories are still
    reported in details but do not deduct from the trust score.
    """
    score = 1.0  # Start at full trust, deduct for findings
    details: list[str] = []
    suggestions: list[str] = []
    _ignored = {c.upper() for c in (ignore_categories or set())}

    # Layer 1: All prose text
    all_text = f"{' '.join(a.steps)} {a.raw_body} {' '.join(a.gotchas)} {' '.join(a.examples)}"

    # Documentation-only text: description + gotchas (used for context-aware filtering)
    # Patterns found ONLY here and nowhere else are likely documenting dangers, not executing them
    doc_only_text = f"{a.description} {' '.join(a.gotchas)}"

    # Layer 2: Extract executable code blocks
    code_blocks = _extract_code_blocks(all_text)
    exec_blocks = [(lang, code) for lang, code in code_blocks if lang in _EXEC_LANGUAGES]
    non_exec_blocks = [(lang, code) for lang, code in code_blocks if lang and lang not in _EXEC_LANGUAGES]

    if exec_blocks:
        langs = sorted(set(lang for lang, _ in exec_blocks))
        details.append(f"Contains {len(exec_blocks)} executable code block(s): {', '.join(langs)}")
        for lang, code in exec_blocks:
            # Show first line of each block as preview
            first_line = code.split("\n")[0].strip()[:80]
            details.append(f"  [{lang}] {first_line}")

    # Layer 3: Scan companion scripts
    scripts = _scan_companion_scripts(a.file_path)
    if scripts:
        details.append(f"Includes {len(scripts)} companion script(s): {', '.join(name for name, _ in scripts)}")

    # Layer 2b: Extract inline commands (deduplicated for display)
    inline_cmds = _extract_inline_commands(all_text)
    unique_cmds = list(dict.fromkeys(inline_cmds))  # preserve order, remove dupes
    if unique_cmds:
        details.append(f"Contains {len(unique_cmds)} inline command(s):")
        for cmd in unique_cmds:
            truncated = cmd[:80] + "..." if len(cmd) > 80 else cmd
            details.append(f"  $ {truncated}")

    # Build full scan text: prose + code blocks + scripts + inline commands
    scan_texts = [all_text]
    for _, code in exec_blocks:
        scan_texts.append(code)
    for _, content in scripts:
        scan_texts.append(content)
    for cmd in inline_cmds:
        scan_texts.append(cmd)

    full_scan = "\n".join(scan_texts)
    full_scan_lower = full_scan.lower()

    # Build "actionable" text — everything except description field
    # Description often documents what the skill *warns about* (e.g., "warns before rm -rf")
    # which is not the same as executing it
    actionable_texts = [' '.join(a.steps), a.raw_body, ' '.join(a.gotchas), ' '.join(a.examples)]
    for _, code in exec_blocks:
        actionable_texts.append(code)
    for _, content in scripts:
        actionable_texts.append(content)
    for cmd in inline_cmds:
        actionable_texts.append(cmd)
    actionable_scan = "\n".join(actionable_texts)
    actionable_lower = actionable_scan.lower()

    # Categories where documentation context matters — patterns in description/gotchas
    # that warn about dangers should not flag if the pattern isn't in executable code
    _DOC_AWARE_CATEGORIES = {"DESTRUCTIVE"}

    findings: list[tuple[str, str]] = []  # (category, description)

    # Scan all pattern categories
    _ALL_PATTERN_GROUPS = [
        (_DESTRUCTIVE_PATTERNS, "DESTRUCTIVE", True),      # case-insensitive
        (_EXFILTRATION_PATTERNS, "EXFILTRATION", True),
        (_OBFUSCATION_PATTERNS, "OBFUSCATION", False),     # case-sensitive
        (_PRIVILEGE_PATTERNS, "PRIVILEGE", True),
        (_INJECTION_PATTERNS, "INJECTION", True),
        (_SECRET_PATTERNS, "SECRET", False),                # case-sensitive
        (_SUSPICIOUS_URL_PATTERNS, "SUSPICIOUS_URL", True),
    ]

    for patterns, category, case_insensitive in _ALL_PATTERN_GROUPS:
        text_to_scan = full_scan_lower if case_insensitive else full_scan
        for pattern, desc in patterns:
            if re.search(pattern, text_to_scan):
                # Context-aware filtering: for DESTRUCTIVE patterns, check if the
                # match is ONLY in documentation (description/gotchas) and not in
                # any actionable context (code blocks, scripts, steps, commands).
                # A skill that warns "don't run rm -rf" shouldn't be flagged the
                # same as one that instructs "run rm -rf".
                if category in _DOC_AWARE_CATEGORIES:
                    action_text = actionable_lower if case_insensitive else actionable_scan
                    if not re.search(pattern, action_text):
                        # Pattern only in docs/description — skip it
                        continue
                findings.append((category, desc))

    # Custom patterns from config file
    if custom_patterns:
        for pat, desc, category in custom_patterns:
            try:
                if re.search(pat, full_scan, re.IGNORECASE):
                    findings.append((category, desc))
            except re.error:
                pass  # Skip invalid regex patterns

    # Entropy analysis: flag high-entropy strings (encoded payloads)
    entropy_findings = _check_entropy(full_scan, threshold=entropy_threshold)
    findings.extend(entropy_findings)

    if not findings:
        if not exec_blocks and not scripts and not inline_cmds:
            details.append("No executable code or suspicious patterns detected")
        else:
            details.append("Executable code found — no suspicious patterns detected")
        return ScoreDimension(
            name="trust",
            score=1.0,
            weight=weight,
            details=details,
            suggestions=suggestions,
        )

    # Deduct based on severity
    severity_weights = {
        "INJECTION": 0.50,         # Most critical — 91% of real attacks
        "OBFUSCATION": 0.40,       # Why hide what you're doing?
        "SECRET": 0.40,            # Hardcoded secrets are always wrong
        "EXFILTRATION": 0.35,      # Sending data out
        "SUSPICIOUS_URL": 0.30,    # curl|bash, IP addresses, shorteners
        "DESTRUCTIVE": 0.25,       # May be intentional but risky
        "PRIVILEGE": 0.15,         # sudo is common but worth flagging
        "ENTROPY": 0.20,           # High entropy = possible encoded payload
    }

    total_deduction = 0.0
    seen_categories: set[str] = set()
    suppressed_categories: set[str] = set()

    for category, desc in findings:
        if category in _ignored:
            suppressed_categories.add(category)
            suggestions.append(f"[{category}] (ignored) {desc}")
            continue
        suggestions.append(f"[{category}] {desc}")
        if category not in seen_categories:
            total_deduction += severity_weights.get(category, 0.2)
            seen_categories.add(category)
        else:
            # Additional findings in same category add smaller penalty
            total_deduction += 0.05

    if suppressed_categories:
        details.append(f"Suppressed categories: {', '.join(sorted(suppressed_categories))}")

    score = max(0.0, 1.0 - total_deduction)

    # Count only non-ignored findings for severity reporting
    active_findings = [(c, d) for c, d in findings if c not in _ignored]

    if not active_findings and findings:
        details.append(f"All {len(findings)} finding(s) suppressed by ignore rules")
    elif total_deduction >= 0.5:
        details.append(f"CRITICAL: {len(active_findings)} suspicious pattern(s) found — review carefully before use")
    elif total_deduction >= 0.3:
        details.append(f"HIGH: {len(active_findings)} suspicious pattern(s) found")
    elif active_findings:
        details.append(f"WARNING: {len(active_findings)} pattern(s) worth reviewing")

    return ScoreDimension(
        name="trust",
        score=score,
        weight=weight,
        details=details,
        suggestions=suggestions,
    )


def _check_entropy(text: str, threshold: float = 4.8) -> list[tuple[str, str]]:
    """Find high-entropy strings that may be encoded payloads or obfuscated code.

    Uses context-aware checks:
    - Skips known safe patterns (URLs, data URIs, hashes, file paths)
    - Requires both high entropy AND mixed character classes
    - Configurable threshold (default 4.8, up from 4.5 to reduce false positives)
    """
    findings: list[tuple[str, str]] = []

    # Known safe prefixes — URLs, data URIs, file paths, hash prefixes
    _SAFE_PREFIXES = (
        "http", "https", "file", "data:image", "data:application",
        "/usr", "/var", "/tmp", "/etc", "/home", "/opt",
        "sha256:", "sha1:", "md5:", "sha512:",
    )

    for match in re.finditer(r"[A-Za-z0-9+/=_-]{40,}", text):
        s = match.group()

        # Skip short strings (< 40 chars already filtered by regex, but guard)
        if len(s) < 40:
            continue

        # Skip known safe prefixes
        s_lower = s.lower()
        if any(s_lower.startswith(p) for p in _SAFE_PREFIXES):
            continue

        # Skip base64-encoded images (common in markdown: data:image/png;base64,...)
        # Check surrounding context for data URI
        start = max(0, match.start() - 30)
        context_before = text[start:match.start()].lower()
        if "data:" in context_before or "base64," in context_before:
            continue

        # Skip strings that are all same case + digits (likely hashes, not payloads)
        has_upper = any(c.isupper() for c in s)
        has_lower = any(c.islower() for c in s)
        has_digit = any(c.isdigit() for c in s)
        has_special = any(c in "+/=" for c in s)

        # Require mixed character classes — pure hex hashes have low class diversity
        char_classes = sum([has_upper, has_lower, has_digit, has_special])
        if char_classes < 2:
            continue

        entropy = _shannon_entropy(s)
        if entropy > threshold:
            snippet = s[:30] + "..." if len(s) > 30 else s
            findings.append(("ENTROPY", f"High-entropy string ({entropy:.1f} bits): {snippet}"))
            break  # One finding is enough to flag

    return findings


def _shannon_entropy(s: str) -> float:
    """Calculate Shannon entropy of a string. Higher = more random/encoded."""
    import math
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    length = len(s)
    return -sum((count / length) * math.log2(count / length) for count in freq.values())
