from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Optional, Union

from .validation import (
    ValidationError,
    reject_credential_shapes,
    reject_credential_shapes_deep,
)


SCHEMA_VERSION = "plzdo-local.context.v1"
CONTEXT_SCHEMA_VERSION = SCHEMA_VERSION
FRESHNESS_SCHEMA_VERSION = "plzdo-local.context-freshness.v1"

MODE_COMPACT = "compact"
MODE_FULL = "full"
CONTEXT_MODES = (MODE_COMPACT, MODE_FULL)

PROJECT_CONTROL_PATHS = (
    "AGENTS.md",
    "CHECKS.md",
    "TASKS/current.md",
    "docs/requirements.md",
    "docs/technical-design.md",
)
CONTROL_SOURCE_ALLOWLIST = PROJECT_CONTROL_PATHS

MAX_SOURCE_BYTES = 256 * 1024
MAX_TOTAL_SOURCE_BYTES = 1024 * 1024
MAX_SUMMARY_CHARS = 1200
MAX_SUMMARY_LINE_CHARS = 240
MAX_SUMMARY_LINES = 8
MAX_CONTEXT_BYTES = 8 * 1024 * 1024
MAX_PROJECT_BYTES = 32 * 1024
MAX_ROUTE_BYTES = 64 * 1024
MAX_FORMALIZATION_BYTES = 128 * 1024
MAX_STATE_SUMMARY_BYTES = 128 * 1024
MAX_CAPABILITY_INPUT_BYTES = 512 * 1024

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOP_LEVEL_KEYS = {
    "schemaVersion",
    "mode",
    "generatedAt",
    "authoritative",
    "localOnly",
    "sourceManifest",
    "controlText",
    "project",
    "route",
    "activeFormalization",
    "stateSummary",
    "capabilityDigest",
}
_SOURCE_KEYS = {"path", "bytes", "sha256", "summary", "summaryTruncated"}
_PROJECTION_KEYS = {"authoritative", "value"}
_CAPABILITY_DIGEST_KEYS = {"authoritative", "algorithm", "sha256", "inputBytes"}


