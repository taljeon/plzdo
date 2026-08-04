from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, Optional, Type
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import plzdo_local.apply_gate as apply_gate
from plzdo_local.apply_gate import (
    ApplyAuthorizationError,
    ApplyConfirmationError,
    ApplyExecutionError,
    ApplyFingerprintError,
    ApplyGateError,
    ApplyGitError,
    ApplyPathError,
    ApplyPlanError,
    ApplyPolicyError,
    ApplyRollbackError,
    apply_report_path,
    apply_status,
    authorize_apply,
    execute_apply,
    plan_apply,
    rollback_apply,
    validate_apply_plan,
)
from plzdo_local.catalog import build_catalog, build_repository
from plzdo_local.renderer import FILE_MODES, PROJECT_FRAME_PATHS, plan_project_frame


PROJECT = {
    "id": "fixture-project",
    "name": "Fixture Project",
    "objective": "Verify the guarded local apply contract.",
}
APPROVAL = {
    "id": "fixture-approval",
    "approvedAt": "2026-08-05T00:00:00+00:00",
    "approvalHash": "a" * 64,
}
PLAN_TIME = "2026-08-05T01:00:00+00:00"
APPLY_TIME = "2026-08-05T01:01:00+00:00"
ROLLBACK_TIME = "2026-08-05T01:02:00+00:00"


def main() -> int:
    if sys.flags.optimize:
        print("FAIL Python optimization disables executable assertions")
        return 1
    checks = [
        ("apply schema and exact planned bytes are bound", check_schema_and_plan_bytes),
        ("default and policy gates fail closed", check_negative_policy_gates),
        ("clean Git and foreground fingerprint confirmation are mandatory", check_clean_git_and_confirmation),
        ("target source catalog and plan drift are rejected", check_fingerprint_drift),
        ("post-plan target symlinks cannot redirect writes", check_symlink_substitution),
        ("fixture apply verifies exact bytes and rolls back", check_successful_apply_and_rollback),
        ("updated managed bytes use exact backups", check_existing_byte_backup),
        ("mid-write failure restores the original fixture", check_mid_write_rollback),
        ("authorization MAC expiry and one-time consumption are enforced", check_authorization_integrity),
        ("root replacement and per-file TOCTOU are detected", check_root_and_file_toctou),
        ("interrupted apply and rollback resume idempotently", check_crash_resumable_rollback),
        ("repository Git filters never execute", check_git_filters_never_execute),
        ("report MAC and canonical evidence paths are enforced", check_report_mac_and_evidence),
    ]
    failures: list[str] = []
    for label, check in checks:
        try:
            check()
        except Exception as exc:
            failures.append(f"{label}: {type(exc).__name__}: {exc}")
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(f"phase4 P5 check passed: {len(checks)} checks")
    return 0


def check_schema_and_plan_bytes() -> None:
    schema = json.loads((ROOT / "schemas/apply-plan.schema.json").read_text(encoding="utf-8"))
    require(schema["additionalProperties"] is False, "apply schema is not exact-key")
    require(schema["properties"]["schemaVersion"]["const"] == "plzdo-local.apply-plan.v2", "schema version")
    require(schema["properties"]["files"]["minItems"] == len(PROJECT_FRAME_PATHS), "schema file minimum")
    require(schema["properties"]["files"]["items"] is False, "schema permits trailing frame entries")
    require(len(schema["properties"]["files"]["prefixItems"]) == len(PROJECT_FRAME_PATHS), "schema prefix order")
    require(
        schema["x-runtime-semantic-validator"] == "plzdo_local.apply_gate.validate_apply_plan",
        "runtime validator is not declared",
    )
    require("not claimed to be equivalent" in schema["description"], "schema overclaims runtime equivalence")
    require("command" not in json.dumps(schema, sort_keys=True), "apply schema exposes command execution")

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        repeated = make_plan(fixture)
        require(repeated == plan, "identical target and source did not produce an identical apply plan")
        require(fixture_git(fixture.target, "status") == "", "apply planning changed the target")
        validate_apply_plan(plan)
        require(plan["confirmation"] == {"type": "plan-fingerprint"}, "confirmation binding")
        require(plan["approval"] == APPROVAL, "approval metadata was not bound")
        require(plan["source"]["project"] == PROJECT, "validated project input was not bound")
        require(plan["target"]["missingDirectories"] == ["TASKS", "docs", "scripts"], "frame parents")
        require(plan["target"]["gitIdentity"]["topLevel"] == str(fixture.target), "Git top-level binding")
        for field in ("gitDirectory", "commonDirectory"):
            identity = plan["target"]["gitIdentity"][field]
            metadata = Path(identity["path"]).stat()
            require((identity["device"], identity["inode"]) == (metadata.st_dev, metadata.st_ino), field)
        require(tuple(item["path"] for item in plan["files"]) == PROJECT_FRAME_PATHS, "planned path order")
        later_plan = plan_apply(
            fixture.catalog,
            "fixture-repo",
            PROJECT,
            force=True,
            created_at="2026-08-05T01:00:01+00:00",
        )
        require(later_plan["planFingerprint"] != plan["planFingerprint"], "distinct plans share a fingerprint")
        require(
            apply_gate._target_lock_id(later_plan) == apply_gate._target_lock_id(plan),
            "target-global lock depends on the plan fingerprint",
        )
        alternate_repository = build_repository(
            repository_id="alternate-repo",
            path=fixture.target,
            workflow_lane="operational",
            rollout_tier="enforced",
            outputs=sorted(PROJECT_FRAME_PATHS),
            real_apply={"enabled": True, "operatorOnly": True, "approval": copy.deepcopy(APPROVAL)},
            path_must_exist=True,
        )
        alternate_plan = plan_apply(
            build_catalog([alternate_repository]),
            "alternate-repo",
            PROJECT,
            force=True,
            created_at=PLAN_TIME,
        )
        require(
            apply_gate._target_lock_id(alternate_plan) == apply_gate._target_lock_id(plan),
            "catalog repository identity split the target-global lock",
        )
        for planned, rendered in zip(plan["files"], fixture.frame.files):
            exact = base64.b64decode(planned["contentBase64"], validate=True)
            require(exact == rendered.content, f"planned bytes differ: {planned['path']}")
            require(planned["sha256"] == rendered.sha256, f"planned hash differs: {planned['path']}")
            require(planned["mode"] == format(rendered.mode, "04o"), f"planned mode differs: {planned['path']}")

        reordered = copy.deepcopy(plan)
        reordered["files"][0], reordered["files"][1] = reordered["files"][1], reordered["files"][0]
        unsorted_directories = copy.deepcopy(plan)
        unsorted_directories["target"]["missingDirectories"] = ["docs", "TASKS"]
        invalid_conditional = copy.deepcopy(plan)
        invalid_conditional["files"][0]["action"] = "update"
        semantic_only = copy.deepcopy(plan)
        semantic_only["files"][0]["contentBase64"] = base64.b64encode(b"different\n").decode("ascii")
        corpus = (
            ("valid", plan, True, True),
            ("file-order", reordered, False, False),
            ("directory-order", unsorted_directories, False, False),
            ("previous-action", invalid_conditional, False, False),
            ("runtime-hash", semantic_only, True, False),
        )
        for label, candidate, structural, semantic in corpus:
            require(_schema_accepts(schema, candidate) is structural, f"schema corpus mismatch: {label}")
            require(_runtime_plan_accepts(candidate) is semantic, f"runtime corpus mismatch: {label}")

        injected = copy.deepcopy(plan)
        injected["commands"] = [["/usr/bin/false"]]
        expect_error(ApplyPlanError, lambda: validate_apply_plan(injected), code="plan-keys")
        tampered = copy.deepcopy(plan)
        tampered["files"][0]["contentBase64"] = base64.b64encode(b"different\n").decode("ascii")
        expect_error(ApplyPlanError, lambda: validate_apply_plan(tampered))

        expect_error(
            ApplyPlanError,
            lambda: plan_apply(fixture.catalog, "fixture-repo", fixture.frame, force=True),
            code="renderer-plan-input",
        )
        expect_type_error(
            lambda: plan_apply(
                fixture.catalog,
                "fixture-repo",
                PROJECT,
                force=True,
                template_root=fixture.base,
            )
        )
        expect_type_error(lambda: execute_apply(plan, fixture.catalog, frame=fixture.frame))

        class CustomProject(dict):
            pass

        expect_error(
            ApplyPlanError,
            lambda: plan_apply(fixture.catalog, "fixture-repo", CustomProject(PROJECT), force=True),
            code="project-input",
        )
        binary_project = dict(PROJECT, objective=b"binary")
        expect_error(
            ApplyPlanError,
            lambda: plan_apply(fixture.catalog, "fixture-repo", binary_project, force=True),
            code="project-input",
        )
        for invalid_project in (
            dict(PROJECT, objective="line\u2028break"),
            dict(PROJECT, name="invalid-\ud800"),
        ):
            expect_error(
                ApplyPlanError,
                lambda invalid_project=invalid_project: plan_apply(
                    fixture.catalog,
                    "fixture-repo",
                    invalid_project,
                    force=True,
                ),
                code="project-input",
            )
        binary_plan = copy.deepcopy(plan)
        binary_plan["files"][0]["contentBase64"] = base64.b64encode(b"\xff").decode("ascii")
        binary_plan["files"][0]["bytes"] = 1
        binary_plan["files"][0]["sha256"] = hashlib.sha256(b"\xff").hexdigest()
        expect_error(ApplyPlanError, lambda: validate_apply_plan(binary_plan), code="plan-binary-frame")


