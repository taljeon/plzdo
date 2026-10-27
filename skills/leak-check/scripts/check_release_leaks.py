#!/usr/bin/env python3
"""Conservative public-release leak scanner.

The scanner reports finding type, path, and line only. It intentionally does
not print matched secret values or mail snippets.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


TEXT_EXTENSIONS = {
    ".cfg",
    ".conf",
    ".css",
    ".csv",
    ".env",
    ".example",
    ".gitignore",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".log",
    ".md",
    ".py",
    ".rb",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}

MEDIA_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".mov", ".mp4", ".png", ".webp"}

SKIP_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "vendor",
}

PROTECTED_PATH_PATTERNS = [
    ".env",
    ".env.*",
    "auth",
    "auth/**",
    "data",
    "data/**",
    "playwright/.auth",
    "playwright/.auth/**",
    "*.db",
    "**/*.db",
    "*.sqlite",
    "**/*.sqlite",
    "*.sqlite3",
    "**/*.sqlite3",
    "*.pem",
    "**/*.pem",
    "*.key",
    "**/*.key",
    "*.p12",
    "**/*.p12",
    "*token*.json",
    "**/*token*.json",
    "*credential*.json",
    "**/*credential*.json",
    "*credentials*.json",
    "**/*credentials*.json",
    "*service-account*.json",
    "**/*service-account*.json",
    "cookies*.json",
    "**/cookies*.json",
    "session*.json",
    "**/session*.json",
]

RECOMMENDED_GITIGNORE = [
    ".env",
    ".env.*",
    "auth/",
    "data/",
    "playwright/.auth/",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*token*.json",
    "*credentials*.json",
]

SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b|github_pat_[A-Za-z0-9_]{20,}")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe-live-key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}\b")),
    ("sensitive-token-field", re.compile(r"(?i)\b(access_token|refresh_token|id_token|client_secret|private_key)\b\s*[:=]")),
    ("password-field", re.compile(r"(?i)\b(passwd|password|pwd)\b\s*[:=]\s*['\"][^'\"]{4,}")),
]

RELEASE_RISK_PATTERNS = [
    ("local-absolute-path", re.compile(r"(/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+|[A-Za-z]:\\Users\\[A-Za-z0-9._-]+)")),
    ("google-meet-link", re.compile(r"https?://meet\.google\.com/[A-Za-z0-9-]+")),
    ("zoom-meeting-link", re.compile(r"https?://[A-Za-z0-9.-]*zoom\.us/[A-Za-z0-9/?=&._%-]+")),
    ("teams-meeting-link", re.compile(r"https?://teams\.microsoft\.com/l/meetup-join/[A-Za-z0-9/?=&._%+-]+")),
    ("gmail-message-link", re.compile(r"https?://mail\.google\.com/mail/[A-Za-z0-9/?=#._%-]+")),
]

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})\b", re.IGNORECASE)
SAFE_EMAIL_DOMAINS = {
    "example.com",
    "example.jp",
    "example.org",
    "example.net",
    "localhost.localdomain",
    "test.com",
    "test.local",
}

SUSPICIOUS_MEDIA_NAME_RE = re.compile(
    r"(screenshot|screen|capture|gmail|calendar|inbox|mail|oauth|auth|token|secret|dashboard|admin)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    severity: str
    check: str
    path: str
    line: int | None
    detail: str


def run_git(root: Path, args: list[str], *, nul: bool = False) -> list[str] | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    output = os.fsdecode(proc.stdout)
    return [item for item in (output.split("\0") if nul else output.splitlines()) if item]


def is_git_repo(root: Path) -> bool:
    result = run_git(root, ["rev-parse", "--is-inside-work-tree"])
    return result == ["true"]


def normalize_rel(path: str) -> str:
    rel = path.replace(os.sep, "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel


def path_matches(path: str, patterns: Iterable[str]) -> bool:
    rel = normalize_rel(path)
    return any(fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch("/" + rel, pattern) for pattern in patterns)


def git_tracked_files(root: Path) -> list[str]:
    files = run_git(root, ["-c", "core.quotepath=off", "ls-files", "-z"], nul=True)
    if files is not None:
        return [normalize_rel(item) for item in files]

    collected: list[str] = []
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for filename in filenames:
            path = Path(current_root, filename)
            collected.append(normalize_rel(str(path.relative_to(root))))
    return sorted(collected)


def git_untracked_files(root: Path) -> list[str]:
    files = run_git(
        root, ["-c", "core.quotepath=off", "ls-files", "-z", "--others", "--exclude-standard"], nul=True,
    )
    return [normalize_rel(item) for item in files] if files is not None else []


def is_probably_text(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    try:
        with path.open("rb") as handle:
            chunk = handle.read(4096)
    except OSError:
        return False
    return b"\0" not in chunk


def scan_text_file(root: Path, rel: str, max_bytes: int) -> list[Finding]:
    path = root / rel
    if not path.is_file() or not is_probably_text(path):
        return []
    try:
        if path.stat().st_size > max_bytes:
            return [
                Finding("medium", "large-text-file-skipped", rel, None, f"larger than {max_bytes} bytes; inspect before public release")
            ]
    except OSError:
        return []

    findings: list[Finding] = []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line_number, line in enumerate(handle, start=1):
                for label, pattern in SECRET_PATTERNS:
                    if pattern.search(line):
                        findings.append(Finding("high", "secret-pattern", rel, line_number, label))
                for label, pattern in RELEASE_RISK_PATTERNS:
                    if pattern.search(line):
                        findings.append(Finding("medium", "release-risk-pattern", rel, line_number, label))
                for match in EMAIL_RE.finditer(line):
                    domain = match.group(1).lower()
                    if domain not in SAFE_EMAIL_DOMAINS and not domain.endswith(".example"):
                        findings.append(Finding("medium", "personal-or-real-email", rel, line_number, "email address present"))
    except OSError:
        return findings
    return findings


def check_gitignore(root: Path) -> list[Finding]:
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return [Finding("medium", "gitignore-missing", ".gitignore", None, "missing .gitignore for public-release safeguards")]
    try:
        lines = [
            line.strip()
            for line in gitignore.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    except OSError:
        return []

    findings: list[Finding] = []
    for pattern in RECOMMENDED_GITIGNORE:
        if pattern not in lines:
            findings.append(Finding("low", "gitignore-recommendation", ".gitignore", None, f"consider ignoring {pattern}"))
    return findings


def check_paths(root: Path, tracked: list[str], untracked: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for rel in tracked:
        if path_matches(rel, PROTECTED_PATH_PATTERNS):
            findings.append(Finding("high", "tracked-protected-path", rel, None, "sensitive path is tracked"))
        suffix = Path(rel).suffix.lower()
        if suffix in MEDIA_EXTENSIONS and SUSPICIOUS_MEDIA_NAME_RE.search(rel):
            findings.append(Finding("medium", "tracked-suspicious-media", rel, None, "media filename suggests live screenshot or capture"))

    for rel in untracked:
        if path_matches(rel, PROTECTED_PATH_PATTERNS):
            findings.append(Finding("medium", "untracked-sensitive-path", rel, None, "sensitive untracked path present"))
        suffix = Path(rel).suffix.lower()
        if suffix in MEDIA_EXTENSIONS and SUSPICIOUS_MEDIA_NAME_RE.search(rel):
            findings.append(Finding("low", "untracked-suspicious-media", rel, None, "media filename suggests live screenshot or capture"))
    return findings


def scan(root: Path, max_bytes: int) -> list[Finding]:
    tracked = git_tracked_files(root)
    untracked = git_untracked_files(root) if is_git_repo(root) else []
    findings = []
    findings.extend(check_gitignore(root))
    findings.extend(check_paths(root, tracked, untracked))
    for rel in tracked:
        if any(part in SKIP_DIRS for part in Path(rel).parts):
            continue
        if path_matches(rel, PROTECTED_PATH_PATTERNS):
            continue
        findings.extend(scan_text_file(root, rel, max_bytes))
    return sorted(findings, key=lambda item: (severity_rank(item.severity), item.path, item.line or 0, item.check))


def severity_rank(severity: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(severity, 3)


def print_human(findings: list[Finding]) -> None:
    if not findings:
        print("Leak check: no findings.")
        return

    print(f"Leak check: {len(findings)} finding(s). Values are not printed.")
    for finding in findings:
        location = finding.path
        if finding.line is not None:
            location = f"{location}:{finding.line}"
        print(f"[{finding.severity}] {finding.check} {location} - {finding.detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a repository for public-release leaks without printing secret values.")
    parser.add_argument("--root", default=".", help="Repository root to scan.")
    parser.add_argument("--max-bytes", type=int, default=1_000_000, help="Skip individual text files larger than this size.")
    parser.add_argument("--json", action="store_true", help="Emit JSON findings.")
    parser.add_argument("--no-fail", action="store_true", help="Always exit 0, even when findings are present.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"error: root does not exist or is not a directory: {root}", file=sys.stderr)
        return 2

    findings = scan(root, args.max_bytes)
    if args.json:
        print(json.dumps([asdict(item) for item in findings], ensure_ascii=False, indent=2))
    else:
        print_human(findings)

    if args.no_fail:
        return 0
    return 1 if any(item.severity in {"high", "medium"} for item in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
