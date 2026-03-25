"""Fetch skills from remote sources (GitHub repos, raw URLs) for auditing.

Supports:
- GitHub repo URLs → git clone to temp dir
- GitHub blob URLs → convert to raw URL and fetch single file
- Raw URLs → fetch single .md file
"""

import re
import shutil
import subprocess
import tempfile
import urllib.request
import urllib.error
from pathlib import Path


def is_remote(path: str) -> bool:
    """Check if a path is a remote URL."""
    return path.startswith(("https://", "http://"))


def fetch_remote(url: str) -> tuple[Path, bool]:
    """Fetch a remote skill source to a local temp path.

    Returns (local_path, is_temp) where is_temp indicates the caller
    should clean up the path when done.

    Handles:
    - GitHub repo: https://github.com/user/repo → clones to temp dir
    - GitHub blob: https://github.com/user/repo/blob/main/SKILL.md → fetches raw file
    - GitHub tree: https://github.com/user/repo/tree/main/skills → clones + extracts subdir
    - Raw URL: https://example.com/skill.md → fetches to temp file
    """
    # GitHub blob URL → convert to raw and fetch single file
    blob_match = re.match(
        r"https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.*)",
        url,
    )
    if blob_match:
        owner, repo, branch, filepath = blob_match.groups()
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{filepath}"
        return _fetch_raw_file(raw_url, filepath.split("/")[-1])

    # GitHub tree URL → clone repo, return subdirectory
    tree_match = re.match(
        r"https://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.*)",
        url,
    )
    if tree_match:
        owner, repo, branch, subdir = tree_match.groups()
        repo_url = f"https://github.com/{owner}/{repo}.git"
        tmp = _clone_repo(repo_url, branch)
        target = tmp / subdir
        if target.exists():
            return target, True
        # Fallback to repo root
        return tmp, True

    # GitHub repo URL (no blob/tree) → clone entire repo
    repo_match = re.match(
        r"https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$",
        url,
    )
    if repo_match:
        return _clone_repo(url), True

    # Raw githubusercontent URL → fetch single file
    if "raw.githubusercontent.com" in url:
        filename = url.rstrip("/").split("/")[-1]
        return _fetch_raw_file(url, filename)

    # Generic URL → fetch as single file
    if url.endswith(".md") or url.endswith(".txt"):
        filename = url.rstrip("/").split("/")[-1]
        return _fetch_raw_file(url, filename)

    # Unknown URL format — try cloning as git repo
    try:
        return _clone_repo(url), True
    except Exception:
        raise ValueError(f"Cannot fetch: {url}\nSupported: GitHub repos, GitHub file URLs, raw .md URLs")


def _fetch_raw_file(url: str, filename: str) -> tuple[Path, bool]:
    """Fetch a single file from a URL to a temp directory."""
    tmp = Path(tempfile.mkdtemp(prefix="skill-audit-"))
    dest = tmp / filename

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "skill-audit"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            dest.write_bytes(resp.read())
    except urllib.error.HTTPError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError(f"HTTP {e.code} fetching {url}") from e
    except urllib.error.URLError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError(f"Cannot reach {url}: {e.reason}") from e

    return dest, True


def _clone_repo(url: str, branch: str | None = None) -> Path:
    """Clone a git repo to a temp directory. Returns the repo root path."""
    tmp = Path(tempfile.mkdtemp(prefix="skill-audit-"))

    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd.extend(["--branch", branch])
    cmd.extend([url, str(tmp / "repo")])

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
    except subprocess.CalledProcessError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError(f"git clone failed: {e.stderr.decode().strip()}") from e
    except FileNotFoundError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError("git not found — install git to audit remote repos")

    return tmp / "repo"


def cleanup_temp(path: Path) -> None:
    """Clean up a temp directory created by fetch_remote."""
    # Walk up to find the skill-audit- prefixed temp dir
    for parent in [path] + list(path.parents):
        if parent.name.startswith("skill-audit-") or str(parent).startswith(tempfile.gettempdir()):
            shutil.rmtree(parent, ignore_errors=True)
            return
    # Fallback: if path is in a temp-looking location, clean it
    if str(path).startswith("/tmp") or str(path).startswith("/var/folders"):
        shutil.rmtree(path, ignore_errors=True)
