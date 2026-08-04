from __future__ import annotations

import base64
import copy
import errno
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional, Sequence

from .atomic_io import atomic_write_json, exclusive_file_lock
from .catalog import CatalogError, get_repository, validate_catalog
from .paths import PathPolicyError, ensure_contained, resolve_state_root
from .renderer import (
    FILE_MODES,
    PROJECT_FRAME_PATHS,
    RENDERER_VERSION,
    ProjectFramePlan,
    RendererError,
    plan_project_frame,
)


APPLY_PLAN_SCHEMA_VERSION = "plzdo-local.apply-plan.v2"
APPLY_REPORT_SCHEMA_VERSION = "plzdo-local.apply-report.v2"
AUTHORIZATION_SCHEMA_VERSION = "plzdo-local.apply-authorization.v1"
CONFIRMATION_TYPE = "plan-fingerprint"
AUTHORIZATION_TTL_SECONDS = 5 * 60
INTEGRITY_KEY_BYTES = 32
MAX_PLAN_BYTES = 4 * 1024 * 1024
MAX_REPORT_BYTES = 12 * 1024 * 1024
MAX_GRANT_BYTES = 32 * 1024
MAX_TARGET_FILE_BYTES = 1024 * 1024
MAX_GIT_OUTPUT_BYTES = 1024 * 1024
GIT_TIMEOUT_SECONDS = 15

_git_path = shutil.which("git", path=os.defpath)
GIT_EXECUTABLE = str(Path(_git_path).resolve()) if _git_path else ""

_SAFE_ID = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_HEAD = re.compile(r"^[0-9a-f]{40,64}$")
_PLAN_ID = re.compile(r"^apply-[0-9a-f]{24}$")
_NONCE = re.compile(r"^[0-9a-f]{64}$")
_MODE = re.compile(r"^0[0-7]{3}$")
_GIT_INDEX_MODE = re.compile(rb"^[0-7]{6}$")
_TEMPORARY_NAME = re.compile(r"^\.plzdo-(?:apply|rollback)-[0-9a-f]{24}$")
_ACTIONS = {"create", "no-change", "update", "update-mode"}
_REPORT_STATUSES = {
    "rollback-in-progress",
    "applied",
    "failed-rolled-back",
    "rollback-failed",
    "rolled-back",
}
_DANGEROUS_GIT_KEYS = {
    "core.attributesfile",
    "core.fsmonitor",
    "core.hookspath",
    "core.worktree",
    "diff.external",
    "extensions.worktreeconfig",
    "gpg.program",
    "ssh.variant",
}


class ApplyGateError(ValueError):
    """Base class for typed, fail-closed P5 errors."""

    def __init__(self, code: str, message: str, *, report_path: Optional[Path] = None) -> None:
        super().__init__(message)
        self.code = code
        self.report_path = report_path


class ApplyPolicyError(ApplyGateError):
    pass


class ApplyPlanError(ApplyGateError):
    pass


class ApplyGitError(ApplyGateError):
    pass


class ApplyConfirmationError(ApplyGateError):
    pass


class ApplyAuthorizationError(ApplyGateError):
    pass


class ApplyFingerprintError(ApplyGateError):
    pass


class ApplyPathError(ApplyGateError):
    pass


class ApplyExecutionError(ApplyGateError):
    pass


class ApplyRollbackError(ApplyGateError):
    pass


@dataclass(frozen=True)
class _FileState:
    exists: bool
    content: Optional[bytes]
    mode: Optional[int]

    @property
    def sha256(self) -> Optional[str]:
        if self.content is None:
            return None
        return _sha256(self.content)

    def as_plan_previous(self) -> dict[str, object]:
        return {
            "exists": self.exists,
            "mode": _format_mode(self.mode),
            "bytes": len(self.content) if self.content is not None else None,
            "sha256": self.sha256,
        }

    def as_backup(self, relative: str) -> dict[str, object]:
        return {
            "path": relative,
            "previousExists": self.exists,
            "previousMode": _format_mode(self.mode),
            "previousBytes": len(self.content) if self.content is not None else None,
            "previousSha256": self.sha256,
            "previousContentBase64": _encode_bytes(self.content) if self.content is not None else None,
        }


def plan_apply(
    catalog: Mapping[str, Any],
    repository_id: str,
    project: Mapping[str, Any],
    *,
    force: bool = False,
    created_at: Optional[str] = None,
) -> dict[str, Any]:
    """Build a non-writing plan from bundled templates and exact project input."""

    repository = _require_enabled_repository(catalog, repository_id)
    project_input = _validate_project_input(project)
    if type(force) is not bool:
        raise ApplyPlanError("force-type", "apply force must be a boolean")
    target = _repository_target(repository)
    frame_plan = _owned_frame_plan(target, project_input, force=force)
    _require_allowed_outputs(repository)
    timestamp = _timestamp(created_at)

    root_descriptor = _open_target_root(target)
    try:
        root_fingerprint = _root_fingerprint(target, root_descriptor)
        git_identity = _require_safe_git_configuration_bound(target, root_descriptor, root_fingerprint)
        head = _git_head_bound(target, root_descriptor, root_fingerprint)
        _require_clean_git_bound(target, root_descriptor, root_fingerprint, git_identity)
        states = _snapshot_files_bound(target, root_descriptor, root_fingerprint, PROJECT_FRAME_PATHS)
        missing_directories = _missing_parent_directories_bound(
            target,
            root_descriptor,
            root_fingerprint,
            PROJECT_FRAME_PATHS,
        )
        _require_frame_previous_matches(frame_plan, states)
        _require_root_fingerprint(target, root_descriptor, root_fingerprint)
        _require_git_repository_binding_bound(
            target,
            root_descriptor,
            root_fingerprint,
            git_identity,
        )
        _require_git_head_bound(target, root_descriptor, root_fingerprint, head)
        _require_clean_git_bound(target, root_descriptor, root_fingerprint, git_identity)
    finally:
        os.close(root_descriptor)

    files = [_planned_file(item, states[item.path]) for item in frame_plan.files]
    source = {
        "rendererVersion": RENDERER_VERSION,
        "targetState": frame_plan.target_state,
        "force": frame_plan.force,
        "project": project_input,
        "fingerprint": _source_fingerprint(frame_plan, project_input),
    }
    target_contract = {
        "root": str(target),
        "rootFingerprint": root_fingerprint,
        "head": head,
        "gitIdentity": git_identity,
        "stateFingerprint": _target_state_fingerprint(
            str(target),
            head,
            git_identity,
            files,
            missing_directories,
        ),
        "missingDirectories": missing_directories,
    }
    core: dict[str, Any] = {
        "schemaVersion": APPLY_PLAN_SCHEMA_VERSION,
        "createdAt": timestamp,
        "repositoryId": repository["id"],
        "catalogFingerprint": _json_fingerprint(catalog),
        "approval": copy.deepcopy(repository["realApply"]["approval"]),
        "confirmation": {"type": CONFIRMATION_TYPE},
        "target": target_contract,
        "source": source,
        "plannedBytesFingerprint": _planned_bytes_fingerprint(files),
        "files": files,
    }
    plan_id = "apply-" + _json_fingerprint(core)[:24]
    plan = dict(core)
    plan["planId"] = plan_id
    plan["planFingerprint"] = _json_fingerprint(plan)
    validate_apply_plan(plan)
    return plan


def validate_apply_plan(value: Any) -> None:
    """Validate the exact v2 plan, embedded bytes, and all self-fingerprints."""

    plan = _object(value, "apply plan")
    _exact_keys(
        plan,
        {
            "schemaVersion",
            "planId",
            "planFingerprint",
            "createdAt",
            "repositoryId",
            "catalogFingerprint",
            "approval",
            "confirmation",
            "target",
            "source",
            "plannedBytesFingerprint",
            "files",
        },
        "apply plan",
    )
    if plan["schemaVersion"] != APPLY_PLAN_SCHEMA_VERSION:
        raise ApplyPlanError("plan-schema", "apply plan schemaVersion is unsupported")
    _require_match(plan["planId"], _PLAN_ID, "apply plan planId")
    _require_match(plan["planFingerprint"], _SHA256, "apply plan planFingerprint")
    _require_timestamp(plan["createdAt"], "apply plan createdAt")
    _require_match(plan["repositoryId"], _SAFE_ID, "apply plan repositoryId")
    _require_match(plan["catalogFingerprint"], _SHA256, "apply plan catalogFingerprint")

    approval = _object(plan["approval"], "apply plan approval")
    _exact_keys(approval, {"id", "approvedAt", "approvalHash"}, "apply plan approval")
    _require_match(approval["id"], _SAFE_ID, "apply plan approval.id")
    _require_timestamp(approval["approvedAt"], "apply plan approval.approvedAt")
    _require_match(approval["approvalHash"], _SHA256, "apply plan approval.approvalHash")

    confirmation = _object(plan["confirmation"], "apply plan confirmation")
    _exact_keys(confirmation, {"type"}, "apply plan confirmation")
    if confirmation["type"] != CONFIRMATION_TYPE:
        raise ApplyPlanError("plan-confirmation", "apply confirmation must name the exact plan fingerprint")

    target = _object(plan["target"], "apply plan target")
    _exact_keys(
        target,
        {"root", "rootFingerprint", "head", "gitIdentity", "stateFingerprint", "missingDirectories"},
        "apply plan target",
    )
    _require_absolute_canonical_text(target["root"], "apply plan target.root")
    _require_match(target["rootFingerprint"], _SHA256, "apply plan target.rootFingerprint")
    _require_match(target["head"], _GIT_HEAD, "apply plan target.head")
    git_identity = _validate_git_identity(target["gitIdentity"], "apply plan target.gitIdentity")
    if git_identity["topLevel"] != target["root"]:
        raise ApplyPlanError("plan-git-identity", "Git top-level must equal the canonical target root")
    _require_match(target["stateFingerprint"], _SHA256, "apply plan target.stateFingerprint")
    missing_directories = _validate_missing_directories(target["missingDirectories"], "apply plan")

    source = _object(plan["source"], "apply plan source")
    _exact_keys(
        source,
        {"rendererVersion", "targetState", "force", "project", "fingerprint"},
        "apply plan source",
    )
    if source["rendererVersion"] != RENDERER_VERSION:
        raise ApplyPlanError("plan-source", "apply plan renderer version is unsupported")
    if source["targetState"] not in {"missing", "empty", "unmanaged", "managed"}:
        raise ApplyPlanError("plan-source", "apply plan target state is unsupported")
    if type(source["force"]) is not bool:
        raise ApplyPlanError("plan-source", "apply plan source.force must be a boolean")
    project_input = _validate_project_input(source["project"])
    _require_match(source["fingerprint"], _SHA256, "apply plan source.fingerprint")
    _require_match(plan["plannedBytesFingerprint"], _SHA256, "apply plan plannedBytesFingerprint")

    raw_files = plan["files"]
    if not isinstance(raw_files, list) or len(raw_files) != len(PROJECT_FRAME_PATHS):
        raise ApplyPlanError("plan-files", "apply plan must contain the complete project frame")
    files = [_validate_planned_file(item, index) for index, item in enumerate(raw_files)]
    if tuple(item["path"] for item in files) != PROJECT_FRAME_PATHS:
        raise ApplyPlanError("plan-files", "apply plan files are not in canonical project-frame order")
    if plan["plannedBytesFingerprint"] != _planned_bytes_fingerprint(files):
        raise ApplyPlanError("plan-bytes-fingerprint", "apply plan planned-byte fingerprint is invalid")
    expected_source = _source_fingerprint_from_files(source, project_input, files)
    if source["fingerprint"] != expected_source:
        raise ApplyPlanError("plan-source-fingerprint", "apply plan source fingerprint is invalid")
    expected_target = _target_state_fingerprint(
        target["root"],
        target["head"],
        git_identity,
        files,
        missing_directories,
    )
    if target["stateFingerprint"] != expected_target:
        raise ApplyPlanError("plan-target-fingerprint", "apply plan target-state fingerprint is invalid")

    unsealed = dict(plan)
    supplied_fingerprint = unsealed.pop("planFingerprint")
    if supplied_fingerprint != _json_fingerprint(unsealed):
        raise ApplyPlanError("plan-fingerprint", "apply plan fingerprint is invalid")
    core = dict(unsealed)
    supplied_id = core.pop("planId")
    if supplied_id != "apply-" + _json_fingerprint(core)[:24]:
        raise ApplyPlanError("plan-id", "apply plan id is invalid")
    _require_json_bound(plan, MAX_PLAN_BYTES, "apply plan")


def authorize_apply(plan: Mapping[str, Any], catalog: Mapping[str, Any]) -> dict[str, Any]:
    """Create one short-lived, MACed authorization after a foreground TTY prompt."""

    validate_apply_plan(plan)
    durable_plan = copy.deepcopy(dict(plan))
    repository = _require_enabled_repository(catalog, durable_plan["repositoryId"])
    _require_catalog_binding(catalog, durable_plan, repository)
    state_root = _private_state_root(create=True)
    key = _load_integrity_key(state_root, create=True)
    target = _repository_target(repository)
    lock_path = _target_lock_path(state_root, durable_plan)

    with exclusive_file_lock(lock_path, allowed_root=state_root):
        if _report_path(state_root, durable_plan, create_parent=False, missing_ok=True).exists():
            raise ApplyAuthorizationError(
                "report-exists",
                "this exact plan already has apply evidence; create a fresh plan",
            )
        root_descriptor = _open_target_root(target)
        try:
            _require_runtime_plan_binding(
                durable_plan,
                catalog,
                repository,
                target,
                root_descriptor,
                require_clean=True,
            )
            _require_tty_confirmation("authorize", durable_plan["planFingerprint"])
            now = _utc_now()
            grant = _build_authorization_grant(durable_plan, now, key)
            active_path = _authorization_path(state_root, durable_plan["planFingerprint"])
            _retire_expired_authorization(active_path, state_root, key, now)
            if active_path.exists() or active_path.is_symlink():
                raise ApplyAuthorizationError(
                    "authorization-exists",
                    "an unconsumed authorization already exists for this exact plan",
                )
            _write_new_json(
                active_path,
                grant,
                state_root,
                validator=lambda value: _validate_authorization_grant(value, key),
            )
            return copy.deepcopy(grant)
        finally:
            os.close(root_descriptor)


