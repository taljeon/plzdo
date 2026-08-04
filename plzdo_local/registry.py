from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from .catalog import (
    STATE_ACTIVE,
    STATE_ARCHIVED,
    CatalogError,
    canonicalize_local_path,
    get_repository,
    repository_is_active,
    validate_catalog,
)


SCHEMA_VERSION = "plzdo-local.registry.v1"
REGISTRY_SCHEMA_VERSION = SCHEMA_VERSION
RESOLUTION_SCHEMA_VERSION = "plzdo-local.project-resolution.v1"

PROJECT_STATES = (STATE_ACTIVE, STATE_ARCHIVED)
RESOLUTION_DECISIONS = ("attached", "ask", "create")

RULE_EXACT_ID = "registry-resolve-exact-id-v1"
RULE_EXACT_ALIAS = "registry-resolve-exact-alias-v1"
RULE_EXACT_AMBIGUOUS = "registry-resolve-exact-ambiguous-v1"
RULE_EXACT_INACTIVE = "registry-resolve-exact-inactive-v1"
RULE_DOMAIN_AREA = "registry-resolve-domain-area-v1"
RULE_DOMAIN_AREA_AMBIGUOUS = "registry-resolve-domain-area-ambiguous-v1"
RULE_NO_MATCH_CREATE = "registry-resolve-no-match-create-v1"
RULE_PROVIDED_PROJECT = "registry-resolve-provided-project-v1"

MAX_PROJECTS = 1024
MAX_ALIASES = 32
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024

_SAFE_ID = re.compile(r"^[a-z][a-z0-9-]{1,63}$")


class RegistryError(ValueError):
    """Base error for registry operations."""


class RegistryValidationError(RegistryError):
    """Raised when a registry document does not have the exact v1 shape."""


class RegistryPathError(RegistryValidationError):
    """Raised when a project path is not canonical or catalog-contained."""


class RegistryConflictError(RegistryValidationError):
    """Raised when project identities, aliases, or roots collide."""


class RegistryCatalogError(RegistryValidationError):
    """Raised when a registry-to-catalog reference is invalid."""


class RegistryLookupError(RegistryError):
    """Raised when a requested project cannot be selected."""


class RegistryResolutionError(RegistryError):
    """Raised when a project-resolution request or result is invalid."""


class RegistryRegistrationError(RegistryError):
    """Raised when registration is attempted before a successful render."""


def build_project(
    *,
    project_id: str,
    aliases: Iterable[str] = (),
    domain: str,
    area: str,
    path: Any,
    repository_id: Optional[str] = None,
    state: str = STATE_ACTIVE,
    path_must_exist: bool = False,
) -> dict[str, Any]:
    """Build a canonical project record without persisting it."""

    project = {
        "id": project_id,
        "aliases": sorted(aliases),
        "domain": domain,
        "area": area,
        "path": canonicalize_local_path(path, label="project.path", must_exist=path_must_exist),
        "repositoryId": repository_id,
        "state": state,
    }
    validate_project(project)
    return project


def build_registry(projects: Iterable[dict[str, Any]] = (), *, catalog: Optional[Any] = None) -> dict[str, Any]:
    """Build a deterministic registry from already-shaped project records."""

    items = [copy.deepcopy(item) for item in projects]
    items.sort(key=lambda item: item.get("id", "") if isinstance(item, dict) else "")
    registry = {"schemaVersion": SCHEMA_VERSION, "projects": items}
    validate_registry(registry, catalog=catalog)
    return registry


