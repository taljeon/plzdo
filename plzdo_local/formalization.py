from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional

from .execution_rules import ExecutionRuleError, validate_execution_route
from .validation import (
    ValidationError,
    reject_credential_shapes,
    reject_credential_shapes_deep,
    require_exact_keys,
    require_object,
    require_safe_id,
    require_string,
)


SCHEMA_VERSION = "plzdo-local.formalization.v1"
FORMALIZATION_SCHEMA_VERSION = SCHEMA_VERSION

STATUS_DRAFT = "draft"
STATUS_APPROVED = "approved"
STATUS_COMPLETED = "completed"
STATUS_SUPERSEDED = "superseded"
STATUSES = (STATUS_DRAFT, STATUS_APPROVED, STATUS_COMPLETED, STATUS_SUPERSEDED)
TERMINAL_STATUSES = (STATUS_COMPLETED, STATUS_SUPERSEDED)

GOVERNED_FIELDS = (
    "objective",
    "criteria",
    "nonGoals",
    "constraints",
    "route",
    "plan",
    "evidenceContract",
)
FORMALIZATION_KEYS = {
    "schemaVersion",
    "id",
    "projectId",
    "status",
    *GOVERNED_FIELDS,
    "approval",
    "completion",
    "supersession",
    "createdAt",
    "updatedAt",
}
APPROVAL_KEYS = {"operatorConfirmed", "approvedAt", "approvalHash"}
COMPLETION_KEYS = {"evidenceReference", "evidenceSha256", "completedAt"}
SUPERSESSION_KEYS = {"reason", "supersededAt"}

MAX_OBJECTIVE_LENGTH = 4_000
MAX_TEXT_LENGTH = 1_000
MAX_LIST_ITEMS = 64
MAX_RECORD_BYTES = 512 * 1024

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class FormalizationError(ValueError):
    """Base error for pure formalization operations."""


class FormalizationValidationError(FormalizationError):
    """Raised when a formalization does not match the exact v1 contract."""


class FormalizationApprovalError(FormalizationValidationError):
    """Raised when approval is absent, unconfirmed, or stale."""


class FormalizationTransitionError(FormalizationError):
    """Raised when a lifecycle transition is not permitted."""


class FormalizationImmutableError(FormalizationTransitionError):
    """Raised when a completed or superseded record would change."""


class FormalizationActivationError(FormalizationError):
    """Raised when Goal or bounded-loop activation is not approved."""


def build_formalization(
    *,
    formalization_id: str,
    objective: str,
    criteria: Iterable[str],
    non_goals: Iterable[str],
    constraints: Iterable[str],
    route: dict[str, Any],
    plan: Iterable[str],
    evidence_contract: Iterable[str],
    created_at: Optional[str] = None,
    project_id: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> dict[str, Any]:
    """Build a validated draft without reading or writing persistent state."""

    created = _select_timestamp(created_at, timestamp, label="created_at")
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "id": formalization_id,
        "projectId": project_id,
        "status": STATUS_DRAFT,
        "objective": objective,
        "criteria": _materialize_text_list(criteria, label="formalization.criteria"),
        "nonGoals": _materialize_text_list(non_goals, label="formalization.nonGoals"),
        "constraints": _materialize_text_list(constraints, label="formalization.constraints"),
        "route": copy.deepcopy(route),
        "plan": _materialize_text_list(plan, label="formalization.plan"),
        "evidenceContract": _materialize_text_list(
            evidence_contract,
            label="formalization.evidenceContract",
        ),
        "approval": None,
        "completion": None,
        "supersession": None,
        "createdAt": created,
        "updatedAt": created,
    }
    validate_formalization(record)
    return record


