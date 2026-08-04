from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional, Union

from .paths import PathPolicyError, repository_root
from .validation import require_safe_id, require_string


RENDERER_VERSION = "plzdo-local.renderer.v1"
PROJECT_FRAME_SCHEMA_VERSION = "plzdo-local.project-frame-plan.v1"
DEFAULT_OBJECTIVE = "Deliver the project through scoped, evidence-backed work."
MAX_FILE_BYTES = 256 * 1024
MAX_FRAME_BYTES = 1024 * 1024
MAX_EXISTING_CONTROL_BYTES = 1024 * 1024

PROJECT_FRAME_PATHS = (
    "AGENTS.md",
    "CHECKS.md",
    "TASKS/current.md",
    "docs/requirements.md",
    "docs/technical-design.md",
    "scripts/verify",
)

MARKER_IDS = {
    "AGENTS.md": "project-frame.agents.v1",
    "CHECKS.md": "project-frame.checks.v1",
    "TASKS/current.md": "project-frame.tasks-current.v1",
    "docs/requirements.md": "project-frame.requirements.v1",
    "docs/technical-design.md": "project-frame.technical-design.v1",
    "scripts/verify": "project-frame.verify.v1",
}

FILE_MODES = {path: 0o644 for path in PROJECT_FRAME_PATHS}
FILE_MODES["scripts/verify"] = 0o755

_TOKEN_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
_PROJECT_ID_LINE_RE = re.compile(r"^- Project ID: `([a-z][a-z0-9-]{1,63})`$", re.MULTILINE)
_PROJECT_NAME_LINE_RE = re.compile(r"^# (.+) Agent Guide$", re.MULTILINE)
_PROJECT_OBJECTIVE_LINE_RE = re.compile(r"^- Objective: (.+)$", re.MULTILINE)
_MARKER_RE = re.compile(
    r"^(?:(?P<markdown><!-- )|(?P<shell># ))"
    r"(?P<kind>BEGIN|END) PLZDO-LOCAL:(?P<identifier>[a-z0-9][a-z0-9.-]*)"
    r"(?P<markdown_end> -->)?$"
)
_MARKER_TEXT_RE = re.compile(r"(?:BEGIN|END) PLZDO-LOCAL:")


class RendererError(ValueError):
    pass


ProjectInput = Union[str, Mapping[str, Any]]


@dataclass(frozen=True)
class PlannedFile:
    path: str
    content: bytes
    mode: int
    action: str
    previous_content: Optional[bytes]
    previous_mode: Optional[int]
    template_sha256: str

    @property
    def sha256(self) -> str:
        return _sha256(self.content)

    @property
    def previous_sha256(self) -> Optional[str]:
        if self.previous_content is None:
            return None
        return _sha256(self.previous_content)

    def as_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "bytes": len(self.content),
            "mode": format(self.mode, "04o"),
            "path": self.path,
            "previousSha256": self.previous_sha256,
            "sha256": self.sha256,
            "templateSha256": self.template_sha256,
        }


@dataclass(frozen=True)
class ProjectFramePlan:
    target: Path
    target_state: str
    force: bool
    files: tuple[PlannedFile, ...]

    @property
    def writes_required(self) -> bool:
        return any(item.action != "no-change" for item in self.files)

    def as_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": PROJECT_FRAME_SCHEMA_VERSION,
            "rendererVersion": RENDERER_VERSION,
            "mode": "dry-run",
            "target": str(self.target),
            "targetState": self.target_state,
            "force": self.force,
            "writesRequired": self.writes_required,
            "files": [item.as_dict() for item in self.files],
        }


def render_project_frame(
    project: ProjectInput,
    *,
    project_name: Optional[str] = None,
    objective: Optional[str] = None,
    template_root: Optional[Path] = None,
) -> dict[str, bytes]:
    """Render the complete project frame in memory without touching the target."""

    values = _project_values(project, project_name=project_name, objective=objective)
    return _render_project_frame_values(values, template_root=template_root)


def _render_project_frame_values(
    values: Mapping[str, str],
    *,
    template_root: Optional[Path],
) -> dict[str, bytes]:
    root = _template_root(template_root)
    rendered: dict[str, bytes] = {}
    for relative in PROJECT_FRAME_PATHS:
        _validate_relative_path(relative)
        template_path = root.joinpath(*PurePosixPath(relative).parts)
        _reject_path_symlinks(root, PurePosixPath(relative).parts, label=f"template {relative}")
        try:
            template = _read_regular_bytes(
                template_path,
                label=f"template {relative}",
                maximum=MAX_FILE_BYTES,
            ).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RendererError(f"template {relative} must be UTF-8") from exc
        text = _substitute_template(template, values, relative=relative)
        rendered[relative] = text.encode("utf-8")
    _validate_frame_bytes(rendered)
    return rendered


