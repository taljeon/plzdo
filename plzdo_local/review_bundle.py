from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from .validation import ValidationError, reject_sensitive_text, require_exact_keys, require_object, require_string


MANIFEST_SCHEMA_VERSION = "plzdo-local.review-manifest.v1"
BUNDLE_SCHEMA_VERSION = "plzdo-local.review-bundle.v1"
IMPORT_SCHEMA_VERSION = "plzdo-local.review-import.v1"
MAX_FILES = 24
MAX_FILE_BYTES = 64 * 1024
MAX_TOTAL_SOURCE_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_BUNDLE_BYTES = 1024 * 1024

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PRIVATE_POSIX = re.compile(r"/(?:Users|home)/[^/\s]+")
_PRIVATE_WINDOWS = re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+")
_QUOTED_VALUE = (
    r'"(?:\\.|[^"\\\r\n])*"'
    r"|'(?:\\.|[^'\\\r\n])*'"
    r"|`(?:\\.|[^`\\\r\n])*`"
)
_SENSITIVE_HEADER = re.compile(
    r"(?i)(?P<prefix>(?<![A-Za-z0-9_-])(?:[\"']?)"
    r"(?:proxy-authorization|authorization|cookie|set-cookie|x-api-key|x-auth-token)"
    r"(?:[\"']?)[ \t]*(?:=|:)[ \t]*)"
    r"(?P<value>(?!\[REDACTED\])(?:" + _QUOTED_VALUE + r"|[^\s\r\n][^\r\n]*))"
)
_BRACKET_HEADER = re.compile(
    r"(?i)(?P<prefix>\[[ \t]*[\"']"
    r"(?:proxy-authorization|authorization|cookie|set-cookie|x-api-key|x-auth-token)"
    r"[\"'][ \t]*\][ \t]*(?:=|:)[ \t]*)"
    r"(?P<value>(?!\[REDACTED\])(?:" + _QUOTED_VALUE + r"|[^\s\r\n][^\r\n]*))"
)
_SET_REQUEST_HEADER = re.compile(
    r"(?i)(?P<prefix>\bsetRequestHeader[ \t]*\([ \t]*[\"']"
    r"(?:proxy-authorization|authorization|cookie|set-cookie|x-api-key|x-auth-token)"
    r"[\"'][ \t]*,[ \t]*)"
    r"(?P<value>(?!\[REDACTED\])(?:" + _QUOTED_VALUE + r"|[^\s\r\n)][^\r\n)]*))"
)
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN (?P<label>(?:(?:RSA|EC|DSA|OPENSSH|ENCRYPTED) )?PRIVATE KEY)-----"
    r".*?-----END (?P=label)-----",
    re.DOTALL,
)
_PRIVATE_KEY_BOUNDARY = re.compile(
    r"-----BEGIN (?:(?:RSA|EC|DSA|OPENSSH|ENCRYPTED) )?PRIVATE KEY-----"
    r"|-----END (?:(?:RSA|EC|DSA|OPENSSH|ENCRYPTED) )?PRIVATE KEY-----"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?P<prefix>(?<![A-Za-z0-9_$])(?:[\"']?)[A-Za-z0-9_.$-]*"
    r"(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|"
    r"refresh[_-]?token|token|private[_-]?key|secret[_-]?access[_-]?key|"
    r"secret(?:[_-]?key)?|password|passwd|pwd|credentials?|"
    r"database[_-]?url)(?:[\"']?)[ \t]*(?:=|:)[ \t]*)"
    r"(?P<value>(?!\[REDACTED-CREDENTIAL\])(?:"
    + _QUOTED_VALUE
    + r"|[^\s,;}\]]+))"
)
_JWT = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]{2,}"
    r"(?![A-Za-z0-9_-])"
)
_AUTH_SCHEME = re.compile(r"(?i)\b(?:basic|bearer)[ \t]+[A-Za-z0-9._~+/-]{4,}=*")
_TOKEN_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9_-])" + "sk" + r"-(?:proj-|svcacct-)?[A-Za-z0-9_-]{16,}(?![A-Za-z0-9_-])"),
    re.compile(r"(?<![A-Za-z0-9_-])" + "sk" + r"-ant-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\b(?:AKIA|ASIA|AIDA|AROA|AIPA|ANPA|ANVA)[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"(?<![A-Za-z0-9_-])xox[baprs]-[A-Za-z0-9-]{10,}(?![A-Za-z0-9_-])"),
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
)
_SENSITIVE_COMPONENTS = {
    ".aws",
    ".azure",
    ".git",
    ".kube",
    ".gnupg",
    ".ssh",
    "auth",
    "cookies",
    "credentials",
    "secrets",
}
_SENSITIVE_FILENAMES = {
    ".git-credentials",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".kubeconfig",
    "application_default_credentials.json",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "kubeconfig",
    "login data",
    "service-account.json",
    "service_account.json",
}
_SENSITIVE_FILE_SUFFIXES = {
    ".db",
    ".key",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".sqlite",
    ".sqlite3",
}
_BACKUP_SUFFIXES = (
    ".backup",
    ".bak",
    ".bkp",
    ".copy",
    ".disabled",
    ".old",
    ".orig",
    ".save",
    ".swp",
    ".tmp",
    "~",
)
_PRIVATE_KEY_FILENAME = re.compile(r"^id_(?:rsa|dsa|ecdsa|ed25519)(?:[._-].*)?$")
_TOKEN_FILENAME = re.compile(
    r"^(?:\.?token|(?:access|auth|refresh)[_-]?token)(?:[._-].*)?$",
    re.IGNORECASE,
)
_CREDENTIAL_FILENAME = re.compile(
    r"^(?:.*[_-])?credentials(?:[._-].*)?$"
    r"|^(?:service[_-]?account|application[_-]?default[_-]?credentials)(?:[._-].*)?$",
    re.IGNORECASE,
)
_BACKUP_TRAILER = re.compile(
    r"(?:[._-](?:backup|bak|bkp|copy|disabled|old|orig|save|swp|tmp)(?:[._-][0-9]{1,14})?"
    r"|[._-][0-9]{1,14}|~)$",
    re.IGNORECASE,
)


