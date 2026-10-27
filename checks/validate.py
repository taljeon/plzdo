"""Validate tier-one text, licenses, the manifest, and release hygiene."""

from __future__ import annotations

import argparse
import json
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

if __package__:
    from . import manifest, scan
    from .tree import inventory
else:
    import manifest
    import scan
    from tree import inventory


TEXT_FOLDERS = {"harness", "skills", "agents", "style"}
AGENT_KEYS = {"name", "description", "tools", "disallowedTools", "model", "isolation"}
SETUP_COMMANDS = (
    r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:sh|bash)\b",
    r"\bpip\s+install\b", r"\bpipx\s+install\b",
    r"\bnpm\s+(?:install|i)\s+-g\b", r"\bbrew\s+install\b",
    r"\bcodex\s+login\b", r"\bgh\s+auth\s+login\b", r"\bclaude\s+login\b",
)
# Claude Code expands !`cmd` where ! starts a word; "?!`" inside a code span is punctuation.
BANG = re.compile(r"(?:^|[\s(\[>*_])!`")
TOP_KEY = re.compile(r"^([^\s:#][^:]*):(?:\s+(.*)|\s*)$")
BLOCK = re.compile(r"[|>][+-]?(?:\s+#.*)?$")
# Explicit indentation keeps leading spaces in the value, which dedent would hide from the length check.
EXPLICIT_INDENT = re.compile(r"[|>](?:[+-]?[1-9]|[1-9][+-]?)(?:\s+#.*)?$")


@dataclass(frozen=True)
class Problem:
    rule: str
    path: str
    reason: str
    line: int | None = None

    def __str__(self) -> str:
        location = self.path + (f":{self.line}" if self.line is not None else "")
        return f"FAIL {self.rule} {location} {self.reason}"


def scalar(value: str) -> str:
    quoted = re.fullmatch(r"'((?:[^']|'')*)'(?:\s+#.*)?", value)
    if quoted:
        return quoted.group(1).replace("''", "'")
    if value.startswith('"'):
        try:
            parsed, end = json.JSONDecoder().raw_decode(value)
            tail = value[end:].strip()
            if isinstance(parsed, str) and (not tail or tail.startswith("#")):
                return parsed
        except ValueError:
            pass
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def frontmatter(text: str) -> tuple[dict[str, str], list[tuple[str, int]], str | None]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}, [], "missing opening frontmatter delimiter"
    end = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    if end is None:
        return {}, [], "missing closing frontmatter delimiter"
    values = {}
    keys = []
    index = 1
    while index < end:
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#") or line[0].isspace():
            index += 1
            continue
        match = TOP_KEY.match(line)
        if not match:
            return values, keys, "invalid top-level frontmatter line"
        key, value = match.group(1).strip().strip("\"'"), (match.group(2) or "").strip()
        keys.append((key, index + 1))
        index += 1
        if EXPLICIT_INDENT.fullmatch(value):
            return values, keys, "explicit block indentation indicator is not supported"
        if BLOCK.fullmatch(value):
            block = []
            while index < end and (not lines[index].strip() or lines[index][0].isspace()):
                block.append(lines[index])
                index += 1
            content = textwrap.dedent("\n".join(block)).split("\n") if block else []
            result = ""
            for offset, part in enumerate(content):
                result += part
                following = content[offset + 1] if offset + 1 < len(content) else None
                if value[0] == ">" and part and following and not part[0].isspace() and not following[0].isspace():
                    result += " "
                elif value[0] == ">" and not part and following and not following[0].isspace() and any(content[:offset]):
                    # A blank separator preserves one paragraph break, not two.
                    pass
                else:
                    result += "\n"
            indicator = value.split()[0]
            if "-" in indicator:
                result = result.rstrip("\n")
            elif "+" not in indicator:
                result = result.rstrip("\n") + ("\n" if result else "")
            values[key] = result
        else:
            # Indented lines after a plain or quoted scalar continue it, so they count toward its length.
            parts = [scalar(value)] if value else []
            while index < end and (not lines[index].strip() or lines[index][0].isspace()):
                parts.append(lines[index].strip())
                index += 1
            values[key] = " ".join(part for part in parts if part)
    return values, keys, None


