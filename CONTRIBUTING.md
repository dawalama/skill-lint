# Contributing to skill-audit

Thanks for your interest in making AI skills safer. Here's how to contribute.

## Setup

```bash
git clone https://github.com/dawalama/skill-audit.git
cd skill-audit
uv sync --extra dev
uv run pytest tests/ -v
```

## Adding detection patterns

Detection patterns live in `src/skill_audit/rubrics/skill_rubrics.py`. Each pattern is a tuple of `(regex, description)` in one of 9 categories:

| Category | Variable | What it catches |
|----------|----------|----------------|
| Destructive | `_DESTRUCTIVE_PATTERNS` | Commands that destroy data |
| Exfiltration | `_EXFILTRATION_PATTERNS` | Sending data out, reverse shells, RCE, credential logging, insecure storage |
| Obfuscation | `_OBFUSCATION_PATTERNS` | Hidden or encoded code execution |
| Privilege | `_PRIVILEGE_PATTERNS` | Privilege escalation attempts |
| Injection | `_INJECTION_PATTERNS` | Prompt injection and jailbreaks |
| Secrets | `_SECRET_PATTERNS` | Hardcoded API keys and tokens |
| Suspicious URLs | `_SUSPICIOUS_URL_PATTERNS` | Risky download or callback patterns |
| Persistence | `_PERSISTENCE_PATTERNS` | Backdoors that survive reboots (authorized_keys, systemd, shell profiles) |
| Hijacking | `_HIJACKING_PATTERNS` | Crypto miners and mining pool connections |

Pattern coverage is informed by [arXiv:2604.03070](https://arxiv.org/abs/2604.03070) which analyzed 17,022 LLM agent skills and found 1,708 security issues across 10 vulnerability categories.

### To add a new pattern:

1. Add the regex + description to the appropriate list
2. Add a test in `tests/test_rubrics.py` (see existing trust tests for the pattern)
3. Run `uv run pytest tests/ -v` to verify
4. If it's a novel attack pattern, consider adding an adversarial test in `tests/test_adversarial.py`

### Pattern guidelines

- Patterns should have **low false positive rates** — flag real threats, not common usage
- Include a clear description explaining *why* the pattern is suspicious
- Case sensitivity: injection/destructive/exfiltration patterns are case-insensitive; secrets/obfuscation are case-sensitive (to match actual key formats)
- Test with both true positives (malicious) and true negatives (legitimate usage)

## Adding scoring rubrics

Quality rubrics are in:
- `src/skill_audit/rubrics/skill_rubrics.py` — 6 dimensions for skills
- `src/skill_audit/rubrics/role_rubrics.py` — 4 dimensions for roles

Each dimension function returns a `ScoreDimension` with score (0.0-1.0), weight, details, and suggestions.

## Adding format support

Format detection lives in `src/skill_audit/parser.py`. To support a new format:

1. Add detection logic in `detect_format()`
2. Add parsing in `parse_file()` to populate `ParsedArtifact`
3. Add tests in `tests/test_parser.py`

## Pull requests

- Keep PRs focused — one feature or fix per PR
- Include tests for new functionality
- Run the full test suite before submitting
- Update README.md if adding user-facing features

## Reporting false positives

If skill-audit flags legitimate content, open an issue with:
- The content that triggered the false positive
- Which category flagged it
- Why it's a false positive

This helps us tune patterns for better accuracy.
