from __future__ import annotations

import copy
import inspect
import io
import json
import math
import os
import re
import sys
import tempfile
import threading
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Callable, Optional, Type
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from plzdo_local.findings import (
    FindingTransitionError,
    FindingsValidationError,
    accept_finding_risk,
    add_finding,
    build_findings_ledger,
    close_finding,
    validate_findings_ledger,
    validate_findings_transition,
)
import plzdo_local.context as context_module
from plzdo_local.context import (
    ContextSourceError,
    ContextStaleError,
    ContextValidationError,
    check_context_pack,
    freshness_report,
    generate_context_pack,
    parse_context_pack,
    serialize_context_pack,
    validate_context_pack,
    validate_source_path,
)
from plzdo_local.cli import main as cli_main
import plzdo_local.durable_cli as durable_cli_module
from plzdo_local.execution_rules import classify_execution
from plzdo_local.formalization import (
    FormalizationActivationError,
    FormalizationApprovalError,
    FormalizationImmutableError,
    FormalizationValidationError,
    approve_formalization,
    build_formalization,
    complete_formalization,
    edit_formalization,
    require_activation_approval,
    supersede_formalization,
    validate_formalization,
    validate_formalization_transition,
)
from plzdo_local.local_memory import (
    MemoryValidationError,
    add_memory,
    build_memory_store,
    purge_memory,
    search_memory,
    stable_memory_key,
    validate_memory_store,
)
from plzdo_local.metrics import (
    MetricsValidationError,
    append_metric,
    build_metric,
    parse_metrics,
    serialize_metrics,
    summarize_metrics,
    validate_metric,
)
from plzdo_local.state import (
    BackgroundCheckpointError,
    CheckpointError,
    LoopBindingError,
    LoopContractError,
    LoopStoppedError,
    StateValidationError,
    advance_loop_contract,
    apply_checkpoint,
    build_evidence,
    build_state,
    create_checkpoint,
    create_loop_contract,
    record_state,
    stop_loop_contract,
    validate_loop_contract,
    validate_state,
    validate_state_archive,
)


