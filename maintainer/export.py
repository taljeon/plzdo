#!/usr/bin/env python3
"""Export an owner's local files into a copy-ready mirror, without network access."""

from __future__ import annotations

import argparse
import fnmatch
from functools import partial
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys


KINDS = ("skill", "agent", "hook", "rule", "plugin", "mod", "mcp")
STATUSES = {"copy-ready", "adapted", "needs-runtime", "manual-config", "link-only", "excluded"}
COPY = {"copy-ready", "needs-runtime"}
FIELDS = {"name", "kind", "source", "dest", "origin", "upstream", "commit",
          "upstream_path", "license", "status", "company", "note"}
SKIP = {"__pycache__", ".pytest_cache", ".DS_Store", ".git"}


class ConfigError(ValueError):
    """A diagnostic containing only known field names and rules."""


def report(message: str, identifiers=(), *, file=None, end="\n") -> None:
    patterns = sorted({item.decode("utf-8") for item in identifiers if item}, key=len, reverse=True)
    if patterns:
        message = re.sub("|".join(re.escape(item) for item in patterns), "[private]", message)
    print(message, file=file, end=end)


class ArgumentParser(argparse.ArgumentParser):
    identifiers = ()

    def _print_message(self, message, file=None):
        if message:
            report(message, self.identifiers, file=file, end="")

    def error(self, message):
        # argparse's usual error includes arbitrary command-line values.
        self.exit(2, "export: invalid command line\n")


def inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def config_problems(config: object, root: Path) -> list[str]:
    problems = []
    if not isinstance(config, dict):
        return ["config: expected an object"]
    for key in sorted(set(config) - {"version", "replacements", "entries"}):
        problems.append("config: unknown key")
    for key in ("version", "replacements", "entries"):
        if key not in config:
            problems.append(f"config: missing {key}")
    if type(config.get("version")) is not int or config["version"] != 1:
        problems.append("config: version must be 1")
    replacements = config.get("replacements")
    if not isinstance(replacements, list):
        problems.append("config: replacements must be a list")
    else:
        for i, pair in enumerate(replacements, 1):
            if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(s, str) for s in pair):
                problems.append(f"replacement {i}: expected two strings")
    entries = config.get("entries")
    if not isinstance(entries, list):
        return problems + ["config: entries must be a list"]
    names, dests = set(), set()
    for i, entry in enumerate(entries, 1):
        label = f"config: entries[{i}]"
        if not isinstance(entry, dict):
            problems.append(f"{label}: expected an object")
            continue
        for key in sorted(set(entry) - FIELDS - {"exclude", "add"}):
            problems.append(f"{label}: unknown key")
        for key in sorted(FIELDS - set(entry)):
            problems.append(f"{label}: missing {key}")
        for key in ("name", "license", "note"):
            if not isinstance(entry.get(key), str) or (key != "note" and not entry[key]):
                problems.append(f"{label}: {key} must be a string")
        for key in ("source", "dest", "upstream", "commit", "upstream_path"):
            value = entry.get(key)
            if value is not None and (not isinstance(value, str) or not value or "\0" in value):
                problems.append(f"{label}: {key} must be a nonempty string or null")
        for key, choices in (("kind", KINDS), ("status", STATUSES),
                             ("origin", {"own", "modified", "vendored", "unknown"})):
            if not isinstance(entry.get(key), str) or entry[key] not in choices:
                problems.append(f"{label}: invalid {key}")
        if type(entry.get("company")) is not bool:
            problems.append(f"{label}: company must be boolean")
        exclude = entry.get("exclude", [])
        if not isinstance(exclude, list) or not all(isinstance(s, str) for s in exclude):
            problems.append(f"{label}: exclude must be a list of globs")
        name = entry.get("name")
        if isinstance(name, str):
            if name in names:
                problems.append(f"{label}: duplicate name")
            names.add(name)
        dest = entry.get("dest")
        if isinstance(dest, str) and dest and "\0" not in dest:
            path = PurePosixPath(dest)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                problems.append(f"{label}: dest must stay inside the repo")
            else:
                target = root / dest
                try:
                    safe = inside(target.resolve(), root) and not any(
                        p.is_symlink() for p in (target, *target.parents) if inside(p, root))
                except (OSError, RuntimeError):
                    safe = False
                if not safe:
                    problems.append(f"{label}: dest must stay inside the repo without symlinks")
                normalized = path.as_posix()
                if normalized in dests:
                    problems.append(f"{label}: duplicate dest")
                elif any(inside(Path(normalized), Path(d)) or inside(Path(d), Path(normalized)) for d in dests):
                    problems.append(f"{label}: overlapping dests")
                dests.add(normalized)
        status = entry.get("status")
        if isinstance(status, str) and status in COPY and (not entry.get("source") or not dest):
            problems.append(f"{label}: copy status requires source and dest")
        if status in ("link-only", "excluded") and dest is not None:
            problems.append(f"{label}: link-only/excluded must not have dest")
        if "add" in entry:
            try:
                added_files(entry, root)
            except ConfigError as exc:
                problems.append(f"{label}: {exc}")
    return problems