def plan_project_frame(
    target: Path,
    project: ProjectInput,
    *,
    project_name: Optional[str] = None,
    objective: Optional[str] = None,
    force: bool = False,
    template_root: Optional[Path] = None,
) -> ProjectFramePlan:
    """Build a complete write plan. This function never creates or changes files."""

    rendered = render_project_frame(
        project,
        project_name=project_name,
        objective=objective,
        template_root=template_root,
    )
    target_root = _validate_target_root(target)
    target_state, existing = _inspect_target(target_root, force=force)

    planned: list[PlannedFile] = []
    for relative in PROJECT_FRAME_PATHS:
        rendered_content = rendered[relative]
        previous = existing.get(relative)
        previous_mode: Optional[int] = None
        if previous is None:
            content = rendered_content
            action = "create"
        else:
            destination = target_root.joinpath(*PurePosixPath(relative).parts)
            previous_mode = stat.S_IMODE(destination.lstat().st_mode)
            if target_state == "managed":
                content = _replace_managed_block(relative, previous, rendered_content)
            else:
                content = rendered_content
            expected_mode = FILE_MODES[relative]
            if previous == content:
                action = "no-change" if previous_mode == expected_mode else "update-mode"
            else:
                action = "update"
        planned.append(
            PlannedFile(
                path=relative,
                content=content,
                mode=FILE_MODES[relative],
                action=action,
                previous_content=previous,
                previous_mode=previous_mode,
                template_sha256=_sha256(rendered_content),
            )
        )

    planned_bytes = {item.path: item.content for item in planned}
    _validate_frame_bytes(planned_bytes)
    return ProjectFramePlan(
        target=target_root,
        target_state=target_state,
        force=force,
        files=tuple(planned),
    )


def dry_run_project_frame(
    target: Path,
    project: ProjectInput,
    *,
    project_name: Optional[str] = None,
    objective: Optional[str] = None,
    force: bool = False,
    template_root: Optional[Path] = None,
) -> ProjectFramePlan:
    return plan_project_frame(
        target,
        project,
        project_name=project_name,
        objective=objective,
        force=force,
        template_root=template_root,
    )


def inspect_project_frame(target: Path, *, expected_project_id: Optional[str] = None) -> dict[str, object]:
    """Validate an existing managed frame without changing target bytes."""

    target_root = _validate_target_root(target)
    target_state, existing = _inspect_target(target_root, force=False)
    if target_state != "managed":
        raise RendererError("target does not contain a complete managed project frame")

    agents = existing["AGENTS.md"].decode("utf-8")
    managed_start, managed_end = _managed_block_offsets(agents, "AGENTS.md")
    managed_agents = agents[managed_start:managed_end]
    identifiers = _PROJECT_ID_LINE_RE.findall(managed_agents)
    if len(identifiers) != 1:
        raise RendererError("managed AGENTS.md must declare exactly one project id")
    project_id = identifiers[0]
    names = _PROJECT_NAME_LINE_RE.findall(managed_agents)
    objectives = _PROJECT_OBJECTIVE_LINE_RE.findall(managed_agents)
    if len(names) != 1 or len(objectives) != 1:
        raise RendererError("managed AGENTS.md must declare exactly one project name and objective")
    if expected_project_id is not None:
        try:
            expected = require_safe_id(expected_project_id, label="expected project id")
        except ValueError as exc:
            raise RendererError(str(exc)) from exc
        if project_id != expected:
            raise RendererError("managed project id does not match the requested registration id")

    expected_frame = _render_project_frame_values(
        {
            "PROJECT_ID": project_id,
            "PROJECT_NAME": names[0],
            "PROJECT_OBJECTIVE": objectives[0],
        },
        template_root=None,
    )
    digest = hashlib.sha256()
    files: list[dict[str, object]] = []
    for relative in PROJECT_FRAME_PATHS:
        content = existing[relative]
        actual_text = content.decode("utf-8")
        expected_text = expected_frame[relative].decode("utf-8")
        actual_start, actual_end = _managed_block_offsets(actual_text, relative)
        expected_start, expected_end = _managed_block_offsets(expected_text, relative)
        if actual_text[actual_start:actual_end] != expected_text[expected_start:expected_end]:
            raise RendererError(f"managed content drifted from the public template: {relative}")
        destination = target_root.joinpath(*PurePosixPath(relative).parts)
        actual_mode = stat.S_IMODE(destination.lstat().st_mode)
        if actual_mode != FILE_MODES[relative]:
            raise RendererError(f"managed control file has an unexpected mode: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        files.append(
            {
                "path": relative,
                "bytes": len(content),
                "mode": format(actual_mode, "04o"),
                "sha256": _sha256(content),
            }
        )
    return {
        "schemaVersion": "plzdo-local.project-frame-status.v1",
        "status": "managed",
        "projectId": project_id,
        "frameSha256": digest.hexdigest(),
        "files": files,
    }


