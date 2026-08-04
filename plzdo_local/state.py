from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, NamedTuple, Optional

from .formalization import FormalizationError, require_approved_formalization
from .validation import ValidationError, reject_credential_shapes


SCHEMA_VERSION = "plzdo-local.state.v1"
STATE_SCHEMA_VERSION = SCHEMA_VERSION
STATE_ARCHIVE_SCHEMA_VERSION = "plzdo-local.state-archive.v1"
CHECKPOINT_DECISION_SCHEMA_VERSION = "plzdo-local.checkpoint-decision.v1"
BOUNDED_LOOP_SCHEMA_VERSION = "plzdo-local.bounded-loop.v1"

MAX_ACTIVE_EVIDENCE_COUNT = 40
MAX_ACTIVE_EVIDENCE_BYTES = 16 * 1024
MAX_ACTIVE_STATE_BYTES = 32 * 1024
MAX_UNCOMPACTED_EVIDENCE_COUNT = 1024
MAX_UNCOMPACTED_STATE_BYTES = 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_UNCOMPACTED_STATE_BYTES + 64 * 1024

CHECKPOINT_THRESHOLD_PERCENT = 70
SELF_ESTIMATE_MARGIN_PERCENT = 5
MAX_TOKEN_COUNT = (1 << 63) - 1

MAX_LOOP_ITERATIONS = 100
MAX_LOOP_TIMEOUT_SECONDS = 7 * 24 * 60 * 60
MAX_LOOP_EVIDENCE_ITEMS = 8
MAX_LOOP_EVIDENCE_BYTES = 4096
STAGNATION_LIMIT = 2

CHECKPOINT_SOURCES = ("operator-observed", "token-count", "self-estimate")
LOOP_TERMINAL_STATUSES = (
    "success",
    "clean-no-op",
    "blocked",
    "approval-required",
    "exhausted",
    "stagnated",
)
LOOP_EXPLICIT_STOP_STATUSES = (
    "success",
    "clean-no-op",
    "blocked",
    "approval-required",
    "stagnated",
)
LOOP_STATUSES = ("active",) + LOOP_TERMINAL_STATUSES

_SAFE_ID = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_FALSE_ENV_VALUES = {"", "0", "false", "no", "none", "off", "disabled"}
_BACKGROUND_MARKERS = {
    "automated",
    "automation",
    "background",
    "batch",
    "cron",
    "daemon",
    "headless",
    "hook",
    "hooks",
    "noninteractive",
    "pipeline",
    "schedule",
    "scheduled",
    "scheduler",
    "unattended",
    "watch",
    "watcher",
}
_CONTEXT_ENV_MARKERS = {
    "caller",
    "context",
    "execution",
    "mode",
    "origin",
    "run",
    "runner",
    "trigger",
}
_UNATTENDED_ENV_KEYS = {
    "appveyor",
    "azure_http_user_agent",
    "bitbucket_build_number",
    "buildkite",
    "ci",
    "ci_name",
    "ci_server",
    "circleci",
    "codebuild_build_id",
    "codex_ci",
    "continuous_integration",
    "drone",
    "github-actions",
    "github_actions",
    "github_run_id",
    "github_workflow",
    "gitlab-ci",
    "gitlab_ci",
    "hudson_url",
    "invocation_id",
    "jenkins-url",
    "jenkins_url",
    "teamcity-version",
    "teamcity_version",
    "tf_build",
    "travis",
}
_UNCHANGED = object()


class StateError(ValueError):
    """Base error for work-state operations."""


class StateValidationError(StateError):
    """Raised when a state value violates the exact v1 contract."""


class StateCompactionError(StateError):
    """Raised when an active state cannot be reduced below its bounds."""


class CheckpointError(StateError):
    """Raised when context-checkpoint provenance is invalid."""


class BackgroundCheckpointError(CheckpointError):
    """Raised when an unattended environment marker is present."""


class LoopContractError(StateError):
    """Raised when a bounded-loop contract or transition is invalid."""


class LoopBindingError(LoopContractError):
    """Raised when a loop is resumed with different approval provenance."""


class LoopStoppedError(LoopContractError):
    """Raised when a terminal loop is advanced or stopped again."""


class StateTransition(NamedTuple):
    """Archive-first values for callers that persist a state transition."""

    archive: Optional[dict[str, Any]]
    active: dict[str, Any]


def build_evidence(*, evidence_type: str, summary: str, recorded_at: str) -> dict[str, Any]:
    evidence = {
        "type": _require_safe_id(evidence_type, label="evidence.type"),
        "summary": _require_text(summary, label="evidence.summary", maximum=1000),
        "recordedAt": _require_timestamp(recorded_at, label="evidence.recordedAt"),
    }
    _validate_evidence(evidence, label="evidence")
    return evidence


