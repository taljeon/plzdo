#!/usr/bin/python3
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = "plzdo-local.private-denylist.v1"
ALLOWED_EMAIL_DOMAINS = {
    "example.com",
    "example.net",
    "example.org",
    "users.noreply.github.com",
}
MAX_RELEASE_ENTRIES = 50_000
MAX_RELEASE_FILE_BYTES = 4 * 1024 * 1024
MAX_RELEASE_TOTAL_BYTES = 256 * 1024 * 1024
BLOCKED_SUFFIXES = {
    ".7z",
    ".a",
    ".avi",
    ".bin",
    ".bz2",
    ".class",
    ".csv",
    ".db",
    ".dll",
    ".docx",
    ".dylib",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".jsonl",
    ".key",
    ".log",
    ".m4a",
    ".mov",
    ".mp3",
    ".mp4",
    ".ndjson",
    ".o",
    ".pdf",
    ".pem",
    ".pfx",
    ".png",
    ".pptx",
    ".pyc",
    ".rar",
    ".so",
    ".sqlite",
    ".sqlite3",
    ".svg",
    ".tar",
    ".tgz",
    ".tsv",
    ".wasm",
    ".wav",
    ".webm",
    ".webp",
    ".xlsx",
    ".xz",
    ".zip",
}
BLOCKED_NAMES = {".env", ".envrc", ".npmrc", ".pypirc", "cookies", "login data"}
BLOCKED_DIRECTORIES = {
    ".auth",
    ".git",
    ".obsidian",
    "__pycache__",
    "auth",
    "browser-profile",
    "browser-profiles",
    "data",
    "exports",
    "logs",
    "recordings",
    "screenshots",
}
SENSITIVE_PATH_RULES = {
    "authorization-header",
    "aws-access-key",
    "credential-assignment",
    "credential-header",
    "blocked-sensitive-path-kind",
    "github-token",
    "gitlab-token",
    "google-api-key",
    "jwt-token",
    "machine-hostname",
    "meeting-url",
    "mounted-volume-path",
    "npm-token",
    "openai-style-token",
    "personal-phone",
    "private-key-header",
    "private-repository-url",
    "private-unix-user-path",
    "private-windows-user-path",
    "provider-conversation-url",
    "provider-session-id",
    "pypi-token",
    "real-email",
    "sensitive-json-field",
    "slack-token",
    "street-address",
    "stripe-live-token",
}


@dataclass(frozen=True)
class Finding:
    severity: str
    path: str
    line: int
    rule: str


