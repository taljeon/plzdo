from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional


class PathPolicyError(ValueError):
    pass


def repository_root() -> Path:
    """Fixed resource root for a source checkout or an installed core package.

    The installed root is package-owned, never the containing site-packages.
    Keep this historical name for callers that consume bundled source data.
    """
    package = Path(__file__).resolve().parent
    bundled = package / "_bundled"
    if bundled.exists() or bundled.is_symlink():
        if bundled.is_symlink() or not bundled.is_dir():
            raise PathPolicyError("installed resource root must be a real directory")
        return bundled
    root = package.parent
    if not (root / "VERSION").is_file() or not (root / "bin" / "plzdo_entry.py").is_file():
        raise PathPolicyError("source or installed core resource layout unavailable")
    return root


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