def execute_apply(plan: Mapping[str, Any], catalog: Mapping[str, Any]) -> dict[str, Any]:
    """Consume one canonical grant and apply exact bundled-template bytes."""

    validate_apply_plan(plan)
    durable_plan = copy.deepcopy(dict(plan))
    repository = _require_enabled_repository(catalog, durable_plan["repositoryId"])
    _require_catalog_binding(catalog, durable_plan, repository)
    _require_tty_confirmation("execute", durable_plan["planFingerprint"])
    state_root = _private_state_root(create=False)
    key = _load_integrity_key(state_root, create=False)
    target = _repository_target(repository)
    report_path = _report_path(state_root, durable_plan, create_parent=True)
    lock_path = _target_lock_path(state_root, durable_plan)

    with exclusive_file_lock(lock_path, allowed_root=state_root):
        if report_path.exists() or report_path.is_symlink():
            raise ApplyExecutionError(
                "report-exists",
                "apply evidence already exists; inspect or resume rollback",
                report_path=report_path,
            )
        root_descriptor = _open_target_root(target)
        try:
            _require_runtime_plan_binding(
                durable_plan,
                catalog,
                repository,
                target,
                root_descriptor,
                require_clean=True,
            )
            states = _snapshot_files_bound(
                target,
                root_descriptor,
                durable_plan["target"]["rootFingerprint"],
                PROJECT_FRAME_PATHS,
            )
            _require_plan_previous_matches(durable_plan, states)
            actual_missing = _missing_parent_directories_bound(
                target,
                root_descriptor,
                durable_plan["target"]["rootFingerprint"],
                PROJECT_FRAME_PATHS,
            )
            if actual_missing != durable_plan["target"]["missingDirectories"]:
                raise ApplyFingerprintError(
                    "target-directory-fingerprint",
                    "target parent directories changed after planning",
                )
            grant = _load_active_authorization(state_root, durable_plan, key)
            _require_authorization_binding(grant, durable_plan)
            _require_authorization_current(grant, _utc_now())
            _consume_authorization(state_root, durable_plan, grant, key)

            report = _build_backup_report(
                durable_plan,
                grant,
                states,
                _now_timestamp(),
                key,
            )
            try:
                _write_report(report_path, report, state_root, key)
            except Exception as exc:
                raise ApplyExecutionError(
                    "backup-report-write",
                    "backup report could not be persisted before target writes",
                    report_path=report_path,
                ) from exc

            try:
                _require_runtime_plan_binding(
                    durable_plan,
                    catalog,
                    repository,
                    target,
                    root_descriptor,
                    require_clean=True,
                )
                _require_plan_previous_matches(
                    durable_plan,
                    _snapshot_files_bound(
                        target,
                        root_descriptor,
                        durable_plan["target"]["rootFingerprint"],
                        PROJECT_FRAME_PATHS,
                    ),
                )
                _create_planned_directories(
                    target,
                    root_descriptor,
                    durable_plan,
                    report,
                    report_path,
                    state_root,
                    key,
                )
                _write_planned_files(target, root_descriptor, durable_plan, report)
                _verify_planned_files_bound(target, root_descriptor, durable_plan)
                _require_git_head_bound(
                    target,
                    root_descriptor,
                    durable_plan["target"]["rootFingerprint"],
                    durable_plan["target"]["head"],
                )
                post_status = _git_status_bound(
                    target,
                    root_descriptor,
                    durable_plan["target"]["rootFingerprint"],
                    durable_plan["target"]["gitIdentity"],
                )
                _require_status_paths_within_plan(post_status, durable_plan)
                report["status"] = "applied"
                report["completedAt"] = _now_timestamp()
                report["postApplyGitStatusBase64"] = _encode_bytes(post_status)
                report["postApplyGitStatusSha256"] = _sha256(post_status)
                report = _seal_report(report, key)
                try:
                    _write_report(report_path, report, state_root, key)
                except Exception as exc:
                    raise ApplyExecutionError(
                        "apply-report-write",
                        "final apply report could not be persisted",
                        report_path=report_path,
                    ) from exc
                return copy.deepcopy(report)
            except Exception as exc:
                failure = _normalize_execution_error(exc, report_path)
                report["status"] = "rollback-in-progress"
                report["failureCode"] = failure.code
                report["completedAt"] = None
                _best_effort_report(report_path, report, state_root, key)
                try:
                    _cleanup_journaled_temporary_artifacts(target, root_descriptor, report)
                    _restore_backup(target, root_descriptor, report)
                    _verify_backup_bound(target, root_descriptor, report)
                    _verify_created_directories_restored(root_descriptor, durable_plan)
                    _require_git_head_bound(
                        target,
                        root_descriptor,
                        durable_plan["target"]["rootFingerprint"],
                        durable_plan["target"]["head"],
                    )
                    _require_clean_git_bound(
                        target,
                        root_descriptor,
                        durable_plan["target"]["rootFingerprint"],
                        durable_plan["target"]["gitIdentity"],
                    )
                    report["status"] = "failed-rolled-back"
                except Exception as rollback_exc:
                    report["status"] = "rollback-failed"
                    report["rollbackFailureCode"] = _error_code(rollback_exc, "rollback-failed")
                    report["completedAt"] = _now_timestamp()
                    _best_effort_report(report_path, report, state_root, key)
                    raise ApplyRollbackError(
                        "automatic-rollback-failed",
                        "apply failed and automatic rollback could not restore the target",
                        report_path=report_path,
                    ) from rollback_exc
                report["completedAt"] = _now_timestamp()
                report = _seal_report(report, key)
                try:
                    _write_report(report_path, report, state_root, key)
                except Exception as report_exc:
                    raise ApplyExecutionError(
                        "rollback-report-write",
                        "target was restored but the rollback report could not be updated",
                        report_path=report_path,
                    ) from report_exc
                raise ApplyExecutionError(
                    failure.code,
                    "apply failed; the original target state was restored",
                    report_path=report_path,
                ) from exc
        finally:
            os.close(root_descriptor)


def apply_status(report_path: Path, catalog: Mapping[str, Any]) -> dict[str, Any]:
    """Verify a canonical MACed report and inspect exact target state without writes."""

    state_root = _private_state_root(create=False)
    key = _load_integrity_key(state_root, create=False)
    report_file, report = _read_canonical_report(Path(report_path), state_root, key)
    plan = report["plan"]
    repository = _require_repository_identity(catalog, plan["repositoryId"], require_enabled=False)
    if repository["path"] != plan["target"]["root"]:
        raise ApplyFingerprintError("target-root-drift", "catalog target root no longer matches the report")
    catalog_matches = (
        _json_fingerprint(catalog) == plan["catalogFingerprint"]
        and repository["realApply"]["approval"] == plan["approval"]
    )
    target = Path(plan["target"]["root"])
    root_descriptor = _open_target_root(target)
    try:
        root_matches = _root_fingerprint(target, root_descriptor) == plan["target"]["rootFingerprint"]
        if root_matches:
            _require_git_repository_binding_bound(
                target,
                root_descriptor,
                plan["target"]["rootFingerprint"],
                plan["target"]["gitIdentity"],
            )
            head_matches = (
                _git_head_bound(target, root_descriptor, plan["target"]["rootFingerprint"])
                == plan["target"]["head"]
            )
        else:
            head_matches = False
        if report["status"] == "applied" and root_matches:
            files_match = _planned_files_match_bound(target, root_descriptor, plan)
            directories_match = _created_directory_identities_match(root_descriptor, report)
            status_bytes = _git_status_bound(
                target,
                root_descriptor,
                plan["target"]["rootFingerprint"],
                plan["target"]["gitIdentity"],
            )
            status_matches = (
                report["postApplyGitStatusSha256"] is not None
                and _sha256(status_bytes) == report["postApplyGitStatusSha256"]
            )
            state = (
                "exact"
                if catalog_matches
                and root_matches
                and head_matches
                and files_match
                and directories_match
                and status_matches
                else "drifted"
            )
        elif report["status"] in {"rolled-back", "failed-rolled-back"} and root_matches:
            files_match = _backup_matches_bound(target, root_descriptor, report)
            directories_match = _created_directories_restored_match(root_descriptor, plan)
            status_matches = (
                _git_status_bound(
                    target,
                    root_descriptor,
                    plan["target"]["rootFingerprint"],
                    plan["target"]["gitIdentity"],
                )
                == b""
            )
            state = (
                "exact"
                if catalog_matches
                and root_matches
                and head_matches
                and files_match
                and directories_match
                and status_matches
                else "drifted"
            )
        else:
            files_match = False
            directories_match = False
            status_matches = False
            state = "incomplete"
    finally:
        os.close(root_descriptor)
    return {
        "schemaVersion": "plzdo-local.apply-status.v2",
        "reportId": report["reportId"],
        "reportPath": str(report_file),
        "reportStatus": report["status"],
        "state": state,
        "catalogMatches": catalog_matches,
        "rootMatches": root_matches,
        "headMatches": head_matches,
        "filesMatch": files_match,
        "directoriesMatch": directories_match,
        "gitStatusMatches": status_matches,
    }


def rollback_apply(
    report_path: Path,
    catalog: Mapping[str, Any],
) -> dict[str, Any]:
    """Resume or start idempotent rollback after exact-fingerprint TTY confirmation."""

    state_root = _private_state_root(create=False)
    key = _load_integrity_key(state_root, create=False)
    report_file, first_report = _read_canonical_report(Path(report_path), state_root, key)
    plan = first_report["plan"]
    _require_tty_confirmation("rollback", plan["planFingerprint"])
    repository = _require_repository_identity(catalog, plan["repositoryId"], require_enabled=False)
    if repository["path"] != plan["target"]["root"]:
        raise ApplyFingerprintError("target-root-drift", "catalog target root no longer matches the report")
    target = Path(plan["target"]["root"])
    lock_path = _target_lock_path(state_root, plan)

    with exclusive_file_lock(lock_path, allowed_root=state_root):
        _, report = _read_canonical_report(report_file, state_root, key)
        if report["reportMac"] != first_report["reportMac"]:
            raise ApplyRollbackError(
                "report-drift",
                "apply report changed before rollback acquired its target lock",
                report_path=report_file,
            )
        if report["status"] not in {"applied", "rollback-in-progress", "rollback-failed"}:
            raise ApplyRollbackError(
                "rollback-status",
                "report does not describe an applied or resumable write",
                report_path=report_file,
            )
        root_descriptor = _open_target_root(target)
        try:
            root_fingerprint = plan["target"]["rootFingerprint"]
            _require_root_fingerprint(target, root_descriptor, root_fingerprint)
            _require_git_repository_binding_bound(
                target,
                root_descriptor,
                root_fingerprint,
                plan["target"]["gitIdentity"],
            )
            _require_git_head_bound(
                target,
                root_descriptor,
                root_fingerprint,
                plan["target"]["head"],
            )
            if report["status"] == "rollback-failed":
                report["status"] = "rollback-in-progress"
                report["completedAt"] = None
                report["rollbackFailureCode"] = None
                _write_report(report_file, report, state_root, key)
            if report["status"] in {"rollback-in-progress", "rollback-failed"}:
                _cleanup_journaled_temporary_artifacts(target, root_descriptor, report)
            current_status = _git_status_bound(
                target,
                root_descriptor,
                root_fingerprint,
                plan["target"]["gitIdentity"],
            )
            if report["status"] == "applied":
                _verify_planned_files_bound(target, root_descriptor, plan)
                if (
                    report["postApplyGitStatusSha256"] is None
                    or _sha256(current_status) != report["postApplyGitStatusSha256"]
                ):
                    raise ApplyRollbackError(
                        "rollback-drift",
                        "target Git state changed after apply; rollback was refused",
                        report_path=report_file,
                    )
            else:
                _require_recoverable_files(root_descriptor, report)
                _require_status_paths_within_plan(current_status, plan)

            report["status"] = "rollback-in-progress"
            report["completedAt"] = None
            report["rollbackFailureCode"] = None
            _write_report(report_file, report, state_root, key)
            try:
                _restore_backup(target, root_descriptor, report)
                _verify_backup_bound(target, root_descriptor, report)
                _verify_created_directories_restored(root_descriptor, plan)
                _require_git_head_bound(
                    target,
                    root_descriptor,
                    root_fingerprint,
                    plan["target"]["head"],
                )
                _require_clean_git_bound(
                    target,
                    root_descriptor,
                    root_fingerprint,
                    plan["target"]["gitIdentity"],
                )
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    raise
                report["status"] = "rollback-failed"
                report["rollbackFailureCode"] = _error_code(exc, "rollback-failed")
                report["completedAt"] = _now_timestamp()
                _best_effort_report(report_file, report, state_root, key)
                raise ApplyRollbackError(
                    "rollback-failed",
                    "rollback remains resumable but did not complete",
                    report_path=report_file,
                ) from exc
            report["status"] = "rolled-back"
            report["completedAt"] = _now_timestamp()
            report["failureCode"] = None
            report["rollbackFailureCode"] = None
            report = _seal_report(report, key)
            try:
                _write_report(report_file, report, state_root, key)
            except Exception as exc:
                raise ApplyRollbackError(
                    "rollback-report-write",
                    "target was restored but rollback evidence remains resumable",
                    report_path=report_file,
                ) from exc
            return copy.deepcopy(report)
        finally:
            os.close(root_descriptor)