@dataclass(frozen=True)
class PrivateTerm:
    finding_id: str
    value: str
    case_sensitive: bool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan a PlzDo Local public release candidate")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--private-denylist", type=Path)
    parser.add_argument("--require-private-denylist", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--quiet-warnings", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.self_test:
        return run_self_test()

    try:
        root = args.root.expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        print("FAIL <root>: release root is unavailable")
        return 1
    try:
        root_metadata = root.lstat()
    except OSError:
        print("FAIL <root>: release root is unavailable")
        return 1
    if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISLNK(root_metadata.st_mode):
        print("FAIL <root>: release root is not a real directory")
        return 1
    if args.require_private_denylist and args.private_denylist is None:
        print("FAIL <private-denylist>: required private denylist is missing")
        return 1

    try:
        terms = load_private_denylist(args.private_denylist, root) if args.private_denylist else []
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL <private-denylist>: {type(exc).__name__}")
        return 1

    try:
        findings, warnings = scan_root(root, terms)
    except Exception as exc:
        print(f"FAIL <release-tree>: scan-error:{type(exc).__name__}")
        return 1
    for finding in findings:
        location = f"{finding.path}:{finding.line}" if finding.line else finding.path
        print(f"FAIL {location}: {finding.rule}")
    if warnings and not args.quiet_warnings:
        for finding in warnings:
            print(f"WARN {finding.path}:{finding.line}: {finding.rule}")
    elif warnings:
        print(f"WARN ambiguous-sensitive-word: {len(warnings)} occurrences hidden")

    if findings:
        return 1
    print("release leak check passed")
    return 0


def scan_root(root: Path, private_terms: list[PrivateTerm]) -> tuple[list[Finding], list[Finding]]:
    findings: list[Finding] = []
    warnings: list[Finding] = []
    walk_errors: list[Path] = []
    gitignore = root / ".gitignore"
    try:
        gitignore_metadata = gitignore.lstat()
    except OSError:
        findings.append(Finding("high", ".gitignore", 0, "gitignore-missing"))
    else:
        if not stat.S_ISREG(gitignore_metadata.st_mode) or stat.S_ISLNK(gitignore_metadata.st_mode):
            findings.append(Finding("high", ".gitignore", 0, "gitignore-invalid"))

    entry_count = 0
    total_bytes = 0
    for path in inventory(root, walk_errors):
        entry_count += 1
        if entry_count > MAX_RELEASE_ENTRIES:
            findings.append(Finding("high", "<release-tree>", 0, "release-entry-count-exceeds-bound"))
            break
        try:
            raw_relative = path.relative_to(root).as_posix()
        except (UnicodeError, ValueError):
            findings.append(Finding("high", "<unsafe-path>", 0, "release-path-invalid"))
            continue
        path_findings, path_warnings = scan_release_path(raw_relative, private_terms)
        findings.extend(path_findings)
        warnings.extend(path_warnings)
        display = _display_path(raw_relative, private_terms, path_findings)
        try:
            metadata = path.lstat()
        except OSError:
            findings.append(Finding("high", display, 0, "release-file-read-error"))
            continue
        if stat.S_ISLNK(metadata.st_mode):
            findings.append(Finding("high", display, 0, "symlink-release-file"))
            continue
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            findings.append(Finding("high", display, 0, "special-release-file"))
            continue
        if _is_blocked_file_path(raw_relative):
            continue
        try:
            data = _read_bounded_regular_file(path, maximum=MAX_RELEASE_FILE_BYTES)
        except ValueError:
            findings.append(Finding("high", display, 0, "oversized-or-special-release-file"))
            continue
        except OSError:
            findings.append(Finding("high", display, 0, "release-file-read-error"))
            continue
        total_bytes += len(data)
        if total_bytes > MAX_RELEASE_TOTAL_BYTES:
            findings.append(Finding("high", "<release-tree>", 0, "release-bytes-exceed-bound"))
            break
        file_findings, file_warnings = scan_sensitive_bytes(display, data, private_terms)
        findings.extend(file_findings)
        warnings.extend(file_warnings)
    for error_path in walk_errors:
        try:
            raw_relative = error_path.relative_to(root).as_posix()
        except (UnicodeError, ValueError):
            raw_relative = "<release-tree>"
        path_findings, _ = scan_release_path(raw_relative, private_terms)
        findings.extend(path_findings)
        display = _display_path(raw_relative, private_terms, path_findings)
        findings.append(Finding("high", display, 0, "release-tree-walk-error"))
    return findings, warnings


def inventory(root: Path, walk_errors: list[Path]) -> Iterable[Path]:
    def record_error(error: OSError) -> None:
        walk_errors.append(Path(error.filename) if error.filename else root)

    for directory, names, files in os.walk(root, followlinks=False, onerror=record_error):
        base = Path(directory)
        retained: list[str] = []
        for name in sorted(names):
            candidate = base / name
            yield candidate
            try:
                metadata = candidate.lstat()
            except OSError:
                continue
            if name.casefold() in BLOCKED_DIRECTORIES or stat.S_ISLNK(metadata.st_mode):
                continue
            retained.append(name)
        names[:] = retained
        for name in sorted(files):
            yield base / name


def scan_release_path(relative: str, private_terms: list[PrivateTerm]) -> tuple[list[Finding], list[Finding]]:
    private_ids = _matching_private_term_ids(relative, private_terms)
    probe_findings, probe_warnings = scan_text("<sensitive-path>", relative, private_terms)
    rules = {finding.rule for finding in probe_findings}
    components = relative.split("/")
    lower_components = [component.casefold() for component in components]
    if any(component in BLOCKED_DIRECTORIES for component in lower_components):
        rules.add("blocked-directory-kind")
    if any(_is_blocked_filename(component) for component in lower_components):
        rules.add("blocked-sensitive-path-kind")
    if _is_blocked_file_path(relative):
        rules.add("blocked-file-kind")
    for finding_id in private_ids:
        rules.add(f"private-term:{finding_id}")
    display = _display_path_from_rules(relative, private_ids, rules)
    findings = [Finding("high", display, 0, rule) for rule in sorted(rules)]
    warnings = [Finding("low", display, 0, warning.rule) for warning in probe_warnings]
    return findings, warnings


def scan_sensitive_bytes(
    relative: str,
    data: bytes,
    private_terms: list[PrivateTerm],
) -> tuple[list[Finding], list[Finding]]:
    if len(data) > MAX_RELEASE_FILE_BYTES:
        return [Finding("high", relative, 0, "oversized-release-file")], []
    if b"\0" in data:
        return [Finding("high", relative, 0, "binary-file")], []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [Finding("high", relative, 0, "binary-file")], []
    if any(ord(character) < 32 and character not in "\n\r\t" for character in text):
        return [Finding("high", relative, 0, "binary-control-bytes")], []
    if _is_private_denylist_document(text):
        return [Finding("high", relative, 0, "private-denylist-content")], []
    return scan_text(relative, text, private_terms)


def scan_text(relative: str, text: str, private_terms: list[PrivateTerm]) -> tuple[list[Finding], list[Finding]]:
    findings: list[Finding] = []
    warnings: list[Finding] = []
    patterns = hard_patterns()
    email_pattern = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
    for line_number, line in enumerate(text.splitlines(), 1):
        for rule, pattern in patterns:
            if pattern.search(line):
                findings.append(Finding("high", relative, line_number, rule))
        for match in email_pattern.finditer(line):
            if match.group(1).casefold() not in ALLOWED_EMAIL_DOMAINS:
                findings.append(Finding("high", relative, line_number, "real-email"))
        for finding_id in _matching_private_term_ids(line, private_terms):
            findings.append(Finding("high", relative, line_number, f"private-term:{finding_id}"))
        if re.search(r"\b(token|session|cookie|secret)\b", line, re.IGNORECASE):
            warnings.append(Finding("low", relative, line_number, "ambiguous-sensitive-word"))
    return findings, warnings


def _matching_private_term_ids(value: str, private_terms: list[PrivateTerm]) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value)
    matches: list[str] = []
    for term in private_terms:
        needle = unicodedata.normalize("NFKC", term.value)
        haystack = normalized
        if not term.case_sensitive:
            haystack = haystack.casefold()
            needle = needle.casefold()
        if needle in haystack:
            matches.append(term.finding_id)
    return matches


