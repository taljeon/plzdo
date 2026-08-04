from __future__ import annotations

import argparse
import hashlib
import os
import stat
import tempfile
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "SHA256SUMS"
BLOCKED_DIRECTORIES = {".cache", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__", "cache", "caches"}
BLOCKED_SUFFIXES = {".pyc", ".pyo", ".swp", ".temp", ".tmp"}
MAX_RELEASE_FILE_BYTES = 8 * 1024 * 1024
MAX_RELEASE_FILES = 50_000
MAX_RELEASE_TOTAL_BYTES = 512 * 1024 * 1024
WINDOWS_RESERVED_NAMES = {
    "aux",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "con",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
    "nul",
    "prn",
}


class ManifestError(ValueError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or verify the PlzDo Local release manifest")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        content = render_manifest(ROOT)
        if args.check:
            if not OUTPUT.is_file() or OUTPUT.is_symlink() or OUTPUT.read_bytes() != content:
                raise ManifestError("SHA256SUMS does not match the current release tree")
            print("release manifest check passed")
            return 0
        if args.write:
            atomic_write(OUTPUT, content)
            print(f"release manifest written: {len(content.splitlines())} files")
            return 0
        print(content.decode("utf-8"), end="")
        return 0
    except (ManifestError, OSError) as exc:
        print(f"FAIL release-manifest: {exc}")
        return 1


def render_manifest(root: Path) -> bytes:
    lines: list[str] = []
    total_bytes = 0
    for path in inventory(root):
        relative = path.relative_to(root).as_posix()
        data = read_regular_file(path)
        total_bytes += len(data)
        if total_bytes > MAX_RELEASE_TOTAL_BYTES:
            raise ManifestError("release tree exceeds the total byte bound")
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {relative}\n")
    return "".join(lines).encode("utf-8")


def inventory(root: Path) -> tuple[Path, ...]:
    if root.is_symlink() or not root.is_dir():
        raise ManifestError("release root must be a real directory")
    root = root.resolve(strict=True)
    files: list[Path] = []
    walk_errors: list[OSError] = []
    path_identities: set[str] = set()

    def record_error(error: OSError) -> None:
        walk_errors.append(error)

    for directory, names, filenames in os.walk(root, followlinks=False, onerror=record_error):
        base = Path(directory)
        retained: list[str] = []
        for name in sorted(names):
            candidate = base / name
            relative = candidate.relative_to(root).as_posix()
            _record_safe_relative_path(relative, path_identities)
            metadata = candidate.lstat()
            if candidate.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
                raise ManifestError("release tree contains a non-directory or symlink directory")
            if base == root and name == ".git":
                continue
            if name.casefold() == ".git" or name.casefold() in BLOCKED_DIRECTORIES:
                raise ManifestError("release tree contains nested metadata or cache directory")
            retained.append(name)
        names[:] = retained
        for name in sorted(filenames):
            candidate = base / name
            relative = candidate.relative_to(root).as_posix()
            _record_safe_relative_path(relative, path_identities)
            metadata = candidate.lstat()
            if candidate.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                raise ManifestError("release tree contains a non-regular file")
            if base == root and name == "SHA256SUMS":
                continue
            lower_name = name.casefold()
            if (
                lower_name == ".git"
                or lower_name == ".ds_store"
                or lower_name.startswith(".sha256sums.")
                or Path(lower_name).suffix in BLOCKED_SUFFIXES
            ):
                raise ManifestError("release tree contains a generated or temporary file")
            files.append(candidate)
            if len(files) > MAX_RELEASE_FILES:
                raise ManifestError("release tree exceeds the file count bound")
    if walk_errors:
        raise ManifestError("release tree traversal failed")
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix()))


def _record_safe_relative_path(relative: str, identities: set[str]) -> None:
    _require_safe_relative_path(relative)
    identity = unicodedata.normalize("NFKC", relative).casefold()
    if identity in identities:
        raise ManifestError("release tree contains ambiguous path identities")
    identities.add(identity)


def _require_safe_relative_path(relative: str) -> None:
    if not relative or relative.startswith("/") or "\\" in relative:
        raise ManifestError("release tree contains an unsafe path")
    try:
        encoded = relative.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ManifestError("release tree contains a non-UTF-8 path") from exc
    if len(encoded) > 4096 or unicodedata.normalize("NFC", relative) != relative:
        raise ManifestError("release tree contains a non-canonical path")
    if any(ord(character) < 32 or ord(character) == 127 for character in relative):
        raise ManifestError("release tree contains a control-character path")
    components = relative.split("/")
    for component in components:
        if not component or component in {".", ".."} or len(component.encode("utf-8")) > 255:
            raise ManifestError("release tree contains an unsafe path component")
        if component != component.strip() or component.endswith("."):
            raise ManifestError("release tree contains an ambiguous path component")
        if any(character in component for character in ':*?<>|"'):
            raise ManifestError("release tree contains a non-portable path component")
        if component.split(".", 1)[0].casefold() in WINDOWS_RESERVED_NAMES:
            raise ManifestError("release tree contains a reserved path component")


def read_regular_file(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_RELEASE_FILE_BYTES:
            raise ManifestError("release file is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = MAX_RELEASE_FILE_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > MAX_RELEASE_FILE_BYTES:
            raise ManifestError("release file is oversized")
        return data
    finally:
        os.close(descriptor)


def atomic_write(path: Path, content: bytes) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ManifestError("manifest destination must be a regular file or absent")
    descriptor, temporary = tempfile.mkstemp(prefix=".SHA256SUMS.", dir=str(path.parent))
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