def apply_report_path(plan: Mapping[str, Any]) -> Path:
    """Return the canonical report path without creating evidence directories."""

    validate_apply_plan(plan)
    state_root = _private_state_root(create=False)
    return _report_path(state_root, plan, create_parent=False)


def _require_enabled_repository(catalog: Mapping[str, Any], repository_id: str) -> dict[str, Any]:
    repository = _require_repository_identity(catalog, repository_id, require_enabled=True)
    policy = repository["realApply"]
    if policy["enabled"] is not True:
        raise ApplyPolicyError("apply-disabled", "real apply is disabled")
    if repository["workflowLane"] != "operational":
        raise ApplyPolicyError("workflow-lane", "real apply requires workflowLane=operational")
    if repository["rolloutTier"] != "enforced":
        raise ApplyPolicyError("rollout-tier", "real apply requires rolloutTier=enforced")
    if policy["operatorOnly"] is not True:
        raise ApplyPolicyError("operator-only", "real apply requires operatorOnly=true")
    if not isinstance(policy["approval"], dict):
        raise ApplyPolicyError("approval-required", "real apply requires approval metadata")
    return repository


def _require_repository_identity(
    catalog: Mapping[str, Any],
    repository_id: str,
    *,
    require_enabled: bool,
) -> dict[str, Any]:
    try:
        validate_catalog(catalog)
        repository = get_repository(catalog, repository_id, include_archived=not require_enabled)
    except CatalogError as exc:
        raise ApplyPolicyError("invalid-catalog", "catalog or repository policy is invalid") from exc
    if require_enabled and repository["state"] != "active":
        raise ApplyPolicyError("repository-inactive", "real apply requires an active repository")
    return repository


def _repository_target(repository: Mapping[str, Any]) -> Path:
    target = Path(repository["path"])
    try:
        resolved = target.resolve(strict=True)
    except OSError as exc:
        raise ApplyPathError("target-unavailable", "target root is unavailable") from exc
    if resolved != target or target.is_symlink() or not target.is_dir():
        raise ApplyPathError("target-root", "catalog target must be a canonical real directory")
    return target


def _validate_project_input(value: Any) -> dict[str, str]:
    if isinstance(value, ProjectFramePlan):
        raise ApplyPlanError("renderer-plan-input", "caller-constructed renderer plans are not accepted")
    if type(value) is not dict:
        raise ApplyPlanError("project-input", "apply project input must be an exact JSON object")
    _exact_keys(value, {"id", "name", "objective"}, "apply project input")
    project_id = _plain_project_text(value["id"], "project id", 64)
    if _SAFE_ID.fullmatch(project_id) is None:
        raise ApplyPlanError("project-input", "project id is invalid")
    name = _plain_project_text(value["name"], "project name", 120)
    objective = _plain_project_text(value["objective"], "project objective", 500)
    for label, text in (("project name", name), ("project objective", objective)):
        if text != text.strip() or "\n" in text or "\r" in text:
            raise ApplyPlanError("project-input", f"{label} must be one trimmed line")
        if "{{" in text or "}}" in text or "PLZDO-LOCAL:" in text:
            raise ApplyPlanError("project-input", f"{label} contains reserved renderer syntax")
    return {"id": project_id, "name": name, "objective": objective}


def _plain_project_text(value: Any, label: str, maximum: int) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise ApplyPlanError("project-input", f"{label} must be a bounded string")
    if "\x00" in value or any(ord(character) < 32 for character in value):
        raise ApplyPlanError("project-input", f"{label} contains control characters")
    if len(value.splitlines()) != 1:
        raise ApplyPlanError("project-input", f"{label} must be one line")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ApplyPlanError("project-input", f"{label} must be valid UTF-8 text") from exc
    return value


def _owned_frame_plan(target: Path, project: Mapping[str, str], *, force: bool) -> ProjectFramePlan:
    try:
        return plan_project_frame(target, project, force=force)
    except (RendererError, PathPolicyError) as exc:
        raise ApplyPlanError(
            "renderer-owned-plan",
            "bundled immutable templates could not produce the canonical project frame",
        ) from exc


def _require_allowed_outputs(repository: Mapping[str, Any]) -> None:
    outputs = repository["outputs"]
    protected = repository["protectedPaths"]
    for relative in PROJECT_FRAME_PATHS:
        if not any(_path_is_within(relative, allowed) for allowed in outputs):
            raise ApplyPolicyError("output-not-allowed", "planned file is outside catalog outputs")
        if any(_path_is_within(relative, blocked) for blocked in protected):
            raise ApplyPolicyError("protected-path", "planned file overlaps a protected path")


def _require_runtime_plan_binding(
    plan: Mapping[str, Any],
    catalog: Mapping[str, Any],
    repository: Mapping[str, Any],
    target: Path,
    root_descriptor: int,
    *,
    require_clean: bool,
) -> None:
    _require_catalog_binding(catalog, plan, repository)
    _require_allowed_outputs(repository)
    root_fingerprint = plan["target"]["rootFingerprint"]
    _require_root_fingerprint(target, root_descriptor, root_fingerprint)
    frame_plan = _owned_frame_plan(
        target,
        _validate_project_input(plan["source"]["project"]),
        force=plan["source"]["force"],
    )
    _require_current_frame_binding(frame_plan, plan)
    _require_git_repository_binding_bound(
        target,
        root_descriptor,
        root_fingerprint,
        plan["target"]["gitIdentity"],
    )
    _require_git_head_bound(
        target,
        root_descriptor,
        root_fingerprint,
        plan["target"]["head"],
    )
    if require_clean:
        _require_clean_git_bound(
            target,
            root_descriptor,
            root_fingerprint,
            plan["target"]["gitIdentity"],
        )
    states = _snapshot_files_bound(target, root_descriptor, root_fingerprint, PROJECT_FRAME_PATHS)
    missing = _missing_parent_directories_bound(
        target,
        root_descriptor,
        root_fingerprint,
        PROJECT_FRAME_PATHS,
    )
    actual = _target_state_fingerprint(
        str(target),
        plan["target"]["head"],
        plan["target"]["gitIdentity"],
        [dict(item, previous=states[item["path"]].as_plan_previous()) for item in plan["files"]],
        missing,
    )
    if actual != plan["target"]["stateFingerprint"]:
        raise ApplyFingerprintError("target-state-fingerprint", "target state changed after planning")


def _planned_file(item: Any, state: _FileState) -> dict[str, Any]:
    return {
        "path": item.path,
        "action": item.action,
        "mode": format(item.mode, "04o"),
        "bytes": len(item.content),
        "sha256": _sha256(item.content),
        "contentBase64": _encode_bytes(item.content),
        "templateSha256": item.template_sha256,
        "previous": state.as_plan_previous(),
    }


def _validate_planned_file(value: Any, index: int) -> dict[str, Any]:
    label = f"apply plan files[{index}]"
    item = _object(value, label)
    _exact_keys(
        item,
        {"path", "action", "mode", "bytes", "sha256", "contentBase64", "templateSha256", "previous"},
        label,
    )
    relative = _relative_path(item["path"], f"{label}.path")
    if relative not in FILE_MODES:
        raise ApplyPlanError("plan-path", f"{label}.path is not a renderer-owned output")
    if item["action"] not in _ACTIONS:
        raise ApplyPlanError("plan-action", f"{label}.action is unsupported")
    _require_match(item["mode"], _MODE, f"{label}.mode")
    if item["mode"] != format(FILE_MODES[item["path"]], "04o"):
        raise ApplyPlanError("plan-mode", f"{label}.mode differs from the renderer contract")
    if type(item["bytes"]) is not int or item["bytes"] < 0 or item["bytes"] > MAX_TARGET_FILE_BYTES:
        raise ApplyPlanError("plan-file-bytes", f"{label}.bytes is invalid")
    _require_match(item["sha256"], _SHA256, f"{label}.sha256")
    _require_match(item["templateSha256"], _SHA256, f"{label}.templateSha256")
    content = _decode_bytes(item["contentBase64"], f"{label}.contentBase64")
    if len(content) != item["bytes"] or _sha256(content) != item["sha256"]:
        raise ApplyPlanError("plan-file-content", f"{label} exact bytes do not match their metadata")
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApplyPlanError("plan-binary-frame", "renderer-owned project frames must be UTF-8 text") from exc
    previous = _object(item["previous"], f"{label}.previous")
    _exact_keys(previous, {"exists", "mode", "bytes", "sha256"}, f"{label}.previous")
    if type(previous["exists"]) is not bool:
        raise ApplyPlanError("plan-previous", f"{label}.previous.exists must be a boolean")
    if previous["exists"]:
        _require_match(previous["mode"], _MODE, f"{label}.previous.mode")
        if type(previous["bytes"]) is not int or previous["bytes"] < 0 or previous["bytes"] > MAX_TARGET_FILE_BYTES:
            raise ApplyPlanError("plan-previous", f"{label}.previous.bytes is invalid")
        _require_match(previous["sha256"], _SHA256, f"{label}.previous.sha256")
        if item["action"] == "create":
            raise ApplyPlanError("plan-action", f"{label}.action conflicts with previous state")
    else:
        if previous["mode"] is not None or previous["bytes"] is not None or previous["sha256"] is not None:
            raise ApplyPlanError("plan-previous", f"{label}.previous absent state must use null metadata")
        if item["action"] != "create":
            raise ApplyPlanError("plan-action", f"{label}.action conflicts with previous state")
    if item["action"] == "no-change":
        if previous["sha256"] != item["sha256"] or previous["mode"] != item["mode"]:
            raise ApplyPlanError("plan-action", f"{label}.no-change bytes or mode differ")
    if item["action"] == "update-mode" and previous["sha256"] != item["sha256"]:
        raise ApplyPlanError("plan-action", f"{label}.update-mode changes bytes")
    if item["action"] == "update-mode" and previous["mode"] == item["mode"]:
        raise ApplyPlanError("plan-action", f"{label}.update-mode does not change mode")
    if item["action"] == "update" and previous["sha256"] == item["sha256"]:
        raise ApplyPlanError("plan-action", f"{label}.update does not change bytes")
    return item


def _require_frame_previous_matches(frame_plan: ProjectFramePlan, states: Mapping[str, _FileState]) -> None:
    if tuple(item.path for item in frame_plan.files) != PROJECT_FRAME_PATHS:
        raise ApplyPlanError("renderer-files", "renderer plan does not contain the canonical project frame")
    for item in frame_plan.files:
        state = states[item.path]
        if item.previous_content != state.content or item.previous_mode != state.mode:
            raise ApplyFingerprintError("renderer-target-stale", "renderer plan previous bytes are stale")


def _require_current_frame_binding(frame_plan: ProjectFramePlan, plan: Mapping[str, Any]) -> None:
    if str(frame_plan.target) != plan["target"]["root"]:
        raise ApplyFingerprintError("target-root-mismatch", "current renderer target differs from the apply plan")
    if frame_plan.target_state != plan["source"]["targetState"] or frame_plan.force != plan["source"]["force"]:
        raise ApplyFingerprintError("source-fingerprint-mismatch", "renderer source state changed after planning")
    project = _validate_project_input(plan["source"]["project"])
    if _source_fingerprint(frame_plan, project) != plan["source"]["fingerprint"]:
        raise ApplyFingerprintError("source-fingerprint-mismatch", "bundled templates changed after planning")
    current_files = [_planned_file(item, _state_from_renderer_item(item)) for item in frame_plan.files]
    if _planned_bytes_fingerprint(current_files) != plan["plannedBytesFingerprint"]:
        raise ApplyFingerprintError("planned-bytes-drift", "renderer planned bytes changed after planning")


def _state_from_renderer_item(item: Any) -> _FileState:
    return _FileState(
        exists=item.previous_content is not None,
        content=item.previous_content,
        mode=item.previous_mode,
    )


def _source_fingerprint(frame_plan: ProjectFramePlan, project: Mapping[str, str]) -> str:
    source = {
        "rendererVersion": RENDERER_VERSION,
        "targetState": frame_plan.target_state,
        "force": frame_plan.force,
        "project": dict(project),
    }
    files = [
        {
            "path": item.path,
            "sha256": _sha256(item.content),
            "templateSha256": item.template_sha256,
        }
        for item in frame_plan.files
    ]
    return _json_fingerprint(dict(source, files=files))


def _source_fingerprint_from_files(
    source: Mapping[str, Any],
    project: Mapping[str, str],
    files: Sequence[Mapping[str, Any]],
) -> str:
    payload = {
        "rendererVersion": source["rendererVersion"],
        "targetState": source["targetState"],
        "force": source["force"],
        "project": dict(project),
        "files": [
            {
                "path": item["path"],
                "sha256": item["sha256"],
                "templateSha256": item["templateSha256"],
            }
            for item in files
        ],
    }
    return _json_fingerprint(payload)