def added_files(entry: dict, root: Path) -> list[tuple[str, Path]]:
    if "add" not in entry:
        return []
    if not isinstance(entry["add"], dict):
        raise ConfigError("add must be an object")
    if not isinstance(entry.get("status"), str) or entry["status"] not in COPY:
        raise ConfigError("add requires copy-ready or needs-runtime status")
    try:
        if not Path(entry["source"]).expanduser().resolve(strict=True).is_dir() or not entry.get("dest"):
            raise ConfigError("add requires a folder destination")
        dest = root / entry["dest"]
        files = []
        for target, source in entry["add"].items():
            if not isinstance(target, str) or not target or "\0" in target:
                raise ConfigError("add target must be a relative file path")
            path = PurePosixPath(target)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ConfigError("add target must stay inside dest")
            if not inside((dest / target).resolve(), dest.resolve()):
                raise ConfigError("add target must stay inside dest")
            if not isinstance(source, str) or not source or "\0" in source or Path(source).is_absolute():
                raise ConfigError("add source must be a repo-relative file")
            resolved = (root / source).resolve(strict=True)
            if not resolved.is_file() or not inside(resolved, root) or inside(resolved, dest.resolve()):
                raise ConfigError("add source must be a file inside the repo and outside dest")
            files.append((path.as_posix(), resolved))
        return files
    except (OSError, RuntimeError, TypeError, KeyError) as exc:
        raise ConfigError("add requires an existing folder source and existing repo source files") from exc


def files_at(source: Path, excludes=(), report=None, directories=None, skip_defaults=True) -> list[tuple[str, Path]]:
    """Follow file links; directory links must stay in this resolved source tree."""
    source = source.resolve(strict=True)
    files = []

    def visit(path: Path, relative: str, ancestors: tuple[Path, ...]) -> None:
        if (skip_defaults and path.name in SKIP) or any(fnmatch.fnmatch(relative, pattern) for pattern in excludes):
            return
        resolved = path.resolve(strict=True)
        if path.is_dir():
            if not inside(resolved, source) or resolved in ancestors:
                if report:
                    report(f"skipped directory symlink: {relative}")
                return
            if directories is not None:
                directories.append(relative)
            for child in sorted(path.iterdir()):
                visit(child, f"{relative}/{child.name}" if relative else child.name, ancestors + (resolved,))
        elif path.is_file():
            files.append((relative or ".", resolved))
        else:
            raise ValueError("source contains a non-regular file")

    if source.is_dir():
        for child in sorted(source.iterdir()):
            visit(child, child.name, (source,))
    elif source.is_file():
        visit(source, "", ())
    else:
        raise ValueError("source must be a file or folder")
    return sorted(files)


