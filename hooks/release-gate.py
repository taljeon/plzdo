#!/usr/bin/env python3
"""Guard against Claude accidentally publishing unscanned content via its Bash tool.

This canonical-command guardrail is not a sandbox against a hostile agent.
"""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit


CANONICAL = ("PlzDo release gate: publish this by hand or use the canonical form: "
             "git push <remote> <branch>")
GIT_ENV = {"GIT_DIR", "GIT_WORK_TREE", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_GLOBAL"}
FORBIDDEN = set(';&|(){}<>`$#\n\r')
GH_VALUES = {"--title", "-t", "--body", "-b", "--body-file", "-F", "--base", "-B"}
GH_FLAGS = {"--draft", "-d", "--fill"}


def publish_intent(command: str) -> bool:
    normalized = command.replace("\\\n", "").translate(str.maketrans("", "", "\\'\""))
    normalized = normalized.replace("${IFS}", " ").replace("$IFS", " ")
    return bool(re.search(r"\bpush\b", normalized) or
                re.search(r"\bgh\b[\s\S]*\b(?:pr|release|repo|api)\b", normalized))


def canonical_request(command: str) -> tuple[str, str | None]:
    # Quotes may group simple values; shell expansion and escaped syntax are not canonical.
    if any(char in FORBIDDEN for char in command) or "\\" in command:
        raise ValueError("compound commands and shell expansion are not supported")
    tokens = shlex.split(command)
    if re.match(r"^git[ \t]+push(?:[ \t]|$)", command) and tokens[:2] == ["git", "push"]:
        positionals = []
        for token in tokens[2:]:
            if token in {"-u", "--set-upstream"}:
                continue
            if token.startswith("-"):
                raise ValueError("unsupported push option")
            positionals.append(token)
        if len(positionals) != 2:
            raise ValueError("push requires an explicit remote and branch")
        return positionals[0], positionals[1]
    if re.match(r"^gh[ \t]+pr[ \t]+create(?:[ \t]|$)", command) and tokens[:3] == ["gh", "pr", "create"]:
        if "GH_REPO" in os.environ:
            raise ValueError("GH_REPO overrides the repository")
        index = 3
        while index < len(tokens):
            option = tokens[index]
            if option in GH_VALUES:
                index += 1
                if index == len(tokens) or not tokens[index] or tokens[index].startswith("-"):
                    raise ValueError("gh option requires a simple value")
            elif option not in GH_FLAGS:
                raise ValueError("unsupported gh option or argument")
            index += 1
        return "origin", None
    raise ValueError("unsupported publishing command")


def git(repo: Path, *args: str, optional: bool = False) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args],
                            text=True, capture_output=True, timeout=20)
    if result.returncode and not (optional and result.returncode == 1):
        raise ValueError("git " + args[0] + " failed")
    return result.stdout.strip()


def destination(cwd: Path, remote: str, branch: str | None) -> dict:
    if GIT_ENV.intersection(os.environ):
        raise ValueError("Git environment overrides are not supported")
    repo = Path(git(cwd, "rev-parse", "--show-toplevel")).resolve()
    if remote not in git(repo, "remote").splitlines():
        raise ValueError("push requires a configured remote name")
    ref = branch if branch is not None else git(repo, "symbolic-ref", "--quiet", "HEAD")
    if ref == "HEAD" or (ref.startswith("refs/") and not ref.startswith("refs/heads/")):
        raise ValueError("push requires a branch name or refs/heads/<name>")
    if not ref.startswith("refs/heads/"):
        ref = "refs/heads/" + ref
    git(repo, "check-ref-format", ref)
    commit = git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
    if git(repo, "config", "--get-regexp", r"^url\..*\.(insteadof|pushinsteadof)$", optional=True):
        raise ValueError("URL rewriting is not supported")
    # Even an empty value defines a push override, so inspect keys as well as values.
    if git(repo, "config", "--get-regexp", r"^remote\." + re.escape(remote) + r"\.(push|pushurl)$", optional=True):
        raise ValueError("configured push refspecs and pushurl overrides are not supported")
    if git(repo, "config", "--bool", "--get", f"remote.{remote}.mirror", optional=True) == "true":
        raise ValueError("mirror pushes are not supported")
    if git(repo, "config", "--get", "push.default", optional=True) == "matching":
        raise ValueError("matching pushes are not supported")
    if git(repo, "config", "--type=bool", "--get", "push.followTags", optional=True) == "true":
        raise ValueError("push.followTags is not supported")
    urls = sorted(git(repo, "remote", "get-url", "--push", "--all", remote).splitlines())
    if not urls or any(not url for url in urls):
        raise ValueError("remote has no push URL")
    return {"repo": str(repo), "ref": ref, "commit": commit, "remote": remote, "push_urls": urls}


