from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from .renderer import RendererError, inspect_project_frame
from .review_bundle import sensitive_path_reason


SCHEMA_VERSION = "plzdo-local.monitor-snapshot.v1"
PREFLIGHT_SCHEMA_VERSION = "plzdo-local.repo-preflight.v1"
MAX_ENTRIES = 5000
MAX_DEPTH = 128

_TEST_SCANDIR_OBSERVER: Optional[Callable[[str], None]] = None


class MonitorError(ValueError):
    pass


def repo_preflight(root: Path) -> dict[str, Any]:
    target = _root(root)
    before = _tree_metadata(target)
    files = 0
    symlinks = 0
    risky = 0
    directories = 1
    for relative, metadata in _stream_tree(target):
        if stat.S_ISDIR(metadata.st_mode):
            directories += 1
        else:
            files += 1
        if stat.S_ISLNK(metadata.st_mode):
            symlinks += 1
        if sensitive_path_reason(relative) is not None:
            risky += 1
    try:
        controls = {
            relative: (target / relative).is_file() and not (target / relative).is_symlink()
            for relative in ("AGENTS.md", "CHECKS.md", "TASKS/current.md")
        }
        git_metadata_present = (target / ".git").exists() or (target / ".git").is_symlink()
    except OSError as exc:
        raise MonitorError("repository control-file observation failed") from exc
    try:
        frame = inspect_project_frame(target)
        frame_status = frame["status"]
        frame_sha256 = frame["frameSha256"]
    except RendererError:
        frame_status = "unmanaged"
        frame_sha256 = None
    except OSError as exc:
        raise MonitorError("managed frame observation failed") from exc
    after = _tree_metadata(target)
    if before != after:
        raise MonitorError("repository changed during read-only preflight")
    return {
        "schemaVersion": PREFLIGHT_SCHEMA_VERSION,
        "status": "observed",
        "sourceOfTruth": False,
        "targetMutated": False,
        "rootSha256": hashlib.sha256(str(target).encode("utf-8")).hexdigest(),
        "gitMetadataPresent": git_metadata_present,
        "fileCount": files,
        "directoryCount": directories,
        "symlinkCount": symlinks,
        "riskyNameCount": risky,
        "controlFiles": controls,
        "managedFrameStatus": frame_status,
        "managedFrameSha256": frame_sha256,
    }


def monitor_snapshot(project: dict[str, Any], *, captured_at: str) -> dict[str, Any]:
    if not isinstance(project, dict) or not isinstance(project.get("id"), str) or not isinstance(project.get("path"), str):
        raise MonitorError("monitor project is invalid")
    preflight = repo_preflight(Path(project["path"]))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "observed",
        "sourceOfTruth": False,
        "recommendationOnly": True,
        "targetMutated": False,
        "projectId": project["id"],
        "capturedAt": captured_at,
        "observation": preflight,
    }


def _root(path: Path) -> Path:
    if path.is_symlink():
        raise MonitorError("repository root must not be a symlink")
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise MonitorError("repository root is unavailable") from exc
    if not resolved.is_dir():
        raise MonitorError("repository root must be a directory")
    return resolved


def _tree_metadata(root: Path) -> tuple[tuple[str, int, int, int], ...]:
    values: list[tuple[str, int, int, int]] = []
    for relative, metadata in _stream_tree(root):
        values.append(
            (
                relative,
                metadata.st_mode,
                metadata.st_size,
                metadata.st_mtime_ns,
            )
        )
    return tuple(sorted(values))


def _stream_tree(root: Path) -> Iterator[tuple[str, os.stat_result]]:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        root_fd = os.open(root, flags)
    except OSError as exc:
        raise MonitorError("repository traversal root is unavailable") from exc
    consumed = 0

    def visit(descriptor: int, prefix: Path, depth: int) -> Iterator[tuple[str, os.stat_result]]:
        nonlocal consumed
        if depth > MAX_DEPTH:
            raise MonitorError(f"repository observation exceeds depth {MAX_DEPTH}")
        try:
            iterator = os.scandir(descriptor)
        except OSError as exc:
            raise MonitorError("repository traversal failed") from exc
        try:
            with iterator:
                for entry in iterator:
                    relative_path = prefix / entry.name
                    relative = relative_path.as_posix()
                    observer = _TEST_SCANDIR_OBSERVER
                    if observer is not None:
                        observer(relative)
                    consumed += 1
                    if consumed > MAX_ENTRIES:
                        raise MonitorError(f"repository observation exceeds {MAX_ENTRIES} entries")
                    if depth == 0 and entry.name == ".git":
                        continue
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise MonitorError("repository metadata changed during traversal") from exc
                    yield relative, metadata
                    if stat.S_ISDIR(metadata.st_mode):
                        try:
                            child_fd = os.open(entry.name, flags, dir_fd=descriptor)
                        except OSError as exc:
                            raise MonitorError("repository directory changed during traversal") from exc
                        try:
                            yield from visit(child_fd, relative_path, depth + 1)
                        finally:
                            os.close(child_fd)
        except MonitorError:
            raise
        except OSError as exc:
            raise MonitorError("repository traversal failed") from exc

    try:
        yield from visit(root_fd, Path(), 0)
    finally:
        os.close(root_fd)
