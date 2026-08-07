from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple, Union

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9/3.10 use the strict fixed-format fallback below.
    tomllib = None  # type: ignore[assignment]

from . import __version__


MANAGED_INSTALL_SCHEMA_VERSION = "plzdo-local.managed-install.v1"
STATIC_CATALOG_SCHEMA_VERSION = "plzdo-local.static-catalog.v1"
MANAGED_BY = "plzdo-local"
MANAGED_MARKER = ".plzdo-local-managed.json"

RESOURCE_SKILL = "skill"
RESOURCE_AGENT = "agent"
RESOURCE_TYPES = (RESOURCE_SKILL, RESOURCE_AGENT)

PUBLIC_SKILLS = (
    "leak-check",
    "plzdo-project-harness",
    "ponytail",
    "project-start",
)
PUBLIC_AGENTS = (
    "code-reviewer",
    "explorer",
    "reality-checker",
    "technical-writer",
    "tester",
)
STATIC_CATALOGS = ("design", "sources")

_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
_RESOURCE_ROOTS = {
    RESOURCE_SKILL: _REPOSITORY_ROOT / "resources" / "public-skills",
    RESOURCE_AGENT: _REPOSITORY_ROOT / "resources" / "public-agents",
}
_RESOURCE_FILES = {
    RESOURCE_SKILL: {name: ("SKILL.md",) for name in PUBLIC_SKILLS},
    RESOURCE_AGENT: {name: (name + ".toml",) for name in PUBLIC_AGENTS},
}
_CATALOG_ROOT = _REPOSITORY_ROOT / "resources" / "catalogs"

_SAFE_ID = re.compile(r"^[a-z][a-z0-9-]{1,63}(?![\s\S])$")
_SHA256 = re.compile(r"^[0-9a-f]{64}(?![\s\S])$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(?![\s\S])$")
_COMMIT_REVISION = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})(?![\s\S])$")
_DIGEST_REVISION = re.compile(r"^sha256:[0-9a-f]{64}(?![\s\S])$")
_NAMED_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+:-]{0,127}(?![\s\S])$")
_MOVABLE_REVISIONS = {
    "branch",
    "branches",
    "head",
    "heads",
    "latest",
    "main",
    "master",
    "merge-requests",
    "origin",
    "pull",
    "remote",
    "remotes",
    "tip",
    "trunk",
    "upstream",
}
_BRANCH_REVISION = re.compile(
    r"^(?:(?:refs/)?(?:heads|remotes|branches|pull|merge-requests|changes)/"
    r"|(?:origin|upstream|remote)/)",
    re.IGNORECASE,
)
_GIT_SOURCE_URL = re.compile(
    r"^https://(?:www\.)?(?:github\.com|gitlab\.com|bitbucket\.org|codeberg\.org|"
    r"raw\.githubusercontent\.com)/",
    re.IGNORECASE,
)
_SAFE_RELATIVE_PATH = re.compile(
    r"^(?!\.plzdo-local-managed\.json(?:/|$))"
    r"(?:[A-Za-z0-9_-][A-Za-z0-9._-]*|\.[A-Za-z0-9_-][A-Za-z0-9._-]*)"
    r"(?:/(?:[A-Za-z0-9_-][A-Za-z0-9._-]*|\.[A-Za-z0-9_-][A-Za-z0-9._-]*))*"
    r"(?![\s\S])$"
)
_FIXED_AGENT_TOML = re.compile(
    r'\Aschema_version = (?P<schema>"(?:[^"\\]|\\.)*")\n'
    r'name = (?P<name>"(?:[^"\\]|\\.)*")\n'
    r'description = (?P<description>"(?:[^"\\]|\\.)*")\n'
    r'instructions = """\n(?P<instructions>.*?\n)"""\n?\Z',
    re.DOTALL,
)
_MAX_RESOURCE_BYTES = 512 * 1024
_MAX_MARKER_BYTES = 64 * 1024
_MAX_CATALOG_BYTES = 512 * 1024
_MAX_FILES = 32
_MAX_DRIFT_ENTRIES = 4096
_MAX_DRIFT_DEPTH = 128
_MAX_DRIFT_BYTES = (_MAX_RESOURCE_BYTES * _MAX_FILES) + _MAX_MARKER_BYTES

_TEST_OPERATION_HOOK: Optional[Callable[[str, Mapping[str, Path]], None]] = None
_TEST_SCANDIR_OBSERVER: Optional[Callable[[str], None]] = None
_TEST_CLEANUP_HOOK: Optional[Callable[[str], None]] = None

PathInput = Union[str, Path]


class ManagedInstallError(ValueError):
    """Base error for fixed, repository-owned resource installation."""


class UnknownManagedResourceError(ManagedInstallError):
    """Raised when a resource type or name is not in the public allowlist."""


class ManagedInstallPathError(ManagedInstallError):
    """Raised when a destination or bundled source has an unsafe shape."""


class ManagedInstallCollisionError(ManagedInstallError):
    """Raised when a destination is present but is not owned by this installer."""


class ManagedInstallDriftError(ManagedInstallError):
    """Raised when marker metadata and installed bytes no longer agree."""


class StaticCatalogError(ValueError):
    """Raised when a bundled static catalog is unknown or malformed."""


def list_resources(resource_type: str) -> Tuple[str, ...]:
    """Return the fixed public allowlist for one resource type."""

    kind = _normalize_resource_type(resource_type)
    return tuple(sorted(_RESOURCE_FILES[kind]))


def list_public_skills() -> Tuple[str, ...]:
    return list_resources(RESOURCE_SKILL)


def list_public_agents() -> Tuple[str, ...]:
    return list_resources(RESOURCE_AGENT)


def resource_destination(resource_type: str, name: str, destination_root: PathInput) -> Path:
    """Resolve the fixed destination for an allowlisted resource."""

    kind, resource_name = _require_resource(resource_type, name)
    root = _normalize_destination_root(destination_root)
    target, _marker = _destination_paths(kind, resource_name, root)
    return target


def inspect_resource(
    resource_type: str,
    name: str,
    destination_root: PathInput,
) -> Dict[str, Any]:
    """Inspect marker and content integrity without changing the destination."""

    kind, resource_name = _require_resource(resource_type, name)
    root = _normalize_destination_root(destination_root)
    inspection = _inspect_installation(kind, resource_name, root)
    target, marker = _destination_paths(kind, resource_name, root)
    result: Dict[str, Any] = {
        "resourceType": kind,
        "resourceName": resource_name,
        "destination": str(target),
        "marker": str(marker),
        "status": inspection["status"],
        "reason": inspection["reason"],
        "releaseVersion": None,
        "resourceDigest": None,
    }
    manifest = inspection.get("manifest")
    if isinstance(manifest, dict):
        result["releaseVersion"] = manifest["releaseVersion"]
        result["resourceDigest"] = manifest["resourceDigest"]
    return result


