from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional, Union


SCHEMA_VERSION = "plzdo-local.catalog.v1"
CATALOG_SCHEMA_VERSION = SCHEMA_VERSION

STATE_ACTIVE = "active"
STATE_ARCHIVED = "archived"
REPOSITORY_STATES = (STATE_ACTIVE, STATE_ARCHIVED)

WORKFLOW_LANE_STANDARD = "standard"
WORKFLOW_LANE_OPERATIONAL = "operational"
WORKFLOW_LANES = (WORKFLOW_LANE_STANDARD, WORKFLOW_LANE_OPERATIONAL)

ROLLOUT_TIER_OBSERVE = "observe"
ROLLOUT_TIER_ENFORCED = "enforced"
ROLLOUT_TIERS = (ROLLOUT_TIER_OBSERVE, ROLLOUT_TIER_ENFORCED)

MAX_REPOSITORIES = 256
MAX_PATH_ITEMS = 128
MAX_DOCUMENT_BYTES = 1024 * 1024

_SAFE_ID = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


class CatalogError(ValueError):
    """Base error for catalog operations."""


class CatalogValidationError(CatalogError):
    """Raised when a catalog document does not have the exact v1 shape."""


class CatalogPathError(CatalogValidationError):
    """Raised when a repository path is not canonical and local."""


class CatalogConflictError(CatalogValidationError):
    """Raised when repository identities or roots collide."""


class CatalogLookupError(CatalogError):
    """Raised when an active catalog repository cannot be selected."""


PathInput = Union[str, Path]


def canonicalize_local_path(
    value: PathInput,
    *,
    label: str = "path",
    must_exist: bool = False,
) -> str:
    """Return an absolute, symlink-resolved local directory path.

    Builders use this function to normalize operator-supplied paths. Durable
    document validators require the stored value to already equal this result.
    """

    if isinstance(value, Path):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        raise CatalogPathError(f"{label} must be a path string")
    _require_plain_text(text, label=label, maximum=4096)
    if "://" in text or text.startswith(("//", "\\\\")) or _WINDOWS_DRIVE.match(text):
        raise CatalogPathError(f"{label} must be a local POSIX path")
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        raise CatalogPathError(f"{label} must be absolute")
    try:
        resolved = candidate.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        raise CatalogPathError(f"{label} cannot be canonicalized") from exc
    if resolved == Path(resolved.anchor):
        raise CatalogPathError(f"{label} must not be a filesystem root")
    if must_exist and not resolved.is_dir():
        raise CatalogPathError(f"{label} must name an existing directory")
    return str(resolved)


def build_repository(
    *,
    repository_id: str,
    path: PathInput,
    state: str = STATE_ACTIVE,
    workflow_lane: str = WORKFLOW_LANE_STANDARD,
    rollout_tier: str = ROLLOUT_TIER_OBSERVE,
    source_of_truth: Iterable[str] = (),
    outputs: Iterable[str] = (),
    protected_paths: Iterable[str] = (),
    real_apply: Optional[dict[str, Any]] = None,
    path_must_exist: bool = False,
) -> dict[str, Any]:
    """Build a canonical repository profile without writing to its target."""

    profile = {
        "id": repository_id,
        "path": canonicalize_local_path(path, label="repository.path", must_exist=path_must_exist),
        "state": state,
        "workflowLane": workflow_lane,
        "rolloutTier": rollout_tier,
        "sourceOfTruth": sorted(source_of_truth),
        "outputs": sorted(outputs),
        "protectedPaths": sorted(protected_paths),
        "realApply": copy.deepcopy(real_apply) if real_apply is not None else default_real_apply_policy(),
    }
    validate_repository(profile)
    return profile


def default_real_apply_policy() -> dict[str, Any]:
    return {"enabled": False, "operatorOnly": True, "approval": None}


