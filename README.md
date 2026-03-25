# skill-audit

Audit AI skill and role files for quality and trust. Catches bad prompts before they reach your agent.

## Why

The AI skill ecosystem is growing fast — 80k+ community skills across Claude Code, OpenClaw, and other platforms. Some are excellent. Many are vague or incomplete. And some are actively malicious: audits have found 13-37% of marketplace skills contain critical issues including prompt injection, credential theft, and data exfiltration.

**skill-audit** scores skill and role files across quality and security dimensions so you can:

- **Vet before installing** — is this community skill safe and well-written?
- **Catch threats** — prompt injection, hardcoded secrets, destructive commands, data exfiltration, obfuscation
- **Improve what you write** — get specific, actionable feedback on your own skills
- **Gate quality in CI** — fail pipelines if skill quality drops below a threshold

## What it checks

### Skills (6 dimensions)

| Dimension | Weight | What it checks |
|-----------|--------|---------------|
| **Completeness** | 20% | Has description, steps, examples, gotchas, inputs |
| **Clarity** | 15% | Description length, structure, concrete language |
| **Actionability** | 20% | Steps start with verbs, reference tools/commands |
| **Safety** | 15% | Has gotchas, mentions error handling |
| **Testability** | 10% | Has examples with parameters and expected behavior |
| **Trust** | 20% | Security scan across 7 threat categories |

### Trust scans for

| Category | What it detects |
|----------|----------------|
| **Prompt injection** | "Ignore previous instructions", `<IMPORTANT>` hidden tags, zero-width characters, DAN/jailbreak patterns, identity reassignment |
| **Hardcoded secrets** | API keys (AWS, GitHub, Slack, OpenAI), private keys, JWT tokens, wallet seed phrases |
| **Destructive commands** | `rm -rf /`, `DROP TABLE`, `git push --force`, `dd`, `mkfs` |
| **Data exfiltration** | `curl -d` to external URLs, `~/.ssh/`, `~/.aws/`, env var leaks, credential file reads |
| **Code obfuscation** | `base64 -d \| bash`, `eval($(…))`, `__import__()`, hex/unicode encoding, `compile()+exec` |
| **Suspicious URLs** | `curl \| bash`, URL shorteners, direct IP addresses, pastebin/ngrok, gist URLs |
| **Privilege escalation** | `sudo`, `chmod 777`, privileged Docker, `systemctl`/`launchctl`, crontab |

Trust scans three layers: prose text, executable code blocks (` ```bash `, ` ```python `), and companion `scripts/` files.

### Roles (4 dimensions)

| Dimension | What it checks |
|-----------|---------------|
| **Persona clarity** | Has persona, starts with "You are...", describes mission |
| **Principles quality** | 3+ principles, each specific and >30 chars |
| **Anti-patterns** | Present, 2+ items, specific enough to act on |
| **Scope** | Focused description (<120 chars), has tags |

Grades: **A** (90%+), **B** (80%+), **C** (65%+), **D** (50%+), **F** (<50%)

## Install

No API keys. No LLM calls. Runs entirely offline using static analysis.

```bash
# From PyPI
pip install skill-audit

# Or with uv (recommended)
uv tool install skill-audit

# Or run directly without installing
uvx skill-audit audit ~/.ai/skills/

# From source
git clone https://github.com/dawalama/skill-audit.git
cd skill-audit
uv sync
uv run skill-audit audit ~/.ai/skills/
```

**Requirements:** Python 3.11+. No external dependencies beyond `pydantic`, `typer`, and `rich` (installed automatically).

## Usage

### Audit a single file

```bash
skill-audit audit review.md
```

```
╭──────────────────────────────────────────────────────────────╮
│ Code Review (skill) — Grade: A (97%)                         │
╰──────────────────────────── Format: dotai-skill ─────────────╯
┏━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━┓
┃ Dimension     ┃ Score ┃ Weight ┃ Status     ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━┩
│ completeness  │  100% │    20% │ ██████████ │
│ clarity       │  100% │    15% │ ██████████ │
│ actionability │   85% │    20% │ ████████░░ │
│ safety        │  100% │    15% │ ██████████ │
│ testability   │  100% │    10% │ ██████████ │
│ trust         │  100% │    20% │ ██████████ │
└───────────────┴───────┴────────┴────────────┘
```

