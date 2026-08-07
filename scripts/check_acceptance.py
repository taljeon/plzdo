from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Sequence


GIT = Path("/usr/bin/git")
FULL_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class AcceptanceError(ValueError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bind local verification to one clean Git commit")
    parser.add_argument("root")
    parser.add_argument("expected_commit")
    return parser


def check_acceptance(root: Path, expected_commit: str) -> str:
    if not isinstance(expected_commit, str) or FULL_COMMIT.fullmatch(expected_commit) is None:
        raise AcceptanceError("expected commit must be a full lowercase Git object id")
    if root.is_symlink() or not root.is_dir():
        raise AcceptanceError("acceptance root must be a real directory")
    root = root.resolve(strict=True)
    metadata = root / ".git"
    if metadata.is_symlink() or not metadata.is_dir():
        raise AcceptanceError("acceptance requires a checked-out repository with real Git metadata")

    actual = _git(root, ("rev-parse", "--verify", "HEAD^{commit}")).decode("ascii").strip()
    if actual != expected_commit:
        raise AcceptanceError("expected commit does not match HEAD")
    if _git(root, ("status", "--porcelain=v1", "-z", "--untracked-files=all")):
        raise AcceptanceError("acceptance requires a clean working tree")
    return actual


def _git(root: Path, arguments: Sequence[str]) -> bytes:
    if not GIT.is_file():
        raise AcceptanceError("Git is unavailable at the required system path")
    environment: Dict[str, str] = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/dev/null",
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    }
    completed = subprocess.run(
        [str(GIT), "-C", str(root)] + list(arguments),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    if completed.returncode != 0:
        raise AcceptanceError("Git acceptance inspection failed")
    return completed.stdout


def main() -> int:
    args = build_parser().parse_args()
    try:
        print(check_acceptance(Path(args.root), args.expected_commit))
        return 0
    except (AcceptanceError, OSError, subprocess.SubprocessError) as exc:
        print("FAIL acceptance: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