def check_negative_policy_gates() -> None:
    with git_fixture(enabled=False) as fixture:
        expect_error(
            ApplyPolicyError,
            lambda: make_plan(fixture),
            code="apply-disabled",
        )

    with git_fixture(enabled=True, outputs=["AGENTS.md"]) as fixture:
        expect_error(
            ApplyPolicyError,
            lambda: make_plan(fixture),
            code="output-not-allowed",
        )

    broad_outputs = ["AGENTS.md", "CHECKS.md", "TASKS", "docs", "scripts"]
    with git_fixture(
        enabled=True,
        outputs=broad_outputs,
        protected_paths=["docs/technical-design.md"],
    ) as fixture:
        expect_error(
            ApplyPolicyError,
            lambda: make_plan(fixture),
            code="protected-path",
        )

    with git_fixture(enabled=True) as fixture:
        invalid_catalogs = []
        invalid_lane = copy.deepcopy(fixture.catalog)
        invalid_lane["repositories"][0]["workflowLane"] = "standard"
        invalid_catalogs.append(invalid_lane)
        invalid_tier = copy.deepcopy(fixture.catalog)
        invalid_tier["repositories"][0]["rolloutTier"] = "observe"
        invalid_catalogs.append(invalid_tier)
        invalid_operator = copy.deepcopy(fixture.catalog)
        invalid_operator["repositories"][0]["realApply"]["operatorOnly"] = False
        invalid_catalogs.append(invalid_operator)
        invalid_approval = copy.deepcopy(fixture.catalog)
        invalid_approval["repositories"][0]["realApply"]["approval"] = None
        invalid_catalogs.append(invalid_approval)
        for invalid in invalid_catalogs:
            expect_error(
                ApplyPolicyError,
                lambda invalid=invalid: plan_apply(
                    invalid,
                    "fixture-repo",
                    PROJECT,
                    force=True,
                    created_at=PLAN_TIME,
                ),
                code="invalid-catalog",
            )

    with tempfile.TemporaryDirectory(prefix="plzdo-p5-non-git-") as temporary:
        target = Path(temporary).resolve() / "target"
        target.mkdir()
        (target / "README.md").write_text("not a Git worktree\n", encoding="utf-8")
        repository = build_repository(
            repository_id="fixture-repo",
            path=target,
            workflow_lane="operational",
            rollout_tier="enforced",
            outputs=sorted(PROJECT_FRAME_PATHS),
            real_apply={"enabled": True, "operatorOnly": True, "approval": copy.deepcopy(APPROVAL)},
            path_must_exist=True,
        )
        catalog = build_catalog([repository])
        expect_error(
            ApplyGitError,
            lambda: plan_apply(catalog, "fixture-repo", PROJECT, force=True, created_at=PLAN_TIME),
            code="git-failed",
        )


def check_clean_git_and_confirmation() -> None:
    with git_fixture(enabled=True) as fixture:
        dirty = fixture.target / "dirty.txt"
        dirty.write_text("uncommitted\n", encoding="utf-8")
        expect_error(
            ApplyGitError,
            lambda: make_plan(fixture),
            code="dirty-git",
        )

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        with (
            mock.patch.dict(os.environ, {"PLZDO_APPLY_CONFIRMATION": plan["planFingerprint"]}),
            mock.patch.object(sys, "stdin", io.StringIO(plan["planFingerprint"] + "\n")),
            mock.patch.object(os, "open", side_effect=OSError("no controlling tty")),
        ):
            expect_error(
                ApplyConfirmationError,
                lambda: apply_gate._read_foreground_confirmation("authorize", plan["planFingerprint"]),
                code="foreground-tty",
            )
        with tty_confirmation("wrong-fingerprint"):
            expect_error(
                ApplyConfirmationError,
                lambda: authorize_apply(plan, fixture.catalog),
                code="confirmation-mismatch",
            )

        class InjectedConfirmation(str):
            pass

        with tty_confirmation(InjectedConfirmation(plan["planFingerprint"])):
            expect_error(
                ApplyConfirmationError,
                lambda: authorize_apply(plan, fixture.catalog),
                code="confirmation-type",
            )
        grant = authorize(fixture, plan)
        require(grant["planFingerprint"] == plan["planFingerprint"], "grant plan binding")
        require(grant["repositoryPath"] == str(fixture.target), "grant target binding")
        with tty_confirmation("wrong-fingerprint"):
            expect_error(
                ApplyConfirmationError,
                lambda: execute_apply(plan, fixture.catalog),
                code="confirmation-mismatch",
            )
        expect_type_error(
            lambda: execute_apply(
                plan,
                fixture.catalog,
                confirmation=plan["planFingerprint"],
                evidence_root=fixture.base / "caller-evidence",
            )
        )
        require(not (fixture.base / "caller-evidence").exists(), "caller evidence root was accepted")
        report = execute(fixture, plan)
        require(report["grant"]["nonce"] == grant["nonce"], "report did not bind consumed grant")