def main() -> int:
    checks = [
        ("phase3 schemas remain exact local contracts", check_phase3_schemas),
        ("phase3 uses a structural Draft 2020-12 layer plus stricter typed runtime semantics", check_two_layer_schema_contract),
        ("nine credential shapes fail closed across every Phase 3 text surface", check_credential_shape_matrix),
        ("formalization approval binds governed content and terminal states", check_formalization),
        ("state compaction archives before retaining bounded newest evidence", check_state_compaction),
        ("checkpoint provenance rejects unattended and caller-asserted sources", check_checkpoints),
        ("bounded loops enforce approval binding evidence and stop conditions", check_bounded_loops),
        ("context compact and full modes share one fresh fixed-source generator", check_context_pack_contract),
        ("durable CLI persists only inside an explicit local state root", check_durable_cli),
        ("durable loop transactions serialize plan and step against supersession", check_durable_loop_races),
        ("local memory rejects private shapes and preserves supersession", check_local_memory),
        ("findings cannot disappear or close without evidence", check_findings_ledger),
        ("metrics accept only bounded typed metadata", check_metrics),
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
    print(f"phase3 check passed: {len(checks)} checks")
    return 0


def check_phase3_schemas() -> None:
    expected = {
        "schemas/formalization.schema.json": "plzdo-local.formalization.v1",
        "schemas/state.schema.json": "plzdo-local.state.v1",
        "schemas/context.schema.json": "plzdo-local.context.v1",
        "schemas/memory.schema.json": "plzdo-local.memory.v1",
        "schemas/findings.schema.json": "plzdo-local.findings.v1",
        "schemas/metric.schema.json": "plzdo-local.metric.v1",
    }
    for relative, schema_version in expected.items():
        schema = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        require(schema["additionalProperties"] is False, f"{relative} is not exact-key")
        require(
            schema["properties"]["schemaVersion"]["const"] == schema_version,
            f"{relative} schema version drift",
        )
        require(
            "runtime validation is authoritative" in schema.get("$comment", ""),
            f"{relative} does not declare runtime semantic authority",
        )


def check_two_layer_schema_contract() -> None:
    integral_json_number = json.loads("0.0")
    require(
        draft202012_structural_accepts({"type": "integer"}, integral_json_number),
        "Draft 2020-12 integer must accept a JSON number with zero fractional part",
    )
    require(
        not draft202012_structural_accepts({"type": "integer"}, False),
        "Draft 2020-12 integer must not accept a JSON boolean",
    )
    route = classify_execution("bounded production review", bounded_loop_requested=True)
    draft = build_formalization(
        formalization_id="schema-goal",
        objective="Verify the structural and runtime validation layers.",
        criteria=["Every corpus case declares both layer outcomes."],
        non_goals=["Do not use third-party validators."],
        constraints=["Keep the corpus dependency-free."],
        route=route,
        plan=["Build valid records.", "Mutate one invariant at a time."],
        evidence_contract=["Run the Phase 3 check."],
        created_at="2026-08-05T00:00:00Z",
    )
    bad_route = copy.deepcopy(draft)
    bad_route["route"]["formalizationRequired"] = False
    bad_approval = copy.deepcopy(draft)
    bad_approval["approval"] = {
        "operatorConfirmed": True,
        "approvedAt": "2026-08-05T00:00:00Z",
        "approvalHash": "a" * 64,
    }
    sensitive_draft = copy.deepcopy(draft)
    sensitive_draft["objective"] = synthetic_mixed_assignment()
    assert_two_layer_contract_corpus(
        "schemas/formalization.schema.json",
        validate_formalization,
        [
            (draft, True, None),
            (bad_route, False, FormalizationValidationError),
            (bad_approval, False, FormalizationApprovalError),
            (sensitive_draft, True, FormalizationValidationError),
        ],
    )

    state = build_state(
        work_id="schema-work",
        current="Verify the state validation layers.",
        next_step="Reject a stored skipped checkpoint.",
        updated_at="2026-08-05T00:00:00Z",
    )
    below_threshold = copy.deepcopy(state)
    below_threshold["contextCheckpoint"] = {
        "source": "self-estimate",
        "percent": 74,
        "thresholdPercent": 70,
        "effectiveThresholdPercent": 75,
        "marginPercent": 5,
        "usedTokens": None,
        "maxTokens": None,
        "interactiveTty": None,
        "createdAt": "2026-08-05T00:00:00Z",
    }
    approved = approve_formalization(
        draft,
        operator_confirmed=True,
        approved_at="2026-08-05T00:00:00Z",
    )
    loop = create_loop_contract(
        formalization=approved,
        max_iterations=2,
        timeout_seconds=60,
        checkpoint_iteration=0,
        evidence=["schema-loop"],
        started_at="2026-08-05T00:00:00Z",
    )
    loop_state = build_state(
        work_id="schema-loop-work",
        current="Verify the loop validation layers.",
        next_step="Reject mismatched terminal metadata.",
        loop_state=loop,
        updated_at="2026-08-05T00:00:00Z",
    )
    bad_loop_reason = copy.deepcopy(loop_state)
    bad_loop_reason["loopState"]["status"] = "success"
    bad_loop_reason["loopState"]["stopReason"] = "timeout"
    early_exhaustion = copy.deepcopy(loop_state)
    early_exhaustion["loopState"]["status"] = "exhausted"
    early_exhaustion["loopState"]["stopReason"] = "max-iterations"
    noncanonical_exhaustion = copy.deepcopy(loop_state)
    noncanonical_exhaustion["loopState"]["status"] = "exhausted"
    noncanonical_exhaustion["loopState"]["stopReason"] = "exhausted"
    extra_state = copy.deepcopy(state)
    extra_state["unexpected"] = True
    count_mismatch = copy.deepcopy(state)
    count_mismatch["lastEvidenceCount"] = 1
    sensitive_state = copy.deepcopy(state)
    sensitive_state["current"] = synthetic_sk_style()
    integral_float_state = copy.deepcopy(state)
    integral_float_state["archivedEvidenceCount"] = integral_json_number
    boolean_state = copy.deepcopy(state)
    boolean_state["archivedEvidenceCount"] = False
    require(
        type(integral_float_state["archivedEvidenceCount"]) is float,
        "integral-float corpus did not preserve the JSON 0.0 host representation",
    )
    assert_two_layer_contract_corpus(
        "schemas/state.schema.json",
        validate_state,
        [
            (state, True, None),
            (loop_state, True, None),
            (below_threshold, False, StateValidationError),
            (bad_loop_reason, False, LoopContractError),
            (early_exhaustion, True, LoopContractError),
            (noncanonical_exhaustion, False, LoopContractError),
            (extra_state, False, StateValidationError),
            (count_mismatch, True, StateValidationError),
            (sensitive_state, True, StateValidationError),
            (integral_float_state, True, StateValidationError),
            (boolean_state, False, StateValidationError),
        ],
    )

    memory = add_memory(
        build_memory_store(),
        label="schema layers",
        domain="workflow",
        summary="Keep structural acceptance distinct from runtime semantics.",
        created_at="2026-08-05T09:00:00+09:00",
    )
    noncanonical_memory = copy.deepcopy(memory)
    noncanonical_memory["items"][0]["createdAt"] = "2026-08-05T00:00:00+00:00"
    sensitive_memory = copy.deepcopy(memory)
    sensitive_memory["items"][0]["summary"] = synthetic_mixed_assignment()
    assert_two_layer_contract_corpus(
        "schemas/memory.schema.json",
        validate_memory_store,
        [
            (memory, True, None),
            (noncanonical_memory, False, MemoryValidationError),
            (sensitive_memory, True, MemoryValidationError),
        ],
    )

    findings = add_finding(
        build_findings_ledger(),
        finding_id="schema-finding",
        severity="low",
        title="Two-layer validation requires an executable corpus.",
        evidence=["schema-corpus"],
        created_at="2026-08-05T00:00:00Z",
    )
    open_with_resolution = copy.deepcopy(findings)
    open_with_resolution["findings"][0]["resolution"] = "Invalid while open."
    sensitive_findings = copy.deepcopy(findings)
    sensitive_findings["findings"][0]["title"] = synthetic_bearer_token()
    assert_two_layer_contract_corpus(
        "schemas/findings.schema.json",
        validate_findings_ledger,
        [
            (findings, True, None),
            (open_with_resolution, False, FindingsValidationError),
            (sensitive_findings, True, FindingsValidationError),
        ],
    )

    metric = build_metric(
        run_id="schema-metric",
        project_id="schema-project",
        route="quick",
        bounded_loop=False,
        status="succeeded",
        route_feedback="correct",
        duration_ms=1,
        changed_file_count=1,
        check_count=1,
        finding_count=0,
        recorded_at="2026-08-05T00:00:00Z",
    )
    metric_corpus: list[tuple[object, bool, Optional[Type[BaseException]]]] = [
        (metric, True, None)
    ]
    for field in ("durationMs", "changedFileCount", "checkCount", "findingCount"):
        integral_float_metric = copy.deepcopy(metric)
        integral_float_metric[field] = integral_json_number
        boolean_metric = copy.deepcopy(metric)
        boolean_metric[field] = False
        metric_corpus.extend(
            [
                (integral_float_metric, True, MetricsValidationError),
                (boolean_metric, False, MetricsValidationError),
            ]
        )
    assert_two_layer_contract_corpus(
        "schemas/metric.schema.json",
        validate_metric,
        metric_corpus,
    )

    with tempfile.TemporaryDirectory(prefix="plzdo-schema-context-") as temporary:
        root = Path(temporary).resolve() / "project"
        write_context_fixture(root)
        context = generate_context_pack(root, timestamp="2026-08-05T00:00:00Z")
        bad_mode_shape = copy.deepcopy(context)
        bad_mode_shape["controlText"] = {}
        extra_context = copy.deepcopy(context)
        extra_context["unexpected"] = True
        integral_float_context = copy.deepcopy(context)
        integral_float_context["capabilityDigest"]["inputBytes"] = float(
            context["capabilityDigest"]["inputBytes"]
        )
        boolean_context = copy.deepcopy(context)
        boolean_context["capabilityDigest"]["inputBytes"] = False
        sensitive_context = copy.deepcopy(context)
        sensitive_context["project"]["value"] = {
            "nested": {synthetic_credential_field_name(): "synthetic-value"}
        }
        assert_two_layer_contract_corpus(
            "schemas/context.schema.json",
            validate_context_pack,
            [
                (context, True, None),
                (bad_mode_shape, False, ContextValidationError),
                (extra_context, False, ContextValidationError),
                (integral_float_context, True, ContextValidationError),
                (boolean_context, False, ContextValidationError),
                (sensitive_context, True, ContextValidationError),
            ],
        )


def check_credential_shape_matrix() -> None:
    matrix = synthetic_credential_matrix()
    require(len(matrix) == 9, "credential matrix must contain exactly nine shapes")
    require(len({name for name, _ in matrix}) == len(matrix), "credential matrix names must be unique")
    route = classify_execution("bounded credential validation", bounded_loop_requested=True)
    empty_memory = build_memory_store()
    empty_findings = build_findings_ledger()
    runtime_surfaces: tuple[
        tuple[str, Type[BaseException], Callable[[str], object]], ...
    ] = (
        (
            "formalization",
            FormalizationValidationError,
            lambda shape: build_formalization(
                formalization_id="credential-matrix",
                objective=shape,
                criteria=["Reject credential-shaped formalization text."],
                non_goals=[],
                constraints=[],
                route=route,
                plan=["Validate the shared credential policy."],
                evidence_contract=["Record a typed rejection."],
                created_at="2026-08-05T00:10:00Z",
            ),
        ),
        (
            "state",
            StateValidationError,
            lambda shape: build_state(
                work_id="credential-matrix",
                current=shape,
                next_step="Reject credential-shaped state text.",
                updated_at="2026-08-05T00:10:00Z",
            ),
        ),
        (
            "memory",
            MemoryValidationError,
            lambda shape: add_memory(
                empty_memory,
                label="credential matrix",
                domain="workflow",
                summary=shape,
                created_at="2026-08-05T00:10:00Z",
            ),
        ),
        (
            "findings",
            FindingsValidationError,
            lambda shape: add_finding(
                empty_findings,
                finding_id="credential-matrix",
                severity="high",
                title=shape,
                evidence=["shared credential policy"],
                created_at="2026-08-05T00:10:00Z",
            ),
        ),
    )
    for shape_name, shape in matrix:
        for surface_name, error_type, invoke in runtime_surfaces:
            try:
                expect_error(error_type, lambda invoke=invoke, shape=shape: invoke(shape))
            except AssertionError as exc:
                raise AssertionError(f"{surface_name}/{shape_name}: {exc}") from exc

    context_inputs = (
        "project",
        "route",
        "active_formalization",
        "state_summary",
        "capabilities",
    )
    require(len(context_inputs) == 5, "nested context input inventory drifted")
    with tempfile.TemporaryDirectory(prefix="plzdo-credential-matrix-") as temporary:
        root = Path(temporary).resolve() / "project"
        write_context_fixture(root)
        for shape_name, shape in matrix:
            for input_name in context_inputs:
                nested_value = {"outer": {"inner": {"text": shape}}}
                try:
                    expect_error(
                        ContextValidationError,
                        lambda input_name=input_name, nested_value=nested_value: generate_context_pack(
                            root,
                            timestamp="2026-08-05T00:10:00Z",
                            **{input_name: nested_value},
                        ),
                    )
                except AssertionError as exc:
                    raise AssertionError(f"context.{input_name}/{shape_name}: {exc}") from exc


def check_formalization() -> None:
    route = classify_execution(
        "production architecture migration",
        bounded_loop_requested=True,
    )
    draft = build_formalization(
        formalization_id="goal-1",
        objective="Migrate the bounded architecture without changing production.",
        criteria=["The migration plan is verified by local evidence."],
        non_goals=["Do not deploy."],
        constraints=["Keep all checks local."],
        route=route,
        plan=["Inspect the current contract.", "Verify the bounded result."],
        evidence_contract=["Record the local verification report SHA-256."],
        created_at="2026-08-05T04:00:00+00:00",
    )
    validate_formalization(draft)
    expect_error(FormalizationActivationError, lambda: require_activation_approval(draft))
    expect_error(
        FormalizationApprovalError,
        lambda: approve_formalization(
            draft,
            operator_confirmed=False,
            approved_at="2026-08-05T04:01:00+00:00",
        ),
    )
    approved = approve_formalization(
        draft,
        operator_confirmed=True,
        approved_at="2026-08-05T04:01:00+00:00",
    )
    require_activation_approval(approved)
    expect_error(
        FormalizationApprovalError,
        lambda: validate_formalization_transition(draft, approved),
    )

    tampered = copy.deepcopy(approved)
    tampered["objective"] = "Silently changed objective."
    expect_error(FormalizationApprovalError, lambda: validate_formalization(tampered))
    revised = edit_formalization(
        approved,
        objective="Migrate only the reviewed architecture surface.",
        updated_at="2026-08-05T04:02:00+00:00",
    )
    require(revised["status"] == "draft" and revised["approval"] is None, "approved edit did not reopen draft")

    completed = complete_formalization(
        approved,
        evidence_reference="review/phase3-evidence.json",
        evidence_sha256="a" * 64,
        completed_at="2026-08-05T04:03:00+00:00",
    )
    require(completed["completion"]["evidenceSha256"] == "a" * 64, "completion evidence binding")
    expect_error(
        FormalizationImmutableError,
        lambda: edit_formalization(
            completed,
            objective="Forbidden terminal edit.",
            updated_at="2026-08-05T04:04:00+00:00",
        ),
    )
    superseded = supersede_formalization(
        draft,
        reason="A successor carries the revised objective.",
        superseded_at="2026-08-05T04:02:00+00:00",
    )
    expect_error(
        FormalizationImmutableError,
        lambda: supersede_formalization(
            superseded,
            reason="Do not rewrite terminal history.",
            superseded_at="2026-08-05T04:03:00+00:00",
        ),
    )
    credential_route = copy.deepcopy(route)
    credential_route["explanation"] = synthetic_authorization_header()
    expect_error(
        FormalizationValidationError,
        lambda: build_formalization(
            formalization_id="goal-sensitive",
            objective="Reject credential-shaped commitments.",
            criteria=["Keep persisted commitments sanitized."],
            non_goals=[],
            constraints=[],
            route=credential_route,
            plan=["Validate nested route text."],
            evidence_contract=["Record a typed rejection."],
            created_at="2026-08-05T04:05:00Z",
        ),
    )
    expect_error(
        FormalizationValidationError,
        lambda: complete_formalization(
            approved,
            evidence_reference=synthetic_private_key_block(),
            evidence_sha256="b" * 64,
            completed_at="2026-08-05T04:05:00Z",
        ),
    )


def check_state_compaction() -> None:
    expect_error(
        StateValidationError,
        lambda: build_evidence(
            evidence_type="check-result",
            summary=synthetic_aws_access_key(),
            recorded_at="2026-08-05T05:00:00Z",
        ),
    )
    initial_evidence = [
        build_evidence(
            evidence_type="check-result",
            summary=f"count evidence {index}",
            recorded_at="2026-08-05T05:00:00+00:00",
        )
        for index in range(40)
    ]
    state = build_state(
        work_id="work-1",
        current="Verify count compaction.",
        next_step="Inspect the archive.",
        constraints=["Preserve newest evidence."],
        evidence=initial_evidence,
        updated_at="2026-08-05T05:00:00+00:00",
    )
    newest = build_evidence(
        evidence_type="check-result",
        summary="count evidence 40",
        recorded_at="2026-08-05T05:01:00+00:00",
    )
    transition = record_state(
        state,
        updated_at="2026-08-05T05:01:00+00:00",
        evidence=[newest],
    )
    require(transition.archive is not None, "count cap did not produce an archive")
    validate_state_archive(transition.archive)
    validate_state(transition.active)
    require(transition.archive["sourceEvidenceCount"] == 41, "archive lost pre-compaction evidence")
    require(transition.active["lastEvidence"][-1] == newest, "newest count evidence was lost")
    require(transition.active["current"] == state["current"], "current field changed during compaction")
    require(transition.active["next"] == state["next"], "next field changed during compaction")

    byte_state = build_state(
        work_id="work-2",
        current="Verify byte compaction.",
        next_step="Retain the latest byte-heavy evidence.",
        updated_at="2026-08-05T05:10:00+00:00",
    )
    byte_archive = None
    latest_summary = ""
    for index in range(30):
        latest_summary = f"byte evidence {index} " + ("x" * 850)
        item = build_evidence(
            evidence_type="byte-result",
            summary=latest_summary,
            recorded_at="2026-08-05T05:10:00+00:00",
        )
        next_transition = record_state(
            byte_state,
            updated_at="2026-08-05T05:10:00+00:00",
            evidence=[item],
        )
        byte_state = next_transition.active
        if next_transition.archive is not None:
            byte_archive = next_transition.archive
            break
    require(byte_archive is not None, "byte cap did not produce an archive below the count cap")
    require(byte_archive["sourceEvidenceCount"] < 40, "byte probe accidentally hit the count cap")
    require(byte_state["lastEvidence"][-1]["summary"] == latest_summary, "newest byte evidence was lost")

    chronological = [
        build_evidence(
            evidence_type="time-result",
            summary=f"chronological evidence {index:02d}",
            recorded_at=f"2026-08-05T05:{index:02d}:00Z",
        )
        for index in range(40)
    ]
    late_old_item = build_evidence(
        evidence_type="time-result",
        summary="appended last but chronologically oldest",
        recorded_at="2026-08-05T04:59:00Z",
    )
    chronological_state = build_state(
        work_id="work-time",
        current="Verify chronological compaction.",
        next_step="Keep the newest timestamps.",
        evidence=list(reversed(chronological)),
        updated_at="2026-08-05T05:59:00Z",
    )
    chronological_transition = record_state(
        chronological_state,
        updated_at="2026-08-05T06:00:00Z",
        evidence=[late_old_item],
    )
    require(chronological_transition.archive is not None, "chronological count cap did not archive")
    require(
        chronological_transition.active["lastEvidence"] == chronological,
        "compaction did not retain evidence by chronological recency",
    )
    repeated_state = build_state(
        work_id="work-time",
        current="Verify chronological compaction.",
        next_step="Keep the newest timestamps.",
        evidence=chronological,
        updated_at="2026-08-05T05:59:00Z",
    )
    repeated_transition = record_state(
        repeated_state,
        updated_at="2026-08-05T06:00:00Z",
        evidence=[late_old_item],
    )
    require(
        chronological_transition.active == repeated_transition.active,
        "chronological compaction depends on input ordering",
    )


def check_checkpoints() -> None:
    require("source" not in inspect.signature(create_checkpoint).parameters, "caller can assert checkpoint source")
    signature = inspect.signature(create_checkpoint).parameters
    require("environment" not in signature and "interactive_tty" not in signature, "runtime provenance is caller-controlled")
    require(
        all(parameter.kind is not inspect.Parameter.VAR_KEYWORD for parameter in signature.values()),
        "checkpoint accepts hidden runtime assertions",
    )
    with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
        sys,
        "stdin",
        mock.Mock(isatty=mock.Mock(return_value=True)),
    ):
        operator = create_checkpoint(
            created_at="2026-08-05T06:00:00+00:00",
            operator_percent=70,
        )
        token_count = create_checkpoint(
            created_at="2026-08-05T06:00:01+00:00",
            used_tokens=700,
            max_tokens=1000,
        )
        estimate = create_checkpoint(
            created_at="2026-08-05T06:00:02+00:00",
            self_estimate=75,
        )
        skipped = create_checkpoint(
            created_at="2026-08-05T06:00:03+00:00",
            self_estimate=74,
        )
        maximum_count = (1 << 63) - 1
        threshold_count = (maximum_count * 70 + 99) // 100
        exact_large = create_checkpoint(
            created_at="2026-08-05T06:00:04+00:00",
            used_tokens=threshold_count,
            max_tokens=maximum_count,
        )
        exact_large_below = create_checkpoint(
            created_at="2026-08-05T06:00:05+00:00",
            used_tokens=threshold_count - 1,
            max_tokens=maximum_count,
        )
        expect_error(
            CheckpointError,
            lambda: create_checkpoint(
                created_at="2026-08-05T06:00:06+00:00",
                used_tokens=7 * 10**399,
                max_tokens=10**400,
            ),
        )
    require(operator["source"] == "operator-observed", "operator provenance")
    require(token_count["source"] == "token-count", "token-count provenance")
    require(estimate["source"] == "self-estimate" and estimate["status"] == "created", "self-estimate provenance")
    require(exact_large["status"] == "created", "large exact token threshold")
    require(exact_large_below["status"] == "skipped", "large token arithmetic rounded into a checkpoint")
    require(skipped["status"] == "skipped" and skipped["checkpoint"] is None, "below-threshold result")
    state = build_state(
        work_id="work-3",
        current="Check context pressure.",
        next_step="Persist only a reached checkpoint.",
        updated_at="2026-08-05T06:00:00+00:00",
    )
    expect_error(
        CheckpointError,
        lambda: apply_checkpoint(state, skipped, updated_at="2026-08-05T06:00:03+00:00"),
    )
    applied = apply_checkpoint(state, operator, updated_at="2026-08-05T06:00:04+00:00")
    require(applied.active["contextCheckpoint"]["source"] == "operator-observed", "checkpoint was not applied")
    forged_stored = copy.deepcopy(operator["checkpoint"])
    forged_stored["percent"] = 69
    expect_error(
        StateValidationError,
        lambda: build_state(
            work_id="work-forged-checkpoint",
            current="Reject stored below-threshold state.",
            next_step="Keep state fail-closed.",
            context_checkpoint=forged_stored,
            updated_at="2026-08-05T06:00:05+00:00",
        ),
    )
    for marker in (
        {"CI": "true"},
        {"CODEX_CI": "1"},
        {"GITHUB_RUN_ID": "123"},
        {"PLZDO_EXECUTION_MODE": "headless"},
    ):
        with mock.patch.dict(os.environ, marker, clear=True):
            expect_error(
                BackgroundCheckpointError,
                lambda: create_checkpoint(
                    created_at="2026-08-05T06:00:06+00:00",
                    self_estimate=90,
                ),
            )
    with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
        sys,
        "stdin",
        mock.Mock(isatty=mock.Mock(return_value=False)),
    ):
        expect_error(
            TypeError,
            lambda: create_checkpoint(
                created_at="2026-08-05T06:00:07+00:00",
                operator_percent=70,
                interactive_tty=True,
            ),
        )
        expect_error(
            TypeError,
            lambda: create_checkpoint(
                created_at="2026-08-05T06:00:07+00:00",
                self_estimate=80,
                environment={},
            ),
        )