def validate(root: Path) -> list[Problem]:
    problems: list[Problem] = []
    files, _ = inventory(root)
    harness_chars = 0
    for relative in files:
        path = Path(relative)
        folder = path.parts[0]
        tier1 = folder in TEXT_FOLDERS or folder == "settings"
        if folder in {"harness", "agents", "style"} and not (path.suffix == ".md" or path.name.startswith(("LICENSE", "NOTICE"))):
            problems.append(Problem("tier1-file", relative, "only Markdown and license/notice files are permitted"))
        if folder == "settings" and relative not in {"settings/permissions.snippet.json", "settings/settings.example.json"}:
            problems.append(Problem("tier1-file", relative, "only permissions.snippet.json and settings.example.json are permitted"))
        if not tier1 or (path.suffix != ".md" and folder != "harness"):
            continue
        text = (root / path).read_text(encoding="utf-8", errors="ignore")
        if folder == "harness":
            harness_chars += len(text)
            if len(text.splitlines()) >= 400:
                problems.append(Problem("harness-budget", relative, "file must have fewer than 400 lines"))
        if path.suffix != ".md":
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if BANG.search(line) or line.lstrip().startswith("```!"):
                problems.append(Problem("bang-block", relative, "command expansion or executable fence", number))
            if folder in {"harness", "agents"} and any(re.search(pattern, line) for pattern in SETUP_COMMANDS):
                problems.append(Problem("setup-command", relative, "setup command in tier-one text", number))
        kind = None
        if folder == "skills" and len(path.parts) == 3 and path.name == "SKILL.md":
            kind = "skill"
        elif folder == "agents" and len(path.parts) == 2:
            kind = "agent"
        if kind:
            values, keys, error = frontmatter(text)
            for key, number in keys:
                if kind == "agent" and key not in AGENT_KEYS:
                    problems.append(Problem(kind + "-key", relative, f"unsupported key: {key}", number))
            if error:
                problems.append(Problem(kind + "-frontmatter", relative, error))
            else:
                for required in ("name", "description"):
                    if not values.get(required):
                        problems.append(Problem(kind + "-frontmatter", relative, f"missing {required}"))
            if kind == "skill":
                description = len(values.get("description", ""))
                if description > 1024:
                    problems.append(Problem("skill-length", relative, "description exceeds 1024 characters"))
                if description + len(values.get("when_to_use", "")) > 1536:
                    problems.append(Problem("skill-length", relative, "description plus when_to_use exceeds 1536 characters"))
    if harness_chars >= 30000:
        problems.append(Problem("harness-budget", "harness/", "total must be under 30000 characters"))

    snippet = "settings/permissions.snippet.json"
    try:
        if snippet not in files:
            raise ValueError
        value = json.loads((root / snippet).read_text(encoding="utf-8"))
        valid = isinstance(value, dict) and set(value) == {"permissions"}
        permissions = value.get("permissions") if valid else None
        valid = valid and isinstance(permissions, dict) and set(permissions) <= {"ask", "deny"}
        if not valid or any(not isinstance(items, list) or not all(isinstance(item, str) for item in items) for items in permissions.values()):
            raise ValueError
    except (OSError, ValueError):
        problems.append(Problem("snippet", snippet, "expected only permissions with ask/deny string lists"))

    skills = root / "skills"
    for folder in sorted(skills.iterdir()) if skills.is_dir() else []:
        if not folder.is_dir() or folder.is_symlink():
            continue
        source = folder / "SOURCE.md"
        relative = source.relative_to(root).as_posix()
        if source.is_symlink() or not source.is_file():
            problems.append(Problem("license", relative, "skill folder missing SOURCE.md"))
            continue
        text = source.read_text(encoding="utf-8")
        if re.search(r"^origin:\s*(vendored|modified)\s*$", text, re.I | re.M):
            has_license = any(
                Path(p).is_relative_to(folder.relative_to(root))
                and Path(p).name.startswith(("LICENSE", "LICENCE")) for p in files
            )
            if not has_license:
                problems.append(Problem("license", relative, "vendored or modified skill has no LICENSE or LICENCE file"))
    for issue in manifest.check(root):
        reason, path = issue.split(" ", 1)
        problems.append(Problem("manifest", path, reason))
    for finding in scan.scan(root):
        problems.append(Problem("scan", finding.path, finding.rule, finding.line))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        problems = validate(args.root)
    except (OSError, UnicodeError, ValueError):
        problems = [Problem("manifest", ".", "unable to read tree or manifest")]
    for problem in problems:
        print(problem)
    print(f"validate: {len(problems)} problems" if problems else "validate: ok")
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