def validate_formalization(value: Any) -> None:
    """Validate exact keys, bounded content, lifecycle state, and approval hash."""

    try:
        record = require_object(value, label="formalization")
        require_exact_keys(record, FORMALIZATION_KEYS, label="formalization")
        if record["schemaVersion"] != SCHEMA_VERSION:
            raise FormalizationValidationError(
                f"formalization.schemaVersion must be {SCHEMA_VERSION}"
            )
        require_safe_id(record["id"], label="formalization.id")
        if record["projectId"] is not None:
            require_safe_id(record["projectId"], label="formalization.projectId")
        if record["status"] not in STATUSES:
            raise FormalizationValidationError(
                f"formalization.status must be one of {list(STATUSES)}"
            )

        _validate_governed_fields(record)
        created = _require_timestamp(record["createdAt"], label="formalization.createdAt")
        updated = _require_timestamp(record["updatedAt"], label="formalization.updatedAt")
        if updated < created:
            raise FormalizationValidationError(
                "formalization.updatedAt must not precede createdAt"
            )
        _validate_terminal_metadata(record)
        _validate_approval(record)
        _require_bounded_json(record)
    except ValidationError as exc:
        raise FormalizationValidationError(str(exc)) from exc


def canonical_json(value: Any) -> str:
    """Return deterministic UTF-8 JSON text suitable for SHA-256 binding."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise FormalizationValidationError("value must contain only canonical JSON values") from exc


def canonical_approval_payload(value: Any) -> dict[str, Any]:
    """Return only the commitments governed by operator approval."""

    try:
        record = require_object(value, label="formalization")
        missing = [field for field in GOVERNED_FIELDS if field not in record]
        if missing:
            raise FormalizationValidationError(
                f"formalization approval payload is missing fields: {missing}"
            )
        _validate_governed_fields(record)
        return {field: copy.deepcopy(record[field]) for field in GOVERNED_FIELDS}
    except ValidationError as exc:
        raise FormalizationValidationError(str(exc)) from exc


def approval_hash(value: Any) -> str:
    """Hash the canonical objective, commitments, route, plan, and evidence contract."""

    payload = canonical_approval_payload(value)
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def approve_formalization(
    value: Any,
    *,
    operator_confirmed: bool,
    approved_at: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> dict[str, Any]:
    """Return an approved copy after an explicit operator confirmation."""

    validate_formalization(value)
    if operator_confirmed is not True:
        raise FormalizationApprovalError("approval requires operator_confirmed=True")
    if value["status"] in TERMINAL_STATUSES:
        raise FormalizationImmutableError(
            f"{value['status']} formalization is immutable"
        )
    approved = _select_timestamp(approved_at, timestamp, label="approved_at")
    updated = copy.deepcopy(value)
    updated["status"] = STATUS_APPROVED
    updated["approval"] = {
        "operatorConfirmed": True,
        "approvedAt": approved,
        "approvalHash": approval_hash(updated),
    }
    updated["updatedAt"] = approved
    validate_formalization_transition(
        value,
        updated,
        operator_confirmed=operator_confirmed,
    )
    return updated


def edit_formalization(
    value: Any,
    updates: Optional[Mapping[str, Any]] = None,
    *,
    updated_at: Optional[str] = None,
    timestamp: Optional[str] = None,
    objective: Optional[str] = None,
    criteria: Optional[Iterable[str]] = None,
    non_goals: Optional[Iterable[str]] = None,
    constraints: Optional[Iterable[str]] = None,
    route: Optional[dict[str, Any]] = None,
    plan: Optional[Iterable[str]] = None,
    evidence_contract: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """Edit governed content; changed approved commitments return to draft."""

    validate_formalization(value)
    if value["status"] in TERMINAL_STATUSES:
        raise FormalizationImmutableError(
            f"{value['status']} formalization is immutable"
        )
    changed_at = _select_timestamp(updated_at, timestamp, label="updated_at")
    governed_updates = _collect_updates(
        updates,
        objective=objective,
        criteria=criteria,
        non_goals=non_goals,
        constraints=constraints,
        route=route,
        plan=plan,
        evidence_contract=evidence_contract,
    )
    if not governed_updates:
        raise FormalizationTransitionError("formalization edit requires a governed field")

    updated = copy.deepcopy(value)
    for field, item in governed_updates.items():
        if field == "route":
            updated[field] = copy.deepcopy(item)
        elif field == "objective":
            updated[field] = item
        else:
            updated[field] = _materialize_text_list(
                item,
                label=f"formalization.{field}",
            )

    commitments_changed = any(
        updated[field] != value[field] for field in GOVERNED_FIELDS
    )
    if value["status"] == STATUS_APPROVED and commitments_changed:
        updated["status"] = STATUS_DRAFT
        updated["approval"] = None
    updated["updatedAt"] = changed_at
    validate_formalization_transition(value, updated)
    return updated


def complete_formalization(
    value: Any,
    *,
    evidence_reference: str,
    evidence_sha256: str,
    completed_at: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> dict[str, Any]:
    """Return an immutable completed copy of a currently approved record."""

    validate_formalization(value)
    if value["status"] in TERMINAL_STATUSES:
        raise FormalizationImmutableError(
            f"{value['status']} formalization is immutable"
        )
    if value["status"] != STATUS_APPROVED:
        raise FormalizationTransitionError("only an approved formalization can be completed")
    completed = _select_timestamp(completed_at, timestamp, label="completed_at")
    updated = copy.deepcopy(value)
    updated["status"] = STATUS_COMPLETED
    updated["completion"] = {
        "evidenceReference": evidence_reference,
        "evidenceSha256": evidence_sha256,
        "completedAt": completed,
    }
    updated["updatedAt"] = completed
    validate_formalization_transition(value, updated)
    return updated


def supersede_formalization(
    value: Any,
    *,
    reason: str,
    superseded_at: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> dict[str, Any]:
    """Return an immutable superseded copy of a draft or approved record."""

    validate_formalization(value)
    if value["status"] in TERMINAL_STATUSES:
        raise FormalizationImmutableError(
            f"{value['status']} formalization is immutable"
        )
    superseded = _select_timestamp(
        superseded_at,
        timestamp,
        label="superseded_at",
    )
    updated = copy.deepcopy(value)
    updated["status"] = STATUS_SUPERSEDED
    updated["supersession"] = {
        "reason": reason,
        "supersededAt": superseded,
    }
    updated["updatedAt"] = superseded
    validate_formalization_transition(value, updated)
    return updated


def validate_formalization_transition(
    previous: Any,
    current: Any,
    *,
    operator_confirmed: bool = False,
) -> None:
    """Validate lifecycle movement and terminal immutability between two records."""

    if type(operator_confirmed) is not bool:
        raise FormalizationTransitionError("operator_confirmed must be a boolean")
    validate_formalization(previous)
    validate_formalization(current)
    old = previous
    new = current

    if old["status"] in TERMINAL_STATUSES:
        if new != old:
            raise FormalizationImmutableError(
                f"{old['status']} formalization is immutable"
            )
        return

    for field in ("schemaVersion", "id", "projectId", "createdAt"):
        if new[field] != old[field]:
            raise FormalizationTransitionError(f"formalization.{field} is immutable")
    if _require_timestamp(new["updatedAt"], label="formalization.updatedAt") < _require_timestamp(
        old["updatedAt"],
        label="previous formalization.updatedAt",
    ):
        raise FormalizationTransitionError("formalization.updatedAt must not move backwards")

    legal = {
        STATUS_DRAFT: {STATUS_DRAFT, STATUS_APPROVED, STATUS_SUPERSEDED},
        STATUS_APPROVED: {
            STATUS_APPROVED,
            STATUS_DRAFT,
            STATUS_COMPLETED,
            STATUS_SUPERSEDED,
        },
    }
    if new["status"] not in legal[old["status"]]:
        raise FormalizationTransitionError(
            f"illegal formalization transition: {old['status']} -> {new['status']}"
        )
    if old["status"] == STATUS_DRAFT and new["status"] == STATUS_APPROVED:
        if not operator_confirmed:
            raise FormalizationApprovalError(
                "draft approval transition requires operator_confirmed=True"
            )

    commitments_changed = any(old[field] != new[field] for field in GOVERNED_FIELDS)
    if old["status"] == STATUS_APPROVED and commitments_changed:
        if new["status"] != STATUS_DRAFT or new["approval"] is not None:
            raise FormalizationTransitionError(
                "changed approved commitments must return to draft and clear approval"
            )
    if old["status"] == STATUS_APPROVED and not commitments_changed and new["status"] == STATUS_DRAFT:
        raise FormalizationTransitionError(
            "approved formalization may return to draft only after a governed edit"
        )
    if new["status"] in {STATUS_COMPLETED, STATUS_SUPERSEDED} and commitments_changed:
        raise FormalizationTransitionError(
            "terminal transition cannot change governed commitments"
        )


def activation_requires_approval(route: Any) -> bool:
    """Return whether a validated route is Goal-weighted or bounded-loop work."""

    try:
        validate_execution_route(route)
    except ExecutionRuleError as exc:
        raise FormalizationValidationError("activation route is invalid") from exc
    return route["weight"] == "goal" or route["boundedLoop"] is True


def require_activation_approval(
    value: Any,
    *,
    route: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Require a fresh approved record before Goal or bounded-loop activation."""

    validate_formalization(value)
    selected_route = value["route"] if route is None else route
    try:
        validate_execution_route(selected_route)
    except ExecutionRuleError as exc:
        raise FormalizationActivationError("activation route is invalid") from exc
    if selected_route != value["route"]:
        raise FormalizationActivationError(
            "activation route must match the formalization-bound route"
        )
    if activation_requires_approval(selected_route) and value["status"] != STATUS_APPROVED:
        raise FormalizationActivationError(
            "Goal or bounded-loop activation requires an approved formalization"
        )
    return copy.deepcopy(value)