def _planned_bytes_fingerprint(files: Sequence[Mapping[str, Any]]) -> str:
    payload = [
        {
            "path": item["path"],
            "mode": item["mode"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
            "contentBase64": item["contentBase64"],
        }
        for item in files
    ]
    return _json_fingerprint(payload)


def _target_state_fingerprint(
    root: str,
    head: str,
    git_identity: Mapping[str, Any],
    files: Sequence[Mapping[str, Any]],
    missing_directories: Sequence[str],
) -> str:
    payload = {
        "root": root,
        "head": head,
        "gitIdentity": copy.deepcopy(dict(git_identity)),
        "missingDirectories": list(missing_directories),
        "files": [{"path": item["path"], "previous": item["previous"]} for item in files],
    }
    return _json_fingerprint(payload)


def _require_catalog_binding(
    catalog: Mapping[str, Any],
    plan: Mapping[str, Any],
    repository: Mapping[str, Any],
) -> None:
    if _json_fingerprint(catalog) != plan["catalogFingerprint"]:
        raise ApplyFingerprintError("catalog-fingerprint-mismatch", "catalog changed after apply planning")
    if repository["path"] != plan["target"]["root"]:
        raise ApplyFingerprintError("target-root-drift", "catalog target root changed after apply planning")
    if repository["realApply"]["approval"] != plan["approval"]:
        raise ApplyFingerprintError("approval-drift", "apply approval changed after planning")


def _require_tty_confirmation(action: str, expected: str) -> None:
    typed = _read_foreground_confirmation(action, expected)
    if type(typed) is not str:
        raise ApplyConfirmationError("confirmation-type", "TTY confirmation must be an exact string")
    if typed != expected:
        raise ApplyConfirmationError(
            "confirmation-mismatch",
            "TTY confirmation did not match the exact plan fingerprint",
        )


def _read_foreground_confirmation(action: str, expected: str) -> str:
    """Read only from the controlling foreground terminal, never stdin or environment."""

    if os.name != "posix" or not hasattr(os, "tcgetpgrp"):
        raise ApplyConfirmationError(
            "foreground-tty-unsupported",
            "real apply is disabled where a foreground controlling TTY cannot be verified with stdlib",
        )
    flags = os.O_RDWR
    if hasattr(os, "O_NOCTTY"):
        flags |= os.O_NOCTTY
    try:
        descriptor = os.open("/dev/tty", flags)
    except OSError as exc:
        raise ApplyConfirmationError("foreground-tty", "a controlling TTY is required") from exc
    try:
        if not os.isatty(descriptor) or os.tcgetpgrp(descriptor) != os.getpgrp():
            raise ApplyConfirmationError("foreground-tty", "the process must own the foreground TTY")
        prompt = (
            f"PlzDo {action} requires the exact plan fingerprint.\n"
            f"Type {expected}\n> "
        ).encode("ascii")
        _write_all(descriptor, prompt)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1)
            if not chunk or chunk in {b"\n", b"\r"}:
                break
            chunks.append(chunk)
            if len(chunks) > 128:
                raise ApplyConfirmationError("confirmation-size", "TTY confirmation is too long")
        try:
            return b"".join(chunks).decode("ascii")
        except UnicodeDecodeError as exc:
            raise ApplyConfirmationError("confirmation-encoding", "TTY confirmation must be ASCII") from exc
    finally:
        os.close(descriptor)


def _private_state_root(*, create: bool) -> Path:
    if os.name != "posix" or not hasattr(os, "getuid"):
        raise ApplyPolicyError(
            "private-state-unsupported",
            "real apply is disabled where owner-only state cannot be verified with stdlib",
        )
    try:
        root = resolve_state_root()
    except PathPolicyError as exc:
        raise ApplyPathError("state-root", "PLZDO state root is invalid") from exc
    if not root.is_absolute() or root == Path(root.anchor):
        raise ApplyPathError("state-root", "PLZDO state root must be a non-root absolute path")
    if root.is_symlink():
        raise ApplyPathError("state-root-symlink", "PLZDO state root must not be a symlink")
    if not root.exists():
        if not create:
            raise ApplyPathError("state-root-missing", "PLZDO state root does not exist")
        try:
            root.mkdir(parents=True, mode=0o700)
        except OSError as exc:
            raise ApplyPathError("state-root", "PLZDO state root could not be created") from exc
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise ApplyPathError("state-root", "PLZDO state root is unavailable") from exc
    if resolved != root:
        raise ApplyPathError("state-root", "PLZDO state root must already be canonical")
    _require_private_directory(root, "PLZDO state root")
    return root