def _display_path(relative: str, private_terms: list[PrivateTerm], findings: list[Finding]) -> str:
    private_ids = _matching_private_term_ids(relative, private_terms)
    rules = {finding.rule for finding in findings}
    return _display_path_from_rules(relative, private_ids, rules)


def _display_path_from_rules(relative: str, private_ids: list[str], rules: set[str]) -> str:
    if private_ids:
        return f"<private-path:{private_ids[0]}>"
    if rules.intersection(SENSITIVE_PATH_RULES) or any(
        _is_sensitive_filename(component.casefold()) for component in relative.split("/")
    ):
        return "<sensitive-path>"
    if any(ord(character) < 32 or ord(character) == 127 for character in relative):
        return "<unsafe-path>"
    return relative


def _is_blocked_file_path(relative: str) -> bool:
    lower_name = relative.rsplit("/", 1)[-1].casefold()
    private_manifest = "private-denylist" in lower_name and lower_name.endswith(".json")
    credential_manifest = (
        any(word in lower_name for word in ("token", "credential", "secret", "password"))
        and lower_name.endswith(".json")
    )
    suffix = Path(lower_name).suffix
    return (
        _is_blocked_filename(lower_name)
        or suffix in BLOCKED_SUFFIXES
        or private_manifest
        or credential_manifest
    )