def check_fingerprint_drift() -> None:
    with git_fixture(enabled=True, ignored_paths=["AGENTS.md"]) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        (fixture.target / "AGENTS.md").write_text("ignored stale bytes\n", encoding="utf-8")
        require(fixture_git(fixture.target, "status") == "", "ignored stale fixture is not Git-clean")
        expect_error(
            ApplyPlanError,
            lambda: execute(fixture, plan),
            code="renderer-owned-plan",
        )

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        changed_catalog = copy.deepcopy(fixture.catalog)
        changed_catalog["repositories"][0]["realApply"]["approval"]["approvalHash"] = "b" * 64
        expect_error(
            ApplyFingerprintError,
            lambda: execute_with_catalog(plan, changed_catalog),
            code="catalog-fingerprint-mismatch",
        )
        active = apply_gate._authorization_path(fixture.state, plan["planFingerprint"])
        require(active.is_file(), "catalog drift consumed authorization")

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        (fixture.target / "README.md").write_text("new committed HEAD\n", encoding="utf-8")
        fixture_git(fixture.target, "add-all")
        fixture_git(fixture.target, "commit")
        expect_error(
            ApplyFingerprintError,
            lambda: execute(fixture, plan),
            code="target-head-drift",
        )
        active = apply_gate._authorization_path(fixture.state, plan["planFingerprint"])
        require(active.is_file(), "HEAD drift consumed authorization")

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        replace_git_metadata(fixture)
        with tty_confirmation(plan["planFingerprint"]):
            expect_error(
                ApplyFingerprintError,
                lambda: authorize_apply(plan, fixture.catalog),
                code="git-identity-drift",
            )

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        replace_git_metadata(fixture)
        expect_error(
            ApplyFingerprintError,
            lambda: execute(fixture, plan),
            code="git-identity-drift",
        )
        active = apply_gate._authorization_path(fixture.state, plan["planFingerprint"])
        require(active.is_file(), "Git metadata drift consumed authorization")

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        execute(fixture, plan)
        report_path = apply_report_path(plan)
        replace_git_metadata(fixture)
        expect_error(
            ApplyFingerprintError,
            lambda: apply_status(report_path, fixture.catalog),
            code="git-identity-drift",
        )
        expect_error(
            ApplyFingerprintError,
            lambda: rollback(fixture, report_path),
            code="git-identity-drift",
        )


def check_symlink_substitution() -> None:
    with git_fixture(enabled=True, ignored_paths=["docs"]) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        outside = fixture.base / "outside"
        outside.mkdir()
        marker = outside / "marker.txt"
        marker.write_text("preserve\n", encoding="utf-8")
        (fixture.target / "docs").symlink_to(outside, target_is_directory=True)
        require(fixture_git(fixture.target, "status") == "", "symlink fixture is not Git-clean")
        expect_error(
            ApplyPlanError,
            lambda: execute(fixture, plan),
            code="renderer-owned-plan",
        )
        require(marker.read_text(encoding="utf-8") == "preserve\n", "symlink target was modified")
        require(not (outside / "requirements.md").exists(), "apply escaped through the symlink")


def check_successful_apply_and_rollback() -> None:
    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        report_path = apply_gate._report_path(
            fixture.state,
            plan,
            create_parent=False,
            missing_ok=True,
        )
        observed_backup = {"value": False}

        def observe_barrier(name: str, **context: Any) -> None:
            if name != "before-file-compare" or observed_backup["value"]:
                return
            require(report_path.is_file(), "target write started before rollback evidence existed")
            backup = json.loads(report_path.read_text(encoding="utf-8"))
            require(backup["status"] == "rollback-in-progress", "rollback journal was not durable")
            require(len(backup["backups"]) == len(PROJECT_FRAME_PATHS), "backup report is incomplete")
            require(
                [item["path"] for item in backup["createdDirectories"]] == ["TASKS", "docs", "scripts"],
                "created directory identities were not durable before file mutation",
            )
            observed_backup["value"] = True

        with mock.patch.object(apply_gate, "_test_barrier", side_effect=observe_barrier):
            report = execute(fixture, plan)
        require(observed_backup["value"], "fixture apply performed no observed write")
        require(report["status"] == "applied", "successful apply report status")
        require(
            [item["path"] for item in report["createdDirectories"]] == ["TASKS", "docs", "scripts"],
            "created directory evidence",
        )
        for identity in report["createdDirectories"]:
            metadata = (fixture.target / identity["path"]).stat()
            require(
                (identity["device"], identity["inode"]) == (metadata.st_dev, metadata.st_ino),
                f"created directory identity: {identity['path']}",
            )
        require(len(report["temporaryArtifacts"]) == len(PROJECT_FRAME_PATHS), "temporary journal coverage")
        require(not target_temporary_artifacts(fixture), "successful apply retained target temporary artifacts")
        require(report["reportMac"] != report["reportFingerprint"], "report MAC is not distinct evidence")
        require(apply_status(report_path, fixture.catalog)["state"] == "exact", "applied status is not exact")
        for item in plan["files"]:
            destination = fixture.target.joinpath(*PurePosixPath(item["path"]).parts)
            require(destination.read_bytes() == base64.b64decode(item["contentBase64"]), f"applied bytes: {item['path']}")
            require(stat.S_IMODE(destination.stat().st_mode) == FILE_MODES[item["path"]], f"applied mode: {item['path']}")

        changed_catalog = copy.deepcopy(fixture.catalog)
        changed_catalog["repositories"][0]["realApply"]["approval"]["approvalHash"] = "c" * 64
        require(apply_status(report_path, changed_catalog)["state"] == "drifted", "catalog drift was not reported")

        copied_report = fixture.target / "copied-apply-report.json"
        copied_report.write_bytes(report_path.read_bytes())
        expect_error(
            ApplyPathError,
            lambda: apply_status(copied_report, fixture.catalog),
            code="report-path",
        )
        copied_report.unlink()

        unrelated = fixture.target / "unrelated.txt"
        unrelated.write_text("drift\n", encoding="utf-8")
        expect_error(
            ApplyRollbackError,
            lambda: rollback(fixture, report_path),
            code="rollback-drift",
        )
        unrelated.unlink()
        rolled_back = rollback(fixture, report_path)
        require(rolled_back["status"] == "rolled-back", "rollback report status")
        require(apply_status(report_path, fixture.catalog)["state"] == "exact", "rollback status is not exact")
        for relative in PROJECT_FRAME_PATHS:
            require(not fixture.target.joinpath(*PurePosixPath(relative).parts).exists(), f"rollback retained {relative}")
        require(fixture_git(fixture.target, "status") == "", "rollback did not restore clean Git state")
        lock_path = apply_gate._target_lock_path(fixture.state, plan)
        require(lock_path.parent == fixture.state / "real-apply" / "locks", "target lock is caller-dependent")


