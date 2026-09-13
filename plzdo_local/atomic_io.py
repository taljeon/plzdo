from __future__ import annotations

import json
import os
import secrets
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import fcntl

from .paths import ensure_contained


Validator = Callable[[Any], None]


@contextmanager
def exclusive_file_lock(path: Path, *, allowed_root: Path) -> Iterator[Callable[[], None]]:
    """Hold the canonical lock and yield an explicit pre-side-effect identity guard.

    Existing callers may ignore the guard. Callers that pause or do substantial
    work while locked must invoke it before writes; an exit-only check is too late.
    """
    lock_path = ensure_contained(path, allowed_root, label="lock path")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = ensure_contained(lock_path, allowed_root, label="lock path")
    root_path = allowed_root.expanduser().resolve(strict=True)
    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    lock_flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        lock_flags |= os.O_NOFOLLOW
    directories: list[tuple[Path, int, tuple[int, int]]] = []
    try:
        current_path = root_path
        directory_descriptor = os.open(root_path, directory_flags)
        info = os.fstat(directory_descriptor)
        directories.append((current_path, directory_descriptor, (info.st_dev, info.st_ino)))
        for part in lock_path.parent.relative_to(root_path).parts:
            current_path = current_path / part
            directory_descriptor = os.open(part, directory_flags, dir_fd=directory_descriptor)
            info = os.fstat(directory_descriptor)
            directories.append((current_path, directory_descriptor, (info.st_dev, info.st_ino)))
        descriptor = os.open(lock_path.name, lock_flags, 0o600, dir_fd=directory_descriptor)
        with os.fdopen(descriptor, "a+") as handle:
            locked_info = os.fstat(handle.fileno())
            if not stat.S_ISREG(locked_info.st_mode):
                raise ValueError("lock path must be a regular file")
            locked_identity = (locked_info.st_dev, locked_info.st_ino)

            def verify_held() -> None:
                if ensure_contained(lock_path, root_path, label="lock path") != lock_path:
                    raise ValueError("lock path changed while acquiring or holding the lock")
                for current_path, held_descriptor, identity in directories:
                    current = os.stat(current_path, follow_symlinks=False)
                    held = os.fstat(held_descriptor)
                    if (
                        not stat.S_ISDIR(current.st_mode)
                        or (current.st_dev, current.st_ino) != identity
                        or (held.st_dev, held.st_ino) != identity
                    ):
                        raise ValueError("lock root or ancestor changed while acquiring or holding the lock")
                current = os.stat(lock_path.name, dir_fd=directory_descriptor, follow_symlinks=False)
                held = os.fstat(handle.fileno())
                if (
                    not stat.S_ISREG(current.st_mode)
                    or (current.st_dev, current.st_ino) != locked_identity
                    or (held.st_dev, held.st_ino) != locked_identity
                ):
                    raise ValueError("held lock file is no longer the canonical lock")

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                verify_held()
                yield verify_held
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        for _, descriptor, _ in reversed(directories):
            os.close(descriptor)


def atomic_write_text(
    path: Path,
    text: str,
    *,
    allowed_root: Path,
    validator: Optional[Callable[[str], None]] = None,
) -> None:
    destination = ensure_contained(path, allowed_root, label="output path")
    if destination.is_symlink():
        raise ValueError("output path must not be a symlink")
    if validator is not None:
        validator(text)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = ensure_contained(destination, allowed_root, label="output path")
    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    directory_descriptor = os.open(destination.parent, directory_flags)
    temporary_name = f".{destination.name}.{secrets.token_hex(12)}"
    descriptor: Optional[int] = None
    try:
        try:
            metadata = os.stat(destination.name, dir_fd=directory_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            metadata = None
        if metadata is not None and stat.S_ISLNK(metadata.st_mode):
            raise ValueError("output path must not be a symlink")
        descriptor = os.open(
            temporary_name,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
            dir_fd=directory_descriptor,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = None
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temporary_name,
            destination.name,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        os.fsync(directory_descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=directory_descriptor)
        except FileNotFoundError:
            pass
        os.close(directory_descriptor)


def atomic_write_json(
    path: Path,
    value: Any,
    *,
    allowed_root: Path,
    validator: Optional[Validator] = None,
) -> None:
    if validator is not None:
        validator(value)
    text = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, text, allowed_root=allowed_root)