def require_approved_formalization(value: Any) -> dict[str, Any]:
    """Require approved status regardless of route, for callers already at a gate."""

    validate_formalization(value)
    if value["status"] != STATUS_APPROVED:
        raise FormalizationActivationError("formalization must be approved")
    return copy.deepcopy(value)


def _validate_governed_fields(record: Mapping[str, Any]) -> None:
    objective = _require_safe_text(
        record["objective"],
        label="formalization.objective",
        maximum=MAX_OBJECTIVE_LENGTH,
    )
    if not objective.strip():
        raise FormalizationValidationError("formalization.objective must not be blank")
    _validate_text_list(
        record["criteria"],
        label="formalization.criteria",
        require_nonempty=True,
    )
    _validate_text_list(record["nonGoals"], label="formalization.nonGoals")
    _validate_text_list(record["constraints"], label="formalization.constraints")
    try:
        validate_execution_route(record["route"])
        reject_credential_shapes_deep(record["route"], label="formalization.route")
    except ExecutionRuleError as exc:
        raise FormalizationValidationError("formalization.route is invalid") from exc
    except ValidationError as exc:
        raise FormalizationValidationError(str(exc)) from exc
    _validate_text_list(
        record["plan"],
        label="formalization.plan",
        require_nonempty=True,
    )
    _validate_text_list(
        record["evidenceContract"],
        label="formalization.evidenceContract",
        require_nonempty=True,
    )


