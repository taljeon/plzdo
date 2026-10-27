#!/usr/bin/env python3
"""Measure character changes, with optional removal of Markdown line markers."""

import argparse
import difflib
from pathlib import Path
import re
import sys


FENCE = re.compile(r"^\s*(?:`{3,}[^`]*|~{3,}.*)$")
HORIZONTAL_RULE = re.compile(r"^\s*(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$")
PREFIX = re.compile(
    r"^\s*(?:#{1,6}\s+|[-*+•・]\s+|[0-9０-９]+[.)．）]\s+|>\s*)"
)
TABLE_CELL = re.compile(r":?-+:?")


def strip_markup(text: str) -> str:
    lines = []
    for line in text.splitlines():
        # Recognize rules before stripping bullets: '* * *' is a rule, not a list.
        while True:
            cells = line.strip().strip("|").split("|")
            table_separator = "|" in line and all(
                TABLE_CELL.fullmatch(cell.strip()) for cell in cells
            )
            if FENCE.fullmatch(line) or HORIZONTAL_RULE.fullmatch(line) or table_separator:
                break
            stripped = PREFIX.sub("", line, count=1)
            if stripped == line:
                lines.append(line)
                break
            line = stripped
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--ignore-markup", action="store_true")
    args = parser.parse_args()
    try:
        with args.before.open(encoding="utf-8", newline="") as source:
            before = source.read()
        with args.after.open(encoding="utf-8", newline="") as source:
            after = source.read()
    except (OSError, UnicodeError) as error:
        print(f"Cannot read input: {error}", file=sys.stderr)
        return 3

    if args.ignore_markup:
        before = strip_markup(before)
        after = strip_markup(after)
    rate = 1 - difflib.SequenceMatcher(None, before, after, autojunk=False).ratio()
    print(f"{rate * 100:.1f}%")
    if rate >= 0.5:
        return 2
    if rate >= 0.3:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