class ContextError(ValueError):
    """Base error for context-pack operations."""

    def __init__(self, message: str, *, code: str = "context-error", path: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.path = path


class ContextValidationError(ContextError):
    """Raised when a context pack or caller projection is malformed."""


class ContextSourceError(ContextError):
    """Raised when a fixed control source cannot be read safely."""


class ContextStaleError(ContextError):
    """Raised when a pack cannot be proved fresh against current sources."""

    def __init__(self, reasons: list[dict[str, str]]):
        codes = ", ".join(item["code"] for item in reasons) or "unknown"
        super().__init__(
            f"context pack is not fresh: {codes}",
            code="context-stale",
        )
        self.reasons = tuple(dict(item) for item in reasons)


def generate_context_pack(
    project_root: Union[str, os.PathLike[str]],
    *,
    mode: str = MODE_COMPACT,
    timestamp: Optional[str] = None,
    project: Any = None,
    route: Any = None,
    active_formalization: Any = None,
    state_summary: Any = None,
    capabilities: Any = None,
) -> dict[str, Any]:
    """Generate compact or full context from one bounded source snapshot."""

    selected_mode = _require_mode(mode)
    generated_at = _normalize_timestamp(timestamp)
    sources = _read_control_sources(project_root)

    manifest: list[dict[str, Any]] = []
    control_text: Optional[dict[str, str]] = {} if selected_mode == MODE_FULL else None
    for source in sources:
        summary, truncated = _summarize(source["text"])
        manifest.append(
            {
                "path": source["path"],
                "bytes": len(source["content"]),
                "sha256": hashlib.sha256(source["content"]).hexdigest(),
                "summary": summary,
                "summaryTruncated": truncated,
            }
        )
        if control_text is not None:
            control_text[source["path"]] = source["text"]

    pack = {
        "schemaVersion": SCHEMA_VERSION,
        "mode": selected_mode,
        "generatedAt": generated_at,
        "authoritative": False,
        "localOnly": True,
        "sourceManifest": manifest,
        "controlText": control_text,
        "project": _projection(project, label="project", maximum=MAX_PROJECT_BYTES),
        "route": _projection(route, label="route", maximum=MAX_ROUTE_BYTES),
        "activeFormalization": _projection(
            active_formalization,
            label="active formalization",
            maximum=MAX_FORMALIZATION_BYTES,
        ),
        "stateSummary": _projection(
            state_summary,
            label="state summary",
            maximum=MAX_STATE_SUMMARY_BYTES,
        ),
        "capabilityDigest": _capability_digest(capabilities),
    }
    validate_context_pack(pack)
    return pack


def render_context_pack(
    project_root: Union[str, os.PathLike[str]],
    *,
    mode: str = MODE_COMPACT,
    timestamp: Optional[str] = None,
    project: Any = None,
    route: Any = None,
    active_formalization: Any = None,
    state_summary: Any = None,
    capabilities: Any = None,
) -> bytes:
    """Return deterministic canonical JSON bytes without writing them."""

    pack = generate_context_pack(
        project_root,
        mode=mode,
        timestamp=timestamp,
        project=project,
        route=route,
        active_formalization=active_formalization,
        state_summary=state_summary,
        capabilities=capabilities,
    )
    return serialize_context_pack(pack)


def serialize_context_pack(value: Any) -> bytes:
    """Serialize a validated pack to canonical newline-terminated JSON."""

    validate_context_pack(value)
    payload = _canonical_json_bytes(value) + b"\n"
    if len(payload) > MAX_CONTEXT_BYTES:
        raise ContextValidationError(
            f"context pack exceeds {MAX_CONTEXT_BYTES} bytes",
            code="context-too-large",
        )
    return payload


def parse_context_pack(payload: Union[str, bytes, bytearray]) -> dict[str, Any]:
    """Parse bounded JSON, rejecting duplicate keys and non-finite numbers."""

    if isinstance(payload, str):
        encoded = payload.encode("utf-8")
    elif isinstance(payload, (bytes, bytearray)):
        encoded = bytes(payload)
    else:
        raise ContextValidationError(
            "context payload must be text or bytes",
            code="context-malformed",
        )
    if len(encoded) > MAX_CONTEXT_BYTES:
        raise ContextValidationError(
            f"context payload exceeds {MAX_CONTEXT_BYTES} bytes",
            code="context-too-large",
        )
    try:
        text = encoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContextValidationError(
            "context payload must be UTF-8",
            code="context-malformed",
        ) from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, ContextValidationError) as exc:
        if isinstance(exc, ContextValidationError):
            raise
        raise ContextValidationError(
            "context payload is not valid JSON",
            code="context-malformed",
        ) from exc
    validate_context_pack(value)
    return value