def check_bounded_loops() -> None:
    draft = build_formalization(
        formalization_id="goal-1",
        objective="Run a bounded local verification loop.",
        criteria=["The loop stops with typed evidence."],
        non_goals=["Do not control a model process."],
        constraints=["Recheck approval on every transition."],
        route=classify_execution("production verification loop", bounded_loop_requested=True),
        plan=["Observe.", "Verify."],
        evidence_contract=["Record each checkpoint."],
        created_at="2026-08-05T06:59:00Z",
    )
    approved = approve_formalization(
        draft,
        operator_confirmed=True,
        approved_at="2026-08-05T06:59:30Z",
    )
    for function in (create_loop_contract, advance_loop_contract, stop_loop_contract):
        parameters = inspect.signature(function).parameters
        require(
            not {"formalization_id", "approval_hash", "elapsed_seconds"} & set(parameters),
            "loop binding or elapsed time remains caller-controlled",
        )
        require(
            all(parameter.kind is not inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()),
            "loop API accepts hidden authority assertions",
        )
    expect_error(
        TypeError,
        lambda: create_loop_contract(
            formalization_id=approved["id"],
            approval_hash=approved["approval"]["approvalHash"],
            max_iterations=3,
            timeout_seconds=100,
            checkpoint_iteration=0,
            evidence=["forged binding"],
            started_at="2026-08-05T07:00:00Z",
        ),
    )
    loop = create_loop_contract(
        formalization=approved,
        max_iterations=3,
        timeout_seconds=100,
        checkpoint_iteration=0,
        evidence=["initial evidence"],
        started_at="2026-08-05T07:00:00+00:00",
    )
    require(loop["trackingOnly"] is True, "loop must remain tracking-only")
    require(loop["modelProcessTerminationClaimed"] is False, "loop claimed process control")
    expect_error(
        TypeError,
        lambda: stop_loop_contract(
            loop,
            formalization_id=approved["id"],
            approval_hash=approved["approval"]["approvalHash"],
            checkpoint_iteration=0,
            reason="blocked",
            evidence=["forged binding"],
            stopped_at="2026-08-05T07:00:01Z",
        ),
    )
    expect_error(
        TypeError,
        lambda: advance_loop_contract(
            loop,
            formalization=approved,
            approval_hash="c" * 64,
            checkpoint_iteration=0,
            evidence=["changed evidence"],
            advanced_at="2026-08-05T07:00:01+00:00",
        ),
    )
    superseded = supersede_formalization(
        approved,
        reason="A successor owns subsequent loop work.",
        superseded_at="2026-08-05T07:00:00Z",
    )
    expect_error(
        LoopBindingError,
        lambda: advance_loop_contract(
            loop,
            formalization=superseded,
            checkpoint_iteration=0,
            evidence=["must not advance"],
            advanced_at="2026-08-05T07:00:01Z",
        ),
    )
    tampered = copy.deepcopy(approved)
    tampered["objective"] = "Unapproved loop objective."
    expect_error(
        LoopBindingError,
        lambda: advance_loop_contract(
            loop,
            formalization=tampered,
            checkpoint_iteration=0,
            evidence=["must not advance"],
            advanced_at="2026-08-05T07:00:01Z",
        ),
    )
    first = advance_loop_contract(
        loop,
        formalization=approved,
        checkpoint_iteration=0,
        evidence=["initial evidence"],
        advanced_at="2026-08-05T07:00:01+00:00",
    )
    second = advance_loop_contract(
        first,
        formalization=approved,
        checkpoint_iteration=1,
        evidence=["initial evidence"],
        advanced_at="2026-08-05T07:00:02+00:00",
    )
    require(second["status"] == "stagnated", "stagnation did not stop the loop")
    expect_error(
        LoopStoppedError,
        lambda: advance_loop_contract(
            second,
            formalization=approved,
            checkpoint_iteration=2,
            evidence=["late evidence"],
            advanced_at="2026-08-05T07:00:03+00:00",
        ),
    )

    max_loop = create_loop_contract(
        formalization=approved,
        max_iterations=1,
        timeout_seconds=100,
        checkpoint_iteration=0,
        evidence=["start"],
        started_at="2026-08-05T07:10:00+00:00",
    )
    exhausted = advance_loop_contract(
        max_loop,
        formalization=approved,
        checkpoint_iteration=0,
        evidence=["iteration one"],
        advanced_at="2026-08-05T07:10:01+00:00",
    )
    require(exhausted["status"] == "exhausted" and exhausted["stopReason"] == "max-iterations", "max bound")
    collision_loop = create_loop_contract(
        formalization=approved,
        max_iterations=2,
        timeout_seconds=100,
        checkpoint_iteration=0,
        evidence=["same evidence"],
        started_at="2026-08-05T07:15:00Z",
    )
    collision_first = advance_loop_contract(
        collision_loop,
        formalization=approved,
        checkpoint_iteration=0,
        evidence=["same evidence"],
        advanced_at="2026-08-05T07:15:01Z",
    )
    collision_terminal = advance_loop_contract(
        collision_first,
        formalization=approved,
        checkpoint_iteration=1,
        evidence=["same evidence"],
        advanced_at="2026-08-05T07:15:02Z",
    )
    require(
        collision_terminal["status"] == "exhausted"
        and collision_terminal["stopReason"] == "max-iterations",
        "loop bound priority is not canonical when stagnation coincides",
    )

    timeout_loop = create_loop_contract(
        formalization=approved,
        max_iterations=5,
        timeout_seconds=2,
        checkpoint_iteration=0,
        evidence=["start"],
        started_at="2026-08-05T07:20:00+00:00",
    )
    timeout = advance_loop_contract(
        timeout_loop,
        formalization=approved,
        checkpoint_iteration=0,
        evidence=["timeout boundary"],
        advanced_at="2026-08-05T07:20:02+00:00",
    )
    require(timeout["status"] == "exhausted" and timeout["stopReason"] == "timeout", "timeout bound")
    forged_timeout_status = copy.deepcopy(timeout)
    forged_timeout_status["status"] = "success"
    forged_timeout_status["stopReason"] = "success"
    expect_error(LoopContractError, lambda: validate_loop_contract(forged_timeout_status))
    late_timeout = advance_loop_contract(
        timeout_loop,
        formalization=approved,
        checkpoint_iteration=0,
        evidence=["late timeout"],
        advanced_at="2026-08-05T07:20:03+00:00",
    )
    require(
        late_timeout["status"] == "exhausted"
        and late_timeout["stopReason"] == "timeout"
        and late_timeout["elapsedSeconds"] == 3,
        "timeout overrun did not derive canonical automatic exhaustion",
    )
    expect_error(
        TypeError,
        lambda: advance_loop_contract(
            timeout_loop,
            formalization=approved,
            checkpoint_iteration=0,
            evidence=["forged elapsed"],
            advanced_at="2026-08-05T07:20:01+00:00",
            elapsed_seconds=0,
        ),
    )
    expect_error(
        LoopContractError,
        lambda: advance_loop_contract(
            timeout_loop,
            formalization=approved,
            checkpoint_iteration=0,
            evidence=["fractional elapsed"],
            advanced_at="2026-08-05T07:20:00.500000+00:00",
        ),
    )
    stopped = stop_loop_contract(
        timeout_loop,
        formalization=approved,
        checkpoint_iteration=0,
        reason="success",
        evidence=["verified success"],
        stopped_at="2026-08-05T07:20:01+00:00",
    )
    validate_loop_contract(stopped)
    mismatched_reason = copy.deepcopy(stopped)
    mismatched_reason["stopReason"] = "timeout"
    expect_error(LoopContractError, lambda: validate_loop_contract(mismatched_reason))
    expect_error(
        LoopContractError,
        lambda: stop_loop_contract(
            timeout_loop,
            formalization=approved,
            checkpoint_iteration=0,
            reason="exhausted",
            evidence=["caller cannot select exhaustion"],
            stopped_at="2026-08-05T07:20:01Z",
        ),
    )