def validate_managed_markers(text: str, *, expected_id: Optional[str] = None) -> tuple[str, ...]:
    """Validate non-nested, paired PlzDo Local markers and return their ids."""

    opened: Optional[str] = None
    identifiers: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        marker_candidate = line.lstrip().startswith(("<!--", "#")) and _MARKER_TEXT_RE.search(line)
        if not marker_candidate:
            continue
        match = _MARKER_RE.fullmatch(line)
        if match is None:
            raise RendererError(f"malformed managed marker at line {line_number}")
        if bool(match.group("markdown")) != bool(match.group("markdown_end")):
            raise RendererError(f"malformed managed marker wrapper at line {line_number}")
        kind = match.group("kind")
        identifier = match.group("identifier")
        if kind == "BEGIN":
            if opened is not None:
                raise RendererError(f"nested managed marker at line {line_number}")
            if identifier in identifiers:
                raise RendererError(f"duplicate managed marker: {identifier}")
            opened = identifier
            identifiers.append(identifier)
        else:
            if opened is None:
                raise RendererError(f"END marker without BEGIN at line {line_number}")
            if opened != identifier:
                raise RendererError(
                    f"mismatched END marker at line {line_number}: expected {opened}, got {identifier}"
                )
            opened = None
    if opened is not None:
        raise RendererError(f"missing END marker for {opened}")
    if expected_id is not None and tuple(identifiers) != (expected_id,):
        raise RendererError(f"expected exactly one managed marker {expected_id}")
    return tuple(identifiers)


def _project_values(
    project: ProjectInput,
    *,
    project_name: Optional[str],
    objective: Optional[str],
) -> dict[str, str]:
    if isinstance(project, str):
        project_id_value: Any = project
        mapped_name: Any = None
        mapped_objective: Any = None
    elif isinstance(project, Mapping):
        project_id_value = project.get("id")
        mapped_name = project.get("name")
        mapped_objective = project.get("objective", project.get("goal"))
    else:
        raise RendererError("project must be a project id or mapping")

    try:
        project_id = require_safe_id(project_id_value, label="project id")
    except ValueError as exc:
        raise RendererError(str(exc)) from exc

    raw_name = project_name if project_name is not None else mapped_name
    if raw_name is None:
        raw_name = project_id.replace("-", " ").title()
    raw_objective = objective if objective is not None else mapped_objective
    if raw_objective is None:
        raw_objective = DEFAULT_OBJECTIVE
    name = _single_line(raw_name, label="project name", maximum=120)
    goal = _single_line(raw_objective, label="project objective", maximum=500)
    return {
        "PROJECT_ID": project_id,
        "PROJECT_NAME": _escape_markdown(name),
        "PROJECT_OBJECTIVE": _escape_markdown(goal),
    }


def _single_line(value: Any, *, label: str, maximum: int) -> str:
    try:
        text = require_string(value, label=label, maximum=maximum)
    except ValueError as exc:
        raise RendererError(str(exc)) from exc
    if text != text.strip():
        raise RendererError(f"{label} must not have surrounding whitespace")
    if "\n" in text or "\r" in text:
        raise RendererError(f"{label} must be a single line")
    if "{{" in text or "}}" in text or _MARKER_TEXT_RE.search(text):
        raise RendererError(f"{label} contains reserved renderer syntax")
    return text