def validate_context_pack(value: Any) -> None:
    """Validate the exact in-memory v1 shape and compact/full invariant."""

    pack = _require_object(value, label="context pack")
    _require_exact_keys(pack, _TOP_LEVEL_KEYS, label="context pack")
    if pack["schemaVersion"] != SCHEMA_VERSION:
        raise ContextValidationError(
            f"context pack.schemaVersion must be {SCHEMA_VERSION}",
            code="context-schema-mismatch",
        )
    mode = _require_mode(pack["mode"])
    if _normalize_timestamp(pack["generatedAt"]) != pack["generatedAt"]:
        raise ContextValidationError(
            "context pack.generatedAt must be canonical UTC RFC 3339",
            code="context-malformed",
        )
    if pack["authoritative"] is not False:
        raise ContextValidationError(
            "context pack must be explicitly non-authoritative",
            code="context-authority-invalid",
        )
    if pack["localOnly"] is not True:
        raise ContextValidationError(
            "context pack.localOnly must be true",
            code="context-local-only-invalid",
        )

    manifest = pack["sourceManifest"]
    if not isinstance(manifest, list) or len(manifest) != len(PROJECT_CONTROL_PATHS):
        raise ContextValidationError(
            "context pack.sourceManifest must contain the fixed control source set",
            code="context-source-set-invalid",
        )
    total = 0
    for index, expected_path in enumerate(PROJECT_CONTROL_PATHS):
        entry = _require_object(manifest[index], label=f"sourceManifest[{index}]")
        _require_exact_keys(entry, _SOURCE_KEYS, label=f"sourceManifest[{index}]")
        path = validate_source_path(entry["path"])
        if path != expected_path:
            raise ContextValidationError(
                "context pack source manifest order or path is invalid",
                code="context-source-set-invalid",
                path=path,
            )
        byte_count = _require_int(
            entry["bytes"],
            label=f"sourceManifest[{index}].bytes",
            minimum=1,
            maximum=MAX_SOURCE_BYTES,
        )
        total += byte_count
        _require_sha256(entry["sha256"], label=f"sourceManifest[{index}].sha256")
        summary = _require_text(
            entry["summary"],
            label=f"sourceManifest[{index}].summary",
            maximum=MAX_SUMMARY_CHARS,
            allow_empty=True,
            single_line=True,
        )
        _reject_sensitive_value(summary, label=f"sourceManifest[{index}].summary")
        _require_bool(
            entry["summaryTruncated"],
            label=f"sourceManifest[{index}].summaryTruncated",
        )
    if total > MAX_TOTAL_SOURCE_BYTES:
        raise ContextValidationError(
            f"context source manifest exceeds {MAX_TOTAL_SOURCE_BYTES} bytes",
            code="context-source-set-too-large",
        )

    control_text = pack["controlText"]
    if mode == MODE_COMPACT:
        if control_text is not None:
            raise ContextValidationError(
                "compact context must not contain control text",
                code="context-mode-shape-invalid",
            )
    else:
        controls = _require_object(control_text, label="context pack.controlText")
        _require_exact_keys(controls, set(PROJECT_CONTROL_PATHS), label="context pack.controlText")
        for index, path in enumerate(PROJECT_CONTROL_PATHS):
            text = _require_text(
                controls[path],
                label=f"context pack.controlText[{path}]",
                maximum=MAX_SOURCE_BYTES,
                allow_empty=False,
            )
            _reject_sensitive_value(text, label=f"context pack.controlText[{path}]")
            try:
                content = text.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ContextValidationError(
                    f"context pack control text is not valid UTF-8: {path}",
                    code="context-malformed",
                    path=path,
                ) from exc
            entry = manifest[index]
            if len(content) != entry["bytes"] or hashlib.sha256(content).hexdigest() != entry["sha256"]:
                raise ContextValidationError(
                    "full control text does not match its source manifest",
                    code="context-manifest-invalid",
                    path=path,
                )
            summary, truncated = _summarize(text)
            if summary != entry["summary"] or truncated != entry["summaryTruncated"]:
                raise ContextValidationError(
                    "full control text summary does not match its source manifest",
                    code="context-manifest-invalid",
                    path=path,
                )

    _validate_projection(pack["project"], label="context pack.project", maximum=MAX_PROJECT_BYTES)
    _validate_projection(pack["route"], label="context pack.route", maximum=MAX_ROUTE_BYTES)
    _validate_projection(
        pack["activeFormalization"],
        label="context pack.activeFormalization",
        maximum=MAX_FORMALIZATION_BYTES,
    )
    _validate_projection(
        pack["stateSummary"],
        label="context pack.stateSummary",
        maximum=MAX_STATE_SUMMARY_BYTES,
    )
    _validate_capability_digest(pack["capabilityDigest"])

    try:
        size = len(_canonical_json_bytes(pack))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ContextValidationError(
            "context pack must contain only finite JSON values",
            code="context-malformed",
        ) from exc
    if size > MAX_CONTEXT_BYTES:
        raise ContextValidationError(
            f"context pack exceeds {MAX_CONTEXT_BYTES} bytes",
            code="context-too-large",
        )


