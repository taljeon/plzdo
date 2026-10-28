"""Scan text without printing matched content."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

if __package__:
    from .tree import TIER_ONE, inventory
else:
    from tree import TIER_ONE, inventory


ALL_RULES = frozenset({
    "local-path", "memory-term", "email", "codex-path", "private-key",
    "github-token", "openai-key", "google-api-key", "aws-access-key",
    "slack-token", "stripe-live-key", "sensitive-token-field", "password-field",
})
# Listed vendored files keep upstream examples, one file and rule at a time (npm "@scope/pkg@1.0" reads as an email, test tokens, sample paths).
# maintainer/export.py separately checks every exported file for the owner's private identifiers and home path.
EXCEPTIONS = {
    "checks/scan.py": ALL_RULES,
    "checks/tests/**": ALL_RULES,
    "maintainer/tests/**": ALL_RULES,
    "skills/leak-check/SKILL.md": {"local-path"},
    "skills/leak-check/scripts/check_release_leaks.py": {"local-path"},
    "skills/hyperframes-animation/scripts/animation-map.mjs": {"email"},
    "skills/hyperframes-animation/scripts/animation-map.test.mjs": {"email"},
    "skills/hyperframes-animation/scripts/package-loader.mjs": {"email"},
    "skills/hyperframes-animation/scripts/package-loader.test.mjs": {"email"},
    "skills/hyperframes-audio/scripts/carve.test.mjs": {"email"},
    "skills/hyperframes-creative/scripts/contrast-report.mjs": {"email"},
    "skills/hyperframes-creative/scripts/package-loader.mjs": {"email"},
    "skills/hyperframes-creative/scripts/package-loader.test.mjs": {"email"},
    "skills/hyperframes-cli/references/preview-render.md": {"local-path"},
    "skills/media-use/audio/scripts/lib/python.test.mjs": {"local-path"},
    "skills/media-use/audio/scripts/lib/heygen.test.mjs": {"sensitive-token-field"},
    "skills/media-use/audio/scripts/gemini-pipeline.test.mjs": {"sensitive-token-field"},
    "skills/cro/references/form.md": {"email"},
    "skills/impeccable/reference/hooks.md": {"codex-path"},
}

PATTERNS = [
    ("local-path", re.compile(r"/Users/[^/\s]+|/home/[^/\s]+|C:\\Users\\[^\\\s]+|~/Documents")),
    ("memory-term", re.compile(r"memory_")),
    ("codex-path", re.compile(r"\.codex/")),
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
EMAIL = re.compile(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@([A-Z0-9.-]+\.[A-Z]{2,})\b", re.IGNORECASE)
QUOTED_OR_LITERAL_EMAIL = re.compile(r'"[^"\n]+"@\S|@\[[0-9A-Fa-f.:]+\]')
SAFE_EMAIL_DOMAINS ={"users.noreply.github.com", "example.com", "example.org", "example.net"}


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int


def selected_files(root: Path, paths: list[str] | None = None) -> list[str]:
    files, _ = inventory(root)
    if paths is not None:
        selected = set()
        for name in paths:
            path = root / name
            relative = path.absolute().relative_to(root.absolute()).as_posix()
            if ".." in Path(relative).parts:
                raise ValueError("scan paths must stay within root")
            if not path.exists() or path.is_symlink():
                raise ValueError("scan path is missing or a symlink")
            selected.update(p for p in files if relative == "." or p == relative or p.startswith(relative + "/"))
        return sorted(selected)
    inside_fixtures = any(
        parent.name == "fixtures" and parent.parent.name == "checks"
        for parent in (root.resolve(), *root.resolve().parents)
    )
    return [p for p in files if inside_fixtures or not p.startswith("checks/fixtures/")]


def scan_file(root: Path, relative: str) -> list[Finding]:
    data = (root / relative).read_bytes()
    if b"\0" in data[:8192]:
        return []
    return scan_data(data, relative, exceptions=True)


def scan_data(data: bytes, relative: str, *, exceptions: bool) -> list[Finding]:
    allowed = set()
    for pattern, rules in EXCEPTIONS.items():
        if exceptions and fnmatch.fnmatchcase(relative, pattern):
            allowed.update(rules)
    findings = []
    for number, line in enumerate(data.decode("utf-8", errors="ignore").splitlines(), 1):
        for rule, pattern in PATTERNS:
            if rule not in allowed and pattern.search(line):
                findings.append(Finding(rule, relative, number))
        if "email" not in allowed and (QUOTED_OR_LITERAL_EMAIL.search(line) or any(
            match.group(1).lower() not in SAFE_EMAIL_DOMAINS for match in EMAIL.finditer(line)
        )):
            findings.append(Finding("email", relative, number))
    return findings


def scan(root: Path, paths: list[str] | None = None) -> list[Finding]:
    return [finding for path in selected_files(root, paths) for finding in scan_file(root, path)]


def git_bytes(root: Path, *args: str, optional: bool = False) -> bytes:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=30)
    if result.returncode and not (optional and result.returncode == 1):
        raise ValueError("git " + args[0] + " failed")
    return result.stdout


def release_details(root: Path, remote: str, ref: str | None) -> dict:
    def git(*args: str) -> str:
        return git_bytes(root, *args).decode("utf-8", errors="surrogateescape").strip()

    root = root.resolve()
    if Path(git("rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("root must be the repository root")
    if git("status", "--porcelain"):
        raise ValueError("working tree is dirty")
    if any(entry[:1].islower() or entry[:1] == b"S"
           for entry in git_bytes(root, "ls-files", "-v", "-z").split(b"\0") if entry):
        raise ValueError("hidden index flags (assume-unchanged or skip-worktree)")
    if remote not in git("remote").splitlines():
        raise ValueError("a configured remote is required")
    if git_bytes(root, "config", "--type=bool", "--get", "push.followTags", optional=True).strip() == b"true":
        raise ValueError("push.followTags is not supported")
    # ls-remote follows fetch rewrites, so its tips could come from a different repository than the push.
    if git_bytes(root, "config", "--get-regexp", r"^url\..*\.(insteadof|pushinsteadof)$", optional=True).strip():
        raise ValueError("URL rewriting is not supported")
    ref = ref if ref is not None else git("symbolic-ref", "--quiet", "HEAD")
    if ref == "HEAD" or (ref.startswith("refs/") and not ref.startswith("refs/heads/")):
        raise ValueError("--ref must name a branch")
    if not ref.startswith("refs/heads/"):
        ref = "refs/heads/" + ref
    git("check-ref-format", ref)
    commit = git("rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
    urls = sorted(git("remote", "get-url", "--push", "--all", remote).splitlines())
    if not urls or any(not url for url in urls):
        raise ValueError("remote has no push URL")
    return {"version": 2, "repo": str(root), "commit": commit,
            "ref": ref, "remote": remote, "push_urls": urls}


def scan_release(details: dict) -> list[Finding]:
    root = Path(details["repo"])
    commit = details["commit"]
    own_repo = root == Path(__file__).resolve().parents[1]
    blobs = set()
    for entry in git_bytes(root, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
        if entry:
            metadata, path = entry.split(b"\t", 1)
            _, kind, sha = metadata.split()
            if kind == b"blob":
                blobs.add((commit, path, sha))
    commits = set()
    # Destinations are read at scan time; the hook's 30 min TTL bounds drift.
    for url in details["push_urls"]:
        tips = set()
        try:
            result = subprocess.run(["git", "-C", str(root), "ls-remote", "--", url],
                                    env=dict(os.environ, GIT_TERMINAL_PROMPT="0"),
                                    capture_output=True, timeout=30)
            lines = result.stdout.splitlines() if result.returncode == 0 else []
        except (OSError, subprocess.TimeoutExpired):
            lines = []
        for line in lines:
            oid = line.split(b"\t", 1)[0]
            if not re.fullmatch(rb"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", oid):
                continue
            try:
                tip = git_bytes(root, "rev-parse", "--verify", "--end-of-options",
                                oid.decode("ascii") + "^{commit}")
                tips.add(tip.decode("ascii").strip())
            except ValueError:
                continue
        commits.update(git_bytes(root, "rev-list", commit, "--not", *sorted(tips)).splitlines())
    for revision in sorted(commits):
        current = revision.decode("ascii")
        # Compare merges against each parent so merge-only additions are scanned too.
        entries = git_bytes(root, "diff-tree", "-r", "--root", "--no-commit-id",
                            "--no-renames", "-m", "-z", current).split(b"\0")
        for index in range(0, len(entries) - 1, 2):
            metadata, path = entries[index:index + 2]
            _, mode, _, sha, _ = metadata.split()
            if mode not in {b"000000", b"160000"}:
                blobs.add((current, path, sha))
    findings = []
    for current, raw_path, sha in sorted(blobs):
        path = raw_path.decode("utf-8", errors="surrogateescape")
        parts = Path(path).parts
        if own_repo and (path.startswith("checks/fixtures/") or parts[-1] == ".DS_Store" or
                         (parts[0] not in TIER_ONE and "__pycache__" in parts[:-1])):
            continue
        data = git_bytes(root, "cat-file", "blob", sha.decode("ascii"))
        for finding in scan_data(data, path, exceptions=own_repo):
            findings.append(Finding(finding.rule, current[:7] + ":" + path, finding.line))
    return findings


def write_release_pass(details: dict) -> None:
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
    config.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = config / "plzdo" / "state"
    for directory in (state.parent, state):
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
    descriptor, name = tempfile.mkstemp(prefix=".release-pass-", dir=state)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(dict(details, created=time.time()), output)
            output.write("\n")
        os.replace(name, state / "release-pass.json")
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--release-pass", action="store_true")
    parser.add_argument("--remote")
    parser.add_argument("--ref")
    args = parser.parse_args()
    details = None
    if args.release_pass:
        try:
            if not args.remote or args.paths:
                raise ValueError("--remote is required and partial scans are not permitted")
            details = release_details(args.root, args.remote, args.ref)
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            print(f"scan: release pass refused: {error}")
            return 1
    try:
        if details is not None:
            findings = scan_release(details)
        else:
            files = selected_files(args.root, args.paths or None)
            findings = [finding for path in files for finding in scan_file(args.root, path)]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        print("scan: unable to read requested tree")
        return 1
    for finding in findings:
        print(f"{finding.rule} {finding.path}:{finding.line}")
    if details is not None and not findings:
        try:
            if release_details(args.root, args.remote, args.ref) != details:
                raise ValueError("repository changed during scan")
            write_release_pass(details)
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            print(f"scan: release pass refused: {error}")
            return 1
        print(f"scan: release pass written for {details['commit'][:7]} -> {args.remote}")
        return 0
    if not findings:
        print(f"scan: clean ({len(files)} files)")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