def _validate_terminal_metadata(record: Mapping[str, Any]) -> None:
    status = record["status"]
    completion = record["completion"]
    supersession = record["supersession"]

    if status in {STATUS_DRAFT, STATUS_APPROVED}:
        if completion is not None or supersession is not None:
            raise FormalizationValidationError(
                f"{status} formalization terminal metadata must be null"
            )
        return

    if status == STATUS_COMPLETED:
        if supersession is not None:
            raise FormalizationValidationError(
                "completed formalization.supersession must be null"
            )
        metadata = require_object(completion, label="formalization.completion")
        require_exact_keys(metadata, COMPLETION_KEYS, label="formalization.completion")
        reference = _require_safe_text(
            metadata["evidenceReference"],
            label="formalization.completion.evidenceReference",
            maximum=MAX_TEXT_LENGTH,
        )
        if not reference.strip():
            raise FormalizationValidationError(
                "formalization.completion.evidenceReference must not be blank"
            )
        digest = require_string(
            metadata["evidenceSha256"],
            label="formalization.completion.evidenceSha256",
            minimum=64,
            maximum=64,
        )
        if _SHA256.fullmatch(digest) is None:
            raise FormalizationValidationError(
                "formalization.completion.evidenceSha256 must be a lowercase SHA-256 digest"
            )
        _require_timestamp(
            metadata["completedAt"],
            label="formalization.completion.completedAt",
        )
        if metadata["completedAt"] != record["updatedAt"]:
            raise FormalizationValidationError(
                "formalization.completion.completedAt must equal updatedAt"
            )
        return

    if completion is not None:
        raise FormalizationValidationError(
            "superseded formalization.completion must be null"
        )
    metadata = require_object(supersession, label="formalization.supersession")
    require_exact_keys(metadata, SUPERSESSION_KEYS, label="formalization.supersession")
    reason = _require_safe_text(
        metadata["reason"],
        label="formalization.supersession.reason",
        maximum=MAX_TEXT_LENGTH,
    )
    if not reason.strip():
        raise FormalizationValidationError(
            "formalization.supersession.reason must not be blank"
        )
    _require_timestamp(
        metadata["supersededAt"],
        label="formalization.supersession.supersededAt",
    )
    if metadata["supersededAt"] != record["updatedAt"]:
        raise FormalizationValidationError(
            "formalization.supersession.supersededAt must equal updatedAt"
        )