def check_mid_write_rollback() -> None:
    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        calls = {"count": 0}

        def failing_barrier(name: str, **context: Any) -> None:
            if name == "after-file-replace":
                calls["count"] += 1
                if calls["count"] == 4:
                    raise OSError("synthetic write failure")

        with mock.patch.object(apply_gate, "_test_barrier", side_effect=failing_barrier):
            failure = expect_error(
                ApplyExecutionError,
                lambda: execute(fixture, plan),
                code="apply-write-failed",
            )
        require(calls["count"] == 4, "failure was not injected after multiple writes")
        require(failure.report_path is not None and failure.report_path.is_file(), "rollback report is missing")
        report = json.loads(failure.report_path.read_text(encoding="utf-8"))
        require(report["status"] == "failed-rolled-back", "automatic rollback status")
        require(apply_status(failure.report_path, fixture.catalog)["state"] == "exact", "automatic rollback is not exact")
        for relative in PROJECT_FRAME_PATHS:
            require(not fixture.target.joinpath(*PurePosixPath(relative).parts).exists(), f"failed apply retained {relative}")
        for relative in ("TASKS", "docs", "scripts"):
            require(not (fixture.target / relative).exists(), f"failed apply retained directory {relative}")
        require(fixture_git(fixture.target, "status") == "", "automatic rollback did not restore clean Git state")


def check_existing_byte_backup() -> None:
    with git_fixture(enabled=True) as fixture:
        initial_plan = make_plan(fixture)
        authorize(fixture, initial_plan)
        execute(fixture, initial_plan)
        fixture_git(fixture.target, "add-all")
        fixture_git(fixture.target, "commit")
        baseline = {
            relative: fixture.target.joinpath(*PurePosixPath(relative).parts).read_bytes()
            for relative in PROJECT_FRAME_PATHS
        }

        updated_project = dict(PROJECT, objective="Verify exact backups for updated managed bytes.")
        updated_plan = plan_apply(
            fixture.catalog,
            "fixture-repo",
            updated_project,
            created_at="2026-08-05T02:00:00+00:00",
        )
        authorize(fixture, updated_plan)
        report = execute(fixture, updated_plan)
        for backup in report["backups"]:
            require(backup["previousExists"] is True, f"missing update backup: {backup['path']}")
            restored = base64.b64decode(backup["previousContentBase64"], validate=True)
            require(restored == baseline[backup["path"]], f"backup bytes differ: {backup['path']}")
        report_path = apply_report_path(updated_plan)
        disabled_catalog = copy.deepcopy(fixture.catalog)
        disabled_catalog["repositories"][0]["realApply"]["enabled"] = False
        with tty_confirmation(updated_plan["planFingerprint"]):
            rollback_apply(report_path, disabled_catalog)
        for relative, expected in baseline.items():
            destination = fixture.target.joinpath(*PurePosixPath(relative).parts)
            require(destination.read_bytes() == expected, f"updated rollback bytes differ: {relative}")
            require(stat.S_IMODE(destination.stat().st_mode) == FILE_MODES[relative], f"updated rollback mode: {relative}")
        require(fixture_git(fixture.target, "status") == "", "updated rollback did not restore clean Git state")


def check_authorization_integrity() -> None:
    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        active = apply_gate._authorization_path(fixture.state, plan["planFingerprint"])
        require(stat.S_IMODE(fixture.state.stat().st_mode) == 0o700, "state root is not owner-only")
        require(stat.S_IMODE((fixture.state / "real-apply").stat().st_mode) == 0o700, "apply state is not owner-only")
        require(stat.S_IMODE((fixture.state / "real-apply" / "integrity.key").stat().st_mode) == 0o600, "key mode")
        require(stat.S_IMODE(active.stat().st_mode) == 0o600, "grant mode")
        grant = json.loads(active.read_text(encoding="utf-8"))
        grant["repositoryId"] = "other-repo"
        active.write_text(json.dumps(grant), encoding="utf-8")
        expect_error(
            ApplyAuthorizationError,
            lambda: execute(fixture, plan),
            code="authorization-mac",
        )
        require(not (fixture.target / "AGENTS.md").exists(), "tampered grant mutated target")

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        grant = authorize(fixture, plan)
        expired = apply_gate._parse_timestamp(grant["expiresAt"], "test expiry") + timedelta(seconds=1)
        with mock.patch.object(apply_gate, "_utc_now", return_value=expired):
            expect_error(
                ApplyAuthorizationError,
                lambda: execute(fixture, plan),
                code="authorization-expired",
            )
        active = apply_gate._authorization_path(fixture.state, plan["planFingerprint"])
        require(active.is_file(), "expired grant was consumed")

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        grant = authorize(fixture, plan)
        report = execute(fixture, plan)
        active = apply_gate._authorization_path(fixture.state, plan["planFingerprint"])
        consumed = fixture.state / "real-apply" / "consumed"
        require(not active.exists(), "successful execution retained active grant")
        require(len(list(consumed.glob("*.json"))) == 1, "grant nonce was not consumed exactly once")
        require(report["grant"]["nonce"] == grant["nonce"], "report grant nonce differs")
        with tty_confirmation(plan["planFingerprint"]):
            expect_error(
                ApplyExecutionError,
                lambda: execute_apply(plan, fixture.catalog),
                code="report-exists",
            )

    with git_fixture(enabled=True) as fixture:
        fixture.state.mkdir(mode=0o755)
        plan = make_plan(fixture)
        with tty_confirmation(plan["planFingerprint"]):
            expect_error(
                ApplyPolicyError,
                lambda: authorize_apply(plan, fixture.catalog),
                code="private-state-permissions",
            )
        require(not (fixture.target / "AGENTS.md").exists(), "non-private state allowed mutation")

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        key_path = fixture.state / "real-apply" / "integrity.key"
        key_path.chmod(0o644)
        with tty_confirmation(plan["planFingerprint"]):
            expect_error(
                ApplyPolicyError,
                lambda: execute_apply(plan, fixture.catalog),
                code="integrity-key-permissions",
            )
        active = apply_gate._authorization_path(fixture.state, plan["planFingerprint"])
        require(active.is_file(), "unsafe key permissions consumed authorization")
        require(not (fixture.target / "AGENTS.md").exists(), "unsafe key permissions allowed mutation")

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        active = apply_gate._authorization_path(fixture.state, plan["planFingerprint"])

        with mock.patch.object(apply_gate, "_write_report", side_effect=OSError("synthetic journal failure")):
            expect_error(
                ApplyExecutionError,
                lambda: execute(fixture, plan),
                code="backup-report-write",
            )
        require(not active.exists(), "execution start did not consume authorization")
        consumed = fixture.state / "real-apply" / "consumed"
        require(len(list(consumed.glob("*.json"))) == 1, "consumed authorization evidence is missing")
        require(not (fixture.target / "AGENTS.md").exists(), "journal failure mutated the target")