class ReviewBundleError(ValueError):
    pass


def build_manifest(*, purpose: str, files: list[str]) -> dict[str, Any]:
    manifest = {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "purpose": purpose,
        "files": list(files),
    }
    validate_manifest(manifest)
    return manifest


def validate_manifest(value: Any) -> None:
    try:
        manifest = require_object(value, label="review manifest")
        require_exact_keys(manifest, {"schemaVersion", "purpose", "files"}, label="review manifest")
        if manifest["schemaVersion"] != MANIFEST_SCHEMA_VERSION:
            raise ReviewBundleError("review manifest schema is invalid")
        purpose = require_string(manifest["purpose"], label="review manifest purpose", maximum=500).strip()
        if not purpose:
            raise ReviewBundleError("review manifest purpose must not be blank")
        reject_sensitive_text(purpose, label="review manifest purpose")
        if sanitize_review_text(purpose)[1]:
            raise ReviewBundleError("review manifest purpose contains a sensitive shape")
        files = manifest["files"]
        if not isinstance(files, list) or not files or len(files) > MAX_FILES:
            raise ReviewBundleError(f"review manifest files must contain 1 to {MAX_FILES} paths")
        checked = [_relative_path(item) for item in files]
        if checked != sorted(set(checked)):
            raise ReviewBundleError("review manifest files must be sorted and unique")
    except ValidationError as exc:
        raise ReviewBundleError(str(exc)) from exc


def prepare_bundle(project_root: Path, manifest: Any, *, created_at: str) -> dict[str, Any]:
    validate_manifest(manifest)
    root_fd = _open_root(project_root)
    try:
        total = 0
        entries: list[dict[str, Any]] = []
        contents: dict[str, str] = {}
        redaction_count = 0
        for relative in manifest["files"]:
            raw = _read_relative(root_fd, relative)
            total += len(raw)
            if total > MAX_TOTAL_SOURCE_BYTES:
                raise ReviewBundleError(f"review source set exceeds {MAX_TOTAL_SOURCE_BYTES} bytes")
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ReviewBundleError(f"review source must be UTF-8: {relative}") from exc
            sanitized, count = sanitize_review_text(text)
            encoded = sanitized.encode("utf-8")
            entries.append(
                {
                    "path": relative,
                    "sourceBytes": len(raw),
                    "sourceSha256": hashlib.sha256(raw).hexdigest(),
                    "sanitizedBytes": len(encoded),
                    "sanitizedSha256": hashlib.sha256(encoded).hexdigest(),
                    "redactions": count,
                }
            )
            contents[relative] = sanitized
            redaction_count += count
    finally:
        os.close(root_fd)
    bundle = {
        "schemaVersion": BUNDLE_SCHEMA_VERSION,
        "createdAt": created_at,
        "purpose": manifest["purpose"],
        "sourceOfTruth": False,
        "notInstructions": True,
        "toolAuthority": False,
        "egressPerformed": False,
        "redactionCount": redaction_count,
        "manifest": entries,
        "files": contents,
    }
    validate_bundle(bundle)
    return bundle