def validate_registry(value: Any, *, catalog: Optional[Any] = None) -> None:
    registry = _require_object(value, label="registry")
    _require_exact_keys(registry, {"schemaVersion", "projects"}, label="registry")
    if registry["schemaVersion"] != SCHEMA_VERSION:
        raise RegistryValidationError(f"registry.schemaVersion must be {SCHEMA_VERSION}")
    projects = registry["projects"]
    if not isinstance(projects, list):
        raise RegistryValidationError("registry.projects must be an array")
    if len(projects) > MAX_PROJECTS:
        raise RegistryValidationError(f"registry.projects must contain at most {MAX_PROJECTS} items")

    if catalog is not None:
        try:
            validate_catalog(catalog)
        except CatalogError as exc:
            raise RegistryCatalogError("catalog is invalid") from exc
    elif any(
        isinstance(project, dict) and project.get("repositoryId") is not None
        for project in projects
    ):
        raise RegistryCatalogError("registry contains repository references but no catalog is available")

    identities: dict[str, str] = {}
    paths: set[str] = set()
    ordered_ids: list[str] = []
    for index, project in enumerate(projects):
        label = f"registry.projects[{index}]"
        validate_project(project, label=label)
        project_id = project["id"]
        ordered_ids.append(project_id)
        for identity in [project_id] + project["aliases"]:
            previous = identities.get(identity)
            if previous is not None:
                raise RegistryConflictError(f"project identity {identity} is shared by {previous} and {project_id}")
            identities[identity] = project_id
        if project["path"] in paths:
            raise RegistryConflictError("project paths must be unique")
        paths.add(project["path"])
        if catalog is not None and project["repositoryId"] is not None:
            _validate_catalog_reference(project, catalog=catalog, label=label)
    if ordered_ids != sorted(ordered_ids):
        raise RegistryValidationError("registry.projects must be sorted by id")
    _require_bounded_json(value, label="registry")


def validate_project(value: Any, *, label: str = "project") -> None:
    project = _require_object(value, label=label)
    _require_exact_keys(
        project,
        {"id", "aliases", "domain", "area", "path", "repositoryId", "state"},
        label=label,
    )
    project_id = _require_safe_id(project["id"], label=f"{label}.id")
    aliases = project["aliases"]
    if not isinstance(aliases, list):
        raise RegistryValidationError(f"{label}.aliases must be an array")
    if len(aliases) > MAX_ALIASES:
        raise RegistryValidationError(f"{label}.aliases must contain at most {MAX_ALIASES} items")
    checked_aliases = [
        _require_safe_id(alias, label=f"{label}.aliases[{index}]") for index, alias in enumerate(aliases)
    ]
    if checked_aliases != sorted(set(checked_aliases)):
        raise RegistryValidationError(f"{label}.aliases must be sorted and unique")
    if project_id in checked_aliases:
        raise RegistryConflictError(f"{label}.aliases must not repeat the project id")
    _require_safe_id(project["domain"], label=f"{label}.domain")
    _require_safe_id(project["area"], label=f"{label}.area")
    _require_canonical_path(project["path"], label=f"{label}.path")
    repository_id = project["repositoryId"]
    if repository_id is not None:
        _require_safe_id(repository_id, label=f"{label}.repositoryId")
    _require_choice(project["state"], PROJECT_STATES, label=f"{label}.state")


def register_project(
    registry: Any,
    project: dict[str, Any],
    *,
    render_succeeded: bool = False,
    catalog: Optional[Any] = None,
) -> dict[str, Any]:
    """Return a registry containing a rendered project; never writes files."""

    if type(render_succeeded) is not bool:
        raise RegistryRegistrationError("render_succeeded must be a boolean")
    if not render_succeeded:
        raise RegistryRegistrationError("project registration requires a successful render")
    validate_registry(registry, catalog=catalog)
    validate_project(project)
    try:
        canonical = canonicalize_local_path(project["path"], label="project.path", must_exist=True)
    except CatalogError as exc:
        raise RegistryRegistrationError("rendered project path must be an existing local directory") from exc
    if canonical != project["path"]:
        raise RegistryRegistrationError("rendered project path must already be canonical")

    updated = copy.deepcopy(registry)
    updated["projects"].append(copy.deepcopy(project))
    updated["projects"].sort(key=lambda item: item["id"])
    try:
        validate_registry(updated, catalog=catalog)
    except RegistryValidationError as exc:
        raise RegistryRegistrationError(str(exc)) from exc
    return updated


def archive_project(registry: Any, identifier: str, *, catalog: Optional[Any] = None) -> dict[str, Any]:
    """Return a registry copy with one exact id or alias archived."""

    validate_registry(registry, catalog=catalog)
    project = get_project(registry, identifier, include_archived=True, catalog=catalog)
    updated = copy.deepcopy(registry)
    for item in updated["projects"]:
        if item["id"] == project["id"]:
            item["state"] = STATE_ARCHIVED
            break
    validate_registry(updated, catalog=catalog)
    return updated