def plan_install(
    resource_type: str,
    name: str,
    destination_root: PathInput,
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """Build a non-writing install plan from fixed repository resources."""

    prepared = _prepare_install(resource_type, name, destination_root, force=force)
    return dict(prepared["plan"])


def install_resource(
    resource_type: str,
    name: str,
    destination_root: PathInput,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    """Install one allowlisted resource and its deterministic ownership marker."""

    prepared = _prepare_install(resource_type, name, destination_root, force=force)
    plan = dict(prepared["plan"])
    plan["dryRun"] = bool(dry_run)
    if dry_run or not plan["changed"]:
        return plan

    kind = prepared["resourceType"]
    resource_name = prepared["resourceName"]
    root = prepared["destinationRoot"]
    source_files = prepared["sourceFiles"]
    manifest = prepared["manifest"]
    inspection = prepared["inspection"]
    _run_operation_hook("before-root-create", kind, resource_name, root)
    _prepare_writable_root(root)
    root_fd = _open_directory_descriptor(root, label="managed destination root")
    try:
        _require_root_identity(root, root_fd)
        current = _inspect_installation_at(kind, resource_name, root_fd)
        _require_prepared_snapshot(current, inspection)
        _write_installation(
            kind,
            resource_name,
            root,
            root_fd,
            source_files,
            manifest,
            current,
        )
        final = _inspect_installation_at(kind, resource_name, root_fd)
        if final["status"] != "managed" or final.get("manifest") != manifest:
            raise ManagedInstallDriftError("installed resource did not verify against its marker")
    finally:
        os.close(root_fd)
    return plan


def plan_uninstall(
    resource_type: str,
    name: str,
    destination_root: PathInput,
) -> Dict[str, Any]:
    """Build a non-writing removal plan for exact managed content only."""

    prepared = _prepare_uninstall(resource_type, name, destination_root)
    return dict(prepared["plan"])


def uninstall_resource(
    resource_type: str,
    name: str,
    destination_root: PathInput,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Remove only content whose current bytes exactly match its managed marker."""

    prepared = _prepare_uninstall(resource_type, name, destination_root)
    plan = dict(prepared["plan"])
    plan["dryRun"] = bool(dry_run)
    if dry_run or not plan["changed"]:
        return plan

    kind = prepared["resourceType"]
    resource_name = prepared["resourceName"]
    root = prepared["destinationRoot"]
    root_fd = _open_directory_descriptor(root, label="managed destination root")
    try:
        _require_root_identity(root, root_fd)
        current = _inspect_installation_at(kind, resource_name, root_fd)
        _require_prepared_snapshot(current, prepared["inspection"])
        _remove_installation(kind, resource_name, root, root_fd, current)
        final = _inspect_installation_at(kind, resource_name, root_fd)
        if final["status"] != "absent":
            raise ManagedInstallDriftError("managed resource removal did not restore an absent state")
    finally:
        os.close(root_fd)
    return plan


def install_skill(
    name: str,
    destination_root: PathInput,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    return install_resource(RESOURCE_SKILL, name, destination_root, dry_run=dry_run, force=force)


def uninstall_skill(
    name: str,
    destination_root: PathInput,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    return uninstall_resource(RESOURCE_SKILL, name, destination_root, dry_run=dry_run)


def install_agent(
    name: str,
    destination_root: PathInput,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    return install_resource(RESOURCE_AGENT, name, destination_root, dry_run=dry_run, force=force)


def uninstall_agent(
    name: str,
    destination_root: PathInput,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    return uninstall_resource(RESOURCE_AGENT, name, destination_root, dry_run=dry_run)


def load_static_catalog(catalog: str) -> Dict[str, Any]:
    """Load and validate one repository-vendored metadata catalog."""

    catalog_name = _normalize_catalog_name(catalog)
    path = _CATALOG_ROOT / (catalog_name + ".json")
    raw = _read_fixed_regular_file(path, root=_CATALOG_ROOT, maximum=_MAX_CATALOG_BYTES)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StaticCatalogError("static catalog must be valid UTF-8 JSON") from exc
    validate_static_catalog(value, expected_catalog=catalog_name)
    return value


def validate_static_catalog(value: Any, *, expected_catalog: Optional[str] = None) -> None:
    """Validate the exact local-only static catalog contract."""

    if not isinstance(value, dict):
        raise StaticCatalogError("static catalog must be an object")
    _require_exact_keys(
        value,
        ("schemaVersion", "catalog", "localOnly", "entries"),
        label="static catalog",
        error_type=StaticCatalogError,
    )
    if value["schemaVersion"] != STATIC_CATALOG_SCHEMA_VERSION:
        raise StaticCatalogError("static catalog schemaVersion is unsupported")
    catalog_name = _normalize_catalog_name(value["catalog"])
    if expected_catalog is not None and catalog_name != _normalize_catalog_name(expected_catalog):
        raise StaticCatalogError("static catalog identity does not match its fixed file")
    if value["localOnly"] is not True:
        raise StaticCatalogError("static catalog must declare localOnly=true")
    entries = value["entries"]
    if not isinstance(entries, list) or not entries or len(entries) > 128:
        raise StaticCatalogError("static catalog entries must be a non-empty bounded list")
    seen = set()
    previous = ""
    for index, entry in enumerate(entries):
        label = "static catalog entry %d" % index
        if not isinstance(entry, dict):
            raise StaticCatalogError(label + " must be an object")
        _require_exact_keys(
            entry,
            (
                "id",
                "name",
                "description",
                "sourceUrl",
                "licenseStatus",
                "licenseUrl",
                "revisionKind",
                "reviewedRevision",
                "reviewedDate",
                "decision",
                "tags",
            ),
            label=label,
            error_type=StaticCatalogError,
        )
        entry_id = _require_safe_id(entry["id"], label=label + ".id", error_type=StaticCatalogError)
        if entry_id in seen or entry_id <= previous:
            raise StaticCatalogError("static catalog entries must have unique sorted ids")
        seen.add(entry_id)
        previous = entry_id
        _require_text(entry["name"], label=label + ".name", maximum=120, error_type=StaticCatalogError)
        _require_text(
            entry["description"],
            label=label + ".description",
            maximum=500,
            error_type=StaticCatalogError,
        )
        for key in ("sourceUrl", "licenseUrl"):
            url = _require_text(entry[key], label=label + "." + key, maximum=500, error_type=StaticCatalogError)
            if not url.startswith("https://") or any(char.isspace() for char in url):
                raise StaticCatalogError(label + "." + key + " must be an HTTPS URL")
        if entry["licenseStatus"] not in ("verified-open", "review-required"):
            raise StaticCatalogError(label + ".licenseStatus is unsupported")
        revision_kind = entry["revisionKind"]
        if revision_kind not in ("commit", "digest", "spec-version", "tag", "unversioned"):
            raise StaticCatalogError(label + ".revisionKind is unsupported")
        reviewed_revision = _require_text(
            entry["reviewedRevision"],
            label=label + ".reviewedRevision",
            maximum=160,
            error_type=StaticCatalogError,
        )
        revision_parts = set(re.split(r"[/@:]+", reviewed_revision.casefold()))
        if revision_parts & _MOVABLE_REVISIONS or _BRANCH_REVISION.search(reviewed_revision):
            raise StaticCatalogError(label + ".reviewedRevision is a movable revision")
        if revision_kind == "commit" and _COMMIT_REVISION.fullmatch(reviewed_revision) is None:
            raise StaticCatalogError(label + ".reviewedRevision must be an exact commit id")
        if revision_kind == "digest" and _DIGEST_REVISION.fullmatch(reviewed_revision) is None:
            raise StaticCatalogError(label + ".reviewedRevision must be an exact sha256 digest")
        if revision_kind in ("tag", "spec-version") and _NAMED_REVISION.fullmatch(reviewed_revision) is None:
            raise StaticCatalogError(label + ".reviewedRevision must be an exact named revision")
        if revision_kind == "unversioned" and reviewed_revision != "unversioned":
            raise StaticCatalogError(label + ".reviewedRevision must declare unversioned evidence exactly")
        if entry["licenseStatus"] == "verified-open":
            git_derived = _GIT_SOURCE_URL.search(entry["sourceUrl"]) is not None or entry[
                "sourceUrl"
            ].casefold().endswith(".git")
            allowed_evidence = ("commit", "digest") if git_derived else (
                "commit",
                "digest",
                "spec-version",
            )
            if revision_kind not in allowed_evidence:
                raise StaticCatalogError(
                    label + " cannot be verified-open without fixed source revision evidence"
                )
        reviewed_date = entry["reviewedDate"]
        if not isinstance(reviewed_date, str) or _DATE.fullmatch(reviewed_date) is None:
            raise StaticCatalogError(label + ".reviewedDate must be YYYY-MM-DD")
        if entry["decision"] not in ("adopt", "reference", "exclude"):
            raise StaticCatalogError(label + ".decision is unsupported")
        tags = entry["tags"]
        if not isinstance(tags, list) or not tags or len(tags) > 12:
            raise StaticCatalogError(label + ".tags must be a non-empty bounded list")
        normalized_tags = []
        for tag in tags:
            normalized_tags.append(
                _require_safe_id(tag, label=label + ".tags", error_type=StaticCatalogError)
            )
        if normalized_tags != sorted(set(normalized_tags)):
            raise StaticCatalogError(label + ".tags must be sorted and unique")


def list_catalog_entries(catalog: str) -> Tuple[Dict[str, Any], ...]:
    value = load_static_catalog(catalog)
    return tuple(_copy_json_object(entry) for entry in value["entries"])


def search_static_catalog(catalog: str, query: str) -> Tuple[Dict[str, Any], ...]:
    """Search vendored metadata only; this function has no transport path."""

    text = _require_text(query, label="query", maximum=200, error_type=StaticCatalogError)
    tokens = tuple(part for part in re.split(r"[^a-z0-9]+", text.casefold()) if part)
    matches = []
    for entry in list_catalog_entries(catalog):
        searchable = " ".join(
            [
                entry["id"],
                entry["name"],
                entry["description"],
                entry["licenseStatus"],
                entry["revisionKind"],
                entry["reviewedRevision"],
                entry["decision"],
            ]
            + entry["tags"]
        ).casefold()
        if all(token in searchable for token in tokens):
            matches.append(entry)
    return tuple(matches)


def show_static_catalog_entry(catalog: str, entry_id: str) -> Dict[str, Any]:
    wanted = _require_safe_id(entry_id, label="entry id", error_type=StaticCatalogError)
    for entry in list_catalog_entries(catalog):
        if entry["id"] == wanted:
            return entry
    raise StaticCatalogError("static catalog entry was not found: " + wanted)


def _prepare_install(
    resource_type: str,
    name: str,
    destination_root: PathInput,
    *,
    force: bool,
) -> Dict[str, Any]:
    kind, resource_name = _require_resource(resource_type, name)
    root = _normalize_destination_root(destination_root)
    source_files = _load_source_files(kind, resource_name)
    manifest = _build_manifest(kind, resource_name, source_files)
    inspection = _inspect_installation(kind, resource_name, root)
    status = inspection["status"]
    if status == "unmanaged":
        raise ManagedInstallCollisionError("destination exists without a valid managed marker")
    if status == "drifted":
        if not force:
            raise ManagedInstallDriftError("managed destination has drifted from its marker")
        if inspection.get("manifest") is None:
            raise ManagedInstallDriftError("force cannot repair an untrusted or malformed marker")
        _require_repair_scope(kind, resource_name, inspection, manifest)
        operation = "repair"
    elif status == "managed":
        operation = "unchanged" if inspection["manifest"] == manifest else "upgrade"
    else:
        operation = "create"
    target, marker = _destination_paths(kind, resource_name, root)
    changed = operation != "unchanged"
    plan = {
        "action": "install",
        "resourceType": kind,
        "resourceName": resource_name,
        "destination": str(target),
        "marker": str(marker),
        "operation": operation,
        "changed": changed,
        "dryRun": True,
        "force": bool(force),
        "resourceDigest": manifest["resourceDigest"],
        "writes": [str(target), str(marker)] if changed else [],
        "removals": [],
    }
    return {
        "resourceType": kind,
        "resourceName": resource_name,
        "destinationRoot": root,
        "sourceFiles": source_files,
        "manifest": manifest,
        "inspection": inspection,
        "plan": plan,
    }


def _prepare_uninstall(
    resource_type: str,
    name: str,
    destination_root: PathInput,
) -> Dict[str, Any]:
    kind, resource_name = _require_resource(resource_type, name)
    root = _normalize_destination_root(destination_root)
    inspection = _inspect_installation(kind, resource_name, root)
    status = inspection["status"]
    if status == "unmanaged":
        raise ManagedInstallCollisionError("destination is unmanaged and cannot be removed")
    if status == "drifted":
        raise ManagedInstallDriftError("uninstall requires exact managed content")
    target, marker = _destination_paths(kind, resource_name, root)
    changed = status == "managed"
    plan = {
        "action": "uninstall",
        "resourceType": kind,
        "resourceName": resource_name,
        "destination": str(target),
        "marker": str(marker),
        "operation": "remove" if changed else "absent",
        "changed": changed,
        "dryRun": True,
        "resourceDigest": inspection["manifest"]["resourceDigest"] if changed else None,
        "writes": [],
        "removals": [str(target), str(marker)] if changed else [],
    }
    return {
        "resourceType": kind,
        "resourceName": resource_name,
        "destinationRoot": root,
        "inspection": inspection,
        "plan": plan,
    }


def _inspect_installation(kind: str, name: str, root: Path) -> Dict[str, Any]:
    if not _lexists(root):
        state = _empty_installation_state(kind)
        result = _inspect_captured_installation(kind, name, state)
        result["snapshot"] = state["snapshot"]
        result["_state"] = state
        return result
    root_fd = _open_directory_descriptor(root, label="managed destination root")
    try:
        return _inspect_installation_at(kind, name, root_fd)
    finally:
        os.close(root_fd)


def _inspect_installation_at(kind: str, name: str, root_fd: int) -> Dict[str, Any]:
    try:
        before = _capture_installation_state_at(kind, name, root_fd)
        result = _inspect_captured_installation(kind, name, before)
        after = _capture_installation_state_at(kind, name, root_fd)
    except (OSError, ManagedInstallError) as exc:
        return {
            "status": "drifted",
            "reason": "managed installation could not be safely traversed: " + str(exc),
            "manifest": None,
        }
    if before["snapshot"] != after["snapshot"]:
        return {
            "status": "drifted",
            "reason": "managed installation changed while it was inspected",
            "manifest": None,
        }
    result["snapshot"] = after["snapshot"]
    result["_state"] = after
    return result


def _inspect_captured_installation(kind: str, name: str, state: Mapping[str, Any]) -> Dict[str, Any]:
    records = state["records"]
    files = state["files"]
    if kind == RESOURCE_SKILL:
        target_kind = state["targetKind"]
        if target_kind == "absent":
            return {"status": "absent", "reason": None, "manifest": None}
        if target_kind != "directory":
            return {
                "status": "unmanaged",
                "reason": "skill destination is not an owned directory",
                "manifest": None,
            }
        marker_path = MANAGED_MARKER
    else:
        target_path = name + ".toml"
        marker_path = "." + name + ".toml" + MANAGED_MARKER
        if target_path not in records and marker_path not in records:
            return {"status": "absent", "reason": None, "manifest": None}

    marker_record = records.get(marker_path)
    if marker_record is None:
        return {"status": "unmanaged", "reason": "managed marker is absent", "manifest": None}
    if marker_record[0] != "file":
        return {
            "status": "drifted",
            "reason": "managed marker is not a regular file",
            "manifest": None,
        }
    try:
        raw = files[marker_path]
        if len(raw) > _MAX_MARKER_BYTES:
            raise ManagedInstallDriftError("managed marker exceeds the allowed size")
        manifest = json.loads(raw.decode("utf-8"))
        validate_managed_install_marker(manifest, resource_type=kind, resource_name=name)
    except (UnicodeDecodeError, json.JSONDecodeError, ManagedInstallError) as exc:
        return {
            "status": "drifted",
            "reason": "managed marker is malformed: " + str(exc),
            "manifest": None,
        }
    if raw != _serialize_json(manifest):
        return {"status": "drifted", "reason": "managed marker bytes drifted", "manifest": manifest}
    if marker_record[1] != 0o644:
        return {"status": "drifted", "reason": "managed marker mode drifted", "manifest": manifest}

    if kind == RESOURCE_SKILL:
        inventory_error = _captured_skill_inventory_error(records, manifest)
        if inventory_error is not None:
            return {"status": "drifted", "reason": inventory_error, "manifest": manifest}
    else:
        target_path = name + ".toml"
        target_record = records.get(target_path)
        if target_record is None:
            return {"status": "drifted", "reason": "managed destination is missing", "manifest": manifest}
        if target_record[0] != "file":
            return {
                "status": "drifted",
                "reason": "managed agent destination is not a regular file",
                "manifest": manifest,
            }
        if [entry["path"] for entry in manifest["files"]] != [target_path]:
            return {
                "status": "drifted",
                "reason": "agent marker has an unexpected file inventory",
                "manifest": manifest,
            }

    for entry in manifest["files"]:
        record = records.get(entry["path"])
        if record is None or record[0] != "file":
            return {
                "status": "drifted",
                "reason": "managed file is missing or unsafe: " + entry["path"],
                "manifest": manifest,
            }
        if record[1] != entry["mode"]:
            return {
                "status": "drifted",
                "reason": "managed file mode drifted: " + entry["path"],
                "manifest": manifest,
            }
        if record[2] != entry["sizeBytes"]:
            return {
                "status": "drifted",
                "reason": "managed file size drifted: " + entry["path"],
                "manifest": manifest,
            }
        if record[3] != entry["sha256"]:
            return {
                "status": "drifted",
                "reason": "managed file hash drifted: " + entry["path"],
                "manifest": manifest,
            }
    return {"status": "managed", "reason": None, "manifest": manifest}


def _captured_skill_inventory_error(
    records: Mapping[str, Tuple[str, int, int, str]],
    manifest: Mapping[str, Any],
) -> Optional[str]:
    expected_files = {entry["path"] for entry in manifest["files"]}
    expected_files.add(MANAGED_MARKER)
    expected_directories = set()
    for relative in expected_files:
        parent = PurePosixPath(relative).parent
        while str(parent) != ".":
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    for relative, record in records.items():
        if record[0] == "symlink":
            return "managed skill inventory contains a symlink: " + relative
        if record[0] not in ("directory", "file"):
            return "managed skill inventory contains a non-regular entry: " + relative
    actual_files = {relative for relative, record in records.items() if record[0] == "file"}
    actual_directories = {relative for relative, record in records.items() if record[0] == "directory"}
    if actual_files != expected_files or actual_directories != expected_directories:
        return "managed skill inventory drifted"
    return None


def _require_repair_scope(
    kind: str,
    name: str,
    inspection: Mapping[str, Any],
    new_manifest: Mapping[str, Any],
) -> None:
    old_manifest = inspection["manifest"]
    records = inspection["_state"]["records"]
    if kind == RESOURCE_AGENT:
        target_record = records.get(name + ".toml")
        if target_record is not None and target_record[0] != "file":
            raise ManagedInstallCollisionError("force cannot replace a non-regular agent destination")
        return
    allowed_files = {MANAGED_MARKER}
    allowed_files.update(entry["path"] for entry in old_manifest["files"])
    allowed_files.update(entry["path"] for entry in new_manifest["files"])
    allowed_directories = set()
    for relative in allowed_files:
        parent = PurePosixPath(relative).parent
        while str(parent) != ".":
            allowed_directories.add(parent.as_posix())
            parent = parent.parent
    for relative, record in records.items():
        if record[0] == "symlink":
            raise ManagedInstallCollisionError("force cannot replace a skill containing symlinks")
        if record[0] == "directory":
            if relative not in allowed_directories:
                raise ManagedInstallCollisionError("force cannot remove an untracked skill directory")
        elif record[0] == "file":
            if relative not in allowed_files:
                raise ManagedInstallCollisionError("force cannot remove an untracked skill file")
        else:
            raise ManagedInstallCollisionError("force cannot replace a skill containing special files")


def _load_source_files(kind: str, name: str) -> Dict[str, bytes]:
    root = _RESOURCE_ROOTS[kind]
    source_root = root / name if kind == RESOURCE_SKILL else root
    result = {}
    total = 0
    for relative in _RESOURCE_FILES[kind][name]:
        path = source_root / relative
        data = _read_fixed_regular_file(path, root=source_root, maximum=_MAX_RESOURCE_BYTES)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ManagedInstallPathError("bundled resources must be UTF-8 text") from exc
        if "\x00" in text:
            raise ManagedInstallPathError("bundled resources must not contain NUL bytes")
        total += len(data)
        if total > _MAX_RESOURCE_BYTES:
            raise ManagedInstallPathError("bundled resource exceeds the size limit")
        if kind == RESOURCE_AGENT:
            _parse_agent_descriptor(text, expected_name=name)
        result[relative] = data
    return result


def _parse_agent_descriptor(text: str, *, expected_name: str) -> Dict[str, str]:
    if tomllib is not None:
        try:
            value = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ManagedInstallPathError("bundled agent descriptor must be valid TOML") from exc
    else:
        match = _FIXED_AGENT_TOML.fullmatch(text)
        if match is None:
            raise ManagedInstallPathError("bundled agent descriptor must use the fixed TOML shape")
        value = {
            "schema_version": _decode_restricted_toml_string(match.group("schema")[1:-1]),
            "name": _decode_restricted_toml_string(match.group("name")[1:-1]),
            "description": _decode_restricted_toml_string(match.group("description")[1:-1]),
            "instructions": _decode_restricted_toml_string(
                match.group("instructions"),
                multiline=True,
            ),
        }
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "name",
        "description",
        "instructions",
    }:
        raise ManagedInstallPathError("bundled agent descriptor keys mismatch")
    if value["schema_version"] != "plzdo-local.agent.v1" or value["name"] != expected_name:
        raise ManagedInstallPathError("bundled agent descriptor identity is invalid")
    description = _require_text(
        value["description"],
        label="bundled agent description",
        maximum=500,
        error_type=ManagedInstallPathError,
    )
    if "\x7f" in description:
        raise ManagedInstallPathError("bundled agent description contains DEL")
    instructions = value["instructions"]
    if (
        not isinstance(instructions, str)
        or not instructions.strip()
        or len(instructions) > 8000
        or "\x00" in instructions
        or any((ord(char) < 32 and char not in "\n\t") or ord(char) == 127 for char in instructions)
    ):
        raise ManagedInstallPathError("bundled agent instructions must be bounded text")
    return {
        "schema_version": value["schema_version"],
        "name": value["name"],
        "description": description,
        "instructions": instructions,
    }


def _decode_restricted_toml_string(value: str, *, multiline: bool = False) -> str:
    """Decode TOML basic-string escapes used by the fixed Python 3.9 grammar."""

    escapes = {
        "b": "\b",
        "t": "\t",
        "n": "\n",
        "f": "\f",
        "r": "\r",
        '"': '"',
        "\\": "\\",
    }
    output: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character != "\\":
            if (
                ord(character) == 127
                or ord(character) < 32
                and character not in (("\n", "\t") if multiline else ())
            ):
                raise ManagedInstallPathError("bundled agent descriptor contains an invalid control character")
            output.append(character)
            index += 1
            continue
        if index + 1 >= len(value):
            raise ManagedInstallPathError("bundled agent descriptor contains an incomplete escape")
        escape = value[index + 1]
        if escape in escapes:
            output.append(escapes[escape])
            index += 2
            continue
        if escape in ("u", "U"):
            width = 4 if escape == "u" else 8
            encoded = value[index + 2 : index + 2 + width]
            if len(encoded) != width or any(character not in "0123456789abcdefABCDEF" for character in encoded):
                raise ManagedInstallPathError("bundled agent descriptor contains an invalid Unicode escape")
            codepoint = int(encoded, 16)
            if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
                raise ManagedInstallPathError("bundled agent descriptor contains an invalid Unicode scalar")
            output.append(chr(codepoint))
            index += 2 + width
            continue
        raise ManagedInstallPathError("bundled agent descriptor contains an unsupported escape")
    return "".join(output)


def _build_manifest(kind: str, name: str, source_files: Mapping[str, bytes]) -> Dict[str, Any]:
    entries = []
    for relative in sorted(source_files):
        data = source_files[relative]
        entries.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "sizeBytes": len(data),
                "mode": 0o644,
            }
        )
    manifest = {
        "schemaVersion": MANAGED_INSTALL_SCHEMA_VERSION,
        "managedBy": MANAGED_BY,
        "resourceType": kind,
        "resourceName": name,
        "releaseVersion": __version__,
        "resourceDigest": _resource_digest(entries),
        "files": entries,
    }
    validate_managed_install_marker(manifest, resource_type=kind, resource_name=name)
    return manifest


def validate_managed_install_marker(
    value: Any,
    *,
    resource_type: str,
    resource_name: str,
) -> None:
    """Apply semantic marker checks that JSON Schema cannot represent."""

    expected_kind = _normalize_resource_type(resource_type)
    expected_name = _require_safe_id(
        resource_name,
        label="managed marker resource name",
        error_type=ManagedInstallDriftError,
    )
    if not isinstance(value, dict):
        raise ManagedInstallDriftError("managed marker must be an object")
    _require_exact_keys(
        value,
        (
            "schemaVersion",
            "managedBy",
            "resourceType",
            "resourceName",
            "releaseVersion",
            "resourceDigest",
            "files",
        ),
        label="managed marker",
        error_type=ManagedInstallDriftError,
    )
    if value["schemaVersion"] != MANAGED_INSTALL_SCHEMA_VERSION or value["managedBy"] != MANAGED_BY:
        raise ManagedInstallDriftError("managed marker identity is unsupported")
    if value["resourceType"] != expected_kind or value["resourceName"] != expected_name:
        raise ManagedInstallDriftError("managed marker resource identity does not match its destination")
    _require_text(
        value["releaseVersion"],
        label="managed marker releaseVersion",
        maximum=64,
        error_type=ManagedInstallDriftError,
    )
    files = value["files"]
    if not isinstance(files, list) or not files or len(files) > _MAX_FILES:
        raise ManagedInstallDriftError("managed marker files must be a non-empty bounded list")
    previous = ""
    seen = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise ManagedInstallDriftError("managed marker file entry must be an object")
        _require_exact_keys(
            entry,
            ("path", "sha256", "sizeBytes", "mode"),
            label="managed marker file",
            error_type=ManagedInstallDriftError,
        )
        relative = _require_safe_relative_path(entry["path"])
        if relative in seen or relative <= previous:
            raise ManagedInstallDriftError("managed marker file paths must be unique and sorted")
        seen.add(relative)
        previous = relative
        if not isinstance(entry["sha256"], str) or _SHA256.fullmatch(entry["sha256"]) is None:
            raise ManagedInstallDriftError("managed marker file sha256 is invalid")
        if type(entry["sizeBytes"]) is not int or not 0 <= entry["sizeBytes"] <= _MAX_RESOURCE_BYTES:
            raise ManagedInstallDriftError("managed marker file sizeBytes is invalid")
        if type(entry["mode"]) is not int or entry["mode"] not in (0o644, 0o755):
            raise ManagedInstallDriftError("managed marker file mode is invalid")
    if expected_kind == RESOURCE_AGENT and [entry["path"] for entry in files] != [expected_name + ".toml"]:
        raise ManagedInstallDriftError("managed agent marker must name its fixed descriptor")
    digest = value["resourceDigest"]
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise ManagedInstallDriftError("managed marker resourceDigest is invalid")
    if digest != _resource_digest(files):
        raise ManagedInstallDriftError("managed marker resourceDigest does not match its file inventory")


def _validate_manifest(value: Any, *, expected_kind: str, expected_name: str) -> None:
    validate_managed_install_marker(
        value,
        resource_type=expected_kind,
        resource_name=expected_name,
    )


def _write_installation(
    kind: str,
    name: str,
    root: Path,
    root_fd: int,
    source_files: Mapping[str, bytes],
    manifest: Mapping[str, Any],
    inspection: Mapping[str, Any],
) -> None:
    stage_name, stage_fd = _new_operation_directory_at(root_fd, "install")
    stage_path = root / stage_name
    quarantine_name: Optional[str] = None
    quarantine_fd: Optional[int] = None
    published: list[Tuple[str, Tuple[int, int, int, int, int]]] = []
    stage_is_owned = True
    try:
        _populate_stage_at(kind, name, stage_fd, source_files, manifest)
        staged = _inspect_installation_at(kind, name, stage_fd)
        if staged["status"] != "managed" or staged.get("manifest") != manifest:
            raise ManagedInstallDriftError("staged resource did not verify against its marker")
        staged_snapshot = staged["snapshot"]

        if inspection["status"] != "absent":
            _run_operation_hook("before-quarantine", kind, name, root, stage=stage_path)
            _require_root_identity(root, root_fd)
            _require_snapshot_at(kind, name, root_fd, inspection["snapshot"])
            quarantine_name, quarantine_fd = _quarantine_installation_at(kind, name, root_fd)
        try:
            if quarantine_name is not None and quarantine_fd is not None:
                quarantine_path = root / quarantine_name
                _run_operation_hook(
                    "after-quarantine",
                    kind,
                    name,
                    root,
                    stage=stage_path,
                    quarantine=quarantine_path,
                )
                _require_root_identity(root, root_fd)
                _require_snapshot_at(kind, name, quarantine_fd, inspection["snapshot"])
            _run_operation_hook(
                "before-publish",
                kind,
                name,
                root,
                stage=stage_path,
                quarantine=root / quarantine_name if quarantine_name is not None else None,
            )
            _require_root_identity(root, root_fd)
            _publish_stage_at(kind, name, stage_fd, root_fd, root, stage_path, published)
            _run_operation_hook(
                "after-publish",
                kind,
                name,
                root,
                stage=stage_path,
                quarantine=root / quarantine_name if quarantine_name is not None else None,
            )
            final = _inspect_installation_at(kind, name, root_fd)
            if final["status"] != "managed" or final.get("manifest") != manifest:
                raise ManagedInstallDriftError("published resource did not verify against its marker")
            if quarantine_name is not None and quarantine_fd is not None:
                _run_operation_hook(
                    "before-cleanup",
                    kind,
                    name,
                    root,
                    stage=stage_path,
                    quarantine=root / quarantine_name,
                )
                _require_root_identity(root, root_fd)
                _require_snapshot_at(kind, name, quarantine_fd, inspection["snapshot"])
            _require_root_identity(root, root_fd)
        except Exception:
            stage_is_owned = False
            stage_is_owned = _rollback_published(
                kind,
                name,
                root_fd,
                stage_fd,
                quarantine_fd,
                published,
                staged_snapshot,
            )
            if quarantine_name is not None and quarantine_fd is not None:
                if _root_identity_matches(root, root_fd):
                    _remove_empty_operation_directory_at(
                        root_fd,
                        quarantine_name,
                        quarantine_fd,
                    )
                    os.close(quarantine_fd)
                    quarantine_fd = None
                    quarantine_name = None
            raise

        _remove_empty_operation_directory_at(root_fd, stage_name, stage_fd)
        os.close(stage_fd)
        stage_fd = -1
        if quarantine_name is not None and quarantine_fd is not None:
            _discard_quarantine_at(root_fd, quarantine_name, quarantine_fd)
            os.close(quarantine_fd)
            quarantine_fd = None
            quarantine_name = None
    finally:
        if stage_fd >= 0:
            try:
                if stage_is_owned and _root_identity_matches(root, root_fd):
                    _discard_operation_directory_at(root_fd, stage_name, stage_fd)
            finally:
                os.close(stage_fd)
        if quarantine_fd is not None:
            os.close(quarantine_fd)


def _remove_installation(
    kind: str,
    name: str,
    root: Path,
    root_fd: int,
    inspection: Mapping[str, Any],
) -> None:
    _run_operation_hook("before-quarantine", kind, name, root)
    _require_root_identity(root, root_fd)
    _require_snapshot_at(kind, name, root_fd, inspection["snapshot"])
    quarantine_name, quarantine_fd = _quarantine_installation_at(kind, name, root_fd)
    try:
        _run_operation_hook(
            "after-quarantine",
            kind,
            name,
            root,
            quarantine=root / quarantine_name,
        )
        _require_root_identity(root, root_fd)
        _require_snapshot_at(kind, name, quarantine_fd, inspection["snapshot"])
        _require_live_destinations_absent_at(kind, name, root_fd)
        _require_root_identity(root, root_fd)
        _run_operation_hook(
            "before-cleanup",
            kind,
            name,
            root,
            quarantine=root / quarantine_name,
        )
        _require_root_identity(root, root_fd)
        _require_snapshot_at(kind, name, quarantine_fd, inspection["snapshot"])
        _require_live_destinations_absent_at(kind, name, root_fd)
    except Exception:
        _restore_quarantine_at(kind, name, quarantine_fd, root_fd)
        if _root_identity_matches(root, root_fd):
            _remove_empty_operation_directory_at(root_fd, quarantine_name, quarantine_fd)
        os.close(quarantine_fd)
        raise
    try:
        _discard_quarantine_at(root_fd, quarantine_name, quarantine_fd)
    finally:
        os.close(quarantine_fd)


def _new_operation_directory_at(root_fd: int, operation: str) -> Tuple[str, int]:
    for _attempt in range(128):
        suffix = hashlib.sha256(os.urandom(32)).hexdigest()[:20]
        name = ".plzdo-" + operation + "-" + suffix
        try:
            os.mkdir(name, mode=0o700, dir_fd=root_fd)
        except FileExistsError:
            continue
        descriptor = _open_directory_at(root_fd, name, label="managed operation directory")
        os.fchmod(descriptor, 0o700)
        return name, descriptor
    raise ManagedInstallError("could not allocate a managed operation directory")


def _populate_stage_at(
    kind: str,
    name: str,
    stage_fd: int,
    source_files: Mapping[str, bytes],
    manifest: Mapping[str, Any],
) -> None:
    if kind == RESOURCE_SKILL:
        os.mkdir(name, mode=0o755, dir_fd=stage_fd)
        target_fd = _open_directory_at(stage_fd, name, label="staged skill destination")
        try:
            os.fchmod(target_fd, 0o755)
            for relative, data in source_files.items():
                _write_relative_file_at(target_fd, relative, data, mode=0o644)
            _write_new_file_at(target_fd, MANAGED_MARKER, _serialize_json(manifest), mode=0o644)
        finally:
            os.close(target_fd)
        return
    target, marker = _component_names(kind, name)
    _write_new_file_at(stage_fd, target, source_files[target], mode=0o644)
    _write_new_file_at(stage_fd, marker, _serialize_json(manifest), mode=0o644)


def _quarantine_installation_at(kind: str, name: str, root_fd: int) -> Tuple[str, int]:
    quarantine_name, quarantine_fd = _new_operation_directory_at(root_fd, "quarantine")
    moved: list[str] = []
    try:
        for component in _component_names(kind, name):
            if not _entry_exists_at(root_fd, component):
                continue
            _move_component_noreplace_at(root_fd, component, quarantine_fd, component)
            moved.append(component)
        if not moved:
            raise ManagedInstallDriftError("managed destination disappeared before quarantine")
        return quarantine_name, quarantine_fd
    except Exception:
        try:
            _restore_named_components_at(tuple(moved), quarantine_fd, root_fd)
        finally:
            try:
                _remove_empty_operation_directory_at(root_fd, quarantine_name, quarantine_fd)
            finally:
                os.close(quarantine_fd)
        raise


def _publish_stage_at(
    kind: str,
    name: str,
    stage_fd: int,
    root_fd: int,
    root: Path,
    stage: Path,
    published: list[Tuple[str, Tuple[int, int, int, int, int]]],
) -> None:
    _require_live_destinations_absent_at(kind, name, root_fd)
    for component in _component_names(kind, name):
        if not _entry_exists_at(stage_fd, component):
            raise ManagedInstallDriftError("staged resource component is missing: " + component)
        try:
            identity = _move_component_noreplace_at(stage_fd, component, root_fd, component)
        except FileExistsError as exc:
            raise ManagedInstallCollisionError(
                "managed destination changed during publication: " + component
            ) from exc
        published.append((component, identity))
        _run_operation_hook(
            "after-publish-component",
            kind,
            name,
            root,
            stage=stage,
            component=root / component,
        )


def _rollback_published(
    kind: str,
    name: str,
    root_fd: int,
    stage_fd: int,
    quarantine_fd: Optional[int],
    published: Sequence[Tuple[str, Tuple[int, int, int, int, int]]],
    staged_snapshot: Any,
) -> bool:
    try:
        if kind == RESOURCE_SKILL and published:
            live_state = _inspect_installation_at(kind, name, root_fd)
            if live_state.get("snapshot") != staged_snapshot:
                raise ManagedInstallDriftError("published skill changed during rollback")
        for component, expected_identity in reversed(tuple(published)):
            if _entry_exists_at(stage_fd, component):
                raise ManagedInstallCollisionError("rollback staging path is unexpectedly occupied")
            if not _entry_exists_at(root_fd, component):
                raise ManagedInstallDriftError("published resource disappeared during rollback")
            if _entry_identity_at(root_fd, component) != expected_identity:
                raise ManagedInstallDriftError("published resource changed during rollback")
            _move_component_noreplace_at(root_fd, component, stage_fd, component)
        stage_state = _inspect_installation_at(kind, name, stage_fd)
        stage_is_owned = stage_state.get("snapshot") == staged_snapshot
        if quarantine_fd is not None:
            _restore_quarantine_at(kind, name, quarantine_fd, root_fd)
        return stage_is_owned
    except Exception as exc:
        raise ManagedInstallError(
            "managed install rollback could not restore the pre-operation state; quarantined data was preserved"
        ) from exc


def _restore_quarantine_at(kind: str, name: str, quarantine_fd: int, root_fd: int) -> None:
    components = tuple(
        component for component in _component_names(kind, name) if _entry_exists_at(quarantine_fd, component)
    )
    _restore_named_components_at(components, quarantine_fd, root_fd)


def _restore_named_components_at(
    components: Sequence[str],
    source_fd: int,
    root_fd: int,
) -> None:
    occupied = [component for component in components if _entry_exists_at(root_fd, component)]
    if occupied:
        raise ManagedInstallCollisionError(
            "managed destination was occupied while restoring quarantine: " + ", ".join(occupied)
        )
    restored: list[str] = []
    try:
        for component in components:
            _move_component_noreplace_at(source_fd, component, root_fd, component)
            restored.append(component)
    except Exception:
        for component in reversed(restored):
            if _entry_exists_at(root_fd, component) and not _entry_exists_at(source_fd, component):
                _move_component_noreplace_at(root_fd, component, source_fd, component)
        raise


def _require_snapshot_at(kind: str, name: str, root_fd: int, expected: Any) -> None:
    current = _inspect_installation_at(kind, name, root_fd)
    if current.get("snapshot") != expected:
        raise ManagedInstallDriftError("managed destination changed after inspection")


def _require_prepared_snapshot(
    current: Mapping[str, Any],
    prepared: Mapping[str, Any],
) -> None:
    if current.get("snapshot") != prepared.get("snapshot"):
        raise ManagedInstallDriftError("managed destination changed after planning")


def _require_live_destinations_absent_at(kind: str, name: str, root_fd: int) -> None:
    occupied = [component for component in _component_names(kind, name) if _entry_exists_at(root_fd, component)]
    if occupied:
        raise ManagedInstallCollisionError(
            "managed destination changed after quarantine: " + ", ".join(occupied)
        )


def _entry_exists_at(parent_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _entry_identity_at(parent_fd: int, name: str) -> Tuple[int, int, int, int, int]:
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise ManagedInstallDriftError("managed component is unavailable") from exc
    return _entry_identity(metadata)


def _entry_identity(metadata: os.stat_result) -> Tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _move_component_noreplace_at(
    source_fd: int,
    source_name: str,
    destination_fd: int,
    destination_name: str,
) -> Tuple[int, int, int, int, int]:
    try:
        source_metadata = os.stat(source_name, dir_fd=source_fd, follow_symlinks=False)
    except OSError as exc:
        raise ManagedInstallDriftError("managed component disappeared before relocation") from exc
    source_identity = _entry_identity(source_metadata)
    if stat.S_ISREG(source_metadata.st_mode):
        os.link(
            source_name,
            destination_name,
            src_dir_fd=source_fd,
            dst_dir_fd=destination_fd,
            follow_symlinks=False,
        )
        try:
            if _entry_identity_at(destination_fd, destination_name) != source_identity:
                raise ManagedInstallDriftError("managed component changed during relocation")
            os.unlink(source_name, dir_fd=source_fd)
            return _entry_identity_at(destination_fd, destination_name)
        except Exception:
            if (
                _entry_exists_at(destination_fd, destination_name)
                and _entry_identity_at(destination_fd, destination_name) == source_identity
            ):
                os.unlink(destination_name, dir_fd=destination_fd)
            raise
    if stat.S_ISDIR(source_metadata.st_mode):
        if _entry_exists_at(destination_fd, destination_name):
            raise FileExistsError(destination_name)
        os.rename(
            source_name,
            destination_name,
            src_dir_fd=source_fd,
            dst_dir_fd=destination_fd,
        )
        return _entry_identity_at(destination_fd, destination_name)
    raise ManagedInstallDriftError("managed component is not a regular file or directory")


def _component_names(kind: str, name: str) -> Tuple[str, ...]:
    if kind == RESOURCE_SKILL:
        return (name,)
    return (name + ".toml", "." + name + ".toml" + MANAGED_MARKER)


def _remove_empty_operation_directory_at(root_fd: int, name: str, descriptor: int) -> None:
    try:
        _require_entry_descriptor_identity(root_fd, name, descriptor)
        with os.scandir(descriptor) as iterator:
            if next(iterator, None) is not None:
                raise ManagedInstallError("managed operation directory was not empty")
        os.rmdir(name, dir_fd=root_fd)
    except OSError as exc:
        raise ManagedInstallError("managed operation directory was not empty") from exc


def _discard_quarantine_at(root_fd: int, name: str, descriptor: int) -> None:
    try:
        _discard_operation_directory_at(root_fd, name, descriptor)
    except (OSError, ManagedInstallError) as exc:
        raise ManagedInstallError(
            "quarantine cleanup was incomplete; partial quarantined content was not restored"
        ) from exc


def _discard_operation_directory_at(root_fd: int, name: str, descriptor: int) -> None:
    _require_entry_descriptor_identity(root_fd, name, descriptor)
    counters = {"entries": 0}

    def remove_contents(current_fd: int, prefix: PurePosixPath, depth: int) -> None:
        if depth > _MAX_DRIFT_DEPTH:
            raise ManagedInstallError("managed cleanup exceeds the traversal depth limit")
        with os.scandir(current_fd) as iterator:
            for entry in iterator:
                counters["entries"] += 1
                if counters["entries"] > _MAX_DRIFT_ENTRIES:
                    raise ManagedInstallError("managed cleanup exceeds the traversal entry limit")
                relative = (prefix / entry.name).as_posix()
                metadata = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(metadata.st_mode):
                    child_fd = _open_directory_at(current_fd, entry.name, label="managed cleanup directory")
                    try:
                        remove_contents(child_fd, PurePosixPath(relative), depth + 1)
                    finally:
                        os.close(child_fd)
                    os.rmdir(entry.name, dir_fd=current_fd)
                else:
                    os.unlink(entry.name, dir_fd=current_fd)
                hook = _TEST_CLEANUP_HOOK
                if hook is not None:
                    hook(relative)

    remove_contents(descriptor, PurePosixPath(), 0)
    _remove_empty_operation_directory_at(root_fd, name, descriptor)


def _run_operation_hook(
    event: str,
    kind: str,
    name: str,
    root: Path,
    **paths: Optional[Path],
) -> None:
    hook = _TEST_OPERATION_HOOK
    if hook is None:
        return
    target, marker = _destination_paths(kind, name, root)
    values = {"root": root, "target": target, "marker": marker}
    values.update({key: value for key, value in paths.items() if value is not None})
    hook(event, values)


def _prepare_writable_root(root: Path) -> None:
    anchor = Path(root.anchor)
    descriptor = _open_directory_descriptor(anchor, label="managed destination anchor")
    try:
        for part in root.relative_to(anchor).parts:
            try:
                os.mkdir(part, mode=0o755, dir_fd=descriptor)
            except FileExistsError:
                pass
            child_fd = _open_directory_at(descriptor, part, label="managed destination component")
            os.close(descriptor)
            descriptor = child_fd
        _require_root_identity(root, descriptor)
    finally:
        os.close(descriptor)
    checked = _normalize_destination_root(root)
    if checked != root or not root.is_dir():
        raise ManagedInstallPathError("destination root changed while preparing installation")


def _write_relative_file_at(root_fd: int, relative: str, data: bytes, *, mode: int) -> None:
    parts = PurePosixPath(relative).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ManagedInstallPathError("staged resource path is invalid")
    parent_fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, mode=0o755, dir_fd=parent_fd)
            except FileExistsError:
                pass
            child_fd = _open_directory_at(parent_fd, part, label="staged resource parent")
            os.close(parent_fd)
            parent_fd = child_fd
        _write_new_file_at(parent_fd, parts[-1], data, mode=mode)
    finally:
        os.close(parent_fd)


def _write_new_file_at(parent_fd: int, name: str, data: bytes, *, mode: int) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(name, flags, mode, dir_fd=parent_fd)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _destination_paths(kind: str, name: str, root: Path) -> Tuple[Path, Path]:
    if kind == RESOURCE_SKILL:
        target = root / name
        return target, target / MANAGED_MARKER
    target = root / (name + ".toml")
    marker = root / ("." + name + ".toml" + MANAGED_MARKER)
    return target, marker


def _normalize_destination_root(value: PathInput) -> Path:
    if isinstance(value, Path):
        candidate = value.expanduser()
    elif isinstance(value, str):
        if "\x00" in value:
            raise ManagedInstallPathError("destination root contains a NUL byte")
        candidate = Path(value).expanduser()
    else:
        raise ManagedInstallPathError("destination root must be a path")
    if not candidate.is_absolute():
        raise ManagedInstallPathError("destination root must be absolute")
    if candidate.is_symlink():
        raise ManagedInstallPathError("destination root must not be a symlink")
    if candidate.exists() and not candidate.is_dir():
        raise ManagedInstallPathError("destination root must be a directory")
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ManagedInstallPathError("destination root cannot be resolved") from exc
    if resolved == Path(resolved.anchor):
        raise ManagedInstallPathError("destination root must not be a filesystem root")
    return resolved


def _normalize_resource_type(value: str) -> str:
    if not isinstance(value, str):
        raise UnknownManagedResourceError("resource type must be a string")
    normalized = value.strip().casefold()
    aliases = {"skill": RESOURCE_SKILL, "skills": RESOURCE_SKILL, "agent": RESOURCE_AGENT, "agents": RESOURCE_AGENT}
    if normalized not in aliases:
        raise UnknownManagedResourceError("unknown managed resource type")
    return aliases[normalized]


def _require_resource(resource_type: str, name: str) -> Tuple[str, str]:
    kind = _normalize_resource_type(resource_type)
    if not isinstance(name, str) or name not in _RESOURCE_FILES[kind]:
        raise UnknownManagedResourceError("resource name is not in the public allowlist")
    return kind, name


def _normalize_catalog_name(value: str) -> str:
    if not isinstance(value, str):
        raise StaticCatalogError("catalog name must be a string")
    normalized = value.strip().casefold()
    aliases = {"source": "sources", "sources": "sources", "design": "design"}
    if normalized not in aliases:
        raise StaticCatalogError("unknown static catalog")
    return aliases[normalized]


def _capture_installation_state(kind: str, name: str, root: Path) -> Dict[str, Any]:
    if not _lexists(root):
        return _empty_installation_state(kind)
    root_fd = _open_directory_descriptor(root, label="managed destination root")
    try:
        return _capture_installation_state_at(kind, name, root_fd)
    finally:
        os.close(root_fd)


def _empty_installation_state(kind: str) -> Dict[str, Any]:
    snapshot: Tuple[Any, ...]
    if kind == RESOURCE_SKILL:
        snapshot = (RESOURCE_SKILL, "absent", ())
    else:
        snapshot = (RESOURCE_AGENT, ())
    return {
        "targetKind": "absent",
        "records": {},
        "files": {},
        "snapshot": snapshot,
    }


def _capture_installation_state_at(kind: str, name: str, root_fd: int) -> Dict[str, Any]:
    if kind == RESOURCE_SKILL:
        return _capture_skill_state(root_fd, name)
    return _capture_agent_state(root_fd, name)


def _capture_skill_state(root_fd: int, name: str) -> Dict[str, Any]:
    try:
        metadata = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    except FileNotFoundError:
        return {
            "targetKind": "absent",
            "records": {},
            "files": {},
            "snapshot": (RESOURCE_SKILL, "absent", ()),
        }
    target_kind = _mode_kind(metadata.st_mode)
    target_record = _metadata_record(metadata, digest="")
    if target_kind != "directory":
        if target_kind == "symlink":
            target_record = _metadata_record(metadata, digest=_readlink_digest(root_fd, name))
        return {
            "targetKind": target_kind,
            "records": {},
            "files": {},
            "snapshot": (RESOURCE_SKILL, target_record, ()),
        }
    descriptor = _open_directory_at(root_fd, name, label="managed skill destination")
    try:
        records, files = _scan_directory_descriptor(descriptor)
        root_metadata = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    root_record = _metadata_record(root_metadata, digest="")
    snapshot = (RESOURCE_SKILL, root_record, tuple(sorted(records.items())))
    return {
        "targetKind": "directory",
        "records": records,
        "files": files,
        "snapshot": snapshot,
    }


def _capture_agent_state(root_fd: int, name: str) -> Dict[str, Any]:
    records: Dict[str, Tuple[str, int, int, str]] = {}
    files: Dict[str, bytes] = {}
    total = 0
    for component in _component_names(RESOURCE_AGENT, name):
        captured = _capture_named_entry(root_fd, component, maximum=_MAX_RESOURCE_BYTES)
        if captured is None:
            continue
        record, data = captured
        records[component] = record
        if data is not None:
            total += len(data)
            if total > _MAX_DRIFT_BYTES:
                raise ManagedInstallPathError("managed installation exceeds the traversal byte limit")
            files[component] = data
    return {
        "targetKind": records.get(name + ".toml", ("absent", 0, 0, ""))[0],
        "records": records,
        "files": files,
        "snapshot": (RESOURCE_AGENT, tuple(sorted(records.items()))),
    }


def _scan_directory_descriptor(
    descriptor: int,
) -> Tuple[Dict[str, Tuple[str, int, int, str]], Dict[str, bytes]]:
    records: Dict[str, Tuple[str, int, int, str]] = {}
    files: Dict[str, bytes] = {}
    counters = {"entries": 0, "bytes": 0}

    def visit(current_fd: int, prefix: PurePosixPath, depth: int) -> None:
        if depth > _MAX_DRIFT_DEPTH:
            raise ManagedInstallPathError("managed installation exceeds the traversal depth limit")
        try:
            iterator = os.scandir(current_fd)
        except OSError as exc:
            raise ManagedInstallPathError("managed installation traversal failed") from exc
        try:
            with iterator:
                for entry in iterator:
                    child_name = entry.name
                    relative = (prefix / child_name).as_posix()
                    observer = _TEST_SCANDIR_OBSERVER
                    if observer is not None:
                        observer(relative)
                    counters["entries"] += 1
                    if counters["entries"] > _MAX_DRIFT_ENTRIES:
                        raise ManagedInstallPathError("managed installation exceeds the traversal entry limit")
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise ManagedInstallPathError("managed installation entry changed during traversal") from exc
                    kind = _mode_kind(metadata.st_mode)
                    if kind == "directory":
                        child_fd = _open_directory_at(current_fd, child_name, label="managed skill directory")
                        try:
                            opened = os.fstat(child_fd)
                            records[relative] = _metadata_record(opened, digest="")
                            visit(child_fd, PurePosixPath(relative), depth + 1)
                        finally:
                            os.close(child_fd)
                    elif kind == "file":
                        opened, data = _read_regular_at(
                            current_fd,
                            child_name,
                            maximum=_MAX_RESOURCE_BYTES,
                            label="managed skill file",
                        )
                        counters["bytes"] += len(data)
                        if counters["bytes"] > _MAX_DRIFT_BYTES:
                            raise ManagedInstallPathError("managed installation exceeds the traversal byte limit")
                        records[relative] = _metadata_record(
                            opened,
                            digest=hashlib.sha256(data).hexdigest(),
                        )
                        files[relative] = data
                    elif kind == "symlink":
                        records[relative] = _metadata_record(
                            metadata,
                            digest=_readlink_digest(current_fd, child_name),
                        )
                    else:
                        records[relative] = _metadata_record(metadata, digest="")
        except ManagedInstallPathError:
            raise
        except OSError as exc:
            raise ManagedInstallPathError("managed installation traversal failed") from exc

    visit(descriptor, PurePosixPath(), 0)
    return records, files


def _capture_named_entry(
    parent_fd: int,
    name: str,
    *,
    maximum: int,
) -> Optional[Tuple[Tuple[str, int, int, str], Optional[bytes]]]:
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    kind = _mode_kind(metadata.st_mode)
    if kind == "file":
        opened, data = _read_regular_at(
            parent_fd,
            name,
            maximum=maximum,
            label="managed file",
        )
        return _metadata_record(opened, digest=hashlib.sha256(data).hexdigest()), data
    digest = _readlink_digest(parent_fd, name) if kind == "symlink" else ""
    return _metadata_record(metadata, digest=digest), None


def _metadata_record(metadata: os.stat_result, *, digest: str) -> Tuple[str, int, int, str]:
    return (
        _mode_kind(metadata.st_mode),
        stat.S_IMODE(metadata.st_mode),
        metadata.st_size,
        digest,
    )


def _mode_kind(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "special"


def _readlink_digest(parent_fd: int, name: str) -> str:
    try:
        value = os.readlink(name, dir_fd=parent_fd)
    except OSError as exc:
        raise ManagedInstallPathError("managed symlink changed during traversal") from exc
    return hashlib.sha256(value.encode("utf-8", errors="surrogateescape")).hexdigest()


def _open_directory_descriptor(path: Path, *, label: str) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ManagedInstallPathError(label + " is unavailable or unsafe") from exc
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ManagedInstallPathError(label + " must be a directory")
    return descriptor


def _root_identity_matches(root: Path, descriptor: int) -> bool:
    try:
        lexical = os.stat(root, follow_symlinks=False)
        opened = os.fstat(descriptor)
    except OSError:
        return False
    return (
        stat.S_ISDIR(lexical.st_mode)
        and stat.S_ISDIR(opened.st_mode)
        and lexical.st_dev == opened.st_dev
        and lexical.st_ino == opened.st_ino
    )


def _require_root_identity(root: Path, descriptor: int) -> None:
    if not _root_identity_matches(root, descriptor):
        raise ManagedInstallDriftError("destination root identity changed during the operation")


def _require_entry_descriptor_identity(parent_fd: int, name: str, descriptor: int) -> None:
    try:
        lexical = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        opened = os.fstat(descriptor)
    except OSError as exc:
        raise ManagedInstallDriftError("managed operation directory identity changed") from exc
    if (
        not stat.S_ISDIR(lexical.st_mode)
        or not stat.S_ISDIR(opened.st_mode)
        or lexical.st_dev != opened.st_dev
        or lexical.st_ino != opened.st_ino
    ):
        raise ManagedInstallDriftError("managed operation directory identity changed")


def _open_directory_at(parent_fd: int, name: str, *, label: str) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise ManagedInstallPathError(label + " is unavailable or unsafe") from exc
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ManagedInstallPathError(label + " must be a directory")
    return descriptor


def _read_regular_at(
    parent_fd: int,
    name: str,
    *,
    maximum: int,
    label: str,
) -> Tuple[os.stat_result, bytes]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise ManagedInstallPathError(label + " is unavailable or unsafe") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ManagedInstallPathError(label + " must be a regular file")
        if before.st_size > maximum:
            raise ManagedInstallPathError(label + " exceeds the allowed size")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(65536, maximum + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum:
                raise ManagedInstallPathError(label + " exceeds the allowed size")
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
            raise ManagedInstallDriftError(label + " changed while it was read")
        return after, b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_fixed_regular_file(path: Path, *, root: Path, maximum: int) -> bytes:
    try:
        lexical_relative = path.relative_to(root)
    except ValueError as exc:
        raise ManagedInstallPathError("bundled resource escaped its fixed repository root") from exc
    if not lexical_relative.parts:
        raise ManagedInstallPathError("bundled resource escaped its fixed repository root")
    root_fd = _open_directory_descriptor(root, label="bundled resource root")
    parent_fd = root_fd
    try:
        for part in lexical_relative.parts[:-1]:
            next_fd = _open_directory_at(parent_fd, part, label="bundled resource parent")
            if parent_fd != root_fd:
                os.close(parent_fd)
            parent_fd = next_fd
        _metadata, data = _read_regular_at(
            parent_fd,
            lexical_relative.parts[-1],
            maximum=maximum,
            label="bundled resource",
        )
        return data
    finally:
        if parent_fd != root_fd:
            os.close(parent_fd)
        os.close(root_fd)


def _read_bounded_file(path: Path, *, maximum: int) -> bytes:
    parent_fd = _open_directory_descriptor(path.parent, label="file parent")
    try:
        _metadata, data = _read_regular_at(
            parent_fd,
            path.name,
            maximum=maximum,
            label="file",
        )
        return data
    finally:
        os.close(parent_fd)


def _require_safe_relative_path(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 240
        or _SAFE_RELATIVE_PATH.fullmatch(value) is None
    ):
        raise ManagedInstallDriftError("managed marker path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(part in ("", ".", "..") for part in path.parts):
        raise ManagedInstallDriftError("managed marker path must be a safe relative path")
    if value == MANAGED_MARKER or value.startswith(MANAGED_MARKER + "/"):
        raise ManagedInstallDriftError("managed marker cannot list itself as content")
    return path.as_posix()


def _resource_digest(entries: Sequence[Mapping[str, Any]]) -> str:
    payload = json.dumps(list(entries), ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _serialize_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("ascii")


def _copy_json_object(value: Mapping[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=True))


def _lexists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _require_exact_keys(
    value: Mapping[str, Any],
    keys: Sequence[str],
    *,
    label: str,
    error_type: type,
) -> None:
    expected = set(keys)
    actual = set(value)
    if actual != expected:
        raise error_type(label + " keys mismatch")


def _require_text(
    value: Any,
    *,
    label: str,
    maximum: int,
    error_type: type,
) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise error_type(label + " must be a non-empty bounded string")
    if "\x00" in value or any(ord(char) < 32 for char in value):
        raise error_type(label + " contains a forbidden control character")
    return value


def _require_safe_id(value: Any, *, label: str, error_type: type) -> str:
    text = _require_text(value, label=label, maximum=64, error_type=error_type)
    if _SAFE_ID.fullmatch(text) is None:
        raise error_type(label + " is not a safe identifier")
    return text