def _escape_markdown(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for character in ("`", "*", "_", "[", "]", "<", ">", "#"):
        escaped = escaped.replace(character, "\\" + character)
    return escaped


def _template_root(configured: Optional[Path]) -> Path:
    root = repository_root() / "templates" / "project-harness" if configured is None else Path(configured)
    if _contains_parent_reference(root):
        raise RendererError("template root must not contain parent traversal")
    if root.is_symlink():
        raise RendererError("template root must not be a symlink")
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise RendererError(f"template root is unavailable: {root}") from exc
    if not resolved.is_dir():
        raise RendererError("template root must be a directory")
    return resolved


def _substitute_template(template: str, values: Mapping[str, str], *, relative: str) -> str:
    if "\r" in template or "\x00" in template:
        raise RendererError(f"template {relative} contains forbidden bytes")

    referenced = set(_TOKEN_RE.findall(template))
    unknown = sorted(referenced - set(values))
    if unknown:
        raise RendererError(f"template {relative} contains unknown tokens: {unknown}")
    text = _TOKEN_RE.sub(lambda match: values[match.group(1)], template)
    if _TOKEN_RE.search(text):
        raise RendererError(f"template {relative} contains unresolved tokens")
    if not text.endswith("\n"):
        raise RendererError(f"template {relative} must end with a newline")
    return text


def _validate_frame_bytes(outputs: Mapping[str, bytes]) -> None:
    if tuple(outputs) != PROJECT_FRAME_PATHS:
        raise RendererError("project frame must contain exactly the declared files in canonical order")
    total = 0
    for relative, content in outputs.items():
        _validate_relative_path(relative)
        if type(content) is not bytes:
            raise RendererError(f"rendered output {relative} must be bytes")
        if len(content) > MAX_FILE_BYTES:
            raise RendererError(f"rendered output {relative} exceeds the byte limit")
        total += len(content)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RendererError(f"rendered output {relative} must be UTF-8") from exc
        _validate_output_text(relative, text)
    if total > MAX_FRAME_BYTES:
        raise RendererError("rendered project frame exceeds the total byte limit")


def _validate_output_text(relative: str, text: str) -> None:
    if "\x00" in text or "\r" in text:
        raise RendererError(f"rendered output {relative} contains forbidden bytes")
    if not text.endswith("\n"):
        raise RendererError(f"rendered output {relative} must end with a newline")
    marker_id = MARKER_IDS[relative]
    validate_managed_markers(text, expected_id=marker_id)
    begin, end = _marker_lines(relative)
    if text.splitlines().count(begin) != 1 or text.splitlines().count(end) != 1:
        raise RendererError(f"rendered output {relative} has the wrong marker style")
    if relative == "scripts/verify" and not text.startswith("#!/usr/bin/env python3\n"):
        raise RendererError("scripts/verify must use the public Python 3 interpreter")


def _validate_target_root(target: Path) -> Path:
    candidate = Path(target).expanduser()
    if _contains_parent_reference(candidate):
        raise PathPolicyError("target path must not contain parent traversal")
    if candidate.is_symlink():
        raise PathPolicyError("target path must not be a symlink")
    if candidate.exists() and not candidate.is_dir():
        raise PathPolicyError("target path must be a directory")
    try:
        return candidate.resolve(strict=False)
    except OSError as exc:
        raise PathPolicyError(f"target path cannot be resolved: {candidate}") from exc


def _inspect_target(target: Path, *, force: bool) -> tuple[str, dict[str, bytes]]:
    _reject_control_symlinks(target)
    if not target.exists():
        return "missing", {}

    try:
        nonempty = next(target.iterdir(), None) is not None
    except OSError as exc:
        raise PathPolicyError(f"target directory cannot be inspected: {target}") from exc

    existing: dict[str, bytes] = {}
    for relative in PROJECT_FRAME_PATHS:
        destination = target.joinpath(*PurePosixPath(relative).parts)
        if destination.exists():
            if not destination.is_file():
                raise PathPolicyError(f"control path must be a regular file: {relative}")
            existing[relative] = _read_regular_bytes(
                destination,
                label=f"control file {relative}",
                maximum=MAX_EXISTING_CONTROL_BYTES,
            )

    count = len(existing)
    if 0 < count < len(PROJECT_FRAME_PATHS):
        missing = [path for path in PROJECT_FRAME_PATHS if path not in existing]
        raise RendererError(f"partial project frame; missing control files: {', '.join(missing)}")
    if count == 0:
        if nonempty and not force:
            raise RendererError("target is nonempty and unmanaged; pass force to add the project frame")
        return ("unmanaged" if nonempty else "empty"), existing

    managed: list[bool] = []
    for relative in PROJECT_FRAME_PATHS:
        content = existing[relative]
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RendererError(f"control file must be UTF-8: {relative}") from exc
        marker_id = MARKER_IDS[relative]
        has_marker_text = _MARKER_TEXT_RE.search(text) is not None
        try:
            identifiers = validate_managed_markers(text)
        except RendererError:
            raise RendererError(f"control file has malformed managed markers: {relative}")
        if identifiers and identifiers != (marker_id,):
            raise RendererError(f"control file has unexpected managed markers: {relative}")
        if has_marker_text and not identifiers:
            raise RendererError(f"control file has malformed managed markers: {relative}")
        if identifiers:
            begin, end = _marker_lines(relative)
            lines = text.splitlines()
            if lines.count(begin) != 1 or lines.count(end) != 1:
                raise RendererError(f"control file has the wrong managed marker style: {relative}")
            if relative == "scripts/verify" and not text.startswith("#!/usr/bin/env python3\n"):
                raise RendererError("managed scripts/verify has an invalid interpreter line")
            managed.append(True)
        else:
            managed.append(False)

    if any(managed) and not all(managed):
        raise RendererError("project frame mixes managed and unmanaged control files")
    if all(managed):
        return "managed", existing
    if not force:
        raise RendererError("project frame is unmanaged; pass force to replace all control files")
    return "unmanaged", existing


def _reject_control_symlinks(target: Path) -> None:
    if target.is_symlink():
        raise PathPolicyError("target path must not be a symlink")
    for relative in PROJECT_FRAME_PATHS:
        current = target
        for part in PurePosixPath(relative).parts:
            current = current / part
            if current.is_symlink():
                raise PathPolicyError(f"control path must not be a symlink: {relative}")
            if current.exists() and current != target and part != PurePosixPath(relative).name:
                if not current.is_dir():
                    raise PathPolicyError(f"control parent must be a directory: {relative}")


def _replace_managed_block(relative: str, existing: bytes, rendered: bytes) -> bytes:
    try:
        existing_text = existing.decode("utf-8")
        rendered_text = rendered.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RendererError(f"managed control file must be UTF-8: {relative}") from exc
    marker_id = MARKER_IDS[relative]
    validate_managed_markers(existing_text, expected_id=marker_id)
    validate_managed_markers(rendered_text, expected_id=marker_id)
    existing_start, existing_end = _managed_block_offsets(existing_text, relative)
    rendered_start, rendered_end = _managed_block_offsets(rendered_text, relative)
    block = rendered_text[rendered_start:rendered_end]
    return (existing_text[:existing_start] + block + existing_text[existing_end:]).encode("utf-8")


def _managed_block_offsets(text: str, relative: str) -> tuple[int, int]:
    begin, end = _marker_lines(relative)
    begin_token = begin + "\n"
    start = text.find(begin_token)
    if start < 0:
        raise RendererError(f"managed BEGIN marker not found: {relative}")
    end_start = text.find(end, start + len(begin_token))
    if end_start < 0:
        raise RendererError(f"managed END marker not found: {relative}")
    end_offset = end_start + len(end)
    if text[end_offset : end_offset + 1] == "\n":
        end_offset += 1
    return start, end_offset


def _marker_lines(relative: str) -> tuple[str, str]:
    marker_id = MARKER_IDS[relative]
    if relative == "scripts/verify":
        return f"# BEGIN PLZDO-LOCAL:{marker_id}", f"# END PLZDO-LOCAL:{marker_id}"
    return f"<!-- BEGIN PLZDO-LOCAL:{marker_id} -->", f"<!-- END PLZDO-LOCAL:{marker_id} -->"


def _read_regular_bytes(path: Path, *, label: str, maximum: int) -> bytes:
    if path.is_symlink():
        raise RendererError(f"{label} must not be a symlink")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RendererError(f"{label} is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RendererError(f"{label} must be a regular file")
        if metadata.st_size > maximum:
            raise RendererError(f"{label} exceeds the byte limit")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(65536, maximum + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum:
                raise RendererError(f"{label} exceeds the byte limit")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _reject_path_symlinks(root: Path, parts: tuple[str, ...], *, label: str) -> None:
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise RendererError(f"{label} must not cross a symlink")


def _validate_relative_path(relative: str) -> None:
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise RendererError(f"unsafe project-frame path: {relative}")
    if path.as_posix() != relative:
        raise RendererError(f"non-canonical project-frame path: {relative}")


def _contains_parent_reference(path: Path) -> bool:
    return any(part == ".." for part in path.parts)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