def get_project(
    registry: Any,
    identifier: str,
    *,
    include_archived: bool = False,
    catalog: Optional[Any] = None,
) -> dict[str, Any]:
    validate_registry(registry, catalog=catalog)
    identity = _require_safe_id(identifier, label="project identifier")
    for project in registry["projects"]:
        if identity != project["id"] and identity not in project["aliases"]:
            continue
        if not include_archived and not _project_is_active(project, catalog=catalog):
            raise RegistryLookupError(f"project is inactive: {project['id']}")
        return copy.deepcopy(project)
    raise RegistryLookupError(f"project not found: {identity}")


def list_projects(
    registry: Any,
    *,
    include_archived: bool = False,
    catalog: Optional[Any] = None,
) -> list[dict[str, Any]]:
    validate_registry(registry, catalog=catalog)
    return [
        copy.deepcopy(project)
        for project in registry["projects"]
        if include_archived or _project_is_active(project, catalog=catalog)
    ]


def resolve_project(
    registry: Any,
    goal: Optional[str] = None,
    *,
    identifier: Optional[str] = None,
    domain: Optional[str] = None,
    area: Optional[str] = None,
    catalog: Optional[Any] = None,
) -> dict[str, Any]:
    """Resolve without persistence using id/alias before domain+area."""

    validate_registry(registry, catalog=catalog)
    goal_text = _require_goal(goal) if goal is not None else None
    if identifier is not None:
        _require_safe_id(identifier, label="identifier")
    if (domain is None) != (area is None):
        raise RegistryResolutionError("domain and area must be provided together")
    if domain is not None and area is not None:
        _require_safe_id(domain, label="domain")
        _require_safe_id(area, label="area")
    if goal_text is None and identifier is None and domain is None:
        raise RegistryResolutionError("resolution requires a goal, identifier, or domain+area")

    exact_matches, exact_rule = _exact_identity_matches(
        registry["projects"],
        goal=goal_text,
        identifier=identifier,
    )
    if exact_matches:
        candidate_ids = sorted(project["id"] for project in exact_matches)
        if len(exact_matches) > 1:
            return build_resolution(
                decision="ask",
                candidate_ids=candidate_ids,
                rule_id=RULE_EXACT_AMBIGUOUS,
                reason="multiple exact project identities were present",
            )
        project = exact_matches[0]
        if not _project_is_active(project, catalog=catalog):
            return build_resolution(
                decision="ask",
                candidate_ids=candidate_ids,
                rule_id=RULE_EXACT_INACTIVE,
                reason="the exact project identity is archived or its repository is archived",
            )
        return build_resolution(
            decision="attached",
            project_id=project["id"],
            candidate_ids=candidate_ids,
            rule_id=exact_rule,
            reason="an exact active project identity matched",
        )

    domain_area_matches = _domain_area_matches(
        registry["projects"],
        goal=goal_text,
        domain=domain,
        area=area,
        catalog=catalog,
    )
    candidate_ids = sorted(project["id"] for project in domain_area_matches)
    if len(domain_area_matches) == 1:
        return build_resolution(
            decision="attached",
            project_id=domain_area_matches[0]["id"],
            candidate_ids=candidate_ids,
            rule_id=RULE_DOMAIN_AREA,
            reason="one active project matched the exact domain and area",
        )
    if len(domain_area_matches) > 1:
        return build_resolution(
            decision="ask",
            candidate_ids=candidate_ids,
            rule_id=RULE_DOMAIN_AREA_AMBIGUOUS,
            reason="multiple active projects matched the exact domain and area",
        )
    return build_resolution(
        decision="create",
        candidate_ids=[],
        rule_id=RULE_NO_MATCH_CREATE,
        reason="no active project matched; rendering is required before registration",
    )


