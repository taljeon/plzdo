"""Write or check the complete shipped file inventory."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

if __package__:
    from .tree import inventory
else:
    from tree import inventory


MANIFEST = "MANIFEST.sha256"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def write(root: Path) -> list[str]:
    files, symlinks = inventory(root)
    if symlinks:
        return [f"symlink {path}" for path in symlinks]
    lines = [f"{digest(root / path)}  {path}\n" for path in files if path != MANIFEST]
    (root / MANIFEST).write_text("".join(lines), encoding="utf-8")
    return []


def check(root: Path) -> list[str]:
    files, symlinks = inventory(root)
    problems = [f"symlink {path}" for path in symlinks]
    if MANIFEST in symlinks:
        return problems
    if MANIFEST not in files:
        return problems + [f"missing {MANIFEST}"]
    expected = {}
    for number, line in enumerate((root / MANIFEST).read_text(encoding="utf-8").splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            problems.append(f"invalid {MANIFEST}:{number}")
            continue
        value, path = match.groups()
        if Path(path).is_absolute() or ".." in Path(path).parts or path == MANIFEST or path in expected:
            problems.append(f"invalid {MANIFEST}:{number}")
            continue
        expected[path] = value
    actual = set(files) - {MANIFEST}
    for path in sorted(set(expected) - actual - set(symlinks)):
        problems.append(f"missing {path}")
    for path in sorted(actual - set(expected)):
        problems.append(f"extra {path}")
    for path in sorted(actual & set(expected)):
        if digest(root / path) != expected[path]:
            problems.append(f"changed {path}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("write", "check"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        problems = write(args.root) if args.action == "write" else check(args.root)
    except (OSError, UnicodeError):
        print("unreadable MANIFEST.sha256 or tree")
        return 1
    for problem in problems:
        print(problem)
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