def check_root_and_file_toctou() -> None:
    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        moved = fixture.base / "original-target"
        replaced = {"value": False}

        def replace_root(name: str, **context: Any) -> None:
            if name != "before-git-config-keys" or replaced["value"]:
                return
            fixture.target.rename(moved)
            fixture.target.mkdir()
            replaced["value"] = True

        with mock.patch.object(apply_gate, "_test_barrier", side_effect=replace_root):
            expect_error(
                ApplyFingerprintError,
                lambda: execute(fixture, plan),
                code="target-root-fingerprint",
            )
        require(replaced["value"], "root replacement barrier did not run")
        require(not (moved / "AGENTS.md").exists(), "detached original root was mutated")
        require(not (fixture.target / "AGENTS.md").exists(), "replacement root was mutated")

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        concurrent = b"concurrent operator bytes\n"
        injected = {"value": False}

        def replace_file(name: str, **context: Any) -> None:
            if name == "before-file-compare" and context.get("path") == "AGENTS.md" and not injected["value"]:
                (fixture.target / "AGENTS.md").write_bytes(concurrent)
                injected["value"] = True

        with mock.patch.object(apply_gate, "_test_barrier", side_effect=replace_file):
            failure = expect_error(
                ApplyRollbackError,
                lambda: execute(fixture, plan),
                code="automatic-rollback-failed",
            )
        require(injected["value"], "file TOCTOU barrier did not run")
        require((fixture.target / "AGENTS.md").read_bytes() == concurrent, "concurrent bytes were overwritten")
        require(failure.report_path is not None, "TOCTOU failure omitted recovery evidence")


def check_crash_resumable_rollback() -> None:
    class SimulatedCrash(BaseException):
        pass

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        crashed = {"value": False}

        def crash_apply(name: str, **context: Any) -> None:
            if name == "after-file-replace" and not crashed["value"]:
                crashed["value"] = True
                raise SimulatedCrash()

        with mock.patch.object(apply_gate, "_test_barrier", side_effect=crash_apply):
            expect_base_exception(SimulatedCrash, lambda: execute(fixture, plan))
        report_path = apply_report_path(plan)
        interrupted = json.loads(report_path.read_text(encoding="utf-8"))
        require(interrupted["status"] == "rollback-in-progress", "crash journal is not resumable")
        require(any((fixture.target / item).exists() for item in ("AGENTS.md", "CHECKS.md")), "crash wrote no file")
        require(rollback(fixture, report_path)["status"] == "rolled-back", "crash rollback did not resume")
        require(fixture_git(fixture.target, "status") == "", "crash resume did not restore Git")

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        marker = fixture.base / "child-temp-created"
        child_pid = os.fork()
        if child_pid == 0:
            def stop_after_temp(name: str, **context: Any) -> None:
                if name == "after-temp-create":
                    marker.write_text(context["temporaryName"], encoding="utf-8")
                    while True:
                        signal.pause()

            with mock.patch.object(apply_gate, "_test_barrier", side_effect=stop_after_temp):
                execute(fixture, plan)
            os._exit(3)

        reaped = False
        child_status = 0
        try:
            deadline = time.monotonic() + 8
            while not marker.exists() and time.monotonic() < deadline:
                ended, child_status = os.waitpid(child_pid, os.WNOHANG)
                if ended == child_pid:
                    reaped = True
                    break
                time.sleep(0.02)
            require(marker.is_file(), "child never reached the target temporary artifact barrier")
            os.kill(child_pid, signal.SIGKILL)
            _, child_status = os.waitpid(child_pid, 0)
            reaped = True
            require(os.WIFSIGNALED(child_status), "child apply was not terminated by a real signal")
        finally:
            if not reaped:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                os.waitpid(child_pid, 0)
        report_path = apply_report_path(plan)
        interrupted = json.loads(report_path.read_text(encoding="utf-8"))
        require(interrupted["status"] == "rollback-in-progress", "killed child lost rollback journal")
        require(target_temporary_artifacts(fixture), "killed child left no target temporary artifact")
        require(rollback(fixture, report_path)["status"] == "rolled-back", "temp-artifact rollback did not resume")
        require(not target_temporary_artifacts(fixture), "rollback retained a journaled target temporary artifact")

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)

        def crash_before_directory_journal(name: str, **context: Any) -> None:
            if name == "after-directory-create-before-journal":
                raise SimulatedCrash()

        with mock.patch.object(apply_gate, "_test_barrier", side_effect=crash_before_directory_journal):
            expect_base_exception(SimulatedCrash, lambda: execute(fixture, plan))
        report_path = apply_report_path(plan)
        interrupted = json.loads(report_path.read_text(encoding="utf-8"))
        require(interrupted["createdDirectories"] == [], "unjournaled directory gained false identity evidence")
        ambiguous = fixture.target / "TASKS"
        identity = (ambiguous.stat().st_dev, ambiguous.stat().st_ino)
        expect_error(
            ApplyRollbackError,
            lambda: rollback(fixture, report_path),
            code="rollback-failed",
        )
        require(ambiguous.is_dir(), "rollback removed an ambiguous unjournaled directory")
        metadata = ambiguous.stat()
        require((metadata.st_dev, metadata.st_ino) == identity, "ambiguous directory identity changed")
        ambiguous.rmdir()
        require(rollback(fixture, report_path)["status"] == "rolled-back", "directory recovery did not resume")

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)

        def crash_after_directory_journal(name: str, **context: Any) -> None:
            if name == "after-directory-journal" and context["path"] == "TASKS":
                raise SimulatedCrash()

        with mock.patch.object(apply_gate, "_test_barrier", side_effect=crash_after_directory_journal):
            expect_base_exception(SimulatedCrash, lambda: execute(fixture, plan))
        report_path = apply_report_path(plan)
        interrupted = json.loads(report_path.read_text(encoding="utf-8"))
        require(len(interrupted["createdDirectories"]) == 1, "created directory identity was not journaled")
        original = interrupted["createdDirectories"][0]
        tasks = fixture.target / "TASKS"
        tasks.rmdir()
        tasks.mkdir()
        replacement = tasks.stat()
        require(
            (replacement.st_dev, replacement.st_ino) != (original["device"], original["inode"]),
            "directory replacement retained the original identity",
        )
        expect_error(
            ApplyRollbackError,
            lambda: rollback(fixture, report_path),
            code="rollback-failed",
        )
        require(tasks.is_dir(), "rollback removed a replacement directory with an unproven inode")
        tasks.rmdir()
        require(rollback(fixture, report_path)["status"] == "rolled-back", "inode-drift recovery did not resume")

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        execute(fixture, plan)
        report_path = apply_report_path(plan)
        crashed = {"value": False}

        def crash_rollback(name: str, **context: Any) -> None:
            if name == "after-rollback-file" and not crashed["value"]:
                crashed["value"] = True
                raise SimulatedCrash()

        with mock.patch.object(apply_gate, "_test_barrier", side_effect=crash_rollback):
            expect_base_exception(SimulatedCrash, lambda: rollback(fixture, report_path))
        interrupted = json.loads(report_path.read_text(encoding="utf-8"))
        require(interrupted["status"] == "rollback-in-progress", "rollback crash lost durable status")
        require(rollback(fixture, report_path)["status"] == "rolled-back", "mixed-state rollback did not resume")

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        original_write_report = apply_gate._write_report
        failed = {"value": False}

        def fail_final_report(path: Path, report: Any, state_root: Path, key: bytes) -> None:
            if report["status"] == "applied" and not failed["value"]:
                failed["value"] = True
                raise OSError("synthetic final report failure")
            original_write_report(path, report, state_root, key)

        with mock.patch.object(apply_gate, "_write_report", side_effect=fail_final_report):
            failure = expect_error(
                ApplyExecutionError,
                lambda: execute(fixture, plan),
                code="apply-report-write",
            )
        require(failed["value"], "final report failure was not injected")
        require(failure.report_path is not None, "final report failure omitted report path")
        require(apply_status(failure.report_path, fixture.catalog)["state"] == "exact", "auto rollback not exact")

    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        execute(fixture, plan)
        report_path = apply_report_path(plan)
        original_write_report = apply_gate._write_report
        failed = {"value": False}

        def fail_rollback_report(path: Path, report: Any, state_root: Path, key: bytes) -> None:
            if report["status"] == "rolled-back" and not failed["value"]:
                failed["value"] = True
                raise OSError("synthetic rollback report failure")
            original_write_report(path, report, state_root, key)

        with mock.patch.object(apply_gate, "_write_report", side_effect=fail_rollback_report):
            expect_error(
                ApplyRollbackError,
                lambda: rollback(fixture, report_path),
                code="rollback-report-write",
            )
        require(json.loads(report_path.read_text(encoding="utf-8"))["status"] == "rollback-in-progress", "resume journal lost")
        require(rollback(fixture, report_path)["status"] == "rolled-back", "restored target did not finalize")