def _validate_approval(record: Mapping[str, Any]) -> None:
    status = record["status"]
    approval = record["approval"]
    if status == STATUS_DRAFT:
        if approval is not None:
            raise FormalizationApprovalError("draft formalization.approval must be null")
        return
    if status in {STATUS_APPROVED, STATUS_COMPLETED} and approval is None:
        raise FormalizationApprovalError(
            f"{status} formalization requires approval metadata"
        )
    if approval is None:
        return

    metadata = require_object(approval, label="formalization.approval")
    require_exact_keys(metadata, APPROVAL_KEYS, label="formalization.approval")
    if metadata["operatorConfirmed"] is not True:
        raise FormalizationApprovalError(
            "formalization.approval.operatorConfirmed must be true"
        )
    approved = _require_timestamp(
        metadata["approvedAt"],
        label="formalization.approval.approvedAt",
    )
    if approved < _require_timestamp(record["createdAt"], label="formalization.createdAt"):
        raise FormalizationApprovalError(
            "formalization.approval.approvedAt must not precede createdAt"
        )
    if approved > _require_timestamp(record["updatedAt"], label="formalization.updatedAt"):
        raise FormalizationApprovalError(
            "formalization.approval.approvedAt must not follow updatedAt"
        )
    digest = require_string(
        metadata["approvalHash"],
        label="formalization.approval.approvalHash",
        minimum=64,
        maximum=64,
    )
    expected = approval_hash(record)
    if digest != expected:
        raise FormalizationApprovalError(
            "formalization.approval.approvalHash does not match governed content"
        )


