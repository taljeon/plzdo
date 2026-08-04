from __future__ import annotations

import copy
import re
from typing import Any, Optional

from .catalog import (
    WORKFLOW_LANE_OPERATIONAL,
    WORKFLOW_LANE_STANDARD,
    WORKFLOW_LANES,
    CatalogError,
    get_repository,
    validate_repository,
)
from .registry import (
    RULE_PROVIDED_PROJECT,
    RegistryError,
    build_resolution,
    get_project,
    resolve_project,
    validate_project,
    validate_resolution,
)


SCHEMA_VERSION = "plzdo-local.execution-route.v1"
ROUTE_SCHEMA_VERSION = SCHEMA_VERSION

WEIGHT_QUICK = "quick"
WEIGHT_PLAN = "plan"
WEIGHT_GOAL = "goal"
EXECUTION_WEIGHTS = (WEIGHT_QUICK, WEIGHT_PLAN, WEIGHT_GOAL)

RULE_WEIGHT_OPERATIONAL_GOAL = "route-weight-operational-goal-v1"
RULE_WEIGHT_CODING_PLAN = "route-weight-coding-plan-v1"
RULE_WEIGHT_PRODUCT_GOAL = "route-weight-product-goal-v1"
RULE_WEIGHT_ATTACHED_QUICK = "route-weight-attached-quick-v1"
RULE_WEIGHT_DEFAULT_PLAN = "route-weight-default-plan-v1"
RULE_LOOP_EXPLICIT = "route-loop-explicit-v1"
RULE_LOOP_NONE = "route-loop-none-v1"

OPERATIONAL_TERMS = (
    "authentication",
    "authorization",
    "credential",
    "customer data",
    "deploy",
    "migration",
    "payment",
    "production",
    "real apply",
    "release",
    "security",
    "target write",
)
CODING_PLAN_TERMS = (
    "code review",
    "coursework",
    "debug",
    "exercise",
    "implement",
    "refactor",
    "test suite",
)
PRODUCT_GOAL_TERMS = (
    "app",
    "application",
    "architecture",
    "platform",
    "product",
    "service",
    "system design",
)
QUICK_TERMS = (
    "fix typo",
    "one line",
    "one-line",
    "quick fix",
    "rename one",
    "single file",
    "small fix",
    "update wording",
)
BOUNDED_LOOP_TERMS = (
    "batch",
    "for each",
    "iterative",
    "iteratively",
    "loop",
    "multiple rounds",
    "repeat",
    "sweep",
    "until clean",
    "until complete",
)


class ExecutionRuleError(ValueError):
    """Base error for execution-route operations."""


class ExecutionRouteValidationError(ExecutionRuleError):
    """Raised when route input or output violates the exact v1 contract."""


class ExecutionRouteContextError(ExecutionRuleError):
    """Raised when project, registry, and catalog context is inconsistent."""