def validate_bundle(value: Any) -> None:
    bundle = require_object(value, label="review bundle")
    require_exact_keys(
        bundle,
        {
            "schemaVersion",
            "createdAt",
            "purpose",
            "sourceOfTruth",
            "notInstructions",
            "toolAuthority",
            "egressPerformed",
            "redactionCount",
            "manifest",
            "files",
        },
        label="review bundle",
    )
    if bundle["schemaVersion"] != BUNDLE_SCHEMA_VERSION:
        raise ReviewBundleError("review bundle schema is invalid")
    if (
        bundle["sourceOfTruth"] is not False
        or bundle["notInstructions"] is not True
        or bundle["toolAuthority"] is not False
        or bundle["egressPerformed"] is not False
    ):
        raise ReviewBundleError("review bundle authority or egress fields are invalid")
    require_string(bundle["createdAt"], label="review bundle createdAt", maximum=64)
    purpose = require_string(bundle["purpose"], label="review bundle purpose", maximum=500)
    reject_sensitive_text(purpose, label="review bundle purpose")
    if sanitize_review_text(purpose)[1]:
        raise ReviewBundleError("review bundle purpose contains a sensitive shape")
    if type(bundle["redactionCount"]) is not int or bundle["redactionCount"] < 0:
        raise ReviewBundleError("review bundle redactionCount must be a non-negative integer")
    entries = bundle["manifest"]
    files = require_object(bundle["files"], label="review bundle files")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_FILES:
        raise ReviewBundleError("review bundle manifest size is invalid")
    paths: list[str] = []
    total_redactions = 0
    for index, entry_value in enumerate(entries):
        entry = require_object(entry_value, label=f"review bundle manifest[{index}]")
        require_exact_keys(
            entry,
            {
                "path",
                "sourceBytes",
                "sourceSha256",
                "sanitizedBytes",
                "sanitizedSha256",
                "redactions",
            },
            label=f"review bundle manifest[{index}]",
        )
        path = _relative_path(entry["path"])
        paths.append(path)
        for field in ("sourceBytes", "sanitizedBytes", "redactions"):
            if type(entry[field]) is not int or entry[field] < 0:
                raise ReviewBundleError(f"review bundle {field} must be a non-negative integer")
        for field in ("sourceSha256", "sanitizedSha256"):
            if not isinstance(entry[field], str) or _SHA256.fullmatch(entry[field]) is None:
                raise ReviewBundleError(f"review bundle {field} must be SHA-256")
        content = files.get(path)
        if not isinstance(content, str):
            raise ReviewBundleError(f"review bundle content is missing: {path}")
        encoded = content.encode("utf-8")
        if len(encoded) != entry["sanitizedBytes"] or hashlib.sha256(encoded).hexdigest() != entry["sanitizedSha256"]:
            raise ReviewBundleError(f"review bundle sanitized evidence drifted: {path}")
        if sanitize_review_text(content)[1] != 0:
            raise ReviewBundleError(f"review bundle contains an unredacted sensitive shape: {path}")
        total_redactions += entry["redactions"]
    if paths != sorted(set(paths)) or set(paths) != set(files):
        raise ReviewBundleError("review bundle path set is invalid")
    if total_redactions != bundle["redactionCount"]:
        raise ReviewBundleError("review bundle redaction count is inconsistent")
    _bounded_json(value, maximum=MAX_BUNDLE_BYTES, label="review bundle")