def build_resolution(
    *,
    decision: str,
    candidate_ids: Iterable[str],
    rule_id: str,
    reason: str,
    project_id: Optional[str] = None,
) -> dict[str, Any]:
    resolution = {
        "schemaVersion": RESOLUTION_SCHEMA_VERSION,
        "decision": decision,
        "projectId": project_id,
        "candidateIds": sorted(candidate_ids),
        "ruleId": rule_id,
        "reason": reason,
    }
    validate_resolution(resolution)
    return resolution


def validate_resolution(value: Any) -> None:
    resolution = _require_object(value, label="project resolution", error_type=RegistryResolutionError)
    _require_exact_keys(
        resolution,
        {"schemaVersion", "decision", "projectId", "candidateIds", "ruleId", "reason"},
        label="project resolution",
        error_type=RegistryResolutionError,
    )
    if resolution["schemaVersion"] != RESOLUTION_SCHEMA_VERSION:
        raise RegistryResolutionError(f"project resolution schemaVersion must be {RESOLUTION_SCHEMA_VERSION}")
    decision = _require_choice(
        resolution["decision"],
        RESOLUTION_DECISIONS,
        label="project resolution.decision",
        error_type=RegistryResolutionError,
    )
    project_id = resolution["projectId"]
    if project_id is not None:
        _require_safe_id(project_id, label="project resolution.projectId", error_type=RegistryResolutionError)
    candidates = resolution["candidateIds"]
    if not isinstance(candidates, list):
        raise RegistryResolutionError("project resolution.candidateIds must be an array")
    checked = [
        _require_safe_id(item, label=f"project resolution.candidateIds[{index}]", error_type=RegistryResolutionError)
        for index, item in enumerate(candidates)
    ]
    if checked != sorted(set(checked)):
        raise RegistryResolutionError("project resolution.candidateIds must be sorted and unique")
    _require_safe_id(resolution["ruleId"], label="project resolution.ruleId", error_type=RegistryResolutionError)
    _require_text(
        resolution["reason"],
        label="project resolution.reason",
        maximum=240,
        error_type=RegistryResolutionError,
    )
    if decision == "attached" and (project_id is None or checked != [project_id]):
        raise RegistryResolutionError("attached resolution requires its projectId as the sole candidate")
    if decision == "ask" and (project_id is not None or not checked):
        raise RegistryResolutionError("ask resolution requires candidates and no selected projectId")
    if decision == "create" and (project_id is not None or checked):
        raise RegistryResolutionError("create resolution cannot contain a selected project or candidates")


def _exact_identity_matches(
    projects: list[dict[str, Any]],
    *,
    goal: Optional[str],
    identifier: Optional[str],
) -> tuple[list[dict[str, Any]], str]:
    if identifier is not None:
        for project in projects:
            if identifier == project["id"]:
                return [project], RULE_EXACT_ID
            if identifier in project["aliases"]:
                return [project], RULE_EXACT_ALIAS
        return [], RULE_EXACT_ID
    if goal is None:
        return [], RULE_EXACT_ID

    normalized = _normalize_goal(goal)
    full_matches: list[tuple[dict[str, Any], str]] = []
    embedded_matches: list[tuple[dict[str, Any], str]] = []
    for project in projects:
        identities = [(project["id"], RULE_EXACT_ID)] + [
            (alias, RULE_EXACT_ALIAS) for alias in project["aliases"]
        ]
        for identity, rule_id in identities:
            if normalized == identity:
                full_matches.append((project, rule_id))
            elif _contains_exact_term(normalized, identity):
                embedded_matches.append((project, rule_id))
    matches = full_matches or embedded_matches
    unique: dict[str, tuple[dict[str, Any], str]] = {}
    for project, rule_id in matches:
        unique[project["id"]] = (project, rule_id)
    ordered = [unique[key] for key in sorted(unique)]
    if not ordered:
        return [], RULE_EXACT_ID
    rule_ids = {rule_id for _, rule_id in ordered}
    selected_rule = next(iter(rule_ids)) if len(rule_ids) == 1 else RULE_EXACT_AMBIGUOUS
    return [project for project, _ in ordered], selected_rule