def freshness_report(
    value: Union[dict[str, Any], str, bytes, bytearray],
    project_root: Union[str, os.PathLike[str]],
) -> dict[str, Any]:
    """Recompute current source evidence and return a fail-closed report."""

    try:
        pack = _coerce_context_pack(value)
        sources = _read_control_sources(project_root)
        for index, source in enumerate(sources):
            expected = pack["sourceManifest"][index]
            content = source["content"]
            actual_sha256 = hashlib.sha256(content).hexdigest()
            if len(content) != expected["bytes"] or actual_sha256 != expected["sha256"]:
                raise ContextSourceError(
                    f"control source drifted: {source['path']}",
                    code="context-source-drift",
                    path=source["path"],
                )
            summary, truncated = _summarize(source["text"])
            if summary != expected["summary"] or truncated != expected["summaryTruncated"]:
                raise ContextSourceError(
                    f"control source summary drifted: {source['path']}",
                    code="context-summary-drift",
                    path=source["path"],
                )
            if pack["mode"] == MODE_FULL and pack["controlText"][source["path"]] != source["text"]:
                raise ContextSourceError(
                    f"full control source drifted: {source['path']}",
                    code="context-control-text-drift",
                    path=source["path"],
                )
    except ContextError as exc:
        reason = {"code": exc.code, "message": str(exc)}
        if exc.path is not None:
            reason["path"] = exc.path
        return {
            "schemaVersion": FRESHNESS_SCHEMA_VERSION,
            "status": "stale",
            "sourceCount": 0,
            "reasons": [reason],
        }
    return {
        "schemaVersion": FRESHNESS_SCHEMA_VERSION,
        "status": "fresh",
        "sourceCount": len(PROJECT_CONTROL_PATHS),
        "reasons": [],
    }


def check_context_pack(
    value: Union[dict[str, Any], str, bytes, bytearray],
    project_root: Union[str, os.PathLike[str]],
) -> dict[str, Any]:
    """Require freshness, raising ContextStaleError when proof fails."""

    report = freshness_report(value, project_root)
    if report["status"] != "fresh":
        raise ContextStaleError(report["reasons"])
    return report


def validate_source_path(path: Any) -> str:
    """Accept only the fixed project-control allowlist."""

    if not isinstance(path, str) or path not in PROJECT_CONTROL_PATHS:
        raise ContextValidationError(
            "context source path is not in the fixed project-control allowlist",
            code="context-source-path-not-allowed",
        )
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or parsed.as_posix() != path or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ContextValidationError(
            "context source path is not canonical",
            code="context-source-path-not-allowed",
            path=path,
        )
    return path