def check_git_filters_never_execute() -> None:
    with git_fixture(enabled=True) as fixture:
        head = fixture_git(fixture.target, "head").strip()
        fixture_git(fixture.target, "add-gitlink", value=head)
        barriers: list[str] = []
        with mock.patch.object(
            apply_gate,
            "_test_barrier",
            side_effect=lambda name, **context: barriers.append(name),
        ):
            expect_error(ApplyGitError, lambda: make_plan(fixture), code="gitlink-forbidden")
        require("before-git-status" not in barriers, "gitlink was checked after Git status")

    for operation in ("set-core-worktree", "set-worktree-config"):
        with git_fixture(enabled=True) as fixture:
            (fixture.base / "redirected").mkdir()
            fixture_git(fixture.target, operation, value=str(fixture.base / "redirected"))
            barriers = []
            with mock.patch.object(
                apply_gate,
                "_test_barrier",
                side_effect=lambda name, **context: barriers.append(name),
            ):
                expect_error(ApplyGitError, lambda: make_plan(fixture), code="git-process-config")
            require("before-git-status" not in barriers, f"{operation} was checked after Git status")

    with git_fixture(enabled=True) as fixture:
        marker = fixture.base / "filter-ran"
        script = fixture.base / "filter-probe.sh"
        script.write_text(f"#!/bin/sh\nprintf ran > {marker}\ncat\n", encoding="utf-8")
        script.chmod(0o700)
        fixture_git(fixture.target, "set-filter", value=str(script))
        (fixture.target / ".gitattributes").write_text("README.md filter=probe\n", encoding="utf-8")
        expect_error(
            ApplyGitError,
            lambda: make_plan(fixture),
            code="git-process-config",
        )
        require(not marker.exists(), "repository filter process executed")

    with git_fixture(enabled=True) as fixture:
        (fixture.target / ".gitattributes").write_text("README.md text\n", encoding="utf-8")
        barriers: list[str] = []
        with mock.patch.object(
            apply_gate,
            "_test_barrier",
            side_effect=lambda name, **context: barriers.append(name),
        ):
            expect_error(
                ApplyGitError,
                lambda: make_plan(fixture),
                code="git-attributes-forbidden",
            )
        require("before-git-status" not in barriers, ".gitattributes was checked after Git status")
        require(not (fixture.state / "real-apply").exists(), "planning created authorization state")

    with git_fixture(enabled=True, ignored_paths=["ignored/"]) as fixture:
        ignored = fixture.target / "ignored"
        ignored.mkdir()
        (ignored / ".gitattributes").write_text("README.md text\n", encoding="utf-8")
        expect_error(
            ApplyGitError,
            lambda: make_plan(fixture),
            code="git-attributes-forbidden",
        )

    with git_fixture(enabled=True) as fixture:
        info_attributes = fixture.target / ".git" / "info" / "attributes"
        info_attributes.write_text("README.md text\n", encoding="utf-8")
        expect_error(
            ApplyGitError,
            lambda: make_plan(fixture),
            code="git-attributes-forbidden",
        )

    with tempfile.TemporaryDirectory(prefix="plzdo-p5-git-bound-") as temporary:
        root = Path(temporary).resolve()
        overflow = root / "overflow-git.sh"
        overflow.write_text("#!/bin/sh\nwhile :; do printf 0123456789abcdef; done\n", encoding="utf-8")
        overflow.chmod(0o700)
        started = time.monotonic()
        with (
            mock.patch.object(apply_gate, "GIT_EXECUTABLE", str(overflow)),
            mock.patch.object(apply_gate, "MAX_GIT_OUTPUT_BYTES", 4096),
        ):
            expect_error(ApplyGitError, lambda: apply_gate._run_git(root, "status"), code="git-output")
        require(time.monotonic() - started < 3, "Git output limit did not terminate the process group")

        hanging = root / "hanging-git.sh"
        hanging.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
        hanging.chmod(0o700)
        started = time.monotonic()
        with (
            mock.patch.object(apply_gate, "GIT_EXECUTABLE", str(hanging)),
            mock.patch.object(apply_gate, "GIT_TIMEOUT_SECONDS", 0.05),
        ):
            expect_error(ApplyGitError, lambda: apply_gate._run_git(root, "status"), code="git-timeout")
        require(time.monotonic() - started < 3, "Git timeout did not terminate the process group")

        descendant_marker = root / "descendant.pid"
        descendant = root / "descendant-git.sh"
        descendant.write_text(
            f"#!/bin/sh\nsleep 30 >/dev/null 2>&1 &\nprintf '%s\\n' \"$!\" > {descendant_marker}\nexit 0\n",
            encoding="utf-8",
        )
        descendant.chmod(0o700)
        child_pid: Optional[int] = None
        try:
            with mock.patch.object(apply_gate, "GIT_EXECUTABLE", str(descendant)):
                require(apply_gate._run_git(root, "status") == b"", "fake Git result changed")
            child_pid = int(descendant_marker.read_text(encoding="utf-8").strip())
            deadline = time.monotonic() + 3
            while process_exists(child_pid) and time.monotonic() < deadline:
                time.sleep(0.02)
            require(not process_exists(child_pid), "descendant survived after the Git leader exited")
        finally:
            if child_pid is not None and process_exists(child_pid):
                os.kill(child_pid, signal.SIGKILL)