def import_response(bundle: Any, response: bytes, *, imported_at: str) -> dict[str, Any]:
    validate_bundle(bundle)
    if len(response) > MAX_RESPONSE_BYTES:
        raise ReviewBundleError(f"review response exceeds {MAX_RESPONSE_BYTES} bytes")
    try:
        decoded = response.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReviewBundleError("review response must be UTF-8") from exc
    sanitized, redactions = sanitize_review_text(decoded)
    bundle_bytes = _canonical_json(bundle)
    result = {
        "schemaVersion": IMPORT_SCHEMA_VERSION,
        "importedAt": imported_at,
        "bundleSha256": hashlib.sha256(bundle_bytes).hexdigest(),
        "responseSha256": hashlib.sha256(response).hexdigest(),
        "sanitizedResponseSha256": hashlib.sha256(sanitized.encode("utf-8")).hexdigest(),
        "redactionCount": redactions,
        "response": sanitized,
        "sourceOfTruth": False,
        "notInstructions": True,
        "toolAuthority": False,
    }
    validate_import(result)
    return result


def validate_import(value: Any) -> None:
    record = require_object(value, label="review import")
    require_exact_keys(
        record,
        {
            "schemaVersion",
            "importedAt",
            "bundleSha256",
            "responseSha256",
            "sanitizedResponseSha256",
            "redactionCount",
            "response",
            "sourceOfTruth",
            "notInstructions",
            "toolAuthority",
        },
        label="review import",
    )
    if record["schemaVersion"] != IMPORT_SCHEMA_VERSION:
        raise ReviewBundleError("review import schema is invalid")
    if record["sourceOfTruth"] is not False or record["notInstructions"] is not True or record["toolAuthority"] is not False:
        raise ReviewBundleError("review import authority fields are invalid")
    for field in ("bundleSha256", "responseSha256", "sanitizedResponseSha256"):
        if not isinstance(record[field], str) or _SHA256.fullmatch(record[field]) is None:
            raise ReviewBundleError(f"review import {field} must be SHA-256")
    response = require_string(
        record["response"],
        label="review import response",
        minimum=0,
        maximum=MAX_RESPONSE_BYTES,
    )
    if hashlib.sha256(response.encode("utf-8")).hexdigest() != record["sanitizedResponseSha256"]:
        raise ReviewBundleError("review import response digest drifted")
    if sanitize_review_text(response)[1] != 0:
        raise ReviewBundleError("review import contains an unredacted sensitive shape")
    if type(record["redactionCount"]) is not int or record["redactionCount"] < 0:
        raise ReviewBundleError("review import redactionCount is invalid")
    _bounded_json(record, maximum=MAX_BUNDLE_BYTES, label="review import")


def sanitize_review_text(text: str) -> tuple[str, int]:
    if not isinstance(text, str):
        raise ReviewBundleError("review text must be a string")
    if "\x00" in text:
        raise ReviewBundleError("review text contains NUL")
    output = text
    count = 0
    output, matches = _PRIVATE_KEY_BLOCK.subn("[REDACTED-PRIVATE-KEY]", output)
    count += matches
    if _PRIVATE_KEY_BOUNDARY.search(output):
        raise ReviewBundleError("review text contains an incomplete private-key block")
    replacements = (
        (_SECRET_ASSIGNMENT, lambda match: f"{match.group('prefix')}[REDACTED-CREDENTIAL]"),
        (_BRACKET_HEADER, lambda match: f"{match.group('prefix')}[REDACTED]"),
        (_SET_REQUEST_HEADER, lambda match: f"{match.group('prefix')}[REDACTED]"),
        (_SENSITIVE_HEADER, lambda match: f"{match.group('prefix')}[REDACTED]"),
        (_AUTH_SCHEME, lambda match: match.group(0).split(None, 1)[0] + " [REDACTED]"),
        (_JWT, lambda _: "[REDACTED-JWT]"),
        (_EMAIL, lambda _: "[REDACTED-EMAIL]"),
        (_PRIVATE_POSIX, lambda _: "<HOME>"),
        (_PRIVATE_WINDOWS, lambda _: "<HOME>"),
    )
    for pattern, replacement in replacements:
        output, matches = pattern.subn(replacement, output)
        count += matches
    for pattern in _TOKEN_PATTERNS:
        output, matches = pattern.subn("[REDACTED-CREDENTIAL]", output)
        count += matches
    return output, count