def check_context_pack_contract() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-context-") as temporary:
        root = Path(temporary).resolve() / "project"
        write_context_fixture(root)
        kwargs = {
            "timestamp": "2026-08-05T08:00:00Z",
            "project": {"id": "fixture-project"},
            "route": {"weight": "plan"},
            "active_formalization": {"id": "goal-1", "status": "approved"},
            "state_summary": {"current": "verify context"},
            "capabilities": ["context", "formalization", "state"],
        }
        compact = generate_context_pack(root, mode="compact", **kwargs)
        repeated = generate_context_pack(root, mode="compact", **kwargs)
        full = generate_context_pack(root, mode="full", **kwargs)
        require(serialize_context_pack(compact) == serialize_context_pack(repeated), "compact render is not deterministic")
        require(compact["sourceManifest"] == full["sourceManifest"], "compact/full source manifests diverged")
        require(compact["controlText"] is None and isinstance(full["controlText"], dict), "mode shape")
        require(all(compact[key]["authoritative"] is False for key in ("project", "route", "activeFormalization", "stateSummary")), "projection authority")
        require(parse_context_pack(serialize_context_pack(full)) == full, "context JSON round trip")
        require(freshness_report(compact, root)["status"] == "fresh", "fresh context reported stale")

        changed_capabilities = generate_context_pack(
            root,
            mode="compact",
            **{**kwargs, "capabilities": ["context", "formalization", "state", "memory"]},
        )
        require(
            compact["capabilityDigest"]["sha256"] != changed_capabilities["capabilityDigest"]["sha256"],
            "capability digest ignored input drift",
        )
        expect_error(
            ContextValidationError,
            lambda: generate_context_pack(
                root,
                timestamp="2026-08-05T08:00:00Z",
                project={synthetic_credential_field_name(): "synthetic-value"},
            ),
        )
        (root / "CHECKS.md").write_text("# Checks\n\nChanged after generation.\n", encoding="utf-8")
        require(freshness_report(compact, root)["status"] == "stale", "source drift was not detected")
        expect_error(ContextStaleError, lambda: check_context_pack(compact, root))
        expect_error(ContextValidationError, lambda: validate_source_path("../AGENTS.md"))
        expect_error(
            ContextValidationError,
            lambda: parse_context_pack('{"schemaVersion":"one","schemaVersion":"two"}'),
        )

    with tempfile.TemporaryDirectory(prefix="plzdo-context-link-") as temporary:
        base = Path(temporary).resolve()
        root = base / "project"
        write_context_fixture(root)
        outside = base / "outside.md"
        outside.write_text("outside\n", encoding="utf-8")
        (root / "AGENTS.md").unlink()
        (root / "AGENTS.md").symlink_to(outside)
        expect_error(ContextSourceError, lambda: generate_context_pack(root, timestamp="2026-08-05T08:00:00Z"))

    with tempfile.TemporaryDirectory(prefix="plzdo-context-sensitive-") as temporary:
        root = Path(temporary).resolve() / "project"
        write_context_fixture(root)
        (root / "CHECKS.md").write_text(
            "# Checks\n\n" + synthetic_mixed_assignment() + "\n",
            encoding="utf-8",
        )
        expect_error(
            ContextSourceError,
            lambda: generate_context_pack(root, timestamp="2026-08-05T08:00:00Z"),
        )

    with tempfile.TemporaryDirectory(prefix="plzdo-context-race-") as temporary:
        root = Path(temporary).resolve() / "project"
        write_context_fixture(root)
        target = root / "AGENTS.md"
        original_reader = context_module._read_relative_regular_file
        calls = 0

        def mutate_after_first_pass(*args: object, **kwargs: object) -> object:
            nonlocal calls
            result = original_reader(*args, **kwargs)
            calls += 1
            if calls == len(context_module.PROJECT_CONTROL_PATHS):
                target.write_text("# Agent Guide\n\nChanged during generation.\n", encoding="utf-8")
            return result

        with mock.patch.object(context_module, "_read_relative_regular_file", mutate_after_first_pass):
            expect_error(
                ContextSourceError,
                lambda: generate_context_pack(root, timestamp="2026-08-05T08:00:00Z"),
            )

    with tempfile.TemporaryDirectory(prefix="plzdo-context-root-race-") as temporary:
        base = Path(temporary).resolve()
        root = base / "project"
        old_root = base / "old-project"
        write_context_fixture(root)
        original_reader = context_module._read_relative_regular_file
        calls = 0

        def replace_root_after_first_pass(*args: object, **kwargs: object) -> object:
            nonlocal calls
            result = original_reader(*args, **kwargs)
            calls += 1
            if calls == len(context_module.PROJECT_CONTROL_PATHS):
                root.rename(old_root)
                write_context_fixture(root)
            return result

        with mock.patch.object(context_module, "_read_relative_regular_file", replace_root_after_first_pass):
            expect_error(
                ContextSourceError,
                lambda: generate_context_pack(root, timestamp="2026-08-05T08:00:00Z"),
            )