def check_report_mac_and_evidence() -> None:
    with git_fixture(enabled=True) as fixture:
        plan = make_plan(fixture)
        authorize(fixture, plan)
        report = execute(fixture, plan)
        report_path = apply_report_path(plan)
        require(stat.S_IMODE(report_path.parent.stat().st_mode) == 0o700, "evidence directory mode")
        require(stat.S_IMODE(report_path.stat().st_mode) == 0o600, "report mode")
        original = report_path.read_bytes()
        tampered = copy.deepcopy(report)
        tampered["status"] = "rolled-back"
        report_path.write_text(json.dumps(tampered), encoding="utf-8")
        expect_error(ApplyPlanError, lambda: apply_status(report_path, fixture.catalog), code="report-mac")
        report_path.write_bytes(original)

        copied = fixture.base / "copied-report.json"
        copied.write_bytes(original)
        expect_error(ApplyPathError, lambda: apply_status(copied, fixture.catalog), code="report-path")
        key = apply_gate._load_integrity_key(fixture.state, create=False)
        unrelated = copy.deepcopy(report)
        unrelated["createdDirectories"] = [{"path": "unrelated", "device": 1, "inode": 1}]
        expect_error(
            ApplyPlanError,
            lambda: apply_gate._seal_report(unrelated, key),
            code="report-directories",
        )
        unrelated_temp = copy.deepcopy(report)
        unrelated_temp["temporaryArtifacts"][0]["applyName"] = ".plzdo-apply-" + "0" * 24
        expect_error(
            ApplyPlanError,
            lambda: apply_gate._seal_report(unrelated_temp, key),
            code="report-temporary-artifact",
        )
        require(report_path.parent.parent == fixture.state / "real-apply" / "evidence", "evidence root is not canonical")


class Fixture:
    def __init__(self, base: Path, target: Path, state: Path, catalog: dict[str, Any], frame: Any) -> None:
        self.base = base
        self.target = target
        self.state = state
        self.catalog = catalog
        self.frame = frame


@contextmanager
def git_fixture(
    *,
    enabled: bool,
    outputs: Optional[list[str]] = None,
    protected_paths: Optional[list[str]] = None,
    ignored_paths: Optional[list[str]] = None,
) -> Iterator[Fixture]:
    with tempfile.TemporaryDirectory(prefix="plzdo-p5-") as temporary:
        base = Path(temporary).resolve()
        target = base / "target"
        target.mkdir()
        fixture_git(target, "init")
        (target / "README.md").write_text("temporary Git fixture\n", encoding="utf-8")
        if ignored_paths:
            (target / ".gitignore").write_text("".join(f"{value}\n" for value in ignored_paths), encoding="utf-8")
        fixture_git(target, "add-all")
        fixture_git(target, "commit")

        real_apply = None
        workflow_lane = "standard"
        rollout_tier = "observe"
        if enabled:
            workflow_lane = "operational"
            rollout_tier = "enforced"
            real_apply = {"enabled": True, "operatorOnly": True, "approval": copy.deepcopy(APPROVAL)}
        repository = build_repository(
            repository_id="fixture-repo",
            path=target,
            workflow_lane=workflow_lane,
            rollout_tier=rollout_tier,
            outputs=sorted(PROJECT_FRAME_PATHS if outputs is None else outputs),
            protected_paths=sorted(protected_paths or []),
            real_apply=real_apply,
            path_must_exist=True,
        )
        catalog = build_catalog([repository])
        frame = plan_project_frame(target, PROJECT, force=True)
        fixture = Fixture(base, target, base / "state", catalog, frame)
        with mock.patch.object(apply_gate, "resolve_state_root", return_value=fixture.state):
            yield fixture


def fixture_git(root: Path, operation: str, *, value: Optional[str] = None) -> str:
    git = apply_gate.GIT_EXECUTABLE or "/usr/bin/git"
    commands = {
        "init": [git, "-C", str(root), "init", "-q"],
        "add-all": [git, "-C", str(root), "add", "--all"],
        "commit": [
            git,
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture" + "@" + "example.invalid",
            "commit",
            "-q",
            "-m",
            "fixture",
        ],
        "status": [git, "-C", str(root), "status", "--porcelain=v1"],
        "head": [git, "-C", str(root), "rev-parse", "--verify", "HEAD"],
        "add-gitlink": [
            git,
            "-C",
            str(root),
            "update-index",
            "--add",
            "--cacheinfo",
            "160000",
            value or "",
            "modules/child",
        ],
        "set-filter": [git, "-C", str(root), "config", "filter.probe.process", value or ""],
        "set-core-worktree": [git, "-C", str(root), "config", "core.worktree", value or ""],
        "set-worktree-config": [
            git,
            "-C",
            str(root),
            "config",
            "extensions.worktreeConfig",
            "true",
        ],
    }
    if operation not in commands:
        raise AssertionError("unsupported fixture Git operation")
    result = subprocess.run(
        commands[operation],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(root.parent),
            "LANG": "C",
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
        },
    )
    require(result.returncode == 0, f"fixture Git {operation} failed")
    require(len(result.stdout) + len(result.stderr) < 1024 * 1024, "fixture Git output is unbounded")
    return result.stdout


