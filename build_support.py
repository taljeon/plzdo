"""Fixed core resource staging. Runtime/private source is never discovered."""
from pathlib import Path
import shutil


RESOURCE_TREES = ("schemas", "templates", "resources")
RESOURCE_FILES = ("VERSION", "LICENSE")


def bundled_inputs(source: Path) -> list[Path]:
    """Return exact source data; reject symlinks and accidental special files."""
    result = []
    for name in RESOURCE_TREES:
        root = source / name
        if root.is_symlink() or not root.is_dir():
            raise ValueError("bundled resource root must be a real directory")
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError("bundled resource has an unsafe type")
            if path.is_file():
                result.append(path)
    for name in RESOURCE_FILES:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("bundled resource must be a regular file")
        result.append(path)
    return sorted(result)


def stage_resources(source: Path, build_lib: Path) -> list[str]:
    destination = build_lib / "plzdo_local" / "_bundled"
    files = bundled_inputs(source)
    outputs = []
    for path in files:
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        outputs.append(str(target))
    return outputs