def classify_execution(
    goal: str,
    *,
    project_decision: Optional[dict[str, Any]] = None,
    project: Optional[dict[str, Any]] = None,
    repository: Optional[dict[str, Any]] = None,
    workflow_lane: Optional[str] = None,
    bounded_loop_requested: bool = False,
    ignored_identity_terms: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Classify weight and bounded-loop need as independent route axes."""

    normalized_goal = _normalize_goal(_require_goal(goal))
    if type(bounded_loop_requested) is not bool:
        raise ExecutionRouteValidationError("bounded_loop_requested must be a boolean")

    if project is not None:
        try:
            validate_project(project)
        except RegistryError as exc:
            raise ExecutionRouteContextError("project context is invalid") from exc
    if repository is not None:
        try:
            validate_repository(repository)
        except CatalogError as exc:
            raise ExecutionRouteContextError("repository context is invalid") from exc

    decision = _prepare_project_decision(project_decision=project_decision, project=project)
    selected_lane = _select_workflow_lane(repository=repository, workflow_lane=workflow_lane)
    if project is not None and decision["decision"] == "attached" and decision["projectId"] != project["id"]:
        raise ExecutionRouteContextError("attached project decision does not match project context")
    if project is not None and decision["decision"] != "attached":
        raise ExecutionRouteContextError("project context requires an attached project decision")

    bounded_loop = bounded_loop_requested or _contains_any(normalized_goal, BOUNDED_LOOP_TERMS)
    loop_rule = RULE_LOOP_EXPLICIT if bounded_loop else RULE_LOOP_NONE

    classification_goal = _without_project_identity_terms(
        normalized_goal,
        project=project,
        extra_terms=ignored_identity_terms,
    )
    weight, weight_rule, weight_explanation = _classify_weight(
        classification_goal,
        attached=decision["decision"] == "attached",
        workflow_lane=selected_lane,
    )
    loop_explanation = (
        "bounded loop requested by explicit repeat language or caller intent"
        if bounded_loop
        else "no bounded-loop trigger matched"
    )
    route = {
        "schemaVersion": SCHEMA_VERSION,
        "weight": weight,
        "boundedLoop": bounded_loop,
        "projectDecision": copy.deepcopy(decision),
        "ruleIds": [decision["ruleId"], weight_rule, loop_rule],
        "explanation": f"{weight_explanation}; {loop_explanation}",
        "formalizationRequired": weight == WEIGHT_GOAL or bounded_loop,
        "recommendedEvidence": _recommended_evidence(weight, bounded_loop=bounded_loop),
    }
    validate_execution_route(route)
    return route


def route_goal(
    goal: str,
    registry: Any,
    *,
    catalog: Optional[Any] = None,
    identifier: Optional[str] = None,
    domain: Optional[str] = None,
    area: Optional[str] = None,
    bounded_loop_requested: bool = False,
) -> dict[str, Any]:
    """Resolve the project and classify execution without writing state."""

    try:
        decision = resolve_project(
            registry,
            goal,
            identifier=identifier,
            domain=domain,
            area=area,
            catalog=catalog,
        )
    except RegistryError as exc:
        raise ExecutionRouteContextError("project resolution failed") from exc

    project = None
    repository = None
    ignored_identity_terms: list[str] = []
    for candidate_id in decision["candidateIds"]:
        try:
            candidate = get_project(
                registry,
                candidate_id,
                include_archived=True,
                catalog=catalog,
            )
        except RegistryError as exc:
            raise ExecutionRouteContextError("project resolution candidates are inconsistent") from exc
        ignored_identity_terms.extend([candidate["id"]] + list(candidate["aliases"]))
    if decision["decision"] == "attached":
        try:
            project = get_project(registry, decision["projectId"], catalog=catalog)
            if catalog is not None and project["repositoryId"] is not None:
                repository = get_repository(catalog, project["repositoryId"])
        except (RegistryError, CatalogError) as exc:
            raise ExecutionRouteContextError("attached route context is inconsistent") from exc
    return classify_execution(
        goal,
        project_decision=decision,
        project=project,
        repository=repository,
        bounded_loop_requested=bounded_loop_requested,
        ignored_identity_terms=tuple(sorted(set(ignored_identity_terms))),
    )


def validate_execution_route(value: Any) -> None:
    route = _require_object(value, label="execution route")
    _require_exact_keys(
        route,
        {
            "schemaVersion",
            "weight",
            "boundedLoop",
            "projectDecision",
            "ruleIds",
            "explanation",
            "formalizationRequired",
            "recommendedEvidence",
        },
        label="execution route",
    )
    if route["schemaVersion"] != SCHEMA_VERSION:
        raise ExecutionRouteValidationError(f"execution route.schemaVersion must be {SCHEMA_VERSION}")
    weight = _require_choice(route["weight"], EXECUTION_WEIGHTS, label="execution route.weight")
    bounded_loop = _require_bool(route["boundedLoop"], label="execution route.boundedLoop")
    try:
        validate_resolution(route["projectDecision"])
    except RegistryError as exc:
        raise ExecutionRouteValidationError("execution route.projectDecision is invalid") from exc

    rule_ids = route["ruleIds"]
    if not isinstance(rule_ids, list) or len(rule_ids) != 3:
        raise ExecutionRouteValidationError("execution route.ruleIds must contain exactly three rule ids")
    checked_rules = [
        _require_rule_id(rule_id, label=f"execution route.ruleIds[{index}]")
        for index, rule_id in enumerate(rule_ids)
    ]
    if len(set(checked_rules)) != len(checked_rules):
        raise ExecutionRouteValidationError("execution route.ruleIds must be unique")
    _require_text(route["explanation"], label="execution route.explanation", maximum=500)
    formalization = _require_bool(
        route["formalizationRequired"],
        label="execution route.formalizationRequired",
    )
    if formalization != (weight == WEIGHT_GOAL or bounded_loop):
        raise ExecutionRouteValidationError("formalizationRequired does not match weight and boundedLoop")
    evidence = route["recommendedEvidence"]
    if not isinstance(evidence, list) or not evidence or len(evidence) > 8:
        raise ExecutionRouteValidationError("execution route.recommendedEvidence must contain 1 to 8 items")
    checked_evidence = [
        _require_rule_id(item, label=f"execution route.recommendedEvidence[{index}]")
        for index, item in enumerate(evidence)
    ]
    if len(set(checked_evidence)) != len(checked_evidence):
        raise ExecutionRouteValidationError("execution route.recommendedEvidence must be unique")


def _prepare_project_decision(
    *,
    project_decision: Optional[dict[str, Any]],
    project: Optional[dict[str, Any]],
) -> dict[str, Any]:
    if project_decision is None:
        if project is not None:
            return build_resolution(
                decision="attached",
                project_id=project["id"],
                candidate_ids=[project["id"]],
                rule_id=RULE_PROVIDED_PROJECT,
                reason="an explicit validated project context was provided",
            )
        return build_resolution(
            decision="create",
            candidate_ids=[],
            rule_id="registry-resolve-not-requested-create-v1",
            reason="no project context was supplied",
        )
    try:
        validate_resolution(project_decision)
    except RegistryError as exc:
        raise ExecutionRouteContextError("project decision is invalid") from exc
    return copy.deepcopy(project_decision)


def _select_workflow_lane(
    *,
    repository: Optional[dict[str, Any]],
    workflow_lane: Optional[str],
) -> str:
    repository_lane = repository["workflowLane"] if repository is not None else None
    if workflow_lane is not None:
        _require_choice(workflow_lane, WORKFLOW_LANES, label="workflow_lane")
    if repository_lane is not None and workflow_lane is not None and repository_lane != workflow_lane:
        raise ExecutionRouteContextError("workflow_lane conflicts with repository context")
    return repository_lane or workflow_lane or WORKFLOW_LANE_STANDARD


def _classify_weight(goal: str, *, attached: bool, workflow_lane: str) -> tuple[str, str, str]:
    if workflow_lane == WORKFLOW_LANE_OPERATIONAL or _contains_any(goal, OPERATIONAL_TERMS):
        return WEIGHT_GOAL, RULE_WEIGHT_OPERATIONAL_GOAL, "goal selected by the operational-risk rule"
    if _contains_any(goal, CODING_PLAN_TERMS):
        return WEIGHT_PLAN, RULE_WEIGHT_CODING_PLAN, "plan selected by the coding-work rule"
    if _contains_any(goal, PRODUCT_GOAL_TERMS):
        return WEIGHT_GOAL, RULE_WEIGHT_PRODUCT_GOAL, "goal selected by the durable-product rule"
    if attached and _contains_any(goal, QUICK_TERMS):
        return WEIGHT_QUICK, RULE_WEIGHT_ATTACHED_QUICK, "quick selected for a small attached-project change"
    return WEIGHT_PLAN, RULE_WEIGHT_DEFAULT_PLAN, "plan selected by the default bounded-work rule"


def _recommended_evidence(weight: str, *, bounded_loop: bool) -> list[str]:
    if weight == WEIGHT_QUICK:
        evidence = ["focused-check"]
    elif weight == WEIGHT_PLAN:
        evidence = ["plan-item-evidence", "focused-checks"]
    else:
        evidence = ["approved-formalization", "plan-item-evidence", "full-verification"]
    if bounded_loop:
        evidence.extend(["iteration-checkpoint", "iteration-evidence", "stop-reason"])
    return evidence


def _normalize_goal(value: str) -> str:
    return " ".join(value.casefold().split())


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_contains_phrase(text, term) for term in terms)


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text) is not None


def _without_project_identity_terms(
    text: str,
    *,
    project: Optional[dict[str, Any]],
    extra_terms: tuple[str, ...],
) -> str:
    stripped = text
    identities = list(extra_terms)
    if project is not None:
        identities.extend([project["id"]] + list(project["aliases"]))
    identities = sorted(set(identities), key=len, reverse=True)
    for identity in identities:
        stripped = re.sub(
            r"(?<![a-z0-9-])" + re.escape(identity) + r"(?![a-z0-9-])",
            " ",
            stripped,
        )
    return " ".join(stripped.split())


def _require_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExecutionRouteValidationError(f"{label} must be an object")
    return value


def _require_exact_keys(value: dict[str, Any], keys: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys)
        raise ExecutionRouteValidationError(f"{label} keys mismatch: missing={missing}, extra={extra}")


def _require_text(value: Any, *, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ExecutionRouteValidationError(f"{label} must be a string")
    if not value or len(value) > maximum:
        raise ExecutionRouteValidationError(f"{label} length must be between 1 and {maximum}")
    if "\x00" in value or any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ExecutionRouteValidationError(f"{label} contains a forbidden control character")
    return value


def _require_goal(value: Any) -> str:
    text = _require_text(value, label="goal", maximum=4000)
    if not text.strip():
        raise ExecutionRouteValidationError("goal must contain non-whitespace text")
    return text


def _require_choice(value: Any, choices: tuple[str, ...], *, label: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ExecutionRouteValidationError(f"{label} must be one of {list(choices)}")
    return value


def _require_bool(value: Any, *, label: str) -> bool:
    if type(value) is not bool:
        raise ExecutionRouteValidationError(f"{label} must be a boolean")
    return value


def _require_rule_id(value: Any, *, label: str) -> str:
    text = _require_text(value, label=label, maximum=96)
    if re.fullmatch(r"[a-z][a-z0-9-]+", text) is None:
        raise ExecutionRouteValidationError(f"{label} must be a public-safe rule id")
    return text


classify_route = classify_execution
route_execution = classify_execution
route = route_goal
validate_route = validate_execution_route