def url_parts(url: str) -> tuple:
    # Git decodes %-escapes in some URL forms (file://.../%2e%2e/x opens a sibling), so none count as private.
    if not url or any(c.isspace() or ord(c) < 32 or 127 <= ord(c) < 160 for c in url) or "\\" in url or "%" in url:
        raise ValueError("invalid destination")
    if url.startswith("/"):
        if ".." in url.split("/"):
            raise ValueError("invalid local path")
        return "file", None, None, os.path.normpath(url)
    if "://" in url:
        value = urlsplit(url)
        scheme = {"git+ssh": "ssh", "ssh+git": "ssh"}.get(value.scheme, value.scheme)
        defaults = {"https": 443, "http": 80, "ssh": 22, "git": 9418, "file": None}
        if (scheme not in defaults or "%" in value.netloc or
                (scheme != "file" and not value.hostname) or
                any(part in {".", ".."} for part in value.path.split("/"))):
            raise ValueError("invalid destination")
        port = value.port if value.port is not None else defaults[scheme]
        path = os.path.normpath(value.path) if scheme == "file" and value.path else value.path
        return scheme, value.hostname, port, path
    match = re.fullmatch(r"(?:[^@/:]+@)?([^@/:\[\]]+):(.*)", url)
    if not match or any(part in {".", ".."} for part in match[2].split("/")):
        raise ValueError("invalid scp destination")
    return "scp", match[1].lower(), None, match[2]


def path_prefix(path: str, prefix: str) -> bool:
    prefix = prefix.rstrip("/")
    return not prefix or path == prefix or path.startswith(prefix + "/")


def private_destination(config: Path, url: str) -> bool:
    try:
        value = json.loads((config / "plzdo" / "release-gate.json").read_text(encoding="utf-8"))
        hosts = value.get("private_hosts", [])
        prefixes = value.get("private_url_prefixes", [])
        if not all(isinstance(items, list) and all(isinstance(item, str) for item in items)
                   for items in (hosts, prefixes)):
            return False
        target = url_parts(url)
        parsed = [url_parts(prefix) for prefix in prefixes]
        return (target[1] is not None and target[1] in {host.lower() for host in hosts}) or any(
            target[:3] == prefix[:3] and path_prefix(target[3], prefix[3]) for prefix in parsed)
    except (OSError, ValueError, AttributeError):
        return False


def check_pass(config: Path, target: dict) -> None:
    try:
        value = json.loads((config / "plzdo" / "state" / "release-pass.json").read_text(encoding="utf-8"))
        if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 2:
            raise ValueError("invalid release pass version")
        if any(value.get(key) != expected for key, expected in target.items()):
            raise ValueError("release pass does not match repo, ref, commit, remote and push URLs")
        created = value.get("created")
        ttl = float(os.environ.get("PLZDO_PASS_TTL", "1800"))
        if type(created) not in (int, float) or not math.isfinite(created):
            raise ValueError("invalid release pass timestamp")
        age = time.time() - created
        if not math.isfinite(ttl) or ttl < 0 or not 0 <= age <= ttl:
            raise ValueError("release pass expired or has an invalid age")
    except (OSError, TypeError) as error:
        raise ValueError("release pass is missing or unreadable") from error


def deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
          "permissionDecision": "deny", "permissionDecisionReason": CANONICAL + "; " + reason}}))


def main() -> int:
    payload = json.load(sys.stdin)
    if payload.get("tool_name") != "Bash":
        return 0
    command = payload["tool_input"]["command"]
    if not publish_intent(command):
        return 0
    try:
        remote, branch = canonical_request(command)
        cwd = Path(payload["cwd"]).resolve()
        target = destination(cwd, remote, branch)
        config = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
        if not all(private_destination(config, url) for url in target["push_urls"]):
            check_pass(config, target)
    except ValueError as error:
        deny(str(error))
    return 0


if __name__ == "__main__":
    try:
        status = main()
    except Exception:
        # Exit 2 blocks PreToolUse independently of the host's onFailure handling.
        print("PlzDo release gate: unable to verify publishing command", file=sys.stderr)
        status = 2
    raise SystemExit(status)