def _is_blocked_filename(lower_name: str) -> bool:
    if lower_name in BLOCKED_NAMES or lower_name.startswith(".env."):
        return True
    return _is_sensitive_filename(lower_name)


def _is_sensitive_filename(lower_name: str) -> bool:
    sensitive_segment = (
        r"(?:auth|oauth|cookies?|credentials?|tokens?|passwords?|passwd|secrets?|"
        r"api[-_]?keys?|access[-_]?keys?|refresh[-_]?tokens?)"
    )
    return bool(re.search(rf"(?:^|[._-]){sensitive_segment}(?:$|[._-])", lower_name))


def hard_patterns() -> list[tuple[str, re.Pattern[str]]]:
    unix_prefix = "/" + "Users/" + r"(?!<)[A-Za-z0-9._-]+|/" + "home/" + r"(?!<)[A-Za-z0-9._-]+"
    windows_prefix = r"C:\\+" + "Users" + r"\\+(?!<)[^\\\s]+"
    key_header_pattern = "BEGIN " + r"(?:RSA |OPENSSH |EC |DSA )?" + "PRIVATE " + "KEY"
    github_token = r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b"
    openai_token = r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}\b"
    slack_token = r"\bxox(?:b|p|a|r|s)-[A-Za-z0-9-]{10,}\b"
    stripe_token = r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b"
    gitlab_token = r"\bglpat-[A-Za-z0-9_-]{20,}\b"
    npm_token = r"\bnpm_[A-Za-z0-9]{20,}\b"
    pypi_token = r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{16,}\b"
    google_api_key = r"\bAIza[0-9A-Za-z_-]{35}\b"
    jwt_token = r"\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]{1,}\.[A-Za-z0-9_-]{1,}\b"
    phone = r"(?<!\d)(?:\+\d{1,3}[- .]?)?(?:\(?\d{2,4}\)?[- .]){2,3}\d{3,4}(?!\d)"
    street_address = r"\b\d{1,6}\s+[A-Za-z0-9 .'-]{2,60}\s(?:Street|St|Road|Rd|Avenue|Ave|Boulevard|Blvd)\b"
    meeting_url = r"https?://(?:meet\.google\.com/|[^/]*zoom\.us/(?:j|my)/|teams\.microsoft\.com/l/meetup-join/)"
    mounted_path = "/" + r"(?:Volumes|mnt)/(?!<)[A-Za-z0-9._ -]+/"
    machine_name = r"(?<!\.)\b[A-Za-z0-9][A-Za-z0-9-]{2,}\.(?:corp|internal|lan|local)\b"
    ssh_repository = r"(?:git@|ssh://git@)[A-Za-z0-9.-]+(?::|/)[A-Za-z0-9._/-]+\.git\b"
    credentialed_https_repository = "https://" + r"[^/\s:@]+:[^@\s/]+@[A-Za-z0-9.-]+/[A-Za-z0-9._/-]+\.git\b"
    named_private_https_repository = (
        "https://"
        + r"[A-Za-z0-9.-]+/[A-Za-z0-9._/-]*(?:private|internal|confidential)[A-Za-z0-9._/-]*\.git\b"
    )
    private_repository = rf"(?:{ssh_repository}|{credentialed_https_repository}|{named_private_https_repository})"
    provider_conversation = r"https?://(?:chatgpt\.com/c/|claude\.ai/chat/|grok\.com/(?:c|share)/)"
    provider_session = r"\bsession[_-]?id\s*[:=]\s*[0-9a-f]{8}-[0-9a-f-]{27,36}\b"
    sensitive_json_field = r"[\"'](?:client_email|client_secret|private_key_id|refresh_token)[\"']\s*:"
    credential_name = (
        r"(?:password|passwd|pwd|secret|client[_-]?secret|api[_-]?key|access[_-]?token|"
        r"refresh[_-]?token)"
    )
    placeholder = r"(?:<[^>]+>|example|sample|synthetic|dummy|redacted|none|null|\$\{?[A-Z_][A-Z0-9_]*\}?)"
    credential_assignment = (
        rf"\b{credential_name}\b\s*[:=]\s*(?![\"']?{placeholder}(?:[\"']|\b))"
        r"[\"']?[A-Za-z0-9_./+=:@-]{1,}"
    )
    credential_header = (
        r"\b(?:authorization|proxy-authorization|cookie|set-cookie|x-api-key|api-key)\s*:\s*"
        rf"(?!{placeholder}\b)[^\s,;]{{4,}}"
    )
    return [
        ("private-unix-user-path", re.compile(unix_prefix)),
        ("private-windows-user-path", re.compile(windows_prefix, re.IGNORECASE)),
        ("private-key-header", re.compile(key_header_pattern)),
        ("github-token", re.compile(github_token)),
        ("aws-access-key", re.compile("AK" + r"IA[0-9A-Z]{16}")),
        ("openai-style-token", re.compile(openai_token)),
        ("slack-token", re.compile(slack_token)),
        ("stripe-live-token", re.compile(stripe_token)),
        ("gitlab-token", re.compile(gitlab_token)),
        ("npm-token", re.compile(npm_token)),
        ("pypi-token", re.compile(pypi_token)),
        ("google-api-key", re.compile(google_api_key)),
        ("jwt-token", re.compile(jwt_token)),
        ("credential-assignment", re.compile(credential_assignment, re.IGNORECASE)),
        ("credential-header", re.compile(credential_header, re.IGNORECASE)),
        ("personal-phone", re.compile(phone)),
        ("street-address", re.compile(street_address, re.IGNORECASE)),
        ("meeting-url", re.compile(meeting_url, re.IGNORECASE)),
        ("mounted-volume-path", re.compile(mounted_path)),
        ("machine-hostname", re.compile(machine_name, re.IGNORECASE)),
        ("private-repository-url", re.compile(private_repository, re.IGNORECASE)),
        ("provider-conversation-url", re.compile(provider_conversation, re.IGNORECASE)),
        ("provider-session-id", re.compile(provider_session, re.IGNORECASE)),
        ("sensitive-json-field", re.compile(sensitive_json_field, re.IGNORECASE)),
    ]


