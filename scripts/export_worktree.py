from __future__ import annotations

import shutil
import sys
from pathlib import Path


def export_worktree(source: Path, destination: Path) -> None:
    root = source.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("source must be a directory")
    git_metadata = root / ".git"
    if not git_metadata.is_dir() or git_metadata.is_symlink():
        raise ValueError("source must contain a real root Git directory")
    if destination.exists() or destination.is_symlink():
        raise ValueError("destination must not exist")

    def root_only_ignore(directory: str, names: list[str]) -> set[str]:
        current = Path(directory)
        return {".git"} if current == root and ".git" in names else set()

    shutil.copytree(root, destination, symlinks=True, ignore=root_only_ignore)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("export_worktree: expected source and destination", file=sys.stderr)
        return 2
    try:
        export_worktree(Path(argv[1]), Path(argv[2]))
    except (OSError, RuntimeError, ValueError) as exc:
        message = " ".join(str(exc).split())[:300] or type(exc).__name__
        print(f"export_worktree: {type(exc).__name__}: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