def _relative_path(value: Any) -> str:
    if not isinstance(value, str):
        raise ReviewBundleError("review file path must be a string")
    sensitive_reason = sensitive_path_reason(value)
    if sensitive_reason is not None:
        raise ReviewBundleError("review file path is sensitive: " + sensitive_reason)
    parsed = PurePosixPath(value)
    if (
        not value
        or parsed.is_absolute()
        or parsed.as_posix() != value
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ReviewBundleError("review file path must be canonical and project-relative")
    return value


def sensitive_path_reason(value: str) -> Optional[str]:
    """Return a stable reason for a high-confidence sensitive path shape."""

    if not isinstance(value, str):
        return "non-text-path"
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return "control-character"
    if _EMAIL.search(value):
        return "email-address"
    if (
        _JWT.search(value)
        or _AUTH_SCHEME.search(value)
        or _SECRET_ASSIGNMENT.search(value)
        or any(pattern.search(value) for pattern in _TOKEN_PATTERNS)
    ):
        return "credential-token"
    for raw_component in re.split(r"[/\\]", value):
        if not raw_component:
            continue
        component = _strip_backup_suffixes(raw_component.casefold())
        normalized = component.replace("_", "-")
        if component in _SENSITIVE_COMPONENTS or component in _SENSITIVE_FILENAMES:
            return "credential-store-name"
        if normalized in {"application-default-credentials.json", "service-account.json"}:
            return "credential-file-name"
        if component == ".envrc" or component == ".env" or component.startswith((".env.", ".env-", ".env_")):
            return "environment-file-name"
        if _PRIVATE_KEY_FILENAME.fullmatch(component):
            return "ssh-private-key-name"
        if _TOKEN_FILENAME.fullmatch(component) or _CREDENTIAL_FILENAME.fullmatch(component):
            return "credential-file-name"
        if component == "kubeconfig" or component.startswith(("kubeconfig.", "kubeconfig-", "kubeconfig_")):
            return "kubeconfig-name"
        if PurePosixPath(component).suffix in _SENSITIVE_FILE_SUFFIXES:
            return "sensitive-file-suffix"
    return None


def _strip_backup_suffixes(value: str) -> str:
    current = value
    while True:
        stripped = _BACKUP_TRAILER.sub("", current)
        if stripped != current:
            current = stripped
            continue
        matched = False
        for suffix in _BACKUP_SUFFIXES:
            if current.endswith(suffix) and len(current) > len(suffix):
                current = current[: -len(suffix)]
                matched = True
                break
        if not matched:
            return current


def _open_root(root: Path) -> int:
    if root.is_symlink():
        raise ReviewBundleError("review project root must not be a symlink")
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(root, flags)
    except OSError as exc:
        raise ReviewBundleError("review project root is unavailable") from exc
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ReviewBundleError("review project root must be a directory")
    return descriptor


def _read_relative(root_fd: int, relative: str) -> bytes:
    parts = PurePosixPath(_relative_path(relative)).parts
    parent_fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            flags = os.O_RDONLY
            if hasattr(os, "O_DIRECTORY"):
                flags |= os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                next_fd = os.open(part, flags, dir_fd=parent_fd)
            except OSError as exc:
                raise ReviewBundleError(f"review source parent is unsafe: {relative}") from exc
            os.close(parent_fd)
            parent_fd = next_fd
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        try:
            descriptor = os.open(parts[-1], flags, dir_fd=parent_fd)
        except OSError as exc:
            reason = "symlink" if exc.errno == errno.ELOOP else "unavailable"
            raise ReviewBundleError(f"review source is {reason}: {relative}") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ReviewBundleError(f"review source must be regular: {relative}")
            if metadata.st_size > MAX_FILE_BYTES:
                raise ReviewBundleError(f"review source exceeds {MAX_FILE_BYTES} bytes: {relative}")
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = os.read(descriptor, min(65536, MAX_FILE_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise ReviewBundleError(f"review source exceeds {MAX_FILE_BYTES} bytes: {relative}")
            return b"".join(chunks)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_fd)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReviewBundleError("review artifact must contain canonical JSON values") from exc


def _bounded_json(value: Any, *, maximum: int, label: str) -> None:
    if len(_canonical_json(value)) > maximum:
        raise ReviewBundleError(f"{label} exceeds {maximum} bytes")