def load_private_denylist(path: Path, release_root: Path) -> list[PrivateTerm]:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        raise ValueError("private denylist must be an absolute path")
    _reject_symlink_components(expanded)
    resolved = expanded.resolve(strict=True)
    root = release_root.expanduser().resolve(strict=True)
    if resolved == root or root in resolved.parents:
        raise ValueError("private denylist must be outside release root")
    encoded = _read_bounded_regular_file(expanded, maximum=65536)
    document = json.loads(encoded.decode("utf-8"))
    if not isinstance(document, dict) or set(document) != {"schemaVersion", "terms"}:
        raise ValueError("private denylist shape is invalid")
    if document["schemaVersion"] != SCHEMA_VERSION or not isinstance(document["terms"], list):
        raise ValueError("private denylist schema is invalid")
    if not document["terms"] or len(document["terms"]) > 256:
        raise ValueError("private denylist must contain between 1 and 256 terms")
    terms: list[PrivateTerm] = []
    ids: set[str] = set()
    for item in document["terms"]:
        if not isinstance(item, dict) or set(item) != {"id", "value", "caseSensitive"}:
            raise ValueError("private denylist term shape is invalid")
        finding_id = item["id"]
        value = item["value"]
        case_sensitive = item["caseSensitive"]
        if not isinstance(finding_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", finding_id):
            raise ValueError("private denylist id is invalid")
        if finding_id in ids:
            raise ValueError("private denylist ids must be unique")
        if not isinstance(value, str) or len(value) < 4 or len(value) > 200 or "\n" in value or "\x00" in value:
            raise ValueError("private denylist value is invalid")
        if type(case_sensitive) is not bool:
            raise ValueError("private denylist caseSensitive must be boolean")
        ids.add(finding_id)
        terms.append(PrivateTerm(finding_id, value, case_sensitive))
    return terms


def _reject_symlink_components(path: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise ValueError("private denylist path must not contain symlinks")
        if current == current.parent:
            break
        current = current.parent


def _read_bounded_regular_file(path: Path, *, maximum: int) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
            raise ValueError("file must be a bounded regular file")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > maximum:
            raise ValueError("file must be a bounded regular file")
        return data
    finally:
        os.close(descriptor)


def _is_private_denylist_document(text: str) -> bool:
    try:
        document = json.loads(text.lstrip("\ufeff"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return isinstance(document, dict) and document.get("schemaVersion") == SCHEMA_VERSION


def run_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="plzdo-leak-self-test-") as temporary:
        base = Path(temporary).resolve()
        release = base / "release"
        release.mkdir()
        (release / ".gitignore").write_text(".env\n", encoding="utf-8")
        cases: dict[str, object] = {
            ".env.staging": "",
            ".envrc": "",
            ".npmrc": "",
            ".pypirc": "",
            "backup-token.txt": "",
            "cookies.json": "{}\n",
            "private-path.txt": "/" + "Users/" + "fixture-user/project\n",
            "real-email.txt": "person@" + "not-example.invalid\n",
            "private-key.txt": "-----" + "BEGIN " + "PRIVATE " + "KEY" + "-----\n",
            "provider-key.txt": "sk" + "-abcdefghijklmnop1234\n",
            "github-key.txt": "gh" + "p_" + ("a" * 36) + "\n",
            "aws-key.txt": "AK" + "IA" + ("A" * 16) + "\n",
            "google-key.txt": "AI" + "za" + ("A" * 35) + "\n",
            "slack-key.txt": "xox" + "b-1234567890-abcdefghijklmnop\n",
            "stripe-key.txt": "sk_" + "live_abcdefghijklmnop1234\n",
            "gitlab-key.txt": "glpat" + "-abcdefghijklmnopqrstuv\n",
            "npm-key.txt": "npm_" + "abcdefghijklmnopqrstuvwxyz1234\n",
            "pypi-key.txt": "pypi-" + "AgEIcHlwaS5vcmc" + "abcdefghijklmnopqrstuv\n",
            "short-jwt.txt": "eyJ" + "hbGciOiJub25lIn0.e30.x\n",
            "password-assignment.txt": "pass" + "word = actual-fixture-value\n",
            "secret-assignment.txt": "client_" + "sec" + "ret: actual-fixture-value\n",
            "authorization-header.txt": "Author" + "ization: Bearer-fixture-value\n",
            "cookie-header.txt": "Coo" + "kie: session-fixture-value\n",
            "api-header.txt": "X-API" + "-Key: fixture-value\n",
            "binary.bin": bytes([255, 254, 253]),
            "media.png": b"synthetic-ascii-media",
            "phone.txt": "+1 " + "202 " + "555 " + "0147\n",
            "address.txt": "1600 Synthetic " + "Example Street\n",
            "meeting.txt": "https://meet." + "google.com/abc-defg-hij\n",
            "mounted-path.txt": "/" + "Volumes/SyntheticDrive/project\n",
            "machine.txt": "devbox-01." + "local\n",
            "private-repository.txt": "git@" + "github.com:private-org/private-repo.git\n",
            "private-https-repository.txt": "https://github." + "com/private-org/private-repo.git\n",
            "credentialed-repository.txt": "https://fixture:" + "credential@" + "example.invalid/org/repo.git\n",
            "provider-conversation.txt": "https://chatgpt." + "com/c/synthetic-session\n",
            "provider-session.txt": "session_id=" + "123e4567-e89b-12d3-a456-426614174000\n",
            "service-account.txt": '{"client_' + 'secret":"actual-fixture-value"}\n',
        }
        for name, value in cases.items():
            target = release / name
            if isinstance(value, bytes):
                target.write_bytes(value)
            else:
                target.write_text(str(value), encoding="utf-8")
            findings, _ = scan_root(release, [])
            if not findings:
                print(f"self-test failed: synthetic case was not rejected: {name}", file=sys.stderr)
                return 1
            target.unlink()

        path_findings, _ = scan_release_path("nested/private-token-backup.txt", [])
        if not path_findings or any(finding.path != "<sensitive-path>" for finding in path_findings):
            print("self-test failed: sensitive path evidence was not redacted", file=sys.stderr)
            return 1
        private_path_value = "person@" + "not-example.invalid"
        private_path_findings, _ = scan_release_path(f"nested/{private_path_value}.txt", [])
        rendered_private_path = "\n".join(f"{finding.path}:{finding.rule}" for finding in private_path_findings)
        if "real-email" not in rendered_private_path or private_path_value in rendered_private_path:
            print("self-test failed: matched private path value entered evidence", file=sys.stderr)
            return 1

        false_positive_findings, _ = scan_text(
            "scanner-source.py",
            "blocked_names = {'.env.local', '.env.production'}\n",
            [],
        )
        if any(finding.rule == "machine-hostname" for finding in false_positive_findings):
            print("self-test failed: environment filenames matched hostnames", file=sys.stderr)
            return 1

        nested_repository = release / "nested" / ".git"
        nested_repository.mkdir(parents=True)
        findings, _ = scan_root(release, [])
        if not any(finding.rule == "blocked-directory-kind" for finding in findings):
            print("self-test failed: nested Git metadata was not rejected", file=sys.stderr)
            return 1
        nested_repository.rmdir()
        nested_repository.parent.rmdir()

        fifo = release / "synthetic-pipe"
        os.mkfifo(fifo)
        findings, _ = scan_root(release, [])
        if not any(finding.path == "synthetic-pipe" and finding.rule == "special-release-file" for finding in findings):
            print("self-test failed: special file was not rejected", file=sys.stderr)
            return 1
        fifo.unlink()

        private_value = "PrivateAliasFixture"
        denylist = base / "private-denylist.json"
        denylist.write_text(
            json.dumps(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "terms": [{"id": "private-alias-fixture", "value": private_value, "caseSensitive": False}],
                }
            ),
            encoding="utf-8",
        )
        (release / "source.txt").write_text(f"mentions {private_value}\n", encoding="utf-8")
        terms = load_private_denylist(denylist, release)
        findings, _ = scan_root(release, terms)
        rendered = "\n".join(f"{finding.path}:{finding.rule}" for finding in findings)
        if "private-term:private-alias-fixture" not in rendered or private_value in rendered:
            print("self-test failed: private denylist evidence was unsafe", file=sys.stderr)
            return 1

        in_tree = release / "denylist.json"
        in_tree.write_text(denylist.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            load_private_denylist(in_tree, release)
        except ValueError:
            pass
        else:
            print("self-test failed: in-tree private denylist was accepted", file=sys.stderr)
            return 1

        named_private_file = release / "private-denylist-local.json"
        named_private_file.write_text("{}\n", encoding="utf-8")
        findings, _ = scan_root(release, [])
        if not any(finding.rule == "blocked-file-kind" for finding in findings):
            print("self-test failed: in-tree private denylist filename was not blocked", file=sys.stderr)
            return 1

        named_private_file.unlink()
        disguised_private_file = release / "aliases.txt"
        disguised_private_file.write_text(denylist.read_text(encoding="utf-8"), encoding="utf-8")
        findings, _ = scan_root(release, [])
        if not any(finding.path == "aliases.txt" and finding.rule == "private-denylist-content" for finding in findings):
            print("self-test failed: renamed private denylist content was not blocked", file=sys.stderr)
            return 1

    print("release leak scanner self-test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