def _domain_area_matches(
    projects: list[dict[str, Any]],
    *,
    goal: Optional[str],
    domain: Optional[str],
    area: Optional[str],
    catalog: Optional[Any],
) -> list[dict[str, Any]]:
    if domain is not None and area is not None:
        return [
            project
            for project in projects
            if project["domain"] == domain
            and project["area"] == area
            and _project_is_active(project, catalog=catalog)
        ]
    if goal is None:
        return []
    normalized = _normalize_goal(goal)
    return [
        project
        for project in projects
        if _contains_exact_term(normalized, project["domain"])
        and _contains_exact_term(normalized, project["area"])
        and _project_is_active(project, catalog=catalog)
    ]


def _validate_catalog_reference(project: dict[str, Any], *, catalog: Any, label: str) -> None:
    repository_id = project["repositoryId"]
    try:
        repository = get_repository(catalog, repository_id, include_archived=True)
    except CatalogError as exc:
        raise RegistryCatalogError(f"{label}.repositoryId does not reference the catalog") from exc
    project_path = Path(project["path"])
    repository_path = Path(repository["path"])
    if project_path != repository_path and repository_path not in project_path.parents:
        raise RegistryPathError(f"{label}.path must be contained by its catalog repository")


def _project_is_active(project: dict[str, Any], *, catalog: Optional[Any]) -> bool:
    if project["state"] != STATE_ACTIVE:
        return False
    repository_id = project["repositoryId"]
    if repository_id is None:
        return True
    if catalog is None:
        return False
    return repository_is_active(catalog, repository_id)


def _require_goal(value: Any) -> str:
    text = _require_text(value, label="goal", maximum=4000, error_type=RegistryResolutionError)
    if not text.strip():
        raise RegistryResolutionError("goal must contain non-whitespace text")
    return text


def _normalize_goal(value: str) -> str:
    return " ".join(value.casefold().split())


def _contains_exact_term(text: str, term: str) -> bool:
    return re.search(r"(?<![a-z0-9-])" + re.escape(term) + r"(?![a-z0-9-])", text) is not None


def _require_object(
    value: Any,
    *,
    label: str,
    error_type: type[RegistryError] = RegistryValidationError,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise error_type(f"{label} must be an object")
    return value


def _require_exact_keys(
    value: dict[str, Any],
    keys: set[str],
    *,
    label: str,
    error_type: type[RegistryError] = RegistryValidationError,
) -> None:
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys)
        raise error_type(f"{label} keys mismatch: missing={missing}, extra={extra}")


def _require_text(
    value: Any,
    *,
    label: str,
    maximum: int,
    error_type: type[RegistryError] = RegistryValidationError,
) -> str:
    if not isinstance(value, str):
        raise error_type(f"{label} must be a string")
    if not value or len(value) > maximum:
        raise error_type(f"{label} length must be between 1 and {maximum}")
    if "\x00" in value or any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise error_type(f"{label} contains a forbidden control character")
    return value


def _require_safe_id(
    value: Any,
    *,
    label: str,
    error_type: type[RegistryError] = RegistryValidationError,
) -> str:
    text = _require_text(value, label=label, maximum=64, error_type=error_type)
    if _SAFE_ID.fullmatch(text) is None:
        raise error_type(f"{label} must match {_SAFE_ID.pattern}")
    return text


def _require_choice(
    value: Any,
    choices: tuple[str, ...],
    *,
    label: str,
    error_type: type[RegistryError] = RegistryValidationError,
) -> str:
    if not isinstance(value, str) or value not in choices:
        raise error_type(f"{label} must be one of {list(choices)}")
    return value


def _require_canonical_path(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise RegistryPathError(f"{label} must be a path string")
    try:
        canonical = canonicalize_local_path(value, label=label)
    except CatalogError as exc:
        raise RegistryPathError(str(exc)) from exc
    if canonical != value:
        raise RegistryPathError(f"{label} must already be canonical")
    return value


def _require_bounded_json(value: Any, *, label: str) -> None:
    try:
        serialized = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise RegistryValidationError(f"{label} must contain only JSON values") from exc
    if len(serialized.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise RegistryValidationError(f"{label} exceeds {MAX_DOCUMENT_BYTES} bytes")


validate_registry_document = validate_registry
register_rendered_project = register_project