def check_durable_cli() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-durable-cli-") as temporary:
        base = Path(temporary).resolve()
        state_root = base / "state"
        project = base / "project"
        write_context_fixture(project)
        previous = os.environ.get("PLZDO_HOME")
        os.environ["PLZDO_HOME"] = str(state_root)
        try:
            code, draft, _ = run_cli(
                [
                    "formalize",
                    "draft",
                    "production architecture migration",
                    "--id",
                    "goal-cli",
                    "--bounded-loop",
                    "--json",
                ]
            )
            require(code == 0 and draft["status"] == "draft", "CLI formalization draft")
            code, _, error = run_cli(["formalize", "approve", "goal-cli", "--json"])
            require(code == 2 and "interactive TTY" in error, "non-TTY approval was not rejected")
            disk_draft = json.loads((state_root / "formalizations" / "goal-cli.json").read_text(encoding="utf-8"))
            require(disk_draft["status"] == "draft", "failed approval changed durable state")

            approved = approve_formalization(
                disk_draft,
                operator_confirmed=True,
                approved_at=disk_draft["createdAt"],
            )
            (state_root / "formalizations" / "goal-cli.json").write_text(
                json.dumps(approved, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            code, context, _ = run_cli(
                ["context", "render", "--root", str(project), "--mode", "compact", "--json"]
            )
            require(code == 0 and context["localOnly"] is True, "CLI context render")
            code, freshness, _ = run_cli(
                ["context", "check", "--root", str(project), "--json"]
            )
            require(code == 0 and freshness["status"] == "fresh", "CLI context freshness")

            code, state_status, _ = run_cli(
                [
                    "state",
                    "record",
                    "--work-id",
                    "work-cli",
                    "--current",
                    "Verify the durable CLI.",
                    "--next",
                    "Inspect local evidence.",
                    "--evidence",
                    "The state record command completed locally.",
                    "--json",
                ]
            )
            require(code == 0 and state_status["workId"] == "work-cli", "CLI state record")
            state_path = state_root / "state" / "state.json"
            before_skip = state_path.read_bytes()
            with mock.patch.dict(os.environ, {"PLZDO_HOME": str(state_root)}, clear=True):
                code, skipped, _ = run_cli(["state", "checkpoint", "--self-estimate", "74", "--json"])
            require(code == 0 and skipped["status"] == "skipped", "CLI checkpoint skip")
            require(state_path.read_bytes() == before_skip, "skipped checkpoint wrote state")

            code, loop, _ = run_cli(
                [
                    "loop",
                    "plan",
                    "--checkpoint",
                    "loop-cli",
                    "--formalization",
                    "goal-cli",
                    "--max-iterations",
                    "2",
                    "--timeout-seconds",
                    "60",
                    "--evidence",
                    "Loop plan evidence.",
                    "--json",
                ]
            )
            require(code == 0 and loop["status"] == "active", "CLI loop plan")
            code, loop_step, _ = run_cli(
                ["loop", "step", "--checkpoint", "loop-cli", "--evidence", "Iteration evidence.", "--json"]
            )
            require(code == 0 and loop_step["iteration"] == 1, "CLI loop step")

            code, memory_item, _ = run_cli(
                [
                    "memory",
                    "add",
                    "--label",
                    "route feedback",
                    "--domain",
                    "workflow",
                    "--summary",
                    "Use the plan route for a bounded cross-module change.",
                    "--json",
                ]
            )
            require(code == 0 and memory_item["sourceOfTruth"] is False, "CLI memory add")
            code, memory_matches, _ = run_cli(["memory", "search", "cross-module", "--json"])
            require(code == 0 and len(memory_matches["items"]) == 1, "CLI memory search")

            code, ledger, _ = run_cli(
                [
                    "findings",
                    "add",
                    "phase3-cli",
                    "--severity",
                    "medium",
                    "--title",
                    "CLI lifecycle needs executable evidence.",
                    "--evidence",
                    "phase3-cli-fixture",
                    "--json",
                ]
            )
            require(code == 0 and ledger["findings"][0]["status"] == "open", "CLI finding add")
            code, ledger, _ = run_cli(
                [
                    "findings",
                    "close",
                    "phase3-cli",
                    "--resolution",
                    "The executable fixture now covers the lifecycle.",
                    "--evidence",
                    "phase3-cli-pass",
                    "--json",
                ]
            )
            require(code == 0 and ledger["findings"][0]["status"] == "closed", "CLI finding close")

            code, metric, _ = run_cli(
                [
                    "metrics",
                    "record",
                    "--run-id",
                    "run-cli",
                    "--route",
                    "goal",
                    "--bounded-loop",
                    "--status",
                    "succeeded",
                    "--route-feedback",
                    "correct",
                    "--duration-ms",
                    "100",
                    "--checks",
                    "10",
                    "--json",
                ]
            )
            require(code == 0 and metric["sourceOfTruth"] is False, "CLI metric record")
            code, metrics_summary, _ = run_cli(["metrics", "summary", "--json"])
            require(code == 0 and metrics_summary["runCount"] == 1, "CLI metric summary")

            evidence_path = base / "completion-evidence.json"
            evidence_path.write_text('{"status":"passed"}\n', encoding="utf-8")
            code, completed, _ = run_cli(
                [
                    "formalize",
                    "complete",
                    "goal-cli",
                    "--evidence",
                    str(evidence_path),
                    "--json",
                ]
            )
            require(code == 0 and completed["status"] == "completed", "CLI formalization completion")
            require(completed["completion"]["evidenceReference"].startswith("sha256:"), "private evidence path persisted")
            require(not any(path.is_symlink() for path in state_root.rglob("*")), "state root contains symlinks")
        finally:
            if previous is None:
                os.environ.pop("PLZDO_HOME", None)
            else:
                os.environ["PLZDO_HOME"] = previous


def check_durable_loop_races() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-loop-races-") as temporary:
        state_root = Path(temporary).resolve() / "state"
        previous = os.environ.get("PLZDO_HOME")
        os.environ["PLZDO_HOME"] = str(state_root)
        try:
            route = classify_execution(
                "bounded race verification",
                bounded_loop_requested=True,
            )

            def approved_record(formalization_id: str) -> dict[str, object]:
                draft = build_formalization(
                    formalization_id=formalization_id,
                    objective="Serialize loop work against formalization supersession.",
                    criteria=["Only a lock-consistent approved snapshot may transition."],
                    non_goals=["Do not control a model process."],
                    constraints=["Acquire lifecycle and loop locks in one order."],
                    route=route,
                    plan=["Acquire locks.", "Reread state.", "Commit one transition."],
                    evidence_contract=["Record the deterministic race result."],
                    created_at="2026-08-05T09:00:00Z",
                )
                return approve_formalization(
                    draft,
                    operator_confirmed=True,
                    approved_at="2026-08-05T09:00:01Z",
                )

            results: dict[str, object] = {}
            errors: dict[str, BaseException] = {}

            def start(name: str, function: Callable[[], object]) -> threading.Thread:
                def target() -> None:
                    try:
                        results[name] = function()
                    except BaseException as exc:
                        errors[name] = exc

                thread = threading.Thread(target=target, name=name, daemon=True)
                thread.start()
                return thread

            def join(thread: threading.Thread) -> None:
                thread.join(2)
                require(not thread.is_alive(), f"race thread did not finish: {thread.name}")

            plan_record = approved_record("goal-plan-race")
            durable_cli_module._write_formalization_new(plan_record)
            supersede_entered = threading.Event()
            release_supersede = threading.Event()

            def hold_plan_supersession(value: dict[str, object]) -> dict[str, object]:
                supersede_entered.set()
                require(release_supersede.wait(2), "plan-race supersession was not released")
                return supersede_formalization(
                    value,
                    reason="Supersession wins before loop planning.",
                    superseded_at="2026-08-05T09:00:02Z",
                )

            superseder = start(
                "plan-superseder",
                lambda: durable_cli_module._update_formalization(
                    "goal-plan-race",
                    hold_plan_supersession,
                ),
            )
            require(supersede_entered.wait(1), "plan-race supersession did not acquire its lock")
            planner_attempted = threading.Event()
            plan_builder_entered = threading.Event()

            def plan_after_attempt() -> object:
                planner_attempted.set()
                return durable_cli_module._write_loop_new(
                    "loop-plan-race",
                    "goal-plan-race",
                    lambda formalization: (
                        plan_builder_entered.set()
                        or create_loop_contract(
                            formalization=formalization,
                            max_iterations=3,
                            timeout_seconds=60,
                            checkpoint_iteration=0,
                            evidence=["plan race"],
                            started_at="2026-08-05T09:00:03Z",
                        )
                    ),
                )

            planner = start("planner", plan_after_attempt)
            require(planner_attempted.wait(1), "plan-race planner did not start")
            require(
                not plan_builder_entered.wait(0.1),
                "loop plan bypassed the formalization lifecycle lock",
            )
            release_supersede.set()
            join(superseder)
            join(planner)
            require("plan-superseder" not in errors, "plan-race supersession failed")
            require(
                type(errors.get("planner")) is FormalizationActivationError,
                "superseded formalization did not block a waiting loop plan",
            )
            require(
                not (state_root / "loops" / "loop-plan-race.json").exists(),
                "blocked loop plan wrote a checkpoint",
            )

            step_record = approved_record("goal-step-race")
            durable_cli_module._write_formalization_new(step_record)
            durable_cli_module._write_loop_new(
                "loop-step-race",
                "goal-step-race",
                lambda formalization: create_loop_contract(
                    formalization=formalization,
                    max_iterations=3,
                    timeout_seconds=60,
                    checkpoint_iteration=0,
                    evidence=["step race start"],
                    started_at="2026-08-05T09:10:00Z",
                ),
            )
            step_entered = threading.Event()
            release_step = threading.Event()

            def hold_step(loop: dict[str, object], formalization: dict[str, object]) -> dict[str, object]:
                step_entered.set()
                require(release_step.wait(2), "step race was not released")
                return advance_loop_contract(
                    loop,
                    formalization=formalization,
                    checkpoint_iteration=0,
                    evidence=["step race committed"],
                    advanced_at="2026-08-05T09:10:01Z",
                )

            stepper = start(
                "stepper",
                lambda: durable_cli_module._update_loop("loop-step-race", hold_step),
            )
            require(step_entered.wait(1), "step race did not acquire both locks")
            step_supersede_entered = threading.Event()
            supersede_attempted = threading.Event()

            def supersede_after_step(value: dict[str, object]) -> dict[str, object]:
                step_supersede_entered.set()
                return supersede_formalization(
                    value,
                    reason="Subsequent loop work is revoked.",
                    superseded_at="2026-08-05T09:10:02Z",
                )

            def attempt_step_supersession() -> object:
                supersede_attempted.set()
                return durable_cli_module._update_formalization(
                    "goal-step-race",
                    supersede_after_step,
                )

            step_superseder = start("step-superseder", attempt_step_supersession)
            require(supersede_attempted.wait(1), "step-race supersession did not start")
            require(
                not step_supersede_entered.wait(0.1),
                "supersession entered while a loop step held lifecycle and loop locks",
            )
            release_step.set()
            join(stepper)
            join(step_superseder)
            require(not errors.keys() & {"stepper", "step-superseder"}, "step race transition failed")
            require(results["stepper"]["iteration"] == 1, "serialized loop step was not committed")
            require(
                results["step-superseder"]["status"] == "superseded",
                "step-race supersession was not committed after the step",
            )
            expect_error(
                FormalizationActivationError,
                lambda: durable_cli_module._update_loop(
                    "loop-step-race",
                    lambda loop, formalization: advance_loop_contract(
                        loop,
                        formalization=formalization,
                        checkpoint_iteration=loop["checkpointIteration"],
                        evidence=["must not run after supersession"],
                        advanced_at="2026-08-05T09:10:03Z",
                    ),
                ),
            )
        finally:
            if previous is None:
                os.environ.pop("PLZDO_HOME", None)
            else:
                os.environ["PLZDO_HOME"] = previous


def check_local_memory() -> None:
    store = build_memory_store()
    first = add_memory(
        store,
        label="routing feedback",
        domain="workflow",
        summary="Use the quick route for a bounded documentation correction.",
        created_at="2026-08-05T01:00:00+00:00",
    )
    require(first["items"][0]["createdAt"] == "2026-08-05T01:00:00Z", "memory timestamp was not normalized to UTC")
    second = add_memory(
        first,
        label="routing feedback",
        domain="workflow",
        summary="Use the plan route when a bounded change crosses two modules.",
        created_at="2026-08-05T01:01:00+00:00",
    )
    require(len(second["items"]) == 2, "memory supersession lost history")
    require([item["state"] for item in second["items"]].count("active") == 1, "memory active cardinality")
    matches = search_memory(second, "two modules")
    require(len(matches) == 1 and matches[0]["state"] == "active", "bounded memory search")
    stable_key = stable_memory_key("routing feedback", "workflow")
    purged, removed = purge_memory(second, stable_key=stable_key)
    require(removed == 2 and purged["items"] == [], "stable-key purge")

    expect_error(
        MemoryValidationError,
        lambda: add_memory(
            store,
            label="raw output",
            domain="workflow",
            summary="ERROR first\nERROR second\nERROR third\nERROR fourth",
            created_at="2026-08-05T01:03:00+00:00",
        ),
    )
    forged = copy.deepcopy(first)
    forged["sourceOfTruth"] = True
    expect_error(MemoryValidationError, lambda: validate_memory_store(forged))
    forged_key = copy.deepcopy(first)
    forged_key["items"][0]["stableKey"] = "mem-00000000000000000000"
    expect_error(MemoryValidationError, lambda: validate_memory_store(forged_key))
    forged_id = copy.deepcopy(first)
    forged_id["items"][0]["id"] = "note-000000000000000000000000"
    expect_error(MemoryValidationError, lambda: validate_memory_store(forged_id))
    forged_text = copy.deepcopy(first)
    forged_text["items"][0]["summary"] += " "
    expect_error(MemoryValidationError, lambda: validate_memory_store(forged_text))
    noncanonical_time = copy.deepcopy(first)
    noncanonical_time["items"][0]["createdAt"] = "2026-08-05T01:00:00+00:00"
    expect_error(MemoryValidationError, lambda: validate_memory_store(noncanonical_time))
    broken_chain = copy.deepcopy(first)
    broken_chain["items"][0]["state"] = "superseded"
    expect_error(MemoryValidationError, lambda: validate_memory_store(broken_chain))
    expect_error(MemoryValidationError, lambda: purge_memory(first))

    zoned = add_memory(
        store,
        label="utc chronology",
        domain="workflow",
        summary="Normalize offset timestamps before ordering memory history.",
        created_at="2026-08-05T10:00:00+09:00",
    )
    require(zoned["items"][0]["createdAt"] == "2026-08-05T01:00:00Z", "offset timestamp normalization")
    expect_error(
        MemoryValidationError,
        lambda: add_memory(
            zoned,
            label="utc chronology",
            domain="workflow",
            summary="Equivalent instants cannot advance supersession history.",
            created_at="2026-08-05T01:00:00Z",
        ),
    )

    chronological = add_memory(
        store,
        label="whole second",
        domain="workflow",
        summary="The whole-second record is chronologically first.",
        created_at="2026-08-05T01:10:00Z",
    )
    chronological = add_memory(
        chronological,
        label="microsecond",
        domain="workflow",
        summary="The microsecond record follows within the same second.",
        created_at="2026-08-05T01:10:00.500000Z",
    )
    chronological = add_memory(
        chronological,
        label="next second",
        domain="workflow",
        summary="The next whole-second record remains last.",
        created_at="2026-08-05T01:10:01Z",
    )
    require(
        [item["createdAt"] for item in chronological["items"]]
        == [
            "2026-08-05T01:10:00Z",
            "2026-08-05T01:10:00.500000Z",
            "2026-08-05T01:10:01Z",
        ],
        "memory ordering compared timestamp text instead of parsed instants",
    )
    microsecond_chain = add_memory(
        store,
        label="precision transition",
        domain="workflow",
        summary="Whole-second baseline.",
        created_at="2026-08-05T01:20:00Z",
    )
    microsecond_chain = add_memory(
        microsecond_chain,
        label="precision transition",
        domain="workflow",
        summary="Microsecond successor.",
        created_at="2026-08-05T01:20:00.000001Z",
    )
    require(
        [item["state"] for item in microsecond_chain["items"]] == ["superseded", "active"],
        "microsecond supersession did not advance parsed chronology",
    )


def check_findings_ledger() -> None:
    ledger = add_finding(
        build_findings_ledger(),
        finding_id="route-1",
        severity="medium",
        title="The route was too heavy for the observed change.",
        evidence=["fixture-route-1"],
        created_at="2026-08-05T02:00:00+00:00",
    )
    closed = close_finding(
        ledger,
        "route-1",
        resolution="The classifier now keeps project identity out of weight selection.",
        evidence=["phase2-route-regression"],
        updated_at="2026-08-05T02:01:00+00:00",
    )
    require(closed["findings"][0]["status"] == "closed", "finding did not close")
    expect_error(
        FindingTransitionError,
        lambda: accept_finding_risk(
            closed,
            "route-1",
            resolution="Do not rewrite a terminal finding.",
            evidence=["invalid-transition"],
            updated_at="2026-08-05T02:02:00+00:00",
        ),
    )
    removed = copy.deepcopy(closed)
    removed["findings"] = []
    expect_error(FindingTransitionError, lambda: validate_findings_transition(closed, removed))
    rewritten_evidence = copy.deepcopy(closed)
    rewritten_evidence["findings"][0]["evidence"][0] = "rewritten-history"
    expect_error(
        FindingTransitionError,
        lambda: validate_findings_transition(ledger, rewritten_evidence),
    )
    expect_error(
        FindingTransitionError,
        lambda: validate_findings_transition(build_findings_ledger(), closed),
    )
    delayed_new = copy.deepcopy(ledger)
    delayed_new["findings"][0]["updatedAt"] = "2026-08-05T02:01:00+00:00"
    expect_error(
        FindingTransitionError,
        lambda: validate_findings_transition(build_findings_ledger(), delayed_new),
    )
    expect_error(
        FindingsValidationError,
        lambda: close_finding(
            ledger,
            "route-1",
            resolution="Evidence is mandatory.",
            evidence=[],
            updated_at="2026-08-05T02:01:00+00:00",
        ),
    )
    later_open = copy.deepcopy(ledger)
    later_open["findings"][0]["updatedAt"] = "2026-08-05T02:05:00+00:00"
    validate_findings_ledger(later_open)
    expect_error(
        FindingTransitionError,
        lambda: close_finding(
            later_open,
            "route-1",
            resolution="Transition time must remain monotonic.",
            evidence=["monotonic-time"],
            updated_at="2026-08-05T02:04:00+00:00",
        ),
    )
    expect_error(
        FindingsValidationError,
        lambda: close_finding(
            ledger,
            "route-1",
            resolution="Time cannot move backward.",
            evidence=["invalid-time"],
            updated_at="2026-08-05T01:59:00+00:00",
        ),
    )


def check_metrics() -> None:
    first = build_metric(
        run_id="run-1",
        project_id="alpha-app",
        route="quick",
        bounded_loop=False,
        status="succeeded",
        route_feedback="correct",
        duration_ms=1200,
        changed_file_count=1,
        check_count=3,
        finding_count=0,
        recorded_at="2026-08-05T03:00:00+00:00",
    )
    second = build_metric(
        run_id="run-2",
        project_id=None,
        route="plan",
        bounded_loop=False,
        status="blocked",
        route_feedback="over-routed",
        duration_ms=800,
        changed_file_count=0,
        check_count=1,
        finding_count=1,
        recorded_at="2026-08-05T03:01:00+00:00",
    )
    records = append_metric([], first)
    records = append_metric(records, second)
    text = serialize_metrics(records)
    require(parse_metrics(text) == records, "metric JSONL round trip")
    summary = summarize_metrics(records)
    require(summary["runCount"] == 2 and summary["totalDurationMs"] == 2000, "metric summary")
    expect_error(MetricsValidationError, lambda: append_metric(records, first))
    forged = copy.deepcopy(first)
    forged["durationMs"] = False
    expect_error(MetricsValidationError, lambda: serialize_metrics([forged]))
    expect_error(MetricsValidationError, lambda: parse_metrics('{"schemaVersion":"plzdo-local.metric.v1","runId":"run-1","runId":"run-2"}\n'))
    time_reversed = copy.deepcopy(second)
    time_reversed["recordedAt"] = "2026-08-05T05:00:00+03:00"
    expect_error(MetricsValidationError, lambda: serialize_metrics([first, time_reversed]))


def assert_two_layer_contract_corpus(
    relative_schema: str,
    runtime_validator: Callable[[object], None],
    corpus: list[tuple[object, bool, Optional[Type[BaseException]]]],
) -> None:
    schema = json.loads((ROOT / relative_schema).read_text(encoding="utf-8"))
    for index, (value, expected_schema, expected_runtime_error) in enumerate(corpus):
        schema_result = draft202012_structural_accepts(schema, value)
        runtime_error: Optional[BaseException] = None
        try:
            runtime_validator(copy.deepcopy(value))
        except Exception as exc:
            runtime_error = exc
        require(
            schema_result == expected_schema,
            f"{relative_schema} structural layer case {index} expected {expected_schema} got {schema_result}",
        )
        if expected_runtime_error is None:
            require(
                runtime_error is None,
                f"{relative_schema} runtime corpus case {index} raised {type(runtime_error).__name__}",
            )
        else:
            require(
                type(runtime_error) is expected_runtime_error,
                f"{relative_schema} runtime corpus case {index} expected "
                f"{expected_runtime_error.__name__} got {type(runtime_error).__name__}",
            )


def draft202012_structural_accepts(root_schema: object, value: object) -> bool:
    """Evaluate the Draft 2020-12 assertion keywords used by Phase 3 schemas."""

    return _draft202012_node_accepts(root_schema, root_schema, value)


def _draft202012_node_accepts(root: object, schema: object, value: object) -> bool:
    if isinstance(schema, bool):
        return schema
    if not isinstance(schema, dict) or not isinstance(root, dict):
        return False

    reference = schema.get("$ref")
    if reference is not None:
        if not isinstance(reference, str) or not reference.startswith("#/"):
            return False
        target: object = root
        for raw_part in reference[2:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                return False
            target = target[part]
        if not _draft202012_node_accepts(root, target, value):
            return False

    if "type" in schema and not _draft202012_type_accepts(schema["type"], value):
        return False
    if "const" in schema and not _json_equal(value, schema["const"]):
        return False
    if "enum" in schema and not any(_json_equal(value, item) for item in schema["enum"]):
        return False
    if "allOf" in schema and not all(
        _draft202012_node_accepts(root, item, value) for item in schema["allOf"]
    ):
        return False
    if "anyOf" in schema and not any(
        _draft202012_node_accepts(root, item, value) for item in schema["anyOf"]
    ):
        return False
    if "oneOf" in schema and sum(
        1 for item in schema["oneOf"] if _draft202012_node_accepts(root, item, value)
    ) != 1:
        return False
    if "not" in schema and _draft202012_node_accepts(root, schema["not"], value):
        return False
    if "if" in schema and _draft202012_node_accepts(root, schema["if"], value):
        if "then" in schema and not _draft202012_node_accepts(root, schema["then"], value):
            return False
    elif "else" in schema and not _draft202012_node_accepts(root, schema["else"], value):
        return False

    if isinstance(value, dict):
        required = schema.get("required", [])
        if any(key not in value for key in required):
            return False
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                if key in value and not _draft202012_node_accepts(root, child_schema, value[key]):
                    return False
            extras = set(value) - set(properties)
            additional = schema.get("additionalProperties", True)
            if additional is False and extras:
                return False
            if isinstance(additional, dict) and any(
                not _draft202012_node_accepts(root, additional, value[key]) for key in extras
            ):
                return False

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            return False
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return False
        if schema.get("uniqueItems") is True:
            if any(
                _json_equal(value[left], value[right])
                for left in range(len(value))
                for right in range(left + 1, len(value))
            ):
                return False
        prefix = schema.get("prefixItems", [])
        for index, child_schema in enumerate(prefix):
            if index < len(value) and not _draft202012_node_accepts(root, child_schema, value[index]):
                return False
        if "items" in schema:
            item_schema = schema["items"]
            start = len(prefix)
            if item_schema is False and len(value) > start:
                return False
            if item_schema is not False and any(
                not _draft202012_node_accepts(root, item_schema, item) for item in value[start:]
            ):
                return False

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            return False
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            return False
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return False
    if _draft202012_number(value):
        if "minimum" in schema and value < schema["minimum"]:
            return False
        if "maximum" in schema and value > schema["maximum"]:
            return False
    return True


def _draft202012_type_accepts(expected: object, value: object) -> bool:
    if isinstance(expected, list):
        return any(_draft202012_type_accepts(item, value) for item in expected)
    mapping = {
        "array": lambda: isinstance(value, list),
        "boolean": lambda: type(value) is bool,
        "integer": lambda: _draft202012_integer(value),
        "null": lambda: value is None,
        "number": lambda: _draft202012_number(value),
        "object": lambda: isinstance(value, dict),
        "string": lambda: isinstance(value, str),
    }
    return isinstance(expected, str) and expected in mapping and mapping[expected]()


def _draft202012_number(value: object) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _draft202012_integer(value: object) -> bool:
    return _draft202012_number(value) and (
        type(value) is int or (type(value) is float and value.is_integer())
    )


def _json_equal(left: object, right: object) -> bool:
    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    if _draft202012_number(left) or _draft202012_number(right):
        return _draft202012_number(left) and _draft202012_number(right) and left == right
    if isinstance(left, list) or isinstance(right, list):
        return (
            isinstance(left, list)
            and isinstance(right, list)
            and len(left) == len(right)
            and all(_json_equal(old, new) for old, new in zip(left, right))
        )
    if isinstance(left, dict) or isinstance(right, dict):
        return (
            isinstance(left, dict)
            and isinstance(right, dict)
            and set(left) == set(right)
            and all(_json_equal(left[key], right[key]) for key in left)
        )
    return left == right


def synthetic_sk_style() -> str:
    return "s" + "k-" + "A" * 24


def synthetic_github_pat() -> str:
    return "g" + "hp_" + "B" * 24


def synthetic_github_fine_grained_pat() -> str:
    return "git" + "hub_" + "pat_" + "D" * 24


def synthetic_aws_access_key() -> str:
    return "AK" + "IA" + "C" * 16


def synthetic_private_key_block() -> str:
    return "-----BEGIN " + "PRIVATE" + " KEY----- fixture -----END " + "PRIVATE" + " KEY-----"


def synthetic_mixed_assignment() -> str:
    return "ClIeNt" + "_SeCrEt = synthetic-value"


def synthetic_authorization_header() -> str:
    return "Authori" + "zation: synthetic-value"


def synthetic_bearer_token() -> str:
    return "Be" + "arer synthetic-token-value"


def synthetic_jwt() -> str:
    return "ey" + "Jheaderpart.fixturepayload.fixturesignature"


def synthetic_credential_field_name() -> str:
    return "Cli" + "ent" + "Se" + "cret"


def synthetic_credential_matrix() -> tuple[tuple[str, str], ...]:
    return (
        ("sk-style", synthetic_sk_style()),
        ("github-classic-pat", synthetic_github_pat()),
        ("github-fine-grained-pat", synthetic_github_fine_grained_pat()),
        ("aws-access-key", synthetic_aws_access_key()),
        ("private-key-block", synthetic_private_key_block()),
        ("mixed-case-assignment", synthetic_mixed_assignment()),
        ("authorization-header", synthetic_authorization_header()),
        ("bearer-token", synthetic_bearer_token()),
        ("jwt", synthetic_jwt()),
    )


def write_context_fixture(root: Path) -> None:
    files = {
        "AGENTS.md": "# Agent Guide\n\nUse the local project contract.\n",
        "CHECKS.md": "# Checks\n\nRun deterministic local checks.\n",
        "TASKS/current.md": "# Current Task\n\nVerify Phase 3.\n",
        "docs/requirements.md": "# Requirements\n\nKeep the runtime local-only.\n",
        "docs/technical-design.md": "# Technical Design\n\nUse fixed control sources.\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def run_cli(arguments: list[str]) -> tuple[int, dict[str, object], str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = cli_main(arguments)
    text = stdout.getvalue().strip()
    payload = json.loads(text) if text else {}
    return code, payload, stderr.getvalue()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def expect_error(error_type: Type[BaseException], function: Callable[[], object]) -> None:
    try:
        function()
    except error_type:
        return
    raise AssertionError(f"expected {error_type.__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