def _collect_updates(
    updates: Optional[Mapping[str, Any]],
    *,
    objective: Optional[str],
    criteria: Optional[Iterable[str]],
    non_goals: Optional[Iterable[str]],
    constraints: Optional[Iterable[str]],
    route: Optional[dict[str, Any]],
    plan: Optional[Iterable[str]],
    evidence_contract: Optional[Iterable[str]],
) -> dict[str, Any]:
    collected: dict[str, Any] = {}
    if updates is not None:
        if not isinstance(updates, Mapping):
            raise FormalizationTransitionError("formalization updates must be an object")
        unknown = sorted(
            (key for key in updates if key not in GOVERNED_FIELDS),
            key=repr,
        )
        if unknown:
            raise FormalizationTransitionError(
                f"formalization updates contain non-governed fields: {unknown}"
            )
        collected.update(updates)

    keyword_updates = {
        "objective": objective,
        "criteria": criteria,
        "nonGoals": non_goals,
        "constraints": constraints,
        "route": route,
        "plan": plan,
        "evidenceContract": evidence_contract,
    }
    for field, item in keyword_updates.items():
        if item is None:
            continue
        if field in collected:
            raise FormalizationTransitionError(
                f"formalization.{field} was supplied more than once"
            )
        collected[field] = item
    return collected


def _materialize_text_list(values: Iterable[str], *, label: str) -> list[str]:
    if isinstance(values, (str, bytes)):
        raise FormalizationValidationError(f"{label} must be an array")
    try:
        items = list(values)
    except TypeError as exc:
        raise FormalizationValidationError(f"{label} must be an array") from exc
    _validate_text_list(items, label=label)
    return items


def _validate_text_list(
    value: Any,
    *,
    label: str,
    require_nonempty: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise FormalizationValidationError(f"{label} must be an array")
    if require_nonempty and not value:
        raise FormalizationValidationError(f"{label} must not be empty")
    if len(value) > MAX_LIST_ITEMS:
        raise FormalizationValidationError(
            f"{label} must contain at most {MAX_LIST_ITEMS} items"
        )
    checked: list[str] = []
    for index, item in enumerate(value):
        text = _require_safe_text(
            item,
            label=f"{label}[{index}]",
            maximum=MAX_TEXT_LENGTH,
        )
        if not text.strip():
            raise FormalizationValidationError(f"{label}[{index}] must not be blank")
        checked.append(text)
    if len(checked) != len(set(checked)):
        raise FormalizationValidationError(f"{label} must contain unique items")
    return checked


def _require_safe_text(value: Any, *, label: str, maximum: int) -> str:
    try:
        text = require_string(value, label=label, maximum=maximum)
        reject_credential_shapes(text, label=label)
        return text
    except ValidationError as exc:
        raise FormalizationValidationError(str(exc)) from exc


def _select_timestamp(
    specific: Optional[str],
    generic: Optional[str],
    *,
    label: str,
) -> str:
    if specific is None and generic is None:
        raise FormalizationValidationError(f"{label} is required")
    if specific is not None and generic is not None and specific != generic:
        raise FormalizationValidationError(
            f"{label} and timestamp must match when both are provided"
        )
    value = specific if specific is not None else generic
    _require_timestamp(value, label=label)
    return value


def _require_timestamp(value: Any, *, label: str) -> datetime:
    text = require_string(value, label=label, maximum=64)
    parseable = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(parseable)
    except ValueError as exc:
        raise FormalizationValidationError(
            f"{label} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise FormalizationValidationError(f"{label} must include a timezone")
    return parsed


def _require_bounded_json(record: Mapping[str, Any]) -> None:
    serialized = canonical_json(record).encode("utf-8")
    if len(serialized) > MAX_RECORD_BYTES:
        raise FormalizationValidationError(
            f"formalization exceeds {MAX_RECORD_BYTES} bytes"
        )


build_draft = build_formalization
create_formalization = build_formalization
compute_approval_hash = approval_hash
formalization_hash = approval_hash
validate_record = validate_formalization
validate_transition = validate_formalization_transition
amend_formalization = edit_formalization
require_approved_for_activation = require_activation_approval
validate_activation = require_activation_approval
