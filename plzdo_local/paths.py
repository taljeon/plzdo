from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional


class PathPolicyError(ValueError):
    pass


def repository_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_state_root(
    *,
    environ: Optional[Mapping[str, str]] = None,
    home: Optional[Path] = None,
) -> Path:
    values = os.environ if environ is None else environ
    configured = values.get("PLZDO_HOME", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            raise PathPolicyError("PLZDO_HOME must be an absolute path")
        return candidate.resolve(strict=False)

    xdg = values.get("XDG_STATE_HOME", "").strip()
    if xdg:
        base = Path(xdg).expanduser()
        if not base.is_absolute():
            raise PathPolicyError("XDG_STATE_HOME must be an absolute path")
        return (base / "plzdo-local").resolve(strict=False)

    base_home = Path.home() if home is None else home
    if not base_home.is_absolute():
        raise PathPolicyError("home path must be absolute")
    return (base_home / ".local" / "state" / "plzdo-local").resolve(strict=False)


def ensure_contained(path: Path, root: Path, *, label: str) -> Path:
    root_lexical = _absolute_lexical(root)
    path_lexical = _absolute_lexical(path)
    root_resolved = root.expanduser().resolve(strict=False)
    path_resolved = path.expanduser().resolve(strict=False)
    if path_resolved != root_resolved and root_resolved not in path_resolved.parents:
        raise PathPolicyError(f"{label} escapes allowed root")
    _reject_child_symlink_components(path_lexical, root_lexical, label=label)
    return path_resolved


def require_external_file(path: Path, release_root: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise PathPolicyError(f"{label} must not be a symlink")
    resolved = path.expanduser().resolve(strict=True)
    root = release_root.expanduser().resolve(strict=True)
    if resolved == root or root in resolved.parents:
        raise PathPolicyError(f"{label} must be outside the release root")
    if not resolved.is_file():
        raise PathPolicyError(f"{label} must be a regular file")
    return resolved


def _absolute_lexical(path: Path) -> Path:
    expanded = path.expanduser()
    return expanded if expanded.is_absolute() else Path.cwd() / expanded


def _reject_child_symlink_components(path: Path, root: Path, *, label: str) -> None:
    current = path
    existing: list[Path] = []
    while True:
        if current.exists() or current.is_symlink():
            existing.append(current)
        if current == current.parent:
            break
        current = current.parent
    for item in existing:
        if item.is_symlink() and item != root and item not in root.parents:
            raise PathPolicyError(f"{label} crosses a symlink below the allowed root")