def _require_private_directory(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ApplyPathError("private-state", f"{label} is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ApplyPathError("private-state", f"{label} must be a real directory")
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ApplyPolicyError("private-state-permissions", f"{label} must be owner-only (0700)")


def _private_directory(root: Path, *parts: str, create: bool) -> Path:
    current = root
    for part in parts:
        current = ensure_contained(current / part, root, label="real-apply state path")
        if current.is_symlink():
            raise ApplyPathError("private-state-symlink", "real-apply state must not cross symlinks")
        if not current.exists():
            if not create:
                raise ApplyPathError("private-state-missing", "required real-apply state is missing")
            try:
                current.mkdir(mode=0o700)
            except OSError as exc:
                raise ApplyPathError("private-state", "real-apply state directory could not be created") from exc
        _require_private_directory(current, "real-apply state directory")
    return current


def _load_integrity_key(state_root: Path, *, create: bool) -> bytes:
    directory = _private_directory(state_root, "real-apply", create=create)
    path = ensure_contained(directory / "integrity.key", state_root, label="integrity key")
    if not path.exists() and not path.is_symlink():
        if not create:
            raise ApplyAuthorizationError("integrity-key-missing", "real-apply integrity key is missing")
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
            try:
                _write_all(descriptor, secrets.token_bytes(INTEGRITY_KEY_BYTES))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            _fsync_directory(directory)
        except FileExistsError:
            pass
        except OSError as exc:
            raise ApplyAuthorizationError("integrity-key-create", "integrity key could not be created") from exc
    if path.is_symlink():
        raise ApplyPathError("integrity-key-symlink", "integrity key must not be a symlink")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ApplyAuthorizationError("integrity-key-open", "integrity key is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or metadata.st_size != INTEGRITY_KEY_BYTES
        ):
            raise ApplyPolicyError(
                "integrity-key-permissions",
                "integrity key must be an owner-only regular 32-byte file",
            )
        key = _read_bounded(descriptor, INTEGRITY_KEY_BYTES)
    finally:
        os.close(descriptor)
    if len(key) != INTEGRITY_KEY_BYTES:
        raise ApplyAuthorizationError("integrity-key-size", "integrity key has an invalid size")
    return key


def _target_lock_id(plan: Mapping[str, Any]) -> str:
    return _json_fingerprint({"targetRoot": plan["target"]["root"]})


def _target_lock_path(state_root: Path, plan: Mapping[str, Any]) -> Path:
    directory = _private_directory(state_root, "real-apply", "locks", create=True)
    return ensure_contained(
        directory / f"target-{_target_lock_id(plan)}.lock",
        state_root,
        label="target-global lock",
    )


def _authorization_path(state_root: Path, plan_fingerprint: str) -> Path:
    _require_match(plan_fingerprint, _SHA256, "authorization plan fingerprint")
    directory = _private_directory(state_root, "real-apply", "authorizations", create=True)
    return ensure_contained(
        directory / f"{plan_fingerprint}.json",
        state_root,
        label="authorization grant",
    )


def _consumed_authorization_path(state_root: Path, grant: Mapping[str, Any]) -> Path:
    directory = _private_directory(state_root, "real-apply", "consumed", create=True)
    return ensure_contained(
        directory / f"{grant['planFingerprint']}-{grant['nonce']}.json",
        state_root,
        label="consumed authorization",
    )


def _report_path(
    state_root: Path,
    plan: Mapping[str, Any],
    *,
    create_parent: bool,
    missing_ok: bool = False,
) -> Path:
    if create_parent:
        evidence = _private_directory(state_root, "real-apply", "evidence", create=True)
        target_directory = _private_directory(
            state_root,
            "real-apply",
            "evidence",
            _target_lock_id(plan),
            create=True,
        )
    elif missing_ok:
        evidence = ensure_contained(state_root / "real-apply" / "evidence", state_root, label="evidence root")
        target_directory = ensure_contained(
            evidence / _target_lock_id(plan),
            state_root,
            label="target evidence root",
        )
    else:
        evidence = _private_directory(state_root, "real-apply", "evidence", create=False)
        target_directory = _private_directory(
            state_root,
            "real-apply",
            "evidence",
            _target_lock_id(plan),
            create=False,
        )
    return ensure_contained(
        target_directory / f"{plan['planFingerprint']}.apply-report.json",
        evidence,
        label="canonical apply report",
    )


def _build_authorization_grant(
    plan: Mapping[str, Any],
    issued_at: datetime,
    key: bytes,
) -> dict[str, Any]:
    grant: dict[str, Any] = {
        "schemaVersion": AUTHORIZATION_SCHEMA_VERSION,
        "nonce": secrets.token_hex(32),
        "issuedAt": issued_at.isoformat(),
        "expiresAt": (issued_at + timedelta(seconds=AUTHORIZATION_TTL_SECONDS)).isoformat(),
        "repositoryId": plan["repositoryId"],
        "repositoryPath": plan["target"]["root"],
        "rootFingerprint": plan["target"]["rootFingerprint"],
        "head": plan["target"]["head"],
        "planFingerprint": plan["planFingerprint"],
        "catalogFingerprint": plan["catalogFingerprint"],
        "keyId": _sha256(key),
    }
    grant["grantMac"] = _mac_json(key, "plzdo-local.apply-authorization.v1", grant)
    _validate_authorization_grant(grant, key)
    return grant


def _validate_authorization_grant(value: Any, key: bytes) -> None:
    grant = _object(value, "authorization grant")
    _exact_keys(
        grant,
        {
            "schemaVersion",
            "nonce",
            "issuedAt",
            "expiresAt",
            "repositoryId",
            "repositoryPath",
            "rootFingerprint",
            "head",
            "planFingerprint",
            "catalogFingerprint",
            "keyId",
            "grantMac",
        },
        "authorization grant",
    )
    if grant["schemaVersion"] != AUTHORIZATION_SCHEMA_VERSION:
        raise ApplyAuthorizationError("authorization-schema", "authorization grant schema is unsupported")
    _require_match(grant["nonce"], _NONCE, "authorization nonce")
    issued = _parse_timestamp(grant["issuedAt"], "authorization issuedAt")
    expires = _parse_timestamp(grant["expiresAt"], "authorization expiresAt")
    if expires <= issued or expires - issued > timedelta(seconds=AUTHORIZATION_TTL_SECONDS):
        raise ApplyAuthorizationError("authorization-expiry", "authorization expiry is invalid")
    _require_match(grant["repositoryId"], _SAFE_ID, "authorization repositoryId")
    _require_absolute_canonical_text(grant["repositoryPath"], "authorization repositoryPath")
    for field in ("rootFingerprint", "planFingerprint", "catalogFingerprint", "keyId", "grantMac"):
        _require_match(grant[field], _SHA256, f"authorization {field}")
    _require_match(grant["head"], _GIT_HEAD, "authorization head")
    if grant["keyId"] != _sha256(key):
        raise ApplyAuthorizationError("authorization-key", "authorization uses a different integrity key")
    unsealed = dict(grant)
    supplied = unsealed.pop("grantMac")
    expected = _mac_json(key, "plzdo-local.apply-authorization.v1", unsealed)
    if not hmac.compare_digest(supplied, expected):
        raise ApplyAuthorizationError("authorization-mac", "authorization grant MAC is invalid")
    _require_json_bound(grant, MAX_GRANT_BYTES, "authorization grant")


def _require_authorization_binding(grant: Mapping[str, Any], plan: Mapping[str, Any]) -> None:
    expected = {
        "repositoryId": plan["repositoryId"],
        "repositoryPath": plan["target"]["root"],
        "rootFingerprint": plan["target"]["rootFingerprint"],
        "head": plan["target"]["head"],
        "planFingerprint": plan["planFingerprint"],
        "catalogFingerprint": plan["catalogFingerprint"],
    }
    if any(grant[field] != expected_value for field, expected_value in expected.items()):
        raise ApplyAuthorizationError(
            "authorization-binding",
            "authorization is not bound to this repository, target, HEAD, and exact plan",
        )


def _require_authorization_current(grant: Mapping[str, Any], now: datetime) -> None:
    if now >= _parse_timestamp(grant["expiresAt"], "authorization expiresAt"):
        raise ApplyAuthorizationError("authorization-expired", "authorization grant has expired")


def _load_active_authorization(
    state_root: Path,
    plan: Mapping[str, Any],
    key: bytes,
) -> dict[str, Any]:
    path = _authorization_path(state_root, plan["planFingerprint"])
    grant = _read_json_file(path, MAX_GRANT_BYTES, "authorization grant")
    _validate_authorization_grant(grant, key)
    consumed = _consumed_authorization_path(state_root, grant)
    if consumed.exists() or consumed.is_symlink():
        raise ApplyAuthorizationError("authorization-consumed", "authorization nonce was already consumed")
    return grant


def _consume_authorization(
    state_root: Path,
    plan: Mapping[str, Any],
    grant: Mapping[str, Any],
    key: bytes,
) -> None:
    source = _authorization_path(state_root, plan["planFingerprint"])
    destination = _consumed_authorization_path(state_root, grant)
    if destination.exists() or destination.is_symlink():
        raise ApplyAuthorizationError("authorization-consumed", "authorization nonce was already consumed")
    try:
        os.replace(source, destination)
        _fsync_directory(source.parent)
        _fsync_directory(destination.parent)
    except OSError as exc:
        raise ApplyAuthorizationError("authorization-consume", "authorization could not be consumed") from exc
    consumed = _read_json_file(destination, MAX_GRANT_BYTES, "consumed authorization")
    _validate_authorization_grant(consumed, key)
    if consumed != grant:
        raise ApplyAuthorizationError("authorization-consume", "consumed authorization changed during rename")


def _retire_expired_authorization(
    active_path: Path,
    state_root: Path,
    key: bytes,
    now: datetime,
) -> None:
    if not active_path.exists() and not active_path.is_symlink():
        return
    grant = _read_json_file(active_path, MAX_GRANT_BYTES, "authorization grant")
    _validate_authorization_grant(grant, key)
    if now < _parse_timestamp(grant["expiresAt"], "authorization expiresAt"):
        return
    destination = _consumed_authorization_path(state_root, grant)
    if destination.exists() or destination.is_symlink():
        raise ApplyAuthorizationError("authorization-consumed", "expired authorization nonce already exists")
    try:
        os.replace(active_path, destination)
        _fsync_directory(active_path.parent)
        _fsync_directory(destination.parent)
    except OSError as exc:
        raise ApplyAuthorizationError("authorization-retire", "expired authorization could not be retired") from exc


def _open_target_root(target: Path) -> int:
    if target.is_symlink():
        raise ApplyPathError("target-symlink", "target root must not be a symlink")
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target, flags)
    except OSError as exc:
        raise ApplyPathError("target-open", "target root cannot be opened safely") from exc
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ApplyPathError("target-root", "target root must be a directory")
    return descriptor


def _root_fingerprint(target: Path, root_descriptor: int) -> str:
    metadata = os.fstat(root_descriptor)
    payload = {
        "root": str(target),
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
    }
    return _json_fingerprint(payload)


def _require_root_fingerprint(target: Path, root_descriptor: int, expected: str) -> None:
    if _root_fingerprint(target, root_descriptor) != expected:
        raise ApplyFingerprintError("target-root-fingerprint", "target root identity changed after planning")
    try:
        path_metadata = target.lstat()
    except OSError as exc:
        raise ApplyPathError("target-root", "target root cannot be revalidated") from exc
    descriptor_metadata = os.fstat(root_descriptor)
    if stat.S_ISLNK(path_metadata.st_mode) or (
        path_metadata.st_dev,
        path_metadata.st_ino,
    ) != (descriptor_metadata.st_dev, descriptor_metadata.st_ino):
        raise ApplyFingerprintError("target-root-fingerprint", "target root path was replaced")


def _snapshot_files_bound(
    target: Path,
    root_descriptor: int,
    root_fingerprint: str,
    paths: Sequence[str],
) -> dict[str, _FileState]:
    _require_root_fingerprint(target, root_descriptor, root_fingerprint)
    states = _snapshot_files(root_descriptor, paths)
    _require_root_fingerprint(target, root_descriptor, root_fingerprint)
    return states


def _snapshot_files(root_descriptor: int, paths: Sequence[str]) -> dict[str, _FileState]:
    return {relative: _read_file_state(root_descriptor, relative) for relative in paths}


def _frame_parent_directories() -> tuple[str, ...]:
    parents: set[str] = set()
    for relative in PROJECT_FRAME_PATHS:
        parts = PurePosixPath(relative).parts[:-1]
        for index in range(1, len(parts) + 1):
            parents.add(PurePosixPath(*parts[:index]).as_posix())
    return tuple(sorted(parents))


def _validate_missing_directories(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or value != sorted(set(value)):
        raise ApplyPlanError("plan-directories", f"{label} missingDirectories must be sorted and unique")
    allowed = set(_frame_parent_directories())
    for relative in value:
        if _relative_path(relative, f"{label} missing directory") not in allowed:
            raise ApplyPlanError(
                "plan-directories",
                "created directories must be derived only from canonical frame parents",
            )
    return list(value)


def _validate_git_identity(value: Any, label: str) -> dict[str, Any]:
    identity = _object(value, label)
    _exact_keys(identity, {"topLevel", "gitDirectory", "commonDirectory"}, label)
    top_level = _require_absolute_canonical_text(identity["topLevel"], f"{label}.topLevel")
    validated: dict[str, Any] = {"topLevel": top_level}
    for field in ("gitDirectory", "commonDirectory"):
        directory = _object(identity[field], f"{label}.{field}")
        _exact_keys(directory, {"path", "device", "inode"}, f"{label}.{field}")
        path = _require_absolute_canonical_text(directory["path"], f"{label}.{field}.path")
        for numeric in ("device", "inode"):
            if type(directory[numeric]) is not int or directory[numeric] < 0:
                raise ApplyPlanError(
                    "plan-git-identity",
                    f"{label}.{field}.{numeric} must be a non-negative integer",
                )
        validated[field] = {
            "path": path,
            "device": directory["device"],
            "inode": directory["inode"],
        }
    return validated


def _missing_parent_directories_bound(
    target: Path,
    root_descriptor: int,
    root_fingerprint: str,
    paths: Sequence[str],
) -> list[str]:
    _require_root_fingerprint(target, root_descriptor, root_fingerprint)
    value = _missing_parent_directories(root_descriptor, paths)
    _require_root_fingerprint(target, root_descriptor, root_fingerprint)
    return value


def _missing_parent_directories(root_descriptor: int, paths: Sequence[str]) -> list[str]:
    missing: set[str] = set()
    for relative in paths:
        parts = PurePosixPath(_relative_path(relative, "target file path")).parts[:-1]
        for index in range(1, len(parts) + 1):
            prefix = PurePosixPath(*parts[:index]).as_posix()
            try:
                descriptor = _open_directory_chain(root_descriptor, parts[:index], create=False)[0]
            except FileNotFoundError:
                missing.add(prefix)
            else:
                os.close(descriptor)
    return sorted(missing)


def _read_file_state(root_descriptor: int, relative: str) -> _FileState:
    path = PurePosixPath(_relative_path(relative, "target file path"))
    try:
        parent_descriptor = _open_directory_chain(root_descriptor, path.parts[:-1], create=False)[0]
    except FileNotFoundError:
        return _FileState(False, None, None)
    try:
        return _read_file_state_at(parent_descriptor, path.name)
    finally:
        os.close(parent_descriptor)


def _read_file_state_at(parent_descriptor: int, name: str) -> _FileState:
    try:
        metadata = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return _FileState(False, None, None)
    if stat.S_ISLNK(metadata.st_mode):
        raise ApplyPathError("target-symlink", "planned target path crosses a symlink")
    if not stat.S_ISREG(metadata.st_mode):
        raise ApplyPathError("target-file-type", "planned target path is not a regular file")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise ApplyPathError("target-file-type", "planned target path is not a regular file")
            if opened.st_size > MAX_TARGET_FILE_BYTES:
                raise ApplyPathError("target-file-size", "planned target file exceeds the byte limit")
            content = _read_bounded(descriptor, MAX_TARGET_FILE_BYTES)
            return _FileState(True, content, stat.S_IMODE(opened.st_mode))
        finally:
            os.close(descriptor)
    except ApplyGateError:
        raise
    except OSError as exc:
        raise ApplyPathError("target-read", "planned target path cannot be read safely") from exc


def _open_directory_chain(
    root_descriptor: int,
    parts: Sequence[str],
    *,
    create: bool,
) -> tuple[int, list[str]]:
    descriptor = os.dup(root_descriptor)
    created: list[str] = []
    traversed: list[str] = []
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        for part in parts:
            traversed.append(part)
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o755, dir_fd=descriptor)
                os.fsync(descriptor)
                created.append(PurePosixPath(*traversed).as_posix())
                child = os.open(part, flags, dir_fd=descriptor)
            except OSError as exc:
                raise ApplyPathError("target-parent", "planned target parent is not a safe directory") from exc
            os.close(descriptor)
            descriptor = child
        return descriptor, created
    except Exception:
        os.close(descriptor)
        raise


def _require_directory_descriptor_current(
    root_descriptor: int,
    parts: Sequence[str],
    descriptor: int,
) -> None:
    current = _open_directory_chain(root_descriptor, parts, create=False)[0]
    try:
        current_stat = os.fstat(current)
        held_stat = os.fstat(descriptor)
        if (current_stat.st_dev, current_stat.st_ino) != (held_stat.st_dev, held_stat.st_ino):
            raise ApplyFingerprintError("target-parent-drift", "target parent directory was replaced")
    finally:
        os.close(current)


def _create_planned_directories(
    target: Path,
    root_descriptor: int,
    plan: Mapping[str, Any],
    report: dict[str, Any],
    report_path: Path,
    state_root: Path,
    key: bytes,
) -> None:
    expected = list(plan["target"]["missingDirectories"])
    root_fingerprint = plan["target"]["rootFingerprint"]
    actual = _missing_parent_directories_bound(
        target,
        root_descriptor,
        root_fingerprint,
        PROJECT_FRAME_PATHS,
    )
    if actual != expected:
        raise ApplyFingerprintError("target-directory-fingerprint", "target parent directories changed")
    for relative in sorted(expected, key=lambda item: (item.count("/"), item)):
        path = PurePosixPath(relative)
        _test_barrier("before-directory-create", path=relative)
        _require_root_fingerprint(target, root_descriptor, root_fingerprint)
        parent_descriptor = _open_directory_chain(root_descriptor, path.parts[:-1], create=False)[0]
        try:
            try:
                os.mkdir(path.name, 0o755, dir_fd=parent_descriptor)
            except FileExistsError as exc:
                raise ApplyFingerprintError(
                    "target-directory-fingerprint",
                    "target parent appeared during apply",
                ) from exc
            os.fsync(parent_descriptor)
            metadata = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
            if not stat.S_ISDIR(metadata.st_mode):
                raise ApplyPathError("target-parent", "created frame parent is not a directory")
            identity = {
                "path": relative,
                "device": metadata.st_dev,
                "inode": metadata.st_ino,
            }
            _test_barrier("after-directory-create-before-journal", path=relative, identity=identity)
            report["createdDirectories"].append(identity)
            _write_report(report_path, report, state_root, key)
        finally:
            os.close(parent_descriptor)
        _require_root_fingerprint(target, root_descriptor, root_fingerprint)
        _test_barrier("after-directory-journal", path=relative, identity=identity)
        _test_barrier("after-directory-create", path=relative)
    if _missing_parent_directories(root_descriptor, PROJECT_FRAME_PATHS):
        raise ApplyExecutionError("target-directory-create", "canonical frame parents were not created")


def _write_planned_files(
    target: Path,
    root_descriptor: int,
    plan: Mapping[str, Any],
    report: Mapping[str, Any],
) -> None:
    backups = {item["path"]: _state_from_backup(item) for item in report["backups"]}
    artifacts = {item["path"]: item for item in report["temporaryArtifacts"]}
    for item in plan["files"]:
        previous = backups[item["path"]]
        if item["action"] == "no-change":
            if _read_file_state(root_descriptor, item["path"]) != previous:
                raise ApplyFingerprintError("pre-write-verification", "no-change target drifted")
            continue
        content = _decode_bytes(item["contentBase64"], "planned file content")
        _atomic_replace_file(
            target,
            root_descriptor,
            plan["target"]["rootFingerprint"],
            item["path"],
            content,
            int(item["mode"], 8),
            expected=previous,
            temporary_name=artifacts[item["path"]]["applyName"],
        )
        _require_file_state(
            _read_file_state(root_descriptor, item["path"]),
            exists=True,
            content=content,
            mode=int(item["mode"], 8),
            code="post-write-verification",
        )
        _test_barrier("after-file-replace", path=item["path"])


def _atomic_replace_file(
    target: Path,
    root_descriptor: int,
    root_fingerprint: str,
    relative: str,
    content: bytes,
    mode: int,
    *,
    expected: _FileState,
    temporary_name: str,
) -> None:
    path = PurePosixPath(_relative_path(relative, "target file path"))
    try:
        parent_descriptor = _open_directory_chain(root_descriptor, path.parts[:-1], create=False)[0]
    except FileNotFoundError as exc:
        raise ApplyPathError("target-parent", "planned target parent is missing") from exc
    if _TEMPORARY_NAME.fullmatch(temporary_name) is None:
        raise ApplyPlanError("report-temporary-artifact", "temporary artifact name is invalid")
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(
            temporary_name,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
            dir_fd=parent_descriptor,
        )
        os.fsync(parent_descriptor)
        _test_barrier("after-temp-create", path=relative, temporaryName=temporary_name)
        _write_all(descriptor, content)
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        _test_barrier("before-file-compare", path=relative)
        _require_root_fingerprint(target, root_descriptor, root_fingerprint)
        _require_directory_descriptor_current(root_descriptor, path.parts[:-1], parent_descriptor)
        if _read_file_state_at(parent_descriptor, path.name) != expected:
            raise ApplyFingerprintError(
                "target-file-toctou",
                "target file changed immediately before atomic replacement",
            )
        os.replace(
            temporary_name,
            path.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        os.fsync(parent_descriptor)
        _require_root_fingerprint(target, root_descriptor, root_fingerprint)
        _require_directory_descriptor_current(root_descriptor, path.parts[:-1], parent_descriptor)
    except ApplyGateError:
        raise
    except OSError as exc:
        raise ApplyExecutionError("atomic-write", "atomic target write failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=parent_descriptor)
        except FileNotFoundError:
            pass
        os.close(parent_descriptor)


def _delete_file(
    target: Path,
    root_descriptor: int,
    root_fingerprint: str,
    relative: str,
    *,
    expected: _FileState,
) -> None:
    path = PurePosixPath(_relative_path(relative, "target file path"))
    try:
        parent_descriptor = _open_directory_chain(root_descriptor, path.parts[:-1], create=False)[0]
    except FileNotFoundError:
        if expected.exists:
            raise ApplyRollbackError("rollback-drift", "rollback target parent disappeared")
        return
    try:
        _test_barrier("before-file-delete", path=relative)
        _require_root_fingerprint(target, root_descriptor, root_fingerprint)
        _require_directory_descriptor_current(root_descriptor, path.parts[:-1], parent_descriptor)
        if _read_file_state_at(parent_descriptor, path.name) != expected:
            raise ApplyRollbackError("rollback-drift", "rollback target changed before deletion")
        os.unlink(path.name, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)
        _require_root_fingerprint(target, root_descriptor, root_fingerprint)
    except ApplyGateError:
        raise
    except OSError as exc:
        raise ApplyRollbackError("rollback-delete", "rollback could not remove a created file") from exc
    finally:
        os.close(parent_descriptor)


def _cleanup_journaled_temporary_artifacts(
    target: Path,
    root_descriptor: int,
    report: Mapping[str, Any],
) -> None:
    root_fingerprint = report["plan"]["target"]["rootFingerprint"]
    for artifact in report["temporaryArtifacts"]:
        path = PurePosixPath(artifact["path"])
        try:
            parent_descriptor = _open_directory_chain(root_descriptor, path.parts[:-1], create=False)[0]
        except FileNotFoundError:
            continue
        try:
            for field in ("applyName", "rollbackName"):
                name = artifact[field]
                try:
                    metadata = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                    raise ApplyRollbackError(
                        "temporary-artifact-ambiguous",
                        "journaled target temporary artifact changed type and was left in place",
                    )
                _require_root_fingerprint(target, root_descriptor, root_fingerprint)
                _require_directory_descriptor_current(
                    root_descriptor,
                    path.parts[:-1],
                    parent_descriptor,
                )
                os.unlink(name, dir_fd=parent_descriptor)
                os.fsync(parent_descriptor)
                _test_barrier("after-temp-cleanup", path=artifact["path"], temporaryName=name)
        except ApplyGateError:
            raise
        except OSError as exc:
            raise ApplyRollbackError(
                "temporary-artifact-cleanup",
                "journaled target temporary artifact could not be removed",
            ) from exc
        finally:
            os.close(parent_descriptor)


def _restore_backup(target: Path, root_descriptor: int, report: Mapping[str, Any]) -> None:
    plan = report["plan"]
    root_fingerprint = plan["target"]["rootFingerprint"]
    _require_recoverable_files(root_descriptor, report)
    artifacts = {item["path"]: item for item in report["temporaryArtifacts"]}
    pairs = list(zip(plan["files"], report["backups"]))
    for item, backup in reversed(pairs):
        actual = _read_file_state(root_descriptor, item["path"])
        planned = _state_from_planned_file(item)
        previous = _state_from_backup(backup)
        if actual == previous:
            continue
        if actual != planned:
            raise ApplyRollbackError("rollback-drift", "rollback target contains unrelated file drift")
        if previous.exists:
            _atomic_replace_file(
                target,
                root_descriptor,
                root_fingerprint,
                item["path"],
                previous.content or b"",
                previous.mode if previous.mode is not None else 0o600,
                expected=planned,
                temporary_name=artifacts[item["path"]]["rollbackName"],
            )
        else:
            _delete_file(
                target,
                root_descriptor,
                root_fingerprint,
                item["path"],
                expected=planned,
            )
        _test_barrier("after-rollback-file", path=item["path"])
    for identity in reversed(report["createdDirectories"]):
        _remove_empty_directory(target, root_descriptor, root_fingerprint, identity)


def _remove_empty_directory(
    target: Path,
    root_descriptor: int,
    root_fingerprint: str,
    identity: Mapping[str, Any],
) -> None:
    relative = identity["path"]
    path = PurePosixPath(_relative_path(relative, "created directory"))
    try:
        parent_descriptor = _open_directory_chain(root_descriptor, path.parts[:-1], create=False)[0]
    except FileNotFoundError:
        return
    try:
        _require_root_fingerprint(target, root_descriptor, root_fingerprint)
        _require_directory_descriptor_current(root_descriptor, path.parts[:-1], parent_descriptor)
        try:
            metadata = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            return
        if (metadata.st_dev, metadata.st_ino) != (identity["device"], identity["inode"]):
            return
        os.rmdir(path.name, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)
        _require_root_fingerprint(target, root_descriptor, root_fingerprint)
    except ApplyGateError:
        raise
    except OSError as exc:
        if exc.errno in {errno.ENOTEMPTY, errno.EEXIST}:
            return
        raise ApplyRollbackError(
            "rollback-directory",
            "rollback could not remove an exact canonical frame directory",
        ) from exc
    finally:
        os.close(parent_descriptor)


def _verify_planned_files(root_descriptor: int, plan: Mapping[str, Any]) -> None:
    for item in plan["files"]:
        _require_file_state(
            _read_file_state(root_descriptor, item["path"]),
            exists=True,
            content=_decode_bytes(item["contentBase64"], "planned file content"),
            mode=int(item["mode"], 8),
            code="post-write-verification",
        )


def _verify_planned_files_bound(target: Path, root_descriptor: int, plan: Mapping[str, Any]) -> None:
    root_fingerprint = plan["target"]["rootFingerprint"]
    _require_root_fingerprint(target, root_descriptor, root_fingerprint)
    _verify_planned_files(root_descriptor, plan)
    _require_root_fingerprint(target, root_descriptor, root_fingerprint)


def _planned_files_match_bound(target: Path, root_descriptor: int, plan: Mapping[str, Any]) -> bool:
    try:
        _verify_planned_files_bound(target, root_descriptor, plan)
    except ApplyGateError:
        return False
    return True


def _verify_backup(root_descriptor: int, report: Mapping[str, Any]) -> None:
    for backup in report["backups"]:
        expected = _state_from_backup(backup)
        _require_file_state(
            _read_file_state(root_descriptor, backup["path"]),
            exists=expected.exists,
            content=expected.content,
            mode=expected.mode,
            code="rollback-verification",
        )


def _verify_backup_bound(target: Path, root_descriptor: int, report: Mapping[str, Any]) -> None:
    root_fingerprint = report["plan"]["target"]["rootFingerprint"]
    _require_root_fingerprint(target, root_descriptor, root_fingerprint)
    _verify_backup(root_descriptor, report)
    _require_root_fingerprint(target, root_descriptor, root_fingerprint)


def _backup_matches_bound(target: Path, root_descriptor: int, report: Mapping[str, Any]) -> bool:
    try:
        _verify_backup_bound(target, root_descriptor, report)
    except ApplyGateError:
        return False
    return True


def _verify_created_directories_restored(
    root_descriptor: int,
    plan: Mapping[str, Any],
) -> None:
    for relative in plan["target"]["missingDirectories"]:
        path = PurePosixPath(relative)
        try:
            descriptor = _open_directory_chain(root_descriptor, path.parts, create=False)[0]
        except FileNotFoundError:
            continue
        else:
            os.close(descriptor)
            raise ApplyRollbackError(
                "rollback-directory-drift",
                "a planned-missing directory remains but its P5 identity is not removable",
            )


def _created_directories_restored_match(
    root_descriptor: int,
    plan: Mapping[str, Any],
) -> bool:
    try:
        _verify_created_directories_restored(root_descriptor, plan)
    except ApplyGateError:
        return False
    return True


def _created_directory_identities_match(
    root_descriptor: int,
    report: Mapping[str, Any],
) -> bool:
    for identity in report["createdDirectories"]:
        path = PurePosixPath(identity["path"])
        try:
            descriptor = _open_directory_chain(root_descriptor, path.parts, create=False)[0]
        except (FileNotFoundError, ApplyGateError):
            return False
        try:
            metadata = os.fstat(descriptor)
            if (metadata.st_dev, metadata.st_ino) != (identity["device"], identity["inode"]):
                return False
        finally:
            os.close(descriptor)
    return True


def _require_recoverable_files(root_descriptor: int, report: Mapping[str, Any]) -> None:
    for item, backup in zip(report["plan"]["files"], report["backups"]):
        actual = _read_file_state(root_descriptor, item["path"])
        planned = _state_from_planned_file(item)
        previous = _state_from_backup(backup)
        if actual != planned and actual != previous:
            raise ApplyRollbackError("rollback-drift", "interrupted apply contains unrelated file drift")


def _state_from_planned_file(item: Mapping[str, Any]) -> _FileState:
    return _FileState(
        True,
        _decode_bytes(item["contentBase64"], "planned file content"),
        int(item["mode"], 8),
    )


def _state_from_backup(backup: Mapping[str, Any]) -> _FileState:
    if not backup["previousExists"]:
        return _FileState(False, None, None)
    return _FileState(
        True,
        _decode_bytes(backup["previousContentBase64"], "backup content"),
        int(backup["previousMode"], 8),
    )


def _require_file_state(
    actual: _FileState,
    *,
    exists: bool,
    content: Optional[bytes],
    mode: Optional[int],
    code: str,
) -> None:
    if actual.exists != exists or actual.content != content or actual.mode != mode:
        raise ApplyFingerprintError(code, "target file bytes or mode do not match the required state")


def _require_plan_previous_matches(plan: Mapping[str, Any], states: Mapping[str, _FileState]) -> None:
    for item in plan["files"]:
        if states[item["path"]].as_plan_previous() != item["previous"]:
            raise ApplyFingerprintError("target-state-fingerprint", "target file state changed after planning")


def _build_backup_report(
    plan: Mapping[str, Any],
    grant: Mapping[str, Any],
    states: Mapping[str, _FileState],
    timestamp: str,
    key: bytes,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schemaVersion": APPLY_REPORT_SCHEMA_VERSION,
        "reportId": plan["planId"],
        "status": "rollback-in-progress",
        "startedAt": timestamp,
        "completedAt": None,
        "failureCode": None,
        "rollbackFailureCode": None,
        "postApplyGitStatusBase64": None,
        "postApplyGitStatusSha256": None,
        "targetLockId": _target_lock_id(plan),
        "createdDirectories": [],
        "temporaryArtifacts": _temporary_artifact_records(plan, key),
        "grant": copy.deepcopy(dict(grant)),
        "plan": copy.deepcopy(dict(plan)),
        "backups": [states[item["path"]].as_backup(item["path"]) for item in plan["files"]],
    }
    return _seal_report(report, key)


def _temporary_artifact_records(
    plan: Mapping[str, Any],
    key: bytes,
) -> list[dict[str, str]]:
    return [
        {
            "path": item["path"],
            "applyName": _temporary_artifact_name(plan, item["path"], "apply", key),
            "rollbackName": _temporary_artifact_name(plan, item["path"], "rollback", key),
        }
        for item in plan["files"]
    ]


def _temporary_artifact_name(
    plan: Mapping[str, Any],
    relative: str,
    phase: str,
    key: bytes,
) -> str:
    if phase not in {"apply", "rollback"}:
        raise ApplyPlanError("report-temporary-artifact", "temporary artifact phase is invalid")
    token = _mac_json(
        key,
        "plzdo-local.target-temporary-artifact.v1",
        {
            "planFingerprint": plan["planFingerprint"],
            "path": relative,
            "phase": phase,
        },
    )[:24]
    return f".plzdo-{phase}-{token}"


def _validate_created_directories(value: Any, plan: Mapping[str, Any]) -> None:
    if not isinstance(value, list):
        raise ApplyPlanError("report-directories", "createdDirectories must be an array")
    ordered = sorted(
        plan["target"]["missingDirectories"],
        key=lambda item: (item.count("/"), item),
    )
    paths: list[str] = []
    for index, raw in enumerate(value):
        label = f"apply report createdDirectories[{index}]"
        item = _object(raw, label)
        _exact_keys(item, {"path", "device", "inode"}, label)
        path = _relative_path(item["path"], f"{label}.path")
        for field in ("device", "inode"):
            if type(item[field]) is not int or item[field] < 0:
                raise ApplyPlanError(
                    "report-directories",
                    f"{label}.{field} must be a non-negative integer",
                )
        paths.append(path)
    if paths != ordered[: len(paths)]:
        raise ApplyPlanError(
            "report-directories",
            "createdDirectories must be an ordered prefix of planned frame parents",
        )


def _validate_temporary_artifacts(
    value: Any,
    plan: Mapping[str, Any],
    key: bytes,
) -> None:
    if not isinstance(value, list) or len(value) != len(plan["files"]):
        raise ApplyPlanError(
            "report-temporary-artifact",
            "temporary artifact journal must cover the complete frame",
        )
    expected = _temporary_artifact_records(plan, key)
    for index, raw in enumerate(value):
        label = f"apply report temporaryArtifacts[{index}]"
        item = _object(raw, label)
        _exact_keys(item, {"path", "applyName", "rollbackName"}, label)
        if item != expected[index]:
            raise ApplyPlanError(
                "report-temporary-artifact",
                "temporary artifact identity is not bound to the report plan",
            )
        for field in ("applyName", "rollbackName"):
            if _TEMPORARY_NAME.fullmatch(item[field]) is None:
                raise ApplyPlanError(
                    "report-temporary-artifact",
                    f"{label}.{field} is invalid",
                )


def _seal_report(report: Mapping[str, Any], key: bytes) -> dict[str, Any]:
    sealed = copy.deepcopy(dict(report))
    sealed.pop("reportFingerprint", None)
    sealed.pop("reportMac", None)
    sealed["reportFingerprint"] = _json_fingerprint(sealed)
    sealed["reportMac"] = _mac_json(key, "plzdo-local.apply-report.v2", sealed)
    _validate_report(sealed, key)
    return sealed


def _validate_report(value: Any, key: bytes) -> None:
    report = _object(value, "apply report")
    _exact_keys(
        report,
        {
            "schemaVersion",
            "reportId",
            "reportFingerprint",
            "reportMac",
            "status",
            "startedAt",
            "completedAt",
            "failureCode",
            "rollbackFailureCode",
            "postApplyGitStatusBase64",
            "postApplyGitStatusSha256",
            "targetLockId",
            "createdDirectories",
            "temporaryArtifacts",
            "grant",
            "plan",
            "backups",
        },
        "apply report",
    )
    if report["schemaVersion"] != APPLY_REPORT_SCHEMA_VERSION:
        raise ApplyPlanError("report-schema", "apply report schemaVersion is unsupported")
    _require_match(report["reportId"], _PLAN_ID, "apply report reportId")
    _require_match(report["reportFingerprint"], _SHA256, "apply report reportFingerprint")
    _require_match(report["reportMac"], _SHA256, "apply report reportMac")
    if report["status"] not in _REPORT_STATUSES:
        raise ApplyPlanError("report-status", "apply report status is unsupported")
    _require_timestamp(report["startedAt"], "apply report startedAt")
    if report["completedAt"] is not None:
        _require_timestamp(report["completedAt"], "apply report completedAt")
    for field in ("failureCode", "rollbackFailureCode"):
        if report[field] is not None:
            _require_match(report[field], _SAFE_ID, f"apply report {field}")
    if report["postApplyGitStatusBase64"] is None:
        if report["postApplyGitStatusSha256"] is not None:
            raise ApplyPlanError("report-git-status", "apply report Git status fields disagree")
    else:
        status_bytes = _decode_bytes(report["postApplyGitStatusBase64"], "apply report Git status")
        if len(status_bytes) > MAX_GIT_OUTPUT_BYTES:
            raise ApplyPlanError("report-git-status", "apply report Git status exceeds the byte limit")
        _require_match(report["postApplyGitStatusSha256"], _SHA256, "apply report Git status hash")
        if _sha256(status_bytes) != report["postApplyGitStatusSha256"]:
            raise ApplyPlanError("report-git-status", "apply report Git status fingerprint is invalid")
    validate_apply_plan(report["plan"])
    plan = report["plan"]
    if report["reportId"] != plan["planId"]:
        raise ApplyPlanError("report-plan", "apply report is not bound to its plan")
    _require_match(report["targetLockId"], _SHA256, "apply report targetLockId")
    if report["targetLockId"] != _target_lock_id(plan):
        raise ApplyPlanError("report-target-lock", "apply report target lock binding is invalid")
    _validate_created_directories(report["createdDirectories"], plan)
    if report["status"] == "applied" and len(report["createdDirectories"]) != len(
        plan["target"]["missingDirectories"]
    ):
        raise ApplyPlanError(
            "report-directories",
            "an applied report must identify every P5-created frame parent",
        )
    _validate_temporary_artifacts(report["temporaryArtifacts"], plan, key)
    _validate_authorization_grant(report["grant"], key)
    _require_authorization_binding(report["grant"], plan)
    backups = report["backups"]
    if not isinstance(backups, list) or len(backups) != len(plan["files"]):
        raise ApplyPlanError("report-backups", "apply report backup set is incomplete")
    for index, backup in enumerate(backups):
        _validate_backup(backup, plan["files"][index], index)
    unsealed = dict(report)
    supplied_mac = unsealed.pop("reportMac")
    expected_mac = _mac_json(key, "plzdo-local.apply-report.v2", unsealed)
    if not hmac.compare_digest(supplied_mac, expected_mac):
        raise ApplyPlanError("report-mac", "apply report MAC is invalid")
    supplied_fingerprint = unsealed.pop("reportFingerprint")
    if supplied_fingerprint != _json_fingerprint(unsealed):
        raise ApplyPlanError("report-fingerprint", "apply report fingerprint is invalid")
    _require_json_bound(report, MAX_REPORT_BYTES, "apply report")


def _validate_backup(value: Any, planned: Mapping[str, Any], index: int) -> None:
    label = f"apply report backups[{index}]"
    backup = _object(value, label)
    _exact_keys(
        backup,
        {
            "path",
            "previousExists",
            "previousMode",
            "previousBytes",
            "previousSha256",
            "previousContentBase64",
        },
        label,
    )
    if backup["path"] != planned["path"]:
        raise ApplyPlanError("report-backup-path", "apply report backup order differs from its plan")
    if type(backup["previousExists"]) is not bool:
        raise ApplyPlanError("report-backup", f"{label}.previousExists must be a boolean")
    if backup["previousExists"]:
        _require_match(backup["previousMode"], _MODE, f"{label}.previousMode")
        if (
            type(backup["previousBytes"]) is not int
            or backup["previousBytes"] < 0
            or backup["previousBytes"] > MAX_TARGET_FILE_BYTES
        ):
            raise ApplyPlanError("report-backup", f"{label}.previousBytes is invalid")
        _require_match(backup["previousSha256"], _SHA256, f"{label}.previousSha256")
        content = _decode_bytes(backup["previousContentBase64"], f"{label}.previousContentBase64")
        if len(content) != backup["previousBytes"] or _sha256(content) != backup["previousSha256"]:
            raise ApplyPlanError("report-backup", f"{label} exact bytes do not match their metadata")
    elif any(
        backup[field] is not None
        for field in ("previousMode", "previousBytes", "previousSha256", "previousContentBase64")
    ):
        raise ApplyPlanError("report-backup", f"{label} absent state must use null metadata")
    if backup["previousExists"] != planned["previous"]["exists"]:
        raise ApplyPlanError("report-backup", f"{label} existence differs from the plan")
    for report_field, plan_field in (
        ("previousMode", "mode"),
        ("previousBytes", "bytes"),
        ("previousSha256", "sha256"),
    ):
        if backup[report_field] != planned["previous"][plan_field]:
            raise ApplyPlanError("report-backup", f"{label} metadata differs from the plan")


def _write_report(
    path: Path,
    report: Mapping[str, Any],
    state_root: Path,
    key: bytes,
) -> None:
    sealed = _seal_report(report, key)
    atomic_write_json(
        path,
        sealed,
        allowed_root=state_root,
        validator=lambda value: _validate_report(value, key),
    )
    _require_private_file(path, "apply report")


def _best_effort_report(
    path: Path,
    report: Mapping[str, Any],
    state_root: Path,
    key: bytes,
) -> None:
    try:
        _write_report(path, report, state_root, key)
    except Exception:
        return


def _read_canonical_report(
    path: Path,
    state_root: Path,
    key: bytes,
) -> tuple[Path, dict[str, Any]]:
    evidence = _private_directory(state_root, "real-apply", "evidence", create=False)
    if not path.is_absolute() or path.is_symlink():
        raise ApplyPathError("report-path", "apply report path must be an absolute non-symlink")
    try:
        report_file = ensure_contained(path, evidence, label="canonical apply report").resolve(strict=True)
    except (OSError, PathPolicyError) as exc:
        raise ApplyPathError("report-path", "apply report is outside canonical evidence state") from exc
    report = _read_json_file(report_file, MAX_REPORT_BYTES, "apply report")
    _validate_report(report, key)
    expected = _report_path(state_root, report["plan"], create_parent=False).resolve(strict=False)
    if report_file != expected:
        raise ApplyPathError("report-path", "apply report does not have its canonical target/plan path")
    _require_private_file(report_file, "apply report")
    return report_file, report


def _require_private_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ApplyPathError("private-state", f"{label} is unavailable") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise ApplyPolicyError("private-state-permissions", f"{label} must be an owner-only regular file")


def _write_new_json(
    path: Path,
    value: Any,
    state_root: Path,
    *,
    validator: Any,
) -> None:
    validator(value)
    path = ensure_contained(path, state_root, label="new real-apply state")
    temporary = path.parent / f".{path.name}.{secrets.token_hex(12)}"
    encoded = (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(temporary, flags, 0o600)
        _write_all(descriptor, encoded)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        if path.exists() or path.is_symlink():
            raise ApplyAuthorizationError("state-exists", "real-apply state already exists")
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    _require_private_file(path, "real-apply state file")


def _read_json_file(path: Path, maximum: int, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise ApplyPathError("state-symlink", f"{label} must not be a symlink")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ApplyPathError("state-open", f"{label} is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
            raise ApplyPathError("state-file", f"{label} must be a bounded regular file")
        raw = _read_bounded(descriptor, maximum)
    finally:
        os.close(descriptor)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ApplyPlanError("state-json", f"{label} is not valid exact JSON") from exc
    if not isinstance(value, dict):
        raise ApplyPlanError("state-json", f"{label} must be a JSON object")
    return value


def _git_repository_identity_bound(
    target: Path,
    root_descriptor: int,
    root_fingerprint: str,
) -> dict[str, Any]:
    root_output = _run_git_bound(target, root_descriptor, root_fingerprint, "root")
    try:
        root_text = root_output.decode("utf-8").rstrip("\n")
    except UnicodeDecodeError as exc:
        raise ApplyGitError("git-root", "Git returned a non-UTF-8 worktree root") from exc
    if "\n" in root_text or not root_text:
        raise ApplyGitError("git-root", "Git returned an invalid worktree root")
    try:
        git_root = Path(root_text).resolve(strict=True)
    except OSError as exc:
        raise ApplyGitError("git-root", "Git worktree root is unavailable") from exc
    if git_root != target:
        raise ApplyGitError("git-root", "catalog target must be the Git worktree root")
    return {
        "topLevel": str(git_root),
        "gitDirectory": _git_directory_identity_bound(
            target,
            root_descriptor,
            root_fingerprint,
            "git-dir",
        ),
        "commonDirectory": _git_directory_identity_bound(
            target,
            root_descriptor,
            root_fingerprint,
            "git-common-dir",
        ),
    }


def _git_directory_identity_bound(
    target: Path,
    root_descriptor: int,
    root_fingerprint: str,
    operation: str,
) -> dict[str, Any]:
    output = _run_git_bound(target, root_descriptor, root_fingerprint, operation)
    try:
        text = output.decode("utf-8").rstrip("\n")
        if not text or "\n" in text:
            raise ValueError("invalid Git metadata path")
        candidate = Path(text)
        directory = (candidate if candidate.is_absolute() else target / candidate).resolve(strict=True)
        metadata = directory.lstat()
    except (UnicodeDecodeError, OSError, ValueError) as exc:
        raise ApplyGitError("git-dir", "Git metadata directory is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ApplyGitError("git-dir", "Git metadata path must be a real directory")
    return {
        "path": str(directory),
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
    }


def _require_git_repository_binding_bound(
    target: Path,
    root_descriptor: int,
    root_fingerprint: str,
    expected: Mapping[str, Any],
) -> None:
    actual = _require_safe_git_configuration_bound(target, root_descriptor, root_fingerprint)
    if actual != expected:
        raise ApplyFingerprintError(
            "git-identity-drift",
            "Git worktree or metadata directory identity changed after planning",
        )


def _git_head_bound(target: Path, root_descriptor: int, root_fingerprint: str) -> str:
    output = _run_git_bound(target, root_descriptor, root_fingerprint, "head")
    try:
        head = output.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ApplyGitError("git-head", "Git HEAD is not ASCII") from exc
    if _GIT_HEAD.fullmatch(head) is None:
        raise ApplyGitError("git-head", "Git HEAD is missing or invalid")
    return head


def _require_git_head_bound(
    target: Path,
    root_descriptor: int,
    root_fingerprint: str,
    expected: str,
) -> None:
    if _git_head_bound(target, root_descriptor, root_fingerprint) != expected:
        raise ApplyFingerprintError("target-head-drift", "Git HEAD changed after apply planning")


def _git_status_bound(
    target: Path,
    root_descriptor: int,
    root_fingerprint: str,
    expected_git_identity: Mapping[str, Any],
) -> bytes:
    _require_git_repository_binding_bound(
        target,
        root_descriptor,
        root_fingerprint,
        expected_git_identity,
    )
    return _run_git_bound(target, root_descriptor, root_fingerprint, "status")


def _require_clean_git_bound(
    target: Path,
    root_descriptor: int,
    root_fingerprint: str,
    expected_git_identity: Mapping[str, Any],
) -> None:
    if _git_status_bound(target, root_descriptor, root_fingerprint, expected_git_identity) != b"":
        raise ApplyGitError("dirty-git", "target Git worktree must be clean")


def _require_safe_git_configuration_bound(
    target: Path,
    root_descriptor: int,
    root_fingerprint: str,
) -> dict[str, Any]:
    keys_output = _run_git_bound(target, root_descriptor, root_fingerprint, "config-keys")
    if keys_output and not keys_output.endswith(b"\0"):
        raise ApplyGitError("git-config-format", "Git config key output is malformed")
    for raw_key in keys_output.split(b"\0"):
        if not raw_key:
            continue
        try:
            key = raw_key.decode("utf-8").lower()
        except UnicodeDecodeError as exc:
            raise ApplyGitError("git-config-encoding", "repository Git config keys must be UTF-8") from exc
        if _git_key_can_start_process(key):
            raise ApplyGitError(
                "git-process-config",
                "repository-local process or worktree-redirection configuration is forbidden",
            )

    index_output = _run_git_bound(target, root_descriptor, root_fingerprint, "index-entries")
    _reject_gitlinks(index_output)

    paths_output = _run_git_bound(target, root_descriptor, root_fingerprint, "all-paths")
    paths_output += _run_git_bound(target, root_descriptor, root_fingerprint, "ignored-paths")
    if paths_output and not paths_output.endswith(b"\0"):
        raise ApplyGitError("git-path-format", "Git path inventory is malformed")
    for raw_path in paths_output.split(b"\0"):
        if not raw_path:
            continue
        try:
            relative = raw_path.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ApplyGitError("git-path-encoding", "Git path inventory must be UTF-8") from exc
        if PurePosixPath(relative).name == ".gitattributes":
            raise ApplyGitError(
                "git-attributes-forbidden",
                "repository .gitattributes files are forbidden before real apply status checks",
            )

    identity = _git_repository_identity_bound(target, root_descriptor, root_fingerprint)
    git_directories = {
        Path(identity["gitDirectory"]["path"]),
        Path(identity["commonDirectory"]["path"]),
    }
    for git_directory in git_directories:
        info_attributes = git_directory / "info" / "attributes"
        if info_attributes.exists() or info_attributes.is_symlink():
            raise ApplyGitError(
                "git-attributes-forbidden",
                "repository info/attributes is forbidden before real apply status checks",
            )
    _require_root_fingerprint(target, root_descriptor, root_fingerprint)
    return identity


def _reject_gitlinks(output: bytes) -> None:
    if output and not output.endswith(b"\0"):
        raise ApplyGitError("git-index-format", "Git index inventory is malformed")
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            metadata, path = record.split(b"\t", 1)
            mode, object_id, stage = metadata.split(b" ")
        except ValueError as exc:
            raise ApplyGitError("git-index-format", "Git index inventory is malformed") from exc
        try:
            object_text = object_id.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ApplyGitError("git-index-format", "Git index inventory is malformed") from exc
        if (
            _GIT_INDEX_MODE.fullmatch(mode) is None
            or _GIT_HEAD.fullmatch(object_text) is None
            or stage not in {b"0", b"1", b"2", b"3"}
            or not path
        ):
            raise ApplyGitError("git-index-format", "Git index inventory is malformed")
        if mode == b"160000":
            raise ApplyGitError("gitlink-forbidden", "Gitlinks and submodules are forbidden for real apply")


def _git_key_can_start_process(key: str) -> bool:
    if key in _DANGEROUS_GIT_KEYS:
        return True
    if key == "include.path" or key.startswith("includeif.") or key.startswith("alias."):
        return True
    if key.startswith("filter."):
        return True
    return key.endswith((".clean", ".smudge", ".process", ".external", ".textconv", ".command"))


def _run_git_bound(
    target: Path,
    root_descriptor: int,
    root_fingerprint: str,
    operation: str,
) -> bytes:
    _test_barrier(f"before-git-{operation}", operation=operation)
    _require_root_fingerprint(target, root_descriptor, root_fingerprint)
    output = _run_git(target, operation)
    _require_root_fingerprint(target, root_descriptor, root_fingerprint)
    _test_barrier(f"after-git-{operation}", operation=operation)
    return output


def _run_git(target: Path, operation: str) -> bytes:
    suffixes = {
        "root": ("rev-parse", "--show-toplevel"),
        "git-dir": ("rev-parse", "--absolute-git-dir"),
        "git-common-dir": ("rev-parse", "--git-common-dir"),
        "head": ("rev-parse", "--verify", "HEAD"),
        "config-keys": (
            "config",
            "--local",
            "--no-includes",
            "--name-only",
            "--null",
            "--list",
        ),
        "index-entries": ("ls-files", "--stage", "-z"),
        "all-paths": (
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ),
        "ignored-paths": (
            "ls-files",
            "-z",
            "--others",
            "--ignored",
            "--exclude-standard",
        ),
        "status": ("status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=all"),
    }
    if operation not in suffixes:
        raise ApplyGitError("git-operation", "unsupported Git operation")
    if not GIT_EXECUTABLE:
        raise ApplyGitError("git-unavailable", "Git executable was not found on the system path")
    argv = [
        GIT_EXECUTABLE,
        "-c",
        f"core.hooksPath={os.devnull}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "diff.external=",
        "-c",
        f"core.attributesFile={os.devnull}",
        "-c",
        "submodule.recurse=false",
        "-C",
        str(target),
        *suffixes[operation],
    ]
    environment = {
        "PATH": os.defpath,
        "HOME": "/var/empty" if os.name == "posix" else str(Path.home()),
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
    }
    popen_kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": environment,
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    elif os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        process = subprocess.Popen(argv, **popen_kwargs)
    except OSError as exc:
        raise ApplyGitError("git-unavailable", "local Git operation failed") from exc
    process_group_id = process.pid if os.name == "posix" else None

    stdout_parts: list[bytes] = []
    stderr_parts: list[bytes] = []
    overflow = threading.Event()
    stdout_thread = threading.Thread(
        target=_drain_bounded_stream,
        args=(process.stdout, stdout_parts, overflow),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_drain_bounded_stream,
        args=(process.stderr, stderr_parts, overflow),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    deadline = time.monotonic() + GIT_TIMEOUT_SECONDS
    timed_out = False
    while process.poll() is None:
        if overflow.is_set():
            _kill_process_group(process, process_group_id)
            break
        if time.monotonic() >= deadline:
            timed_out = True
            _kill_process_group(process, process_group_id)
            break
        time.sleep(0.01)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        _kill_process_group(process, process_group_id)
        process.wait(timeout=2)
    if os.name == "posix":
        _kill_process_group(process, process_group_id)
    stdout_thread.join(timeout=2)
    stderr_thread.join(timeout=2)
    if stdout_thread.is_alive() or stderr_thread.is_alive():
        _kill_process_group(process, process_group_id)
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)
        raise ApplyGitError("git-output", "Git output readers did not terminate")
    stdout = b"".join(stdout_parts)
    stderr = b"".join(stderr_parts)
    if overflow.is_set() or len(stdout) > MAX_GIT_OUTPUT_BYTES or len(stderr) > MAX_GIT_OUTPUT_BYTES:
        raise ApplyGitError("git-output", "local Git output exceeded the byte limit")
    if timed_out:
        raise ApplyGitError("git-timeout", "local Git operation exceeded its timeout")
    if process.returncode != 0:
        raise ApplyGitError("git-failed", "target is not a usable local Git worktree")
    return stdout


def _drain_bounded_stream(stream: Any, chunks: list[bytes], overflow: threading.Event) -> None:
    if stream is None:
        return
    total = 0
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            remaining = MAX_GIT_OUTPUT_BYTES + 1 - total
            if remaining > 0:
                chunks.append(chunk[:remaining])
            total += len(chunk)
            if total > MAX_GIT_OUTPUT_BYTES:
                overflow.set()
                return
    finally:
        stream.close()


def _kill_process_group(process: subprocess.Popen[Any], process_group_id: Optional[int]) -> None:
    try:
        if os.name == "posix" and process_group_id is not None:
            os.killpg(process_group_id, signal.SIGKILL)
        elif os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
            if process.poll() is not None:
                return
            process.send_signal(signal.CTRL_BREAK_EVENT)
            time.sleep(0.05)
            if process.poll() is None:
                process.kill()
        else:
            if process.poll() is not None:
                return
            process.kill()
    except (OSError, ProcessLookupError):
        try:
            process.kill()
        except OSError:
            pass


def _require_status_paths_within_plan(status: bytes, plan: Mapping[str, Any]) -> None:
    allowed = {item["path"] for item in plan["files"]}
    observed = _status_paths(status)
    if not observed.issubset(allowed):
        raise ApplyGitError("unexpected-git-change", "apply observed an unrelated Git worktree change")


def _status_paths(status: bytes) -> set[str]:
    if not status:
        return set()
    fields = status.split(b"\0")
    if fields[-1] != b"":
        raise ApplyGitError("git-status-format", "Git status output is not NUL-terminated")
    paths: set[str] = set()
    index = 0
    while index < len(fields) - 1:
        entry = fields[index]
        index += 1
        if len(entry) < 4 or entry[2:3] != b" ":
            raise ApplyGitError("git-status-format", "Git status output is malformed")
        status_code = entry[:2]
        path_bytes = entry[3:]
        paths.add(_decode_git_path(path_bytes))
        if b"R" in status_code or b"C" in status_code:
            if index >= len(fields) - 1:
                raise ApplyGitError("git-status-format", "Git rename status is incomplete")
            paths.add(_decode_git_path(fields[index]))
            index += 1
    return paths


def _decode_git_path(value: bytes) -> str:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApplyGitError("git-path-encoding", "Git status contains a non-UTF-8 path") from exc
    return _relative_path(text, "Git status path")


def _normalize_execution_error(exc: Exception, report_path: Path) -> ApplyGateError:
    if isinstance(exc, ApplyGateError):
        return exc
    return ApplyExecutionError("apply-write-failed", "target write failed", report_path=report_path)


def _error_code(exc: BaseException, fallback: str) -> str:
    if isinstance(exc, ApplyGateError) and _SAFE_ID.fullmatch(exc.code):
        return exc.code
    return fallback


def _path_is_within(candidate: str, parent: str) -> bool:
    candidate_path = PurePosixPath(candidate)
    parent_path = PurePosixPath(parent)
    return candidate_path == parent_path or parent_path in candidate_path.parents


def _relative_path(value: Any, label: str) -> str:
    if type(value) is not str or not value or len(value) > 256:
        raise ApplyPathError("unsafe-relative-path", f"{label} must be a bounded relative path")
    if value.startswith(("/", "\\")) or "\\" in value or "://" in value or value.endswith("/"):
        raise ApplyPathError("unsafe-relative-path", f"{label} is not a canonical POSIX path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or PurePosixPath(value).as_posix() != value:
        raise ApplyPathError("unsafe-relative-path", f"{label} contains unsafe path segments")
    return value


def _require_absolute_canonical_text(value: Any, label: str) -> str:
    if type(value) is not str or not value or len(value) > 4096 or "\x00" in value:
        raise ApplyPlanError("plan-path", f"{label} must be a bounded path string")
    path = Path(value)
    if not path.is_absolute() or any(part == ".." for part in path.parts):
        raise ApplyPlanError("plan-path", f"{label} must be an absolute canonical path")
    if str(path) != value:
        raise ApplyPlanError("plan-path", f"{label} must be normalized")
    return value


def _format_mode(value: Optional[int]) -> Optional[str]:
    return format(value, "04o") if value is not None else None


def _timestamp(value: Optional[str]) -> str:
    return _now_timestamp() if value is None else _require_timestamp(value, "timestamp")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _now_timestamp() -> str:
    return _utc_now().isoformat()


def _parse_timestamp(value: Any, label: str) -> datetime:
    text = _require_timestamp(value, label)
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    return datetime.fromisoformat(candidate).astimezone(timezone.utc)


def _require_timestamp(value: Any, label: str) -> str:
    if type(value) is not str or not value or len(value) > 64:
        raise ApplyPlanError("timestamp", f"{label} must be an ISO-8601 timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ApplyPlanError("timestamp", f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ApplyPlanError("timestamp", f"{label} must include a timezone")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ApplyPlanError("plan-shape", f"{label} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ApplyPlanError(
            "plan-keys",
            f"{label} keys mismatch: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}",
        )


def _require_match(value: Any, pattern: re.Pattern[str], label: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ApplyPlanError("plan-value", f"{label} is invalid")
    return value


def _encode_bytes(value: Optional[bytes]) -> str:
    if value is None:
        return ""
    return base64.b64encode(value).decode("ascii")


def _decode_bytes(value: Any, label: str) -> bytes:
    if type(value) is not str:
        raise ApplyPlanError("base64", f"{label} must be a base64 string")
    try:
        encoded = value.encode("ascii")
        content = base64.b64decode(encoded, validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise ApplyPlanError("base64", f"{label} is not canonical base64") from exc
    if base64.b64encode(content) != encoded:
        raise ApplyPlanError("base64", f"{label} is not canonical base64")
    return content


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _json_fingerprint(value: Any) -> str:
    return _sha256(_canonical_json(value))


def _mac_json(key: bytes, domain: str, value: Any) -> str:
    payload = domain.encode("ascii") + b"\0" + _canonical_json(value)
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_json_bound(value: Any, maximum: int, label: str) -> None:
    try:
        encoded = _canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise ApplyPlanError("json-value", f"{label} must contain only JSON values") from exc
    if len(encoded) > maximum:
        raise ApplyPlanError("json-size", f"{label} exceeds the byte limit")


def _read_bounded(descriptor: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = os.read(descriptor, min(65536, maximum + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > maximum:
            raise ApplyPathError("file-size", "file exceeds the byte limit")
    return b"".join(chunks)


def _write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    offset = 0
    while offset < len(view):
        written = os.write(descriptor, view[offset:])
        if written <= 0:
            raise OSError("short write")
        offset += written


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _reject_duplicate_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _test_barrier(name: str, **context: Any) -> None:
    """Deterministic no-op hook used only by race/crash regression tests."""

    del name, context


build_apply_plan = plan_apply
authorize_apply_plan = authorize_apply
execute_apply_plan = execute_apply
inspect_apply_status = apply_status
rollback_apply_report = rollback_apply