def build_state(
    *,
    work_id: str,
    current: str,
    next_step: str,
    constraints: Iterable[str] = (),
    evidence: Iterable[dict[str, Any]] = (),
    updated_at: str,
    context_checkpoint: Optional[dict[str, Any]] = None,
    loop_state: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a bounded active work pin without reading or writing files."""

    evidence_items = _copy_evidence(evidence, label="evidence")
    state = {
        "schemaVersion": SCHEMA_VERSION,
        "workId": _require_safe_id(work_id, label="workId"),
        "current": _require_text(current, label="current", maximum=1000),
        "next": _require_text(next_step, label="next", maximum=1000),
        "constraints": _copy_constraints(constraints),
        "lastEvidence": evidence_items,
        "lastEvidenceCount": len(evidence_items),
        "lastEvidenceBytes": _json_size(evidence_items, label="lastEvidence"),
        "archivedEvidenceCount": 0,
        "contextCheckpoint": copy.deepcopy(context_checkpoint),
        "loopState": copy.deepcopy(loop_state),
        "updatedAt": _require_timestamp(updated_at, label="updatedAt"),
    }
    validate_state(state)
    return state


def validate_state(value: Any) -> None:
    """Validate an exact-key, bounded ``plzdo-local.state.v1`` value."""

    _validate_state_shape(value, enforce_active_bounds=True)


def validate_state_archive(value: Any) -> None:
    archive = _require_object(value, label="state archive", error_type=StateValidationError)
    _require_exact_keys(
        archive,
        {
            "schemaVersion",
            "archivedAt",
            "sourceEvidenceCount",
            "sourceEvidenceBytes",
            "sourceState",
        },
        label="state archive",
        error_type=StateValidationError,
    )
    if archive["schemaVersion"] != STATE_ARCHIVE_SCHEMA_VERSION:
        raise StateValidationError(
            f"state archive.schemaVersion must be {STATE_ARCHIVE_SCHEMA_VERSION}"
        )
    archived_at = _require_timestamp(archive["archivedAt"], label="state archive.archivedAt")
    _validate_state_shape(archive["sourceState"], enforce_active_bounds=False)
    source = archive["sourceState"]
    count = _require_non_negative_int(
        archive["sourceEvidenceCount"], label="state archive.sourceEvidenceCount"
    )
    size = _require_non_negative_int(
        archive["sourceEvidenceBytes"], label="state archive.sourceEvidenceBytes"
    )
    if count != source["lastEvidenceCount"] or size != source["lastEvidenceBytes"]:
        raise StateValidationError("state archive evidence metrics do not match sourceState")
    _require_not_before(
        archived_at,
        source["updatedAt"],
        label="state archive.archivedAt",
        earlier_label="sourceState.updatedAt",
    )
    if _json_size(archive, label="state archive") > MAX_ARCHIVE_BYTES:
        raise StateValidationError(f"state archive exceeds {MAX_ARCHIVE_BYTES} bytes")


def record_state(
    state: Any,
    *,
    updated_at: str,
    current: Optional[str] = None,
    next_step: Optional[str] = None,
    constraints: Optional[Iterable[str]] = None,
    evidence: Iterable[dict[str, Any]] = (),
    context_checkpoint: Any = _UNCHANGED,
    loop_state: Any = _UNCHANGED,
) -> StateTransition:
    """Return an archive-first transition, compacting automatically when needed."""

    validate_state(state)
    timestamp = _require_timestamp(updated_at, label="updatedAt")
    _require_not_before(timestamp, state["updatedAt"], label="updatedAt", earlier_label="state.updatedAt")
    working = copy.deepcopy(state)
    if current is not None:
        working["current"] = _require_text(current, label="current", maximum=1000)
    if next_step is not None:
        working["next"] = _require_text(next_step, label="next", maximum=1000)
    if constraints is not None:
        working["constraints"] = _copy_constraints(constraints)

    additions = _copy_evidence(evidence, label="evidence")
    for index, item in enumerate(additions):
        _require_not_before(
            timestamp,
            item["recordedAt"],
            label="updatedAt",
            earlier_label=f"evidence[{index}].recordedAt",
        )
    working["lastEvidence"].extend(additions)

    if context_checkpoint is not _UNCHANGED:
        if context_checkpoint is not None:
            _validate_context_checkpoint(context_checkpoint, label="contextCheckpoint")
        working["contextCheckpoint"] = copy.deepcopy(context_checkpoint)
    if loop_state is not _UNCHANGED:
        if loop_state is not None:
            validate_loop_contract(loop_state)
        working["loopState"] = copy.deepcopy(loop_state)

    working["lastEvidenceCount"] = len(working["lastEvidence"])
    working["lastEvidenceBytes"] = _json_size(working["lastEvidence"], label="lastEvidence")
    working["updatedAt"] = timestamp
    _validate_state_shape(working, enforce_active_bounds=False)
    if _within_active_bounds(working):
        validate_state(working)
        return StateTransition(None, working)
    return compact_state(working, compacted_at=timestamp)


def compact_state(state: Any, *, compacted_at: str) -> StateTransition:
    """Return ``(full_archive, compacted_active)`` so archive can be written first."""

    _validate_state_shape(state, enforce_active_bounds=False)
    timestamp = _require_timestamp(compacted_at, label="compactedAt")
    _require_not_before(timestamp, state["updatedAt"], label="compactedAt", earlier_label="state.updatedAt")
    source = copy.deepcopy(state)
    archive = {
        "schemaVersion": STATE_ARCHIVE_SCHEMA_VERSION,
        "archivedAt": timestamp,
        "sourceEvidenceCount": source["lastEvidenceCount"],
        "sourceEvidenceBytes": source["lastEvidenceBytes"],
        "sourceState": source,
    }

    kept = _newest_evidence_suffix(source["lastEvidence"])
    active = copy.deepcopy(source)
    active["lastEvidence"] = kept
    active["lastEvidenceCount"] = len(kept)
    active["lastEvidenceBytes"] = _json_size(kept, label="lastEvidence")
    active["archivedEvidenceCount"] = source["archivedEvidenceCount"] + (
        source["lastEvidenceCount"] - len(kept)
    )
    active["updatedAt"] = timestamp

    while _json_size(active, label="state") > MAX_ACTIVE_STATE_BYTES and active["lastEvidence"]:
        active["lastEvidence"].pop(0)
        active["lastEvidenceCount"] = len(active["lastEvidence"])
        active["lastEvidenceBytes"] = _json_size(active["lastEvidence"], label="lastEvidence")
        active["archivedEvidenceCount"] += 1
    if _json_size(active, label="state") > MAX_ACTIVE_STATE_BYTES:
        raise StateCompactionError(
            f"state cannot be compacted below {MAX_ACTIVE_STATE_BYTES} bytes"
        )

    validate_state_archive(archive)
    validate_state(active)
    return StateTransition(archive, active)


def create_checkpoint(
    *,
    created_at: str,
    operator_percent: Optional[int] = None,
    used_tokens: Optional[int] = None,
    max_tokens: Optional[int] = None,
    self_estimate: Optional[int] = None,
) -> dict[str, Any]:
    """Create one of three provenance-derived checkpoint decisions.

    There is deliberately no source-label argument. The selected numeric input
    determines the source. Environment and terminal state are read from this
    process and cannot be supplied or asserted by a caller.
    """

    runtime_environment = dict(os.environ)
    _reject_background_environment(runtime_environment)
    operator_branch = operator_percent is not None
    runtime_tty = _runtime_interactive_tty() if operator_branch else None
    timestamp = _require_timestamp(created_at, label="createdAt", error_type=CheckpointError)
    token_branch = used_tokens is not None or max_tokens is not None
    estimate_branch = self_estimate is not None
    if sum((operator_branch, token_branch, estimate_branch)) != 1:
        raise CheckpointError("checkpoint requires exactly one provenance input branch")

    if operator_branch:
        percent = _require_integer_percent(
            operator_percent, label="operator_percent", error_type=CheckpointError
        )
        if runtime_tty is not True:
            raise CheckpointError("operator-observed checkpoint requires an interactive TTY")
        source = "operator-observed"
        margin = 0
        effective_threshold = CHECKPOINT_THRESHOLD_PERCENT
        checked_used = None
        checked_max = None
        tty: Optional[bool] = True
        reached = percent >= effective_threshold
    elif token_branch:
        checked_used = _require_token_count(used_tokens, label="used_tokens")
        checked_max = _require_token_count(max_tokens, label="max_tokens")
        if checked_used > checked_max:
            raise CheckpointError("used_tokens must not exceed max_tokens")
        source = "token-count"
        percent = _derive_token_percent(checked_used, checked_max)
        margin = 0
        effective_threshold = CHECKPOINT_THRESHOLD_PERCENT
        tty = None
        reached = checked_used * 100 >= checked_max * effective_threshold
    else:
        percent = _require_integer_percent(
            self_estimate, label="self_estimate", error_type=CheckpointError
        )
        source = "self-estimate"
        margin = SELF_ESTIMATE_MARGIN_PERCENT
        effective_threshold = min(100, CHECKPOINT_THRESHOLD_PERCENT + margin)
        checked_used = None
        checked_max = None
        tty = None
        reached = percent >= effective_threshold

    checkpoint = None
    if reached:
        checkpoint = _build_context_checkpoint(
            source=source,
            percent=percent,
            effective_threshold=effective_threshold,
            margin=margin,
            used_tokens=checked_used,
            max_tokens=checked_max,
            interactive_tty=tty,
            created_at=timestamp,
        )
    status = "created" if reached else "skipped"
    evidence_type = f"context-checkpoint-{status}"
    summary = _checkpoint_summary(
        status=status,
        source=source,
        percent=percent,
        effective_threshold=effective_threshold,
    )
    decision = {
        "schemaVersion": CHECKPOINT_DECISION_SCHEMA_VERSION,
        "status": status,
        "reason": "threshold-met" if reached else "below-threshold",
        "source": source,
        "percent": percent,
        "thresholdPercent": CHECKPOINT_THRESHOLD_PERCENT,
        "effectiveThresholdPercent": effective_threshold,
        "marginPercent": margin,
        "usedTokens": checked_used,
        "maxTokens": checked_max,
        "interactiveTty": tty,
        "checkpoint": checkpoint,
        "evidence": build_evidence(
            evidence_type=evidence_type,
            summary=summary,
            recorded_at=timestamp,
        ),
    }
    validate_checkpoint_decision(decision)
    return decision


def validate_checkpoint_decision(value: Any) -> None:
    decision = _require_object(value, label="checkpoint decision", error_type=CheckpointError)
    _require_exact_keys(
        decision,
        {
            "schemaVersion",
            "status",
            "reason",
            "source",
            "percent",
            "thresholdPercent",
            "effectiveThresholdPercent",
            "marginPercent",
            "usedTokens",
            "maxTokens",
            "interactiveTty",
            "checkpoint",
            "evidence",
        },
        label="checkpoint decision",
        error_type=CheckpointError,
    )
    if decision["schemaVersion"] != CHECKPOINT_DECISION_SCHEMA_VERSION:
        raise CheckpointError(
            f"checkpoint decision.schemaVersion must be {CHECKPOINT_DECISION_SCHEMA_VERSION}"
        )
    status = _require_choice(
        decision["status"], ("created", "skipped"), label="checkpoint decision.status", error_type=CheckpointError
    )
    expected_reason = "threshold-met" if status == "created" else "below-threshold"
    if decision["reason"] != expected_reason:
        raise CheckpointError("checkpoint decision.reason does not match status")
    _validate_meter_fields(decision, label="checkpoint decision")
    reached = _meter_reaches_threshold(decision)
    if reached != (status == "created"):
        raise CheckpointError("checkpoint decision.status does not match threshold evaluation")

    evidence = decision["evidence"]
    _validate_evidence(evidence, label="checkpoint decision.evidence", error_type=CheckpointError)
    expected_type = f"context-checkpoint-{status}"
    if evidence["type"] != expected_type:
        raise CheckpointError("checkpoint decision.evidence.type does not match status")
    expected_summary = _checkpoint_summary(
        status=status,
        source=decision["source"],
        percent=decision["percent"],
        effective_threshold=decision["effectiveThresholdPercent"],
    )
    if evidence["summary"] != expected_summary:
        raise CheckpointError("checkpoint decision.evidence.summary is not canonical")

    if status == "skipped":
        if decision["checkpoint"] is not None:
            raise CheckpointError("below-threshold decision must not contain an active checkpoint")
        return
    _validate_context_checkpoint(
        decision["checkpoint"], label="checkpoint decision.checkpoint", error_type=CheckpointError
    )
    expected_checkpoint = _build_context_checkpoint(
        source=decision["source"],
        percent=decision["percent"],
        effective_threshold=decision["effectiveThresholdPercent"],
        margin=decision["marginPercent"],
        used_tokens=decision["usedTokens"],
        max_tokens=decision["maxTokens"],
        interactive_tty=decision["interactiveTty"],
        created_at=evidence["recordedAt"],
    )
    if decision["checkpoint"] != expected_checkpoint:
        raise CheckpointError("checkpoint decision.checkpoint does not match derived provenance")


def apply_checkpoint(
    state: Any, decision: Any, *, updated_at: str
) -> StateTransition:
    """Apply a checkpoint decision and its typed evidence to active state."""

    validate_state(state)
    validate_checkpoint_decision(decision)
    if decision["status"] != "created":
        raise CheckpointError(
            "below-threshold checkpoint decisions are evidence-only and must not be applied"
        )
    timestamp = _require_timestamp(updated_at, label="updatedAt", error_type=CheckpointError)
    _require_not_before(
        timestamp,
        decision["evidence"]["recordedAt"],
        label="updatedAt",
        earlier_label="checkpoint decision.evidence.recordedAt",
        error_type=CheckpointError,
    )
    return record_state(
        state,
        updated_at=timestamp,
        evidence=[decision["evidence"]],
        context_checkpoint=decision["checkpoint"],
    )


def create_loop_contract(
    *,
    max_iterations: int,
    timeout_seconds: int,
    checkpoint_iteration: int,
    evidence: Sequence[str],
    started_at: str,
    formalization: Any,
) -> dict[str, Any]:
    """Create an approved-formalization-bound, tracking-only loop contract."""

    formalization_binding, approval = _derive_loop_binding(
        formalization=formalization,
    )
    maximum = _require_positive_int(
        max_iterations, label="max_iterations", error_type=LoopContractError
    )
    if maximum > MAX_LOOP_ITERATIONS:
        raise LoopContractError(f"max_iterations must not exceed {MAX_LOOP_ITERATIONS}")
    timeout = _require_positive_int(
        timeout_seconds, label="timeout_seconds", error_type=LoopContractError
    )
    if timeout > MAX_LOOP_TIMEOUT_SECONDS:
        raise LoopContractError(f"timeout_seconds must not exceed {MAX_LOOP_TIMEOUT_SECONDS}")
    checkpoint = _require_non_negative_int(
        checkpoint_iteration, label="checkpoint_iteration", error_type=LoopContractError
    )
    if checkpoint != 0:
        raise LoopContractError("a new loop requires checkpoint_iteration=0")
    started = _require_timestamp(started_at, label="started_at", error_type=LoopContractError)
    elapsed = 0
    checked_evidence = _copy_loop_evidence(evidence)
    contract = {
        "schemaVersion": BOUNDED_LOOP_SCHEMA_VERSION,
        "formalizationId": formalization_binding,
        "formalizationStatus": "approved",
        "approvalHash": approval,
        "maxIterations": maximum,
        "timeoutSeconds": timeout,
        "iteration": 0,
        "checkpointIteration": checkpoint,
        "startedAt": started,
        "updatedAt": started,
        "elapsedSeconds": elapsed,
        "status": "active",
        "stopReason": None,
        "lastEvidence": checked_evidence,
        "lastEvidenceDigest": _loop_evidence_digest(checked_evidence),
        "stagnationCount": 0,
        "stagnationLimit": STAGNATION_LIMIT,
        "explicitStopRequired": True,
        "trackingOnly": True,
        "modelProcessTerminationClaimed": False,
    }
    validate_loop_contract(contract)
    return contract


def advance_loop_contract(
    loop: Any,
    *,
    checkpoint_iteration: int,
    evidence: Sequence[str],
    advanced_at: str,
    formalization: Any,
) -> dict[str, Any]:
    """Advance one evidenced checkpoint; this never controls a model process."""

    validate_loop_contract(loop)
    if loop["status"] != "active":
        raise LoopStoppedError(f"loop is already terminal: {loop['status']}")
    _require_loop_binding(
        loop,
        formalization=formalization,
    )
    _require_checkpoint_precondition(loop, checkpoint_iteration)
    if loop["iteration"] >= loop["maxIterations"]:
        raise LoopStoppedError("loop maxIterations has already been reached")
    timestamp, elapsed = _validate_loop_transition_time(
        loop,
        at=advanced_at,
        allow_timeout_overrun=True,
    )
    checked_evidence = _copy_loop_evidence(evidence)
    digest = _loop_evidence_digest(checked_evidence)
    stagnation_count = (
        loop["stagnationCount"] + 1 if digest == loop["lastEvidenceDigest"] else 0
    )
    next_iteration = loop["iteration"] + 1

    status = "active"
    stop_reason = None
    if elapsed >= loop["timeoutSeconds"]:
        status = "exhausted"
        stop_reason = "timeout"
    elif next_iteration >= loop["maxIterations"]:
        status = "exhausted"
        stop_reason = "max-iterations"
    elif stagnation_count >= loop["stagnationLimit"]:
        status = "stagnated"
        stop_reason = "stagnation-limit"

    updated = copy.deepcopy(loop)
    updated.update(
        {
            "iteration": next_iteration,
            "checkpointIteration": next_iteration,
            "updatedAt": timestamp,
            "elapsedSeconds": elapsed,
            "status": status,
            "stopReason": stop_reason,
            "lastEvidence": checked_evidence,
            "lastEvidenceDigest": digest,
            "stagnationCount": stagnation_count,
        }
    )
    validate_loop_contract(updated)
    return updated


def stop_loop_contract(
    loop: Any,
    *,
    checkpoint_iteration: int,
    reason: str,
    evidence: Sequence[str],
    stopped_at: str,
    formalization: Any,
) -> dict[str, Any]:
    """Record an explicit terminal reason without claiming process termination."""

    validate_loop_contract(loop)
    if loop["status"] != "active":
        raise LoopStoppedError(f"loop is already terminal: {loop['status']}")
    _require_loop_binding(
        loop,
        formalization=formalization,
    )
    _require_checkpoint_precondition(loop, checkpoint_iteration)
    terminal = _require_choice(
        reason, LOOP_EXPLICIT_STOP_STATUSES, label="reason", error_type=LoopContractError
    )
    timestamp, elapsed = _validate_loop_transition_time(
        loop,
        at=stopped_at,
        allow_timeout_overrun=False,
    )
    if elapsed >= loop["timeoutSeconds"]:
        raise LoopContractError("a loop at or beyond timeout must be advanced to automatic exhaustion")
    checked_evidence = _copy_loop_evidence(evidence)
    digest = _loop_evidence_digest(checked_evidence)

    updated = copy.deepcopy(loop)
    updated.update(
        {
            "updatedAt": timestamp,
            "elapsedSeconds": elapsed,
            "status": terminal,
            "stopReason": terminal,
            "lastEvidence": checked_evidence,
            "lastEvidenceDigest": digest,
            "stagnationCount": (
                loop["stagnationLimit"] if terminal == "stagnated" else loop["stagnationCount"]
            ),
        }
    )
    validate_loop_contract(updated)
    return updated


def validate_loop_contract(value: Any) -> None:
    loop = _require_object(value, label="loop contract", error_type=LoopContractError)
    _require_exact_keys(
        loop,
        {
            "schemaVersion",
            "formalizationId",
            "formalizationStatus",
            "approvalHash",
            "maxIterations",
            "timeoutSeconds",
            "iteration",
            "checkpointIteration",
            "startedAt",
            "updatedAt",
            "elapsedSeconds",
            "status",
            "stopReason",
            "lastEvidence",
            "lastEvidenceDigest",
            "stagnationCount",
            "stagnationLimit",
            "explicitStopRequired",
            "trackingOnly",
            "modelProcessTerminationClaimed",
        },
        label="loop contract",
        error_type=LoopContractError,
    )
    if loop["schemaVersion"] != BOUNDED_LOOP_SCHEMA_VERSION:
        raise LoopContractError(
            f"loop contract.schemaVersion must be {BOUNDED_LOOP_SCHEMA_VERSION}"
        )
    _require_safe_id(
        loop["formalizationId"], label="loop contract.formalizationId", error_type=LoopContractError
    )
    if loop["formalizationStatus"] != "approved":
        raise LoopContractError("loop contract.formalizationStatus must be approved")
    _require_approval_hash(loop["approvalHash"], label="loop contract.approvalHash")
    maximum = _require_positive_int(
        loop["maxIterations"], label="loop contract.maxIterations", error_type=LoopContractError
    )
    if maximum > MAX_LOOP_ITERATIONS:
        raise LoopContractError(f"loop contract.maxIterations must not exceed {MAX_LOOP_ITERATIONS}")
    timeout = _require_positive_int(
        loop["timeoutSeconds"], label="loop contract.timeoutSeconds", error_type=LoopContractError
    )
    if timeout > MAX_LOOP_TIMEOUT_SECONDS:
        raise LoopContractError(
            f"loop contract.timeoutSeconds must not exceed {MAX_LOOP_TIMEOUT_SECONDS}"
        )
    iteration = _require_non_negative_int(
        loop["iteration"], label="loop contract.iteration", error_type=LoopContractError
    )
    checkpoint = _require_non_negative_int(
        loop["checkpointIteration"],
        label="loop contract.checkpointIteration",
        error_type=LoopContractError,
    )
    if iteration > maximum or checkpoint != iteration:
        raise LoopContractError("loop checkpointIteration must equal iteration within maxIterations")
    started = _require_timestamp(
        loop["startedAt"], label="loop contract.startedAt", error_type=LoopContractError
    )
    updated = _require_timestamp(
        loop["updatedAt"], label="loop contract.updatedAt", error_type=LoopContractError
    )
    elapsed = _require_non_negative_int(
        loop["elapsedSeconds"], label="loop contract.elapsedSeconds", error_type=LoopContractError
    )
    _require_elapsed_match(started, updated, elapsed, label="loop contract")
    status = _require_choice(
        loop["status"], LOOP_STATUSES, label="loop contract.status", error_type=LoopContractError
    )
    stop_reason = loop["stopReason"]
    if status == "active":
        if stop_reason is not None:
            raise LoopContractError("active loop contract.stopReason must be null")
        if iteration >= maximum or elapsed >= timeout:
            raise LoopContractError("active loop must remain below iteration and timeout bounds")
    else:
        allowed_reasons = {
            "success": {"success"},
            "clean-no-op": {"clean-no-op"},
            "blocked": {"blocked"},
            "approval-required": {"approval-required"},
            "exhausted": {"max-iterations", "timeout"},
            "stagnated": {"stagnated", "stagnation-limit"},
        }[status]
        if stop_reason not in allowed_reasons:
            raise LoopContractError(
                "loop contract.stopReason is not canonical for its terminal status"
            )
        if status == "exhausted" and stop_reason == "max-iterations" and iteration != maximum:
            raise LoopContractError("max-iterations stop requires iteration == maxIterations")
        if status == "exhausted" and stop_reason == "timeout" and elapsed < timeout:
            raise LoopContractError("timeout stop requires elapsedSeconds >= timeoutSeconds")
        if elapsed >= timeout and status != "exhausted":
            raise LoopContractError("a loop at or beyond timeout must be exhausted")
        if elapsed >= timeout and stop_reason != "timeout":
            raise LoopContractError("timeout exhaustion requires stopReason=timeout")
        if iteration >= maximum and status != "exhausted":
            raise LoopContractError("a loop at maxIterations must be exhausted")

    evidence = _copy_loop_evidence(loop["lastEvidence"])
    digest = _require_text(
        loop["lastEvidenceDigest"],
        label="loop contract.lastEvidenceDigest",
        minimum=64,
        maximum=64,
        error_type=LoopContractError,
    )
    if _SHA256.fullmatch(digest) is None or digest != _loop_evidence_digest(evidence):
        raise LoopContractError("loop contract.lastEvidenceDigest does not match lastEvidence")
    stagnation_count = _require_non_negative_int(
        loop["stagnationCount"], label="loop contract.stagnationCount", error_type=LoopContractError
    )
    if loop["stagnationLimit"] != STAGNATION_LIMIT or stagnation_count > STAGNATION_LIMIT:
        raise LoopContractError("loop contract stagnation bound is invalid")
    if status == "stagnated" and stagnation_count < STAGNATION_LIMIT:
        raise LoopContractError("stagnated loop must meet the stagnation limit")
    if status not in {"stagnated", "exhausted"} and stagnation_count >= STAGNATION_LIMIT:
        raise LoopContractError("stagnation limit requires a stagnated or exhausted status")
    if loop["explicitStopRequired"] is not True:
        raise LoopContractError("loop contract.explicitStopRequired must be true")
    if loop["trackingOnly"] is not True:
        raise LoopContractError("loop contract.trackingOnly must be true")
    if loop["modelProcessTerminationClaimed"] is not False:
        raise LoopContractError("loop contracts never claim model-process termination")


def _validate_state_shape(value: Any, *, enforce_active_bounds: bool) -> None:
    state = _require_object(value, label="state", error_type=StateValidationError)
    _require_exact_keys(
        state,
        {
            "schemaVersion",
            "workId",
            "current",
            "next",
            "constraints",
            "lastEvidence",
            "lastEvidenceCount",
            "lastEvidenceBytes",
            "archivedEvidenceCount",
            "contextCheckpoint",
            "loopState",
            "updatedAt",
        },
        label="state",
        error_type=StateValidationError,
    )
    if state["schemaVersion"] != SCHEMA_VERSION:
        raise StateValidationError(f"state.schemaVersion must be {SCHEMA_VERSION}")
    _require_safe_id(state["workId"], label="state.workId")
    _require_text(state["current"], label="state.current", maximum=1000)
    _require_text(state["next"], label="state.next", maximum=1000)
    _validate_constraints(state["constraints"])
    evidence = state["lastEvidence"]
    if not isinstance(evidence, list):
        raise StateValidationError("state.lastEvidence must be an array")
    hard_count = MAX_ACTIVE_EVIDENCE_COUNT if enforce_active_bounds else MAX_UNCOMPACTED_EVIDENCE_COUNT
    if len(evidence) > hard_count:
        raise StateValidationError(f"state.lastEvidence must contain at most {hard_count} items")
    for index, item in enumerate(evidence):
        _validate_evidence(item, label=f"state.lastEvidence[{index}]")
    count = _require_non_negative_int(state["lastEvidenceCount"], label="state.lastEvidenceCount")
    size = _require_non_negative_int(state["lastEvidenceBytes"], label="state.lastEvidenceBytes")
    actual_size = _json_size(evidence, label="state.lastEvidence")
    if count != len(evidence) or size != actual_size:
        raise StateValidationError("state evidence metrics do not match lastEvidence")
    if enforce_active_bounds and size > MAX_ACTIVE_EVIDENCE_BYTES:
        raise StateValidationError(
            f"state.lastEvidence exceeds {MAX_ACTIVE_EVIDENCE_BYTES} bytes"
        )
    _require_non_negative_int(state["archivedEvidenceCount"], label="state.archivedEvidenceCount")
    if state["contextCheckpoint"] is not None:
        _validate_context_checkpoint(state["contextCheckpoint"], label="state.contextCheckpoint")
    if state["loopState"] is not None:
        validate_loop_contract(state["loopState"])
    updated_at = _require_timestamp(state["updatedAt"], label="state.updatedAt")
    for index, item in enumerate(evidence):
        _require_not_before(
            updated_at,
            item["recordedAt"],
            label="state.updatedAt",
            earlier_label=f"state.lastEvidence[{index}].recordedAt",
        )
    if state["contextCheckpoint"] is not None:
        _require_not_before(
            updated_at,
            state["contextCheckpoint"]["createdAt"],
            label="state.updatedAt",
            earlier_label="state.contextCheckpoint.createdAt",
        )
    if state["loopState"] is not None:
        _require_not_before(
            updated_at,
            state["loopState"]["updatedAt"],
            label="state.updatedAt",
            earlier_label="state.loopState.updatedAt",
        )
    document_size = _json_size(state, label="state")
    maximum = MAX_ACTIVE_STATE_BYTES if enforce_active_bounds else MAX_UNCOMPACTED_STATE_BYTES
    if document_size > maximum:
        raise StateValidationError(f"state exceeds {maximum} bytes")


def _within_active_bounds(state: dict[str, Any]) -> bool:
    return (
        state["lastEvidenceCount"] <= MAX_ACTIVE_EVIDENCE_COUNT
        and state["lastEvidenceBytes"] <= MAX_ACTIVE_EVIDENCE_BYTES
        and _json_size(state, label="state") <= MAX_ACTIVE_STATE_BYTES
    )


def _newest_evidence_suffix(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chronological = [
        item
        for _, item in sorted(
            enumerate(evidence),
            key=lambda indexed: (_evidence_recorded_at(indexed[1]), indexed[0]),
        )
    ]
    kept: list[dict[str, Any]] = []
    for item in reversed(chronological):
        candidate = [copy.deepcopy(item), *kept]
        if len(candidate) > MAX_ACTIVE_EVIDENCE_COUNT:
            break
        if _json_size(candidate, label="lastEvidence") > MAX_ACTIVE_EVIDENCE_BYTES:
            break
        kept = candidate
    if evidence and not kept:
        raise StateCompactionError("newest evidence item cannot fit within the active byte cap")
    return kept


def _evidence_recorded_at(value: dict[str, Any]) -> datetime:
    return _parse_timestamp(
        value["recordedAt"],
        label="evidence.recordedAt",
        error_type=StateCompactionError,
    )


def _copy_constraints(values: Iterable[str]) -> list[str]:
    if isinstance(values, (str, bytes)):
        raise StateValidationError("constraints must be an array")
    items = list(values)
    _validate_constraints(items)
    return items


def _validate_constraints(value: Any) -> None:
    if not isinstance(value, list):
        raise StateValidationError("state.constraints must be an array")
    if len(value) > 32:
        raise StateValidationError("state.constraints must contain at most 32 items")
    for index, item in enumerate(value):
        _require_text(item, label=f"state.constraints[{index}]", maximum=500)


def _copy_evidence(values: Iterable[dict[str, Any]], *, label: str) -> list[dict[str, Any]]:
    if isinstance(values, (str, bytes, Mapping)):
        raise StateValidationError(f"{label} must be an array")
    items = [copy.deepcopy(item) for item in values]
    if len(items) > MAX_UNCOMPACTED_EVIDENCE_COUNT:
        raise StateValidationError(
            f"{label} must contain at most {MAX_UNCOMPACTED_EVIDENCE_COUNT} items"
        )
    for index, item in enumerate(items):
        _validate_evidence(item, label=f"{label}[{index}]")
    return items


def _validate_evidence(
    value: Any, *, label: str, error_type: type[StateError] = StateValidationError
) -> None:
    evidence = _require_object(value, label=label, error_type=error_type)
    _require_exact_keys(
        evidence,
        {"type", "summary", "recordedAt"},
        label=label,
        error_type=error_type,
    )
    _require_safe_id(evidence["type"], label=f"{label}.type", error_type=error_type)
    _require_text(evidence["summary"], label=f"{label}.summary", maximum=1000, error_type=error_type)
    _require_timestamp(evidence["recordedAt"], label=f"{label}.recordedAt", error_type=error_type)


def _build_context_checkpoint(
    *,
    source: str,
    percent: Any,
    effective_threshold: int,
    margin: int,
    used_tokens: Optional[int],
    max_tokens: Optional[int],
    interactive_tty: Optional[bool],
    created_at: str,
) -> dict[str, Any]:
    checkpoint = {
        "source": source,
        "percent": percent,
        "thresholdPercent": CHECKPOINT_THRESHOLD_PERCENT,
        "effectiveThresholdPercent": effective_threshold,
        "marginPercent": margin,
        "usedTokens": used_tokens,
        "maxTokens": max_tokens,
        "interactiveTty": interactive_tty,
        "createdAt": created_at,
    }
    _validate_context_checkpoint(checkpoint, label="context checkpoint", error_type=CheckpointError)
    return checkpoint


def _validate_context_checkpoint(
    value: Any,
    *,
    label: str,
    error_type: type[StateError] = StateValidationError,
) -> None:
    checkpoint = _require_object(value, label=label, error_type=error_type)
    _require_exact_keys(
        checkpoint,
        {
            "source",
            "percent",
            "thresholdPercent",
            "effectiveThresholdPercent",
            "marginPercent",
            "usedTokens",
            "maxTokens",
            "interactiveTty",
            "createdAt",
        },
        label=label,
        error_type=error_type,
    )
    _validate_meter_fields(checkpoint, label=label, error_type=error_type)
    if not _meter_reaches_threshold(checkpoint):
        raise error_type(f"{label} must represent a reached checkpoint threshold")
    _require_timestamp(checkpoint["createdAt"], label=f"{label}.createdAt", error_type=error_type)


def _validate_meter_fields(
    value: dict[str, Any],
    *,
    label: str,
    error_type: type[StateError] = CheckpointError,
) -> None:
    source = _require_choice(
        value["source"], CHECKPOINT_SOURCES, label=f"{label}.source", error_type=error_type
    )
    percent = _require_percent_number(value["percent"], label=f"{label}.percent", error_type=error_type)
    if value["thresholdPercent"] != CHECKPOINT_THRESHOLD_PERCENT:
        raise error_type(f"{label}.thresholdPercent must be {CHECKPOINT_THRESHOLD_PERCENT}")
    effective = _require_integer_percent(
        value["effectiveThresholdPercent"],
        label=f"{label}.effectiveThresholdPercent",
        error_type=error_type,
    )
    margin = _require_non_negative_int(
        value["marginPercent"], label=f"{label}.marginPercent", error_type=error_type
    )
    if source == "operator-observed":
        _require_integer_percent(percent, label=f"{label}.percent", error_type=error_type)
        if value["interactiveTty"] is not True:
            raise error_type(f"{label} operator-observed source requires interactiveTty=true")
        if value["usedTokens"] is not None or value["maxTokens"] is not None:
            raise error_type(f"{label} operator-observed source must not contain token counts")
        expected_margin = 0
        expected_effective = CHECKPOINT_THRESHOLD_PERCENT
    elif source == "token-count":
        used = _require_token_count(
            value["usedTokens"],
            label=f"{label}.usedTokens",
            error_type=error_type,
        )
        maximum = _require_token_count(
            value["maxTokens"],
            label=f"{label}.maxTokens",
            error_type=error_type,
        )
        if used > maximum:
            raise error_type(f"{label}.usedTokens must not exceed maxTokens")
        if value["interactiveTty"] is not None:
            raise error_type(f"{label} token-count source requires interactiveTty=null")
        if percent != _derive_token_percent(used, maximum):
            raise error_type(f"{label}.percent does not match token counts")
        expected_margin = 0
        expected_effective = CHECKPOINT_THRESHOLD_PERCENT
    else:
        _require_integer_percent(percent, label=f"{label}.percent", error_type=error_type)
        if value["interactiveTty"] is not None:
            raise error_type(f"{label} self-estimate source requires interactiveTty=null")
        if value["usedTokens"] is not None or value["maxTokens"] is not None:
            raise error_type(f"{label} self-estimate source must not contain token counts")
        expected_margin = SELF_ESTIMATE_MARGIN_PERCENT
        expected_effective = min(100, CHECKPOINT_THRESHOLD_PERCENT + expected_margin)
    if margin != expected_margin or effective != expected_effective:
        raise error_type(f"{label} margin or effective threshold does not match source")


def _meter_reaches_threshold(value: dict[str, Any]) -> bool:
    if value["source"] == "token-count":
        return value["usedTokens"] * 100 >= value["maxTokens"] * value["effectiveThresholdPercent"]
    return value["percent"] >= value["effectiveThresholdPercent"]


def _checkpoint_summary(*, status: str, source: str, percent: Any, effective_threshold: int) -> str:
    return (
        f"context checkpoint {status}: source={source} percent={_format_percent(percent)} "
        f"effective-threshold={effective_threshold}"
    )


def _format_percent(value: Any) -> str:
    if type(value) is int:
        return str(value)
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _derive_token_percent(used_tokens: int, max_tokens: int) -> Any:
    scale = 10_000
    quotient, remainder = divmod(used_tokens * 100 * scale, max_tokens)
    doubled = remainder * 2
    if doubled > max_tokens or (doubled == max_tokens and quotient % 2):
        quotient += 1
    if quotient % scale == 0:
        return quotient // scale
    return quotient / scale


def _runtime_interactive_tty() -> bool:
    try:
        value = sys.stdin.isatty()
    except (AttributeError, OSError) as exc:
        raise CheckpointError("runtime TTY state is unavailable") from exc
    if type(value) is not bool:
        raise CheckpointError("runtime TTY state must be boolean")
    return value


def _validate_environment(environment: Any) -> None:
    if not isinstance(environment, Mapping):
        raise CheckpointError("environment must be a string mapping")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in environment.items()):
        raise CheckpointError("environment must contain only string keys and values")


def _reject_background_environment(environment: Mapping[str, str]) -> None:
    _validate_environment(environment)
    for key, value in environment.items():
        normalized_value = value.strip().lower()
        if normalized_value in _FALSE_ENV_VALUES:
            continue
        normalized_key = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
        key_tokens = _marker_tokens(key)
        value_tokens = _marker_tokens(value)
        key_is_marker = normalized_key in _UNATTENDED_ENV_KEYS or bool(key_tokens & _BACKGROUND_MARKERS)
        contextual_value_is_marker = bool(key_tokens & _CONTEXT_ENV_MARKERS) and bool(
            value_tokens & _BACKGROUND_MARKERS
        )
        if key_is_marker or contextual_value_is_marker:
            raise BackgroundCheckpointError(
                f"checkpoint is not permitted with unattended environment marker {key}"
            )


def _marker_tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^A-Za-z]+", value.lower()) if token}


def _derive_loop_binding(
    *,
    formalization: Any,
) -> tuple[str, str]:
    try:
        current = require_approved_formalization(formalization)
    except FormalizationError as exc:
        raise LoopBindingError(
            "loop requires the current validated approved formalization"
        ) from exc
    if current["route"]["boundedLoop"] is not True:
        raise LoopBindingError("formalization route does not approve a bounded loop")
    return current["id"], current["approval"]["approvalHash"]


def _require_loop_binding(
    loop: dict[str, Any],
    *,
    formalization: Any,
) -> None:
    checked_id, checked_hash = _derive_loop_binding(
        formalization=formalization,
    )
    if checked_id != loop["formalizationId"] or checked_hash != loop["approvalHash"]:
        raise LoopBindingError("loop formalization id or approval hash binding changed")


def _require_checkpoint_precondition(loop: dict[str, Any], value: Any) -> None:
    checkpoint = _require_non_negative_int(
        value, label="checkpoint_iteration", error_type=LoopContractError
    )
    if checkpoint != loop["checkpointIteration"] or checkpoint != loop["iteration"]:
        raise LoopContractError("checkpoint_iteration is stale or does not match loop iteration")


def _validate_loop_transition_time(
    loop: dict[str, Any],
    *,
    at: str,
    allow_timeout_overrun: bool,
) -> tuple[str, int]:
    timestamp = _require_timestamp(at, label="transition timestamp", error_type=LoopContractError)
    elapsed = _elapsed_between(loop["startedAt"], timestamp, label="loop transition")
    _require_not_before(
        timestamp,
        loop["updatedAt"],
        label="transition timestamp",
        earlier_label="loop.updatedAt",
        error_type=LoopContractError,
    )
    if elapsed < loop["elapsedSeconds"]:
        raise LoopContractError("elapsed_seconds must be monotonic")
    if not allow_timeout_overrun and elapsed > loop["timeoutSeconds"]:
        raise LoopContractError("loop timeout exceeded")
    return timestamp, elapsed


def _copy_loop_evidence(value: Sequence[str]) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise LoopContractError("loop evidence must be an array")
    items = list(value)
    if not items or len(items) > MAX_LOOP_EVIDENCE_ITEMS:
        raise LoopContractError(
            f"loop evidence must contain 1 to {MAX_LOOP_EVIDENCE_ITEMS} items"
        )
    checked = [
        _require_text(
            item,
            label=f"loop evidence[{index}]",
            maximum=500,
            error_type=LoopContractError,
        )
        for index, item in enumerate(items)
    ]
    if _json_size(checked, label="loop evidence", error_type=LoopContractError) > MAX_LOOP_EVIDENCE_BYTES:
        raise LoopContractError(f"loop evidence exceeds {MAX_LOOP_EVIDENCE_BYTES} bytes")
    return checked


def _loop_evidence_digest(value: Sequence[str]) -> str:
    serialized = json.dumps(list(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _require_approval_hash(
    value: Any,
    *,
    label: str,
    error_type: type[StateError] = LoopContractError,
) -> str:
    text = _require_text(
        value, label=label, minimum=64, maximum=64, error_type=error_type
    )
    if _SHA256.fullmatch(text) is None:
        raise error_type(f"{label} must be a lowercase SHA-256 hex digest")
    return text


def _require_elapsed_match(started_at: str, updated_at: str, elapsed: int, *, label: str) -> None:
    expected = _elapsed_between(started_at, updated_at, label=label)
    if expected != elapsed:
        raise LoopContractError(f"{label} elapsed_seconds must match explicit timestamps")


def _elapsed_between(started_at: str, updated_at: str, *, label: str) -> int:
    started = _parse_timestamp(started_at, label=f"{label}.startedAt", error_type=LoopContractError)
    updated = _parse_timestamp(updated_at, label=f"{label}.updatedAt", error_type=LoopContractError)
    difference = updated - started
    microseconds = (
        (difference.days * 86_400 + difference.seconds) * 1_000_000
        + difference.microseconds
    )
    if microseconds < 0 or microseconds % 1_000_000:
        raise LoopContractError(f"{label} timestamps must produce whole non-negative seconds")
    return microseconds // 1_000_000


def _require_not_before(
    later: str,
    earlier: str,
    *,
    label: str,
    earlier_label: str,
    error_type: type[StateError] = StateValidationError,
) -> None:
    later_value = _parse_timestamp(later, label=label, error_type=error_type)
    earlier_value = _parse_timestamp(earlier, label=earlier_label, error_type=error_type)
    if later_value < earlier_value:
        raise error_type(f"{label} must not be before {earlier_label}")


def _require_timestamp(
    value: Any,
    *,
    label: str,
    error_type: type[StateError] = StateValidationError,
) -> str:
    text = _require_text(value, label=label, maximum=64, error_type=error_type)
    _parse_timestamp(text, label=label, error_type=error_type)
    return text


def _parse_timestamp(
    value: str, *, label: str, error_type: type[StateError]
) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise error_type(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise error_type(f"{label} must include a timezone")
    return parsed


def _require_object(
    value: Any, *, label: str, error_type: type[StateError]
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise error_type(f"{label} must be an object")
    return value


def _require_exact_keys(
    value: dict[str, Any],
    keys: set[str],
    *,
    label: str,
    error_type: type[StateError],
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
    minimum: int = 1,
    maximum: int,
    error_type: type[StateError] = StateValidationError,
) -> str:
    if not isinstance(value, str):
        raise error_type(f"{label} must be a string")
    if len(value) < minimum or len(value) > maximum:
        raise error_type(f"{label} length must be between {minimum} and {maximum}")
    if "\x00" in value or any(ord(character) < 32 for character in value):
        raise error_type(f"{label} contains a forbidden control character")
    try:
        reject_credential_shapes(value, label=label)
    except ValidationError as exc:
        raise error_type(str(exc)) from exc
    return value


def _require_safe_id(
    value: Any,
    *,
    label: str,
    error_type: type[StateError] = StateValidationError,
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
    error_type: type[StateError],
) -> str:
    if not isinstance(value, str) or value not in choices:
        raise error_type(f"{label} must be one of {list(choices)}")
    return value


def _require_non_negative_int(
    value: Any,
    *,
    label: str,
    error_type: type[StateError] = StateValidationError,
) -> int:
    if type(value) is not int or value < 0:
        raise error_type(f"{label} must be a non-negative integer")
    return value


def _require_positive_int(
    value: Any, *, label: str, error_type: type[StateError]
) -> int:
    if type(value) is not int or value <= 0:
        raise error_type(f"{label} must be a positive integer")
    return value


def _require_token_count(
    value: Any,
    *,
    label: str,
    error_type: type[StateError] = CheckpointError,
) -> int:
    checked = _require_positive_int(value, label=label, error_type=error_type)
    if checked > MAX_TOKEN_COUNT:
        raise error_type(f"{label} must not exceed {MAX_TOKEN_COUNT}")
    return checked


def _require_integer_percent(
    value: Any, *, label: str, error_type: type[StateError]
) -> int:
    if type(value) is not int or not 0 <= value <= 100:
        raise error_type(f"{label} must be an integer from 0 to 100")
    return value


def _require_percent_number(
    value: Any, *, label: str, error_type: type[StateError]
) -> Any:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
        raise error_type(f"{label} must be a finite number from 0 to 100")
    return value


def _json_size(
    value: Any,
    *,
    label: str,
    error_type: type[StateError] = StateValidationError,
) -> int:
    return len(_canonical_json_bytes(value, label=label, error_type=error_type))


def _canonical_json_bytes(
    value: Any,
    *,
    label: str,
    error_type: type[StateError] = StateValidationError,
) -> bytes:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise error_type(f"{label} must contain only finite JSON values") from exc
    return serialized.encode("utf-8")


# Explicit aliases keep the state API vocabulary concise for callers.
build_loop_contract = create_loop_contract
advance_bounded_loop = advance_loop_contract
stop_bounded_loop = stop_loop_contract