def replace_git_metadata(fixture: Fixture) -> None:
    original = fixture.base / "original-git-metadata"
    (fixture.target / ".git").rename(original)
    fixture_git(fixture.target, "init")
    fixture_git(fixture.target, "add-all")
    fixture_git(fixture.target, "commit")


def target_temporary_artifacts(fixture: Fixture) -> list[Path]:
    artifacts: list[Path] = []
    for relative in ("", "TASKS", "docs", "scripts"):
        parent = fixture.target if not relative else fixture.target / relative
        if parent.is_dir():
            artifacts.extend(parent.glob(".plzdo-*"))
    return sorted(artifacts)


def process_exists(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    return True


def make_plan(fixture: Fixture, project: Optional[dict[str, str]] = None) -> dict[str, Any]:
    return plan_apply(
        fixture.catalog,
        "fixture-repo",
        PROJECT if project is None else project,
        force=True,
        created_at=PLAN_TIME,
    )


@contextmanager
def tty_confirmation(value: str) -> Iterator[None]:
    with mock.patch.object(apply_gate, "_read_foreground_confirmation", return_value=value):
        yield


def authorize(fixture: Fixture, plan: dict[str, Any]) -> dict[str, Any]:
    with tty_confirmation(plan["planFingerprint"]):
        return authorize_apply(plan, fixture.catalog)


def execute(fixture: Fixture, plan: dict[str, Any]) -> dict[str, Any]:
    with tty_confirmation(plan["planFingerprint"]):
        return execute_apply(plan, fixture.catalog)


def execute_with_catalog(plan: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    with tty_confirmation(plan["planFingerprint"]):
        return execute_apply(plan, catalog)


def rollback(fixture: Fixture, report_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    with tty_confirmation(report["plan"]["planFingerprint"]):
        return rollback_apply(report_path, fixture.catalog)


def expect_type_error(operation: Callable[[], Any]) -> TypeError:
    try:
        operation()
    except TypeError as exc:
        return exc
    except Exception as exc:
        raise AssertionError(f"expected TypeError, got {type(exc).__name__}: {exc}") from exc
    raise AssertionError("expected TypeError")


def expect_base_exception(error_type: Type[BaseException], operation: Callable[[], Any]) -> BaseException:
    try:
        operation()
    except error_type as exc:
        return exc
    except BaseException as exc:
        raise AssertionError(f"expected {error_type.__name__}, got {type(exc).__name__}: {exc}") from exc
    raise AssertionError(f"expected {error_type.__name__}")


def _runtime_plan_accepts(value: Any) -> bool:
    try:
        validate_apply_plan(value)
    except ApplyGateError:
        return False
    return True


def _schema_accepts(schema: dict[str, Any], value: Any) -> bool:
    return not _schema_errors(schema, schema, value, "$")


def _schema_errors(
    root: dict[str, Any],
    rule: Any,
    value: Any,
    path: str,
) -> list[str]:
    if rule is True:
        return []
    if rule is False:
        return [path]
    if not isinstance(rule, dict):
        return [path]
    if "$ref" in rule:
        prefix = "#/$defs/"
        reference = rule["$ref"]
        if not isinstance(reference, str) or not reference.startswith(prefix):
            return [path]
        return _schema_errors(root, root["$defs"][reference[len(prefix) :]], value, path)

    errors: list[str] = []
    if "const" in rule and _json_test_key(value) != _json_test_key(rule["const"]):
        errors.append(path)
    if "enum" in rule and all(_json_test_key(value) != _json_test_key(item) for item in rule["enum"]):
        errors.append(path)
    if "type" in rule and not _schema_type_matches(rule["type"], value):
        return errors + [path]
    if "allOf" in rule:
        for item in rule["allOf"]:
            errors.extend(_schema_errors(root, item, value, path))
    if "oneOf" in rule:
        matches = sum(not _schema_errors(root, item, value, path) for item in rule["oneOf"])
        if matches != 1:
            errors.append(path)
    if "if" in rule and not _schema_errors(root, rule["if"], value, path) and "then" in rule:
        errors.extend(_schema_errors(root, rule["then"], value, path))

    if isinstance(value, dict):
        required = rule.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key}")
        properties = rule.get("properties", {})
        for key, item in value.items():
            if key in properties:
                errors.extend(_schema_errors(root, properties[key], item, f"{path}.{key}"))
            elif rule.get("additionalProperties") is False:
                errors.append(f"{path}.{key}")
    if isinstance(value, list):
        if "minItems" in rule and len(value) < rule["minItems"]:
            errors.append(path)
        if "maxItems" in rule and len(value) > rule["maxItems"]:
            errors.append(path)
        if rule.get("uniqueItems") and len({_json_test_key(item) for item in value}) != len(value):
            errors.append(path)
        prefix_items = rule.get("prefixItems", [])
        for index, item in enumerate(value[: len(prefix_items)]):
            errors.extend(_schema_errors(root, prefix_items[index], item, f"{path}[{index}]"))
        remaining = value[len(prefix_items) :]
        if remaining and "items" in rule:
            for index, item in enumerate(remaining, len(prefix_items)):
                errors.extend(_schema_errors(root, rule["items"], item, f"{path}[{index}]"))
        elif not prefix_items and isinstance(rule.get("items"), dict):
            for index, item in enumerate(value):
                errors.extend(_schema_errors(root, rule["items"], item, f"{path}[{index}]"))
    if isinstance(value, str):
        if "minLength" in rule and len(value) < rule["minLength"]:
            errors.append(path)
        if "maxLength" in rule and len(value) > rule["maxLength"]:
            errors.append(path)
        if "pattern" in rule and re.search(rule["pattern"], value) is None:
            errors.append(path)
    if type(value) in {int, float}:
        if "minimum" in rule and value < rule["minimum"]:
            errors.append(path)
        if "maximum" in rule and value > rule["maximum"]:
            errors.append(path)
    return errors


def _schema_type_matches(expected: str, value: Any) -> bool:
    return {
        "array": isinstance(value, list),
        "boolean": type(value) is bool,
        "integer": type(value) is int,
        "null": value is None,
        "number": type(value) in {int, float},
        "object": isinstance(value, dict),
        "string": isinstance(value, str),
    }.get(expected, False)


def _json_test_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def expect_error(
    error_type: Type[ApplyGateError],
    operation: Callable[[], Any],
    *,
    code: Optional[str] = None,
) -> ApplyGateError:
    try:
        operation()
    except error_type as exc:
        if code is not None:
            require(exc.code == code, f"expected error code {code}, got {exc.code}")
        return exc
    except Exception as exc:
        raise AssertionError(f"expected {error_type.__name__}, got {type(exc).__name__}: {exc}") from exc
    raise AssertionError(f"expected {error_type.__name__}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
