#!/usr/bin/env python3
"""Compare multisets of digit runs, Japanese quotations, and ASCII words."""

import argparse
from collections import Counter
from pathlib import Path
import re
import sys
import unicodedata


def quoted_spans(text: str) -> Counter:
    starts = {"「": [], "『": []}
    closers = {"」": "「", "』": "『"}
    spans = Counter()
    for index, char in enumerate(text):
        if char in starts:
            starts[char].append(index)
        elif char in closers:
            stack = starts[closers[char]]
            if stack:
                start = stack.pop()
                spans[text[start:index + 1]] += 1
    return spans


def protected_items(text: str) -> dict:
    return {
        "digit runs": Counter(
            unicodedata.normalize("NFKC", run)
            for run in re.findall(r"[0-9０-９]+", text)
        ),
        "quoted spans": quoted_spans(text),
        # Japanese particles need not have a space after an ASCII word.
        "ASCII words": Counter(re.findall(r"[A-Za-z]{2,}", text)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    args = parser.parse_args()
    try:
        with args.before.open(encoding="utf-8", newline="") as source:
            before = protected_items(source.read())
        with args.after.open(encoding="utf-8", newline="") as source:
            after = protected_items(source.read())
    except (OSError, UnicodeError) as error:
        print(f"Cannot read input: {error}", file=sys.stderr)
        return 1

    changed = False
    for category, original in before.items():
        rewritten = after[category]
        for label, difference in (
            ("removed", original - rewritten),
            ("added", rewritten - original),
        ):
            for item, count in sorted(difference.items()):
                print(f"{category}: {label} {item!r} (count: {count})")
                changed = True
    if changed:
        return 1
    print("All tracked items are preserved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