def build_catalog(repositories: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """Build a deterministic catalog from already-shaped repository profiles."""

    items = [copy.deepcopy(item) for item in repositories]
    items.sort(key=lambda item: item.get("id", "") if isinstance(item, dict) else "")
    catalog = {"schemaVersion": SCHEMA_VERSION, "repositories": items}
    validate_catalog(catalog)
    return catalog


def validate_catalog(value: Any) -> None:
    catalog = _require_object(value, label="catalog")
    _require_exact_keys(catalog, {"schemaVersion", "repositories"}, label="catalog")
    if catalog["schemaVersion"] != SCHEMA_VERSION:
        raise CatalogValidationError(f"catalog.schemaVersion must be {SCHEMA_VERSION}")
    repositories = catalog["repositories"]
    if not isinstance(repositories, list):
        raise CatalogValidationError("catalog.repositories must be an array")
    if len(repositories) > MAX_REPOSITORIES:
        raise CatalogValidationError(f"catalog.repositories must contain at most {MAX_REPOSITORIES} items")

    ids: set[str] = set()
    paths: set[str] = set()
    ordered_ids: list[str] = []
    for index, repository in enumerate(repositories):
        validate_repository(repository, label=f"catalog.repositories[{index}]")
        repository_id = repository["id"]
        repository_path = repository["path"]
        if repository_id in ids:
            raise CatalogConflictError(f"duplicate repository id: {repository_id}")
        if repository_path in paths:
            raise CatalogConflictError("repository paths must be unique")
        ids.add(repository_id)
        paths.add(repository_path)
        ordered_ids.append(repository_id)
    if ordered_ids != sorted(ordered_ids):
        raise CatalogValidationError("catalog.repositories must be sorted by id")
    _require_bounded_json(value, label="catalog")


def validate_repository(value: Any, *, label: str = "repository") -> None:
    repository = _require_object(value, label=label)
    _require_exact_keys(
        repository,
        {
            "id",
            "path",
            "state",
            "workflowLane",
            "rolloutTier",
            "sourceOfTruth",
            "outputs",
            "protectedPaths",
            "realApply",
        },
        label=label,
    )
    _require_safe_id(repository["id"], label=f"{label}.id")
    _require_canonical_path(repository["path"], label=f"{label}.path")
    _require_choice(repository["state"], REPOSITORY_STATES, label=f"{label}.state")
    _require_choice(repository["workflowLane"], WORKFLOW_LANES, label=f"{label}.workflowLane")
    _require_choice(repository["rolloutTier"], ROLLOUT_TIERS, label=f"{label}.rolloutTier")

    source_of_truth = _require_relative_path_array(repository["sourceOfTruth"], label=f"{label}.sourceOfTruth")
    outputs = _require_relative_path_array(repository["outputs"], label=f"{label}.outputs")
    protected = _require_relative_path_array(repository["protectedPaths"], label=f"{label}.protectedPaths")
    for output in outputs:
        if any(_path_is_within(output, blocked) for blocked in protected):
            raise CatalogValidationError(f"{label}.outputs overlaps a protected path")
    if len(set(source_of_truth) | set(outputs) | set(protected)) > MAX_PATH_ITEMS * 3:
        raise CatalogValidationError(f"{label} contains too many path entries")

    _validate_real_apply(repository["realApply"], repository=repository, label=f"{label}.realApply")


def get_repository(
    catalog: Any,
    repository_id: str,
    *,
    include_archived: bool = False,
) -> dict[str, Any]:
    validate_catalog(catalog)
    identifier = _require_safe_id(repository_id, label="repository id")
    for repository in catalog["repositories"]:
        if repository["id"] != identifier:
            continue
        if repository["state"] == STATE_ARCHIVED and not include_archived:
            raise CatalogLookupError(f"repository is archived: {identifier}")
        return copy.deepcopy(repository)
    raise CatalogLookupError(f"repository not found: {identifier}")


def list_repositories(catalog: Any, *, include_archived: bool = False) -> list[dict[str, Any]]:
    validate_catalog(catalog)
    return [
        copy.deepcopy(repository)
        for repository in catalog["repositories"]
        if include_archived or repository["state"] == STATE_ACTIVE
    ]


def repository_is_active(catalog: Any, repository_id: str) -> bool:
    try:
        get_repository(catalog, repository_id, include_archived=False)
    except CatalogLookupError:
        return False
    return True


def _validate_real_apply(value: Any, *, repository: dict[str, Any], label: str) -> None:
    policy = _require_object(value, label=label)
    _require_exact_keys(policy, {"enabled", "operatorOnly", "approval"}, label=label)
    enabled = _require_bool(policy["enabled"], label=f"{label}.enabled")
    operator_only = _require_bool(policy["operatorOnly"], label=f"{label}.operatorOnly")
    approval = policy["approval"]
    if approval is not None:
        approval_object = _require_object(approval, label=f"{label}.approval")
        _require_exact_keys(approval_object, {"id", "approvedAt", "approvalHash"}, label=f"{label}.approval")
        _require_safe_id(approval_object["id"], label=f"{label}.approval.id")
        _require_timestamp(approval_object["approvedAt"], label=f"{label}.approval.approvedAt")
        approval_hash = _require_plain_text(
            approval_object["approvalHash"],
            label=f"{label}.approval.approvalHash",
            maximum=64,
        )
        if _SHA256.fullmatch(approval_hash) is None:
            raise CatalogValidationError(f"{label}.approval.approvalHash must be a lowercase SHA-256 hex digest")
    if enabled:
        if not operator_only:
            raise CatalogValidationError(f"{label}.operatorOnly must be true when real apply is enabled")
        if approval is None:
            raise CatalogValidationError(f"{label}.approval is required when real apply is enabled")
        if repository["state"] != STATE_ACTIVE:
            raise CatalogValidationError("real apply cannot be enabled for an archived repository")
        if repository["workflowLane"] != WORKFLOW_LANE_OPERATIONAL:
            raise CatalogValidationError("real apply requires workflowLane=operational")
        if repository["rolloutTier"] != ROLLOUT_TIER_ENFORCED:
            raise CatalogValidationError("real apply requires rolloutTier=enforced")


def _require_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CatalogValidationError(f"{label} must be an object")
    return value


def _require_exact_keys(value: dict[str, Any], keys: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys)
        raise CatalogValidationError(f"{label} keys mismatch: missing={missing}, extra={extra}")


def _require_plain_text(value: Any, *, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise CatalogValidationError(f"{label} must be a string")
    if not value or len(value) > maximum:
        raise CatalogValidationError(f"{label} length must be between 1 and {maximum}")
    if "\x00" in value or any(ord(character) < 32 for character in value):
        raise CatalogValidationError(f"{label} contains a forbidden control character")
    return value


def _require_safe_id(value: Any, *, label: str) -> str:
    text = _require_plain_text(value, label=label, maximum=64)
    if _SAFE_ID.fullmatch(text) is None:
        raise CatalogValidationError(f"{label} must match {_SAFE_ID.pattern}")
    return text


def _require_choice(value: Any, choices: tuple[str, ...], *, label: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise CatalogValidationError(f"{label} must be one of {list(choices)}")
    return value


def _require_bool(value: Any, *, label: str) -> bool:
    if type(value) is not bool:
        raise CatalogValidationError(f"{label} must be a boolean")
    return value


def _require_canonical_path(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise CatalogPathError(f"{label} must be a path string")
    canonical = canonicalize_local_path(value, label=label)
    if value != canonical:
        raise CatalogPathError(f"{label} must already be canonical")
    return value


def _require_relative_path_array(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list):
        raise CatalogValidationError(f"{label} must be an array")
    if len(value) > MAX_PATH_ITEMS:
        raise CatalogValidationError(f"{label} must contain at most {MAX_PATH_ITEMS} items")
    paths = [_require_relative_path(item, label=f"{label}[{index}]") for index, item in enumerate(value)]
    if paths != sorted(set(paths)):
        raise CatalogValidationError(f"{label} must be sorted and contain unique paths")
    return paths


def _require_relative_path(value: Any, *, label: str) -> str:
    text = _require_plain_text(value, label=label, maximum=256)
    if text.startswith(("/", "\\")) or "\\" in text or "://" in text:
        raise CatalogValidationError(f"{label} must be a project-relative POSIX path")
    if text.endswith("/") or "//" in text:
        raise CatalogValidationError(f"{label} must be normalized")
    raw_parts = text.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise CatalogValidationError(f"{label} must not contain empty, dot, or parent segments")
    if PurePosixPath(text).as_posix() != text:
        raise CatalogValidationError(f"{label} must be normalized")
    return text


def _require_timestamp(value: Any, *, label: str) -> str:
    text = _require_plain_text(value, label=label, maximum=64)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CatalogValidationError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise CatalogValidationError(f"{label} must include a timezone")
    return text


def _path_is_within(candidate: str, parent: str) -> bool:
    candidate_path = PurePosixPath(candidate)
    parent_path = PurePosixPath(parent)
    return candidate_path == parent_path or parent_path in candidate_path.parents


def _require_bounded_json(value: Any, *, label: str) -> None:
    try:
        serialized = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise CatalogValidationError(f"{label} must contain only JSON values") from exc
    if len(serialized.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise CatalogValidationError(f"{label} exceeds {MAX_DOCUMENT_BYTES} bytes")


validate_catalog_document = validate_catalog
canonical_local_path = canonicalize_local_path