def _read_control_sources(project_root: Union[str, os.PathLike[str]]) -> list[dict[str, Any]]:
    root_fd = _open_root_descriptor(project_root)
    try:
        root_identity = _file_snapshot(os.fstat(root_fd))
        sources: list[dict[str, Any]] = []
        total = 0
        for relative in PROJECT_CONTROL_PATHS:
            content, path_identity = _read_relative_regular_file(
                root_fd,
                relative,
                maximum=MAX_SOURCE_BYTES,
            )
            total += len(content)
            if total > MAX_TOTAL_SOURCE_BYTES:
                raise ContextSourceError(
                    f"control sources exceed {MAX_TOTAL_SOURCE_BYTES} bytes",
                    code="context-source-set-too-large",
                )
            text = _decode_control_text(content, path=relative)
            _reject_sensitive_source_text(text, path=relative)
            sources.append(
                {
                    "path": relative,
                    "content": content,
                    "text": text,
                    "pathIdentity": path_identity,
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )

        _verify_root_identity(project_root, root_fd, root_identity)
        for source in sources:
            content, path_identity = _read_relative_regular_file(
                root_fd,
                source["path"],
                maximum=MAX_SOURCE_BYTES,
            )
            digest = hashlib.sha256(content).hexdigest()
            if (
                path_identity != source["pathIdentity"]
                or len(content) != len(source["content"])
                or digest != source["sha256"]
            ):
                raise ContextSourceError(
                    f"control source changed during context generation: {source['path']}",
                    code="context-source-raced",
                    path=source["path"],
                )
        _verify_root_identity(project_root, root_fd, root_identity)
        return [
            {"path": source["path"], "content": source["content"], "text": source["text"]}
            for source in sources
        ]
    finally:
        os.close(root_fd)


def _open_root_descriptor(project_root: Union[str, os.PathLike[str]]) -> int:
    _require_safe_open_support()
    try:
        root_path = os.fspath(project_root)
    except TypeError as exc:
        raise ContextSourceError(
            "project root must be a filesystem path",
            code="context-root-invalid",
        ) from exc
    if not isinstance(root_path, (str, bytes)) or not root_path:
        raise ContextSourceError(
            "project root must be a non-empty filesystem path",
            code="context-root-invalid",
        )
    try:
        root_lstat = os.lstat(root_path)
    except OSError as exc:
        raise ContextSourceError(
            "project root is unavailable",
            code="context-root-unavailable",
            path=".",
        ) from exc
    if stat.S_ISLNK(root_lstat.st_mode):
        raise ContextSourceError(
            "project root must not be a symlink",
            code="context-source-symlink",
            path=".",
        )
    flags = _open_flags(directory=True)
    try:
        descriptor = os.open(root_path, flags)
    except OSError as exc:
        code = "context-source-symlink" if exc.errno == errno.ELOOP else "context-root-unavailable"
        raise ContextSourceError(
            "project root cannot be opened safely",
            code=code,
            path=".",
        ) from exc
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise ContextSourceError(
            "project root must be a directory",
            code="context-root-invalid",
            path=".",
        )
    if (metadata.st_dev, metadata.st_ino) != (root_lstat.st_dev, root_lstat.st_ino):
        os.close(descriptor)
        raise ContextSourceError(
            "project root changed while it was opened",
            code="context-source-raced",
            path=".",
        )
    return descriptor


def _verify_root_identity(
    project_root: Union[str, os.PathLike[str]],
    root_fd: int,
    expected: tuple[int, int, int, int, int, int],
) -> None:
    try:
        root_path = os.fspath(project_root)
        path_metadata = os.lstat(root_path)
        descriptor_metadata = os.fstat(root_fd)
    except (TypeError, OSError) as exc:
        raise ContextSourceError(
            "project root changed during context generation",
            code="context-source-raced",
            path=".",
        ) from exc
    if (
        stat.S_ISLNK(path_metadata.st_mode)
        or not stat.S_ISDIR(path_metadata.st_mode)
        or _file_snapshot(path_metadata) != expected
        or _file_snapshot(descriptor_metadata) != expected
    ):
        raise ContextSourceError(
            "project root changed during context generation",
            code="context-source-raced",
            path=".",
        )


def _read_relative_regular_file(
    root_fd: int,
    relative: str,
    *,
    maximum: int,
) -> tuple[bytes, tuple[tuple[int, int, int, int, int, int], ...]]:
    path = validate_source_path(relative)
    parts = PurePosixPath(path).parts
    parent_fd = os.dup(root_fd)
    path_identity: list[tuple[int, int, int, int, int, int]] = []
    try:
        for part in parts[:-1]:
            next_fd = _open_directory_at(parent_fd, part, source_path=path)
            os.close(parent_fd)
            parent_fd = next_fd
            path_identity.append(_file_snapshot(os.fstat(parent_fd)))
        content, file_identity = _read_regular_file_at(
            parent_fd,
            parts[-1],
            source_path=path,
            maximum=maximum,
        )
        path_identity.append(file_identity)
        return content, tuple(path_identity)
    finally:
        os.close(parent_fd)


def _open_directory_at(parent_fd: int, name: str, *, source_path: str) -> int:
    metadata = _entry_lstat(parent_fd, name, source_path=source_path)
    if stat.S_ISLNK(metadata.st_mode):
        raise ContextSourceError(
            f"control source crosses a symlink: {source_path}",
            code="context-source-symlink",
            path=source_path,
        )
    if not stat.S_ISDIR(metadata.st_mode):
        raise ContextSourceError(
            f"control source parent is not a directory: {source_path}",
            code="context-source-not-regular",
            path=source_path,
        )
    try:
        descriptor = os.open(name, _open_flags(directory=True), dir_fd=parent_fd)
    except OSError as exc:
        code = "context-source-symlink" if exc.errno == errno.ELOOP else "context-source-unavailable"
        raise ContextSourceError(
            f"control source parent cannot be opened safely: {source_path}",
            code=code,
            path=source_path,
        ) from exc
    opened = os.fstat(descriptor)
    if not stat.S_ISDIR(opened.st_mode) or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
        os.close(descriptor)
        raise ContextSourceError(
            f"control source parent changed while it was opened: {source_path}",
            code="context-source-raced",
            path=source_path,
        )
    return descriptor


def _read_regular_file_at(
    parent_fd: int,
    name: str,
    *,
    source_path: str,
    maximum: int,
) -> tuple[bytes, tuple[int, int, int, int, int, int]]:
    metadata = _entry_lstat(parent_fd, name, source_path=source_path)
    if stat.S_ISLNK(metadata.st_mode):
        raise ContextSourceError(
            f"control source must not be a symlink: {source_path}",
            code="context-source-symlink",
            path=source_path,
        )
    if not stat.S_ISREG(metadata.st_mode):
        raise ContextSourceError(
            f"control source must be a regular file: {source_path}",
            code="context-source-not-regular",
            path=source_path,
        )
    try:
        descriptor = os.open(name, _open_flags(directory=False), dir_fd=parent_fd)
    except OSError as exc:
        code = "context-source-symlink" if exc.errno == errno.ELOOP else "context-source-unavailable"
        raise ContextSourceError(
            f"control source cannot be opened safely: {source_path}",
            code=code,
            path=source_path,
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ContextSourceError(
                f"control source must be a regular file: {source_path}",
                code="context-source-not-regular",
                path=source_path,
            )
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise ContextSourceError(
                f"control source changed while it was opened: {source_path}",
                code="context-source-raced",
                path=source_path,
            )
        if opened.st_size > maximum:
            raise ContextSourceError(
                f"control source exceeds {maximum} bytes: {source_path}",
                code="context-source-too-large",
                path=source_path,
            )
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(65536, maximum + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum:
                raise ContextSourceError(
                    f"control source exceeds {maximum} bytes: {source_path}",
                    code="context-source-too-large",
                    path=source_path,
                )
        finished = os.fstat(descriptor)
        if _file_snapshot(opened) != _file_snapshot(finished) or size != finished.st_size:
            raise ContextSourceError(
                f"control source changed while it was read: {source_path}",
                code="context-source-raced",
                path=source_path,
            )
        return b"".join(chunks), _file_snapshot(finished)
    finally:
        os.close(descriptor)


def _entry_lstat(parent_fd: int, name: str, *, source_path: str) -> os.stat_result:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise ContextSourceError(
            f"required control source is missing: {source_path}",
            code="context-source-missing",
            path=source_path,
        ) from exc
    except OSError as exc:
        raise ContextSourceError(
            f"control source is unavailable: {source_path}",
            code="context-source-unavailable",
            path=source_path,
        ) from exc


def _require_safe_open_support() -> None:
    missing = [name for name in ("O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY") if not hasattr(os, name)]
    if os.open not in getattr(os, "supports_dir_fd", set()):
        missing.append("openat")
    if os.stat not in getattr(os, "supports_dir_fd", set()):
        missing.append("fstatat")
    if os.stat not in getattr(os, "supports_follow_symlinks", set()):
        missing.append("AT_SYMLINK_NOFOLLOW")
    if missing:
        raise ContextSourceError(
            "safe descriptor-relative source reads are unavailable",
            code="context-source-safety-unavailable",
        )


def _open_flags(*, directory: bool) -> int:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if directory:
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _file_snapshot(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_mode,
    )


def _decode_control_text(content: bytes, *, path: str) -> str:
    if not content:
        raise ContextSourceError(
            f"control source must not be empty: {path}",
            code="context-source-malformed",
            path=path,
        )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContextSourceError(
            f"control source must be UTF-8: {path}",
            code="context-source-malformed",
            path=path,
        ) from exc
    if "\x00" in text or any(ord(character) < 32 and character not in "\n\r\t" for character in text):
        raise ContextSourceError(
            f"control source contains forbidden control characters: {path}",
            code="context-source-malformed",
            path=path,
        )
    return text


def _reject_sensitive_source_text(value: str, *, path: str) -> None:
    try:
        reject_credential_shapes(value, label=f"control source {path}")
    except ValidationError as exc:
        raise ContextSourceError(
            f"control source contains credential-shaped content: {path}",
            code="context-sensitive-data",
            path=path,
        ) from exc


def _reject_sensitive_value(value: Any, *, label: str) -> None:
    try:
        reject_credential_shapes_deep(value, label=label)
    except ValidationError as exc:
        raise ContextValidationError(
            f"{label} contains credential-shaped content",
            code="context-sensitive-data",
        ) from exc


def _summarize(text: str) -> tuple[str, bool]:
    selected: list[str] = []
    used = 0
    truncated = False
    for raw_line in text.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line or line.startswith("```"):
            continue
        if len(selected) >= MAX_SUMMARY_LINES:
            truncated = True
            break
        separator_size = 3 if selected else 0
        remaining = MAX_SUMMARY_CHARS - used - separator_size
        if remaining <= 0:
            truncated = True
            break
        limit = min(MAX_SUMMARY_LINE_CHARS, remaining)
        piece = line[:limit]
        if len(piece) < len(line):
            truncated = True
        selected.append(piece)
        used += separator_size + len(piece)
    return " | ".join(selected), truncated


def _projection(value: Any, *, label: str, maximum: int) -> dict[str, Any]:
    return {
        "authoritative": False,
        "value": _bounded_json_copy(value, label=label, maximum=maximum),
    }


def _validate_projection(value: Any, *, label: str, maximum: int) -> None:
    projection = _require_object(value, label=label)
    _require_exact_keys(projection, _PROJECTION_KEYS, label=label)
    if projection["authoritative"] is not False:
        raise ContextValidationError(
            f"{label} must be explicitly non-authoritative",
            code="context-authority-invalid",
        )
    _bounded_json_copy(projection["value"], label=f"{label}.value", maximum=maximum)


def _capability_digest(capabilities: Any) -> dict[str, Any]:
    normalized = _bounded_json_copy(
        capabilities,
        label="capabilities",
        maximum=MAX_CAPABILITY_INPUT_BYTES,
    )
    payload = _canonical_json_bytes(normalized)
    return {
        "authoritative": False,
        "algorithm": "sha256",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "inputBytes": len(payload),
    }


def _validate_capability_digest(value: Any) -> None:
    digest = _require_object(value, label="context pack.capabilityDigest")
    _require_exact_keys(digest, _CAPABILITY_DIGEST_KEYS, label="context pack.capabilityDigest")
    if digest["authoritative"] is not False:
        raise ContextValidationError(
            "context pack.capabilityDigest must be explicitly non-authoritative",
            code="context-authority-invalid",
        )
    if digest["algorithm"] != "sha256":
        raise ContextValidationError(
            "context pack.capabilityDigest.algorithm must be sha256",
            code="context-capability-digest-invalid",
        )
    _require_sha256(digest["sha256"], label="context pack.capabilityDigest.sha256")
    _require_int(
        digest["inputBytes"],
        label="context pack.capabilityDigest.inputBytes",
        minimum=0,
        maximum=MAX_CAPABILITY_INPUT_BYTES,
    )


def _bounded_json_copy(value: Any, *, label: str, maximum: int) -> Any:
    try:
        payload = _canonical_json_bytes(value)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ContextValidationError(
            f"{label} must contain only finite JSON values",
            code="context-projection-malformed",
        ) from exc
    if len(payload) > maximum:
        raise ContextValidationError(
            f"{label} exceeds {maximum} bytes",
            code="context-projection-too-large",
        )
    copied = json.loads(payload.decode("ascii"))
    _reject_sensitive_value(copied, label=label)
    return copied


def _coerce_context_pack(value: Union[dict[str, Any], str, bytes, bytearray]) -> dict[str, Any]:
    if isinstance(value, dict):
        validate_context_pack(value)
        return value
    return parse_context_pack(value)


def _require_mode(value: Any) -> str:
    if not isinstance(value, str) or value not in CONTEXT_MODES:
        raise ContextValidationError(
            f"context mode must be one of {list(CONTEXT_MODES)}",
            code="context-mode-invalid",
        )
    return value


def _normalize_timestamp(value: Optional[str]) -> str:
    if value is None:
        parsed = datetime.now(timezone.utc)
    else:
        if not isinstance(value, str) or len(value) > 40 or len(value) < 20 or value[10:11] != "T":
            raise ContextValidationError(
                "timestamp must be timezone-aware RFC 3339 text",
                code="context-timestamp-invalid",
            )
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ContextValidationError(
                "timestamp must be timezone-aware RFC 3339 text",
                code="context-timestamp-invalid",
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ContextValidationError(
                "timestamp must include a timezone",
                code="context-timestamp-invalid",
            )
    utc = parsed.astimezone(timezone.utc)
    timespec = "microseconds" if utc.microsecond else "seconds"
    return utc.isoformat(timespec=timespec).replace("+00:00", "Z")


def _require_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContextValidationError(
            f"{label} must be an object",
            code="context-malformed",
        )
    return value


def _require_exact_keys(value: dict[str, Any], keys: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys)
        raise ContextValidationError(
            f"{label} keys mismatch: missing={missing}, extra={extra}",
            code="context-malformed",
        )


def _require_text(
    value: Any,
    *,
    label: str,
    maximum: int,
    allow_empty: bool,
    single_line: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ContextValidationError(
            f"{label} must be a string",
            code="context-malformed",
        )
    if (not allow_empty and not value) or len(value) > maximum:
        minimum = 0 if allow_empty else 1
        raise ContextValidationError(
            f"{label} length must be between {minimum} and {maximum}",
            code="context-malformed",
        )
    if "\x00" in value or any(ord(character) < 32 and character not in "\n\r\t" for character in value):
        raise ContextValidationError(
            f"{label} contains a forbidden control character",
            code="context-malformed",
        )
    if single_line and ("\n" in value or "\r" in value):
        raise ContextValidationError(
            f"{label} must be a single line",
            code="context-malformed",
        )
    return value


def _require_bool(value: Any, *, label: str) -> bool:
    if type(value) is not bool:
        raise ContextValidationError(
            f"{label} must be a boolean",
            code="context-malformed",
        )
    return value


def _require_int(value: Any, *, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise ContextValidationError(
            f"{label} must be an integer between {minimum} and {maximum}",
            code="context-malformed",
        )
    return value


def _require_sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ContextValidationError(
            f"{label} must be a lowercase SHA-256 digest",
            code="context-malformed",
        )
    return value


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ContextValidationError(
                "context payload contains a duplicate object key",
                code="context-malformed",
            )
        value[key] = item
    return value


def _reject_json_constant(value: str) -> Any:
    raise ContextValidationError(
        f"context payload contains non-finite number {value}",
        code="context-malformed",
    )


build_context_pack = generate_context_pack
context_pack_bytes = render_context_pack
require_fresh_context_pack = check_context_pack
validate_context_document = validate_context_pack