def digest(files: list[tuple[str, Path]], exclude_source: bool = False) -> str:
    """Hash a UTF-8 JSON list of [relative POSIX path, file SHA256] pairs.

    Single files use '.' so a rename does not change their content digest.
    """
    pairs = [[name, hashlib.sha256(path.read_bytes()).hexdigest()] for name, path in sorted(files)
             if not (exclude_source and name == "SOURCE.md")]
    return hashlib.sha256(json.dumps(pairs, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def replaced(data: bytes, replacements: list[list[str]]) -> bytes:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    for old, new in replacements:
        text = text.replace(old, new)
    return text.encode("utf-8")


def source_note(entry: dict) -> bytes:
    lines = [f"{key}: {entry[key] or 'none'}" for key in
             ("name", "origin", "upstream", "commit", "upstream_path", "license", "status")]
    lines += ["company: " + ("yes" if entry["company"] else "no"), f"note: {entry['note']}",
              "Exported from the owner's live setup by maintainer/export.py."]  # source paths stay out: they name private folders
    return ("\n".join(lines) + "\n").encode("utf-8")


def scan_private(dest: Path, root: Path, identifiers: list[bytes]) -> bool:
    found = False
    # Scan all output bytes, including binary files and SOURCE.md.
    for _, path in files_at(dest, skip_defaults=False):
        for number, line in enumerate(path.read_bytes().split(b"\n"), 1):
            for index, identifier in enumerate(identifiers, 1):
                if identifier in line:
                    report(f"{path.relative_to(root).as_posix()}:{number}: private-id {index}", identifiers)
                    found = True
            if str(Path.home()).encode("utf-8") in line:
                report(f"{path.relative_to(root).as_posix()}:{number}: home-path", identifiers)
                found = True
    return found


def export(config: dict, root: Path, identifiers: list[bytes]) -> int:
    sources = {}
    additions = {}
    say = partial(report, identifiers=identifiers)
    dests = [root / entry["dest"] for entry in config["entries"] if entry["status"] in COPY]
    for entry in config["entries"]:
        if entry["source"] is not None:
            source = Path(entry["source"]).expanduser().resolve(strict=True)
            dest = root / entry["dest"] if entry["dest"] else None
            if dest and (inside(source, dest) or inside(dest, source)):
                raise ConfigError("source and destination overlap")
            directories = []
            files = files_at(source, entry.get("exclude", []), say, directories)
            sources[entry["name"]] = (source, files, directories)
            additions[entry["name"]] = added_files(entry, root)
            # Check every destination before the first deletion, including other entries.
            for resolved in [source] + [path for _, path in files + additions[entry["name"]]]:
                if any(inside(resolved, dest) or inside(dest, resolved) for dest in dests):
                    raise ConfigError("source and destination overlap")
    problems = False
    written = []
    for entry in config["entries"]:
        dest = root / entry["dest"] if entry["dest"] else None
        if entry["status"] == "adapted":
            if dest is None or not dest.exists():
                say(f"missing adapted dest: {entry['name']}")
                problems = True
        if entry["status"] not in COPY:
            continue
        source, files, directories = sources[entry["name"]]
        removable = len(dest.relative_to(root).parts) > 1 and dest.relative_to(root).parts[0] in {"skills", "agents", "hooks"}
        if dest.is_dir() and removable:
            shutil.rmtree(dest)
        elif dest.is_file() and source.is_dir() and removable:
            dest.unlink()
        elif dest.exists() and source.is_dir():
            # Never remove or merge an unapproved existing tree.
            raise ValueError("existing folder destination cannot be replaced outside skills/agents/hooks")
        if source.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            for relative in directories:
                (dest / relative).mkdir(parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
        for relative, path in files:
            if source.is_dir() and relative == "SOURCE.md":
                continue
            target = dest / relative if source.is_dir() else dest
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(replaced(path.read_bytes(), config["replacements"]))
            shutil.copymode(path, target)
        if source.is_dir():
            for relative, path in additions[entry["name"]]:
                target = dest / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                shutil.copymode(path, target)
            (dest / "SOURCE.md").write_bytes(replaced(source_note(entry), config["replacements"]))
        written.append(dest)
    for dest in written:
        problems = scan_private(dest, root, identifiers) or problems
    configured = {PurePosixPath(entry["dest"]).as_posix() for entry in config["entries"] if entry["dest"]}
    candidates = list((root / "skills").glob("*"))
    candidates = [p for p in candidates if p.is_dir()]
    candidates += list((root / "agents").glob("*.md")) + list((root / "hooks").glob("*.py"))
    for path in sorted(candidates):
        relative = path.relative_to(root).as_posix()
        if relative not in configured:
            say(f"orphan: {relative}")
    if problems:
        return 1
    entries = {}
    for entry in config["entries"]:
        if entry["source"] is None:
            continue
        dest = root / entry["dest"] if entry["dest"] else None
        entries[entry["name"]] = {
            "source_sha256": digest(sources[entry["name"]][1]),
            "dest_sha256": digest(files_at(dest, skip_defaults=False), exclude_source=True) if dest and dest.exists() else None,
        }
    lock = root / "maintainer/export.lock.json"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"version": 1, "entries": entries}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def check(config: dict, root: Path, identifiers=()) -> int:
    say = partial(report, identifiers=identifiers)
    lock = root / "maintainer/export.lock.json"
    previous = json.loads(lock.read_text(encoding="utf-8")) if lock.exists() else {"version": 1, "entries": {}}
    if not isinstance(previous, dict) or previous.get("version") != 1 or not isinstance(previous.get("entries"), dict):
        raise ValueError("invalid export lock")
    old = previous["entries"]
    changed = False
    for entry in sorted(config["entries"], key=lambda e: e["name"]):
        if entry["source"] is None:
            continue
        name = entry["name"]
        current = digest(files_at(Path(entry["source"]).expanduser(), entry.get("exclude", []), say))
        if name not in old:
            say(f"new: {name}")
            changed = True
        elif not isinstance(old[name], dict) or old[name].get("source_sha256") != current:
            label = "adapted-source-changed" if entry["status"] == "adapted" else "changed"
            say(f"{label}: {name}")
            changed = True
    for name in sorted(set(old) - {e["name"] for e in config["entries"]}):
        say(f"removed: {name}")
        changed = True
    return int(changed)


def inventory(config: dict, root: Path) -> int:
    path = root / "INVENTORY.md"
    data = path.read_bytes()
    start = list(re.finditer(rb"(?m)^<!-- inventory:start -->\r?$", data))
    end = list(re.finditer(rb"(?m)^<!-- inventory:end -->\r?$", data))
    if len(start) != 1 or len(end) != 1 or start[0].end() >= end[0].start():
        raise ValueError("INVENTORY.md requires ordered inventory:start and inventory:end marker lines")
    newline = "\r\n" if data[start[0].end() - 1:start[0].end()] == b"\r" else "\n"
    lines = [""]
    for kind in KINDS:
        entries = sorted((e for e in config["entries"] if e["kind"] == kind), key=lambda e: e["name"])
        if not entries:
            continue
        lines += [f"### {kind.title()}", "", "| Name | Company | Status | Origin | Upstream | License | Repo path | Note |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for entry in entries:
            upstream = entry["upstream"] or "-"
            commit = entry["commit"]
            if entry["upstream"] and commit:
                upstream += "@" + (commit[:12] if re.fullmatch(r"[0-9a-fA-F]{40}", commit) else commit)
            cells = [entry["name"], "yes" if entry["company"] else "", entry["status"], entry["origin"], upstream,
                     entry["license"], f"`{entry['dest']}`" if entry["dest"] else "-", entry["note"]]
            lines.append("| " + " | ".join(c.replace("|", "\\|").replace("\r", " ").replace("\n", " ") for c in cells) + " |")
        lines.append("")
    # Keep both marker lines and all surrounding bytes untouched (including CRLF).
    offset = start[0].end() + 1
    path.write_bytes(data[:offset] + (newline.join(lines) + newline).encode("utf-8") + data[end[0].start():])
    return 0


def main(argv=None) -> int:
    private_parser = ArgumentParser(prog="export.py", add_help=False)
    private_parser.add_argument("--private-ids", type=Path,
                                default=Path(os.environ.get("PLZDO_PRIVATE_IDS", str(Path.home() / ".config/plzdo/private-ids.txt"))))
    private_args, _ = private_parser.parse_known_args(argv)
    root = Path(__file__).resolve().parents[1]
    identifiers = []
    try:
        try:
            private_ids = private_args.private_ids.expanduser().resolve()
            if inside(private_ids, root):
                report("private identifiers file must be outside the repo", file=sys.stderr)
                return 2
            lines = private_ids.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError, RuntimeError):
            report("private identifiers file missing or unreadable", file=sys.stderr)
            return 2
        identifiers = [line.encode("utf-8") for line in lines if line.strip() and not line.lstrip().startswith("#")]
        parser = ArgumentParser(prog="export.py", description=__doc__, parents=[private_parser])
        parser.identifiers = identifiers
        parser.add_argument("command", choices=("export", "check", "inventory"))
        # The config names the owner's private source folders, so it lives outside the repo like the identifier list.
        parser.add_argument("--config", type=Path, default=Path(os.environ.get("PLZDO_EXPORT_CONFIG", str(Path.home() / ".config/plzdo/export.json"))))
        args = parser.parse_args(argv)
        config_path = args.config.expanduser().resolve()
        if inside(config_path, root):
            report("export config must be outside the repo", file=sys.stderr)
            return 2
        config = json.loads(config_path.read_text(encoding="utf-8"))
        problems = config_problems(config, root)
        if problems:
            for problem in problems:
                report(problem, identifiers, file=sys.stderr)
            return 2
        if args.command == "export":
            return export(config, root, identifiers)
        if args.command == "check":
            return check(config, root, identifiers)
        return inventory(config, root)
    except ConfigError as exc:
        report(f"config: {exc}", identifiers, file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError) as exc:
        # File contents and exception payloads can contain private identifiers.
        report(f"export: unable to complete ({type(exc).__name__})", identifiers, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