### Audit with detailed findings

```bash
skill-audit audit review.md --verbose
```

Shows per-dimension findings (what's good) and suggestions (what to improve).

### Audit a directory

```bash
skill-audit audit ~/.ai/skills/ --summary
```

```
                        Skill Audit Summary
┏━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━┓
┃ File           ┃ Type  ┃ Name             ┃ Grade ┃ Score ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━┩
│ verify.md      │ skill │ Verify           │   A   │   99% │
│ review.md      │ skill │ Code Review      │   A   │   97% │
│ investigate.md │ skill │ Investigate      │   A   │   95% │
│ ship.md        │ skill │ Ship             │   A   │   90% │
│ plan.md        │ skill │ Plan             │   B   │   88% │
└────────────────┴───────┴──────────────────┴───────┴───────┘

  5 files analyzed, average score: 94%
```

### Inspect without scoring

```bash
skill-audit info SKILL.md
```

Shows detected format, entity type, parsed name, and extracted structure.

### LLM-powered review (optional)

Add `--llm` for deeper analysis that static patterns can't catch: intent mismatch, sophisticated prompt injection, and semantic quality review.

```bash
# Uses claude CLI if installed (zero config — already authenticated)
skill-audit audit SKILL.md --llm

# Force a specific provider
skill-audit audit SKILL.md --llm --llm-provider openrouter
skill-audit audit SKILL.md --llm --llm-provider ollama --llm-model llama3.2

# Check which providers are available
skill-audit providers
```

**No LLM SDK required.** Uses tools you already have:

| Provider | Config needed | How it works |
|----------|--------------|--------------|
| **claude CLI** | None — already authenticated | Pipes prompt to `claude --print` |
| **OpenRouter** | `OPENROUTER_API_KEY` env var | HTTP POST to OpenRouter API (any model) |
| **Ollama** | Ollama running locally | HTTP to `localhost:11434` |

The LLM reviews what static analysis can't: "this skill says it reviews code but actually instructs the agent to email files externally" (intent mismatch), conditional logic that changes behavior after first run (rug-pull), and subtle manipulation patterns.

Static analysis always runs first. LLM review is additive — it never replaces the pattern-based checks.

### Use in CI

```bash
# Fail if any skill scores below B
skill-audit audit ~/.ai/skills/ --min-grade B
```

Exit code 1 if any file is below the threshold.

### Output formats

```bash
# JSON (for programmatic use)
skill-audit audit review.md --output json

# Markdown (for PRs and docs)
skill-audit audit review.md --output markdown
```

### Force format detection

```bash
skill-audit audit SKILL.md --format claude-native
skill-audit audit custom.md --format dotai-skill
```

## Supported formats

| Format | Description | Auto-detected by |
|--------|-------------|-----------------|
| `dotai-skill` | [dotai](https://github.com/dawalama/dotai) structured skills | `trigger`, `category`, `## Steps` in frontmatter/body |
| `dotai-role` | dotai role files | `## Principles` + `## Anti-patterns` sections |
| `claude-native` | Claude Code SKILL.md files | `argument-hint`, `compatibility`/`license` in frontmatter, `SKILL.md` filename |
| `unknown` | Plain markdown | Fallback — still scored as a skill |

## Limitations

This is a **static analysis tool**. It uses pattern matching and heuristics to identify known threat patterns. It cannot:

- Detect obfuscated or encoded malware beyond known patterns
- Catch novel attack techniques not in its ruleset
- Determine contextual intent (legitimate `rm -rf` vs. malicious)
- Detect indirect prompt injection from external data sources
- Analyze runtime behavior or dynamic code generation
- Identify supply-chain attacks from compromised dependencies
- Replace manual code review for high-risk skills

**A passing audit does not mean a skill is safe.** Always review skills manually before granting them access to your systems, especially skills that request broad permissions (Bash, filesystem, network).

False positives are possible — legitimate skills may trigger warnings for patterns that match their intended functionality.

## Development

```bash
git clone https://github.com/dawalama/skill-audit.git
cd skill-audit
uv sync --extra dev
uv run pytest tests/ -v
```

## License

MIT
