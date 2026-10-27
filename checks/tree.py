"""Shared file inventory; never follow symlinks."""

from pathlib import Path


# Python caches are expected next to tier-two code, never inside tier-one text folders.
TIER_ONE = {"harness", "skills", "agents", "style", "settings"}


def inventory(root: Path) -> tuple[list[str], list[str]]:
    files: list[str] = []
    symlinks: list[str] = []

    def visit(directory: Path) -> None:
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(root).as_posix()
            if relative == ".git":
                continue
            if path.is_symlink():
                symlinks.append(relative)
            elif path.is_dir():
                if path.name == "__pycache__" and relative.split("/")[0] not in TIER_ONE:
                    continue
                visit(path)
            elif path.is_file() and path.name != ".DS_Store":
                files.append(relative)

    visit(root)
    return sorted(files), sorted(symlinks)
