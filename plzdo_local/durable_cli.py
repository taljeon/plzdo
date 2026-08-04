from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .atomic_io import atomic_write_json, atomic_write_text, exclusive_file_lock
from .context import (
    ContextError,
    check_context_pack,
    freshness_report,
    generate_context_pack,
    parse_context_pack,
    serialize_context_pack,
)
from .execution_rules import route_goal
from .findings import (
    FindingsError,
    accept_finding_risk,
    add_finding,
    build_findings_ledger,
    close_finding,
    list_findings,
    validate_findings_ledger,
)
from .formalization import (
    FormalizationError,
    approve_formalization,
    approval_hash,
    build_formalization,
    complete_formalization,
    require_approved_formalization,
    supersede_formalization,
    validate_formalization,
)
from .local_memory import (
    MemoryError,
    add_memory,
    build_memory_store,
    purge_memory,
    search_memory,
    validate_memory_store,
)
from .metrics import (
    MetricsError,
    append_metric,
    build_metric,
    parse_metrics,
    serialize_metrics,
    summarize_metrics,
)
from .paths import PathPolicyError, ensure_contained, resolve_state_root
from .registry import build_registry, get_project, validate_registry
from .state import (
    LOOP_EXPLICIT_STOP_STATUSES,
    StateError,
    StateTransition,
    advance_loop_contract,
    apply_checkpoint,
    build_evidence,
    build_state,
    compact_state,
    create_checkpoint,
    create_loop_contract,
    record_state,
    stop_loop_contract,
    validate_loop_contract,
    validate_state,
    validate_state_archive,
)
from .validation import require_safe_id


MAX_LOCAL_DOCUMENT_BYTES = 2 * 1024 * 1024
CAPABILITIES = (
    "catalog",
    "context",
    "findings",
    "formalization",
    "local-memory",
    "metrics",
    "project-registry",
    "routing",
    "state",
    "tracking-only-bounded-loop",
)


class DurableCommandError(ValueError):
    pass


HANDLED_ERRORS = (
    ContextError,
    DurableCommandError,
    FindingsError,
    FormalizationError,
    MemoryError,
    MetricsError,
    StateError,
)


def install_parsers(subparsers: argparse._SubParsersAction[Any]) -> None:
    formalize = subparsers.add_parser("formalize", help="Manage durable goal formalizations")
    formalize_sub = formalize.add_subparsers(dest="formalize_command", required=True)
    draft = formalize_sub.add_parser("draft")
    draft.add_argument("goal")
    draft.add_argument("--id", dest="formalization_id")
    draft.add_argument("--project")
    draft.add_argument("--criterion", action="append", default=[])
    draft.add_argument("--non-goal", action="append", default=[])
    draft.add_argument("--constraint", action="append", default=[])
    draft.add_argument("--plan-step", action="append", default=[])
    draft.add_argument("--evidence-requirement", action="append", default=[])
    draft.add_argument("--bounded-loop", action="store_true")
    draft.add_argument("--json", action="store_true")
    approve = formalize_sub.add_parser("approve")
    approve.add_argument("formalization_id")
    approve.add_argument("--json", action="store_true")
    status = formalize_sub.add_parser("status")
    status.add_argument("formalization_id", nargs="?")
    status.add_argument("--json", action="store_true")
    complete = formalize_sub.add_parser("complete")
    complete.add_argument("formalization_id")
    complete.add_argument("--evidence", required=True)
    complete.add_argument("--json", action="store_true")
    supersede = formalize_sub.add_parser("supersede")
    supersede.add_argument("formalization_id")
    supersede.add_argument("--reason", required=True)
    supersede.add_argument("--json", action="store_true")
    listing = formalize_sub.add_parser("list")
    listing.add_argument("--json", action="store_true")

    context = subparsers.add_parser("context", help="Render and verify local context packs")
    context_sub = context.add_subparsers(dest="context_command", required=True)
    render = context_sub.add_parser("render")
    render.add_argument("--mode", choices=("compact", "full"), default="compact")
    render.add_argument("--root", default=".")
    render.add_argument("--project")
    render.add_argument("--goal")
    render.add_argument("--json", action="store_true")
    check = context_sub.add_parser("check")
    check.add_argument("path", nargs="?")
    check.add_argument("--root", default=".")
    check.add_argument("--json", action="store_true")
    context_status = context_sub.add_parser("status")
    context_status.add_argument("--root")
    context_status.add_argument("--json", action="store_true")

    state = subparsers.add_parser("state", help="Manage bounded local work state")
    state_sub = state.add_subparsers(dest="state_command", required=True)
    state_status = state_sub.add_parser("status")
    state_status.add_argument("--json", action="store_true")
    state_record = state_sub.add_parser("record")
    state_record.add_argument("--work-id")
    state_record.add_argument("--current", required=True)
    state_record.add_argument("--next", required=True, dest="next_step")
    state_record.add_argument("--constraint", action="append", default=[])
    state_record.add_argument("--evidence", required=True)
    state_record.add_argument("--json", action="store_true")
    state_compact = state_sub.add_parser("compact")
    state_compact.add_argument("--dry-run", action="store_true")
    state_compact.add_argument("--json", action="store_true")
    checkpoint = state_sub.add_parser("checkpoint")
    checkpoint_inputs = checkpoint.add_mutually_exclusive_group(required=True)
    checkpoint_inputs.add_argument("--operator-percent", type=int)
    checkpoint_inputs.add_argument("--self-estimate", type=int)
    checkpoint_inputs.add_argument("--used-tokens", type=int)
    checkpoint.add_argument("--max-tokens", type=int)
    checkpoint.add_argument("--json", action="store_true")

    loop = subparsers.add_parser("loop", help="Track a bounded loop contract")
    loop_sub = loop.add_subparsers(dest="loop_command", required=True)
    loop_plan = loop_sub.add_parser("plan")
    loop_plan.add_argument("--checkpoint", required=True)
    loop_plan.add_argument("--formalization", required=True)
    loop_plan.add_argument("--max-iterations", required=True, type=int)
    loop_plan.add_argument("--timeout-seconds", required=True, type=int)
    loop_plan.add_argument("--evidence", required=True)
    loop_plan.add_argument("--json", action="store_true")
    loop_step = loop_sub.add_parser("step")
    loop_step.add_argument("--checkpoint", required=True)
    loop_step.add_argument("--evidence", required=True)
    loop_step.add_argument("--json", action="store_true")
    loop_stop = loop_sub.add_parser("stop")
    loop_stop.add_argument("--checkpoint", required=True)
    loop_stop.add_argument("--reason", required=True, choices=LOOP_EXPLICIT_STOP_STATUSES)
    loop_stop.add_argument("--evidence", required=True)
    loop_stop.add_argument("--json", action="store_true")
    loop_status = loop_sub.add_parser("status")
    loop_status.add_argument("--checkpoint", required=True)
    loop_status.add_argument("--json", action="store_true")

    memory = subparsers.add_parser("memory", help="Manage sanitized local non-SoT memory")
    memory_sub = memory.add_subparsers(dest="memory_command", required=True)
    memory_add = memory_sub.add_parser("add")
    memory_add.add_argument("--label", required=True)
    memory_add.add_argument("--domain", required=True)
    memory_add.add_argument("--summary", required=True)
    memory_add.add_argument("--json", action="store_true")
    memory_search = memory_sub.add_parser("search")
    memory_search.add_argument("query")
    memory_search.add_argument("--limit", type=int, default=20)
    memory_search.add_argument("--json", action="store_true")
    memory_status = memory_sub.add_parser("status")
    memory_status.add_argument("--json", action="store_true")
    memory_export = memory_sub.add_parser("export")
    memory_export.add_argument("name")
    memory_export.add_argument("--json", action="store_true")
    memory_purge = memory_sub.add_parser("purge")
    purge_group = memory_purge.add_mutually_exclusive_group(required=True)
    purge_group.add_argument("--all", action="store_true", dest="purge_all")
    purge_group.add_argument("--stable-key")
    memory_purge.add_argument("--json", action="store_true")

    findings = subparsers.add_parser("findings", help="Manage the append-preserving findings ledger")
    findings_sub = findings.add_subparsers(dest="findings_command", required=True)
    findings_add = findings_sub.add_parser("add")
    findings_add.add_argument("finding_id")
    findings_add.add_argument("--severity", required=True, choices=("low", "medium", "high", "blocking"))
    findings_add.add_argument("--title", required=True)
    findings_add.add_argument("--evidence", action="append", required=True)
    findings_add.add_argument("--json", action="store_true")
    findings_list = findings_sub.add_parser("list")
    findings_list.add_argument("--all", action="store_true", dest="include_terminal")
    findings_list.add_argument("--json", action="store_true")
    for command in ("close", "accept-risk"):
        resolver = findings_sub.add_parser(command)
        resolver.add_argument("finding_id")
        resolver.add_argument("--resolution", required=True)
        resolver.add_argument("--evidence", action="append", required=True)
        resolver.add_argument("--json", action="store_true")
    findings_check = findings_sub.add_parser("check")
    findings_check.add_argument("--json", action="store_true")

    metrics = subparsers.add_parser("metrics", help="Record bounded local run metadata")
    metrics_sub = metrics.add_subparsers(dest="metrics_command", required=True)
    metrics_record = metrics_sub.add_parser("record")
    metrics_record.add_argument("--run-id", required=True)
    metrics_record.add_argument("--project")
    metrics_record.add_argument("--route", required=True, choices=("quick", "plan", "goal"))
    metrics_record.add_argument("--bounded-loop", action="store_true")
    metrics_record.add_argument("--status", required=True, choices=("succeeded", "failed", "blocked", "skipped"))
    metrics_record.add_argument(
        "--route-feedback",
        required=True,
        choices=("correct", "under-routed", "over-routed", "operator-override", "unknown"),
    )
    metrics_record.add_argument("--duration-ms", type=int, required=True)
    metrics_record.add_argument("--changed-files", type=int, default=0)
    metrics_record.add_argument("--checks", type=int, default=0)
    metrics_record.add_argument("--findings", type=int, default=0)
    metrics_record.add_argument("--json", action="store_true")
    metrics_summary = metrics_sub.add_parser("summary")
    metrics_summary.add_argument("--json", action="store_true")


def handles(args: argparse.Namespace) -> bool:
    return args.command in {"formalize", "context", "state", "loop", "memory", "findings", "metrics"}


def dispatch(args: argparse.Namespace) -> int:
    handlers = {
        "formalize": _formalize,
        "context": _context,
        "state": _state,
        "loop": _loop,
        "memory": _memory,
        "findings": _findings,
        "metrics": _metrics,
    }
    return handlers[args.command](args)


def _formalize(args: argparse.Namespace) -> int:
    if args.formalize_command == "draft":
        registry = _load_registry()
        route = route_goal(
            args.goal,
            registry,
            identifier=args.project,
            bounded_loop_requested=args.bounded_loop,
        )
        record_id = args.formalization_id or _derived_id("goal", args.goal)
        timestamp = _now()
        record = build_formalization(
            formalization_id=record_id,
            project_id=route["projectDecision"]["projectId"],
            objective=args.goal,
            criteria=args.criterion or ["The declared goal is completed with local verification evidence."],
            non_goals=args.non_goal or ["Do not add undeclared external or production side effects."],
            constraints=args.constraint or ["Use bounded local tools and preserve unrelated user work."],
            route=route,
            plan=args.plan_step or [
                "Inspect the governed local context.",
                "Perform the smallest declared implementation.",
                "Run the declared checks and record evidence.",
            ],
            evidence_contract=args.evidence_requirement
            or ["Record changed files, local checks, skipped checks, and residual risk."],
            created_at=timestamp,
        )
        _write_formalization_new(record)
        payload = record
    elif args.formalize_command == "approve":
        current = _load_formalization(args.formalization_id)
        digest = approval_hash(current)
        phrase = f"APPROVE {current['id']} {digest[:12]}"
        if not sys.stdin.isatty():
            raise DurableCommandError("formalization approval requires an interactive TTY")
        typed = input(f"Type {phrase}: ")
        if typed != phrase:
            raise DurableCommandError("formalization approval phrase did not match")
        payload = _update_formalization(
            current["id"],
            lambda value: approve_formalization(
                value,
                operator_confirmed=True,
                approved_at=_now(),
            ),
        )
    elif args.formalize_command == "complete":
        evidence = _read_regular_bytes(Path(args.evidence), label="completion evidence")
        digest = hashlib.sha256(evidence).hexdigest()
        payload = _update_formalization(
            args.formalization_id,
            lambda value: complete_formalization(
                value,
                evidence_reference=f"sha256:{digest}",
                evidence_sha256=digest,
                completed_at=_now(),
            ),
        )
    elif args.formalize_command == "supersede":
        payload = _update_formalization(
            args.formalization_id,
            lambda value: supersede_formalization(
                value,
                reason=args.reason,
                superseded_at=_now(),
            ),
        )
    elif args.formalize_command in {"status", "list"}:
        records = _list_formalizations()
        if args.formalize_command == "status" and args.formalization_id:
            payload = _load_formalization(args.formalization_id)
        else:
            payload = {
                "schemaVersion": "plzdo-local.formalization-list.v1",
                "status": "ok",
                "records": records,
            }
    else:
        raise AssertionError("unhandled formalize command")
    _emit(payload, json_output=args.json)
    return 0


def _context(args: argparse.Namespace) -> int:
    path = _context_path() if getattr(args, "path", None) is None else Path(args.path)
    if args.context_command == "render":
        registry = _load_registry()
        project = get_project(registry, args.project) if args.project else None
        root = Path(project["path"]) if project else Path(args.root)
        route = route_goal(args.goal, registry, identifier=args.project) if args.goal else None
        state_summary = _state_summary(_load_state(required=False))
        pack = generate_context_pack(
            root,
            mode=args.mode,
            timestamp=_now(),
            project=project,
            route=route,
            active_formalization=_single_active_formalization(args.project),
            state_summary=state_summary,
            capabilities=list(CAPABILITIES),
        )
        state_root = resolve_state_root()
        lock = _state_path("locks", "context.lock")
        with exclusive_file_lock(lock, allowed_root=state_root):
            atomic_write_text(
                _context_path(),
                serialize_context_pack(pack).decode("utf-8"),
                allowed_root=state_root,
                validator=lambda text: parse_context_pack(text),
            )
        payload = pack
    elif args.context_command == "check":
        pack = parse_context_pack(_read_regular_bytes(path, label="context pack"))
        payload = check_context_pack(pack, Path(args.root))
    elif args.context_command == "status":
        pack = parse_context_pack(_read_regular_bytes(_context_path(), label="context pack"))
        if args.root:
            payload = freshness_report(pack, Path(args.root))
        else:
            payload = {
                "schemaVersion": "plzdo-local.context-status.v1",
                "status": "valid",
                "mode": pack["mode"],
                "generatedAt": pack["generatedAt"],
                "sourceCount": len(pack["sourceManifest"]),
            }
    else:
        raise AssertionError("unhandled context command")
    _emit(payload, json_output=args.json)
    return 0


def _state(args: argparse.Namespace) -> int:
    if args.state_command == "status":
        current = _load_state(required=False)
        payload = _state_summary(current)
    elif args.state_command == "record":
        timestamp = _now()
        item = build_evidence(evidence_type="run-evidence", summary=args.evidence, recorded_at=timestamp)

        def transition(current: Optional[dict[str, Any]]) -> StateTransition:
            if current is None:
                work_id = args.work_id or _derived_id("work", str(Path.cwd().resolve()))
                active = build_state(
                    work_id=work_id,
                    current=args.current,
                    next_step=args.next_step,
                    constraints=args.constraint,
                    evidence=[item],
                    updated_at=timestamp,
                )
                return StateTransition(None, active)
            return record_state(
                current,
                current=args.current,
                next_step=args.next_step,
                constraints=args.constraint,
                evidence=[item],
                updated_at=timestamp,
            )

        result = _persist_state_transition(transition)
        payload = _state_summary(result.active)
        payload["archiveWritten"] = result.archive is not None
    elif args.state_command == "compact":
        current = _load_state(required=True)
        preview = compact_state(current, compacted_at=_now())
        if args.dry_run:
            result = preview
        else:
            result = _persist_state_transition(
                lambda latest: compact_state(latest, compacted_at=_now()) if latest is not None else _missing_state()
            )
        payload = _state_summary(result.active)
        payload.update({"status": "planned" if args.dry_run else "compacted", "archiveWritten": not args.dry_run})
    elif args.state_command == "checkpoint":
        if (args.used_tokens is None) != (args.max_tokens is None):
            raise DurableCommandError("--used-tokens and --max-tokens must be provided together")
        decision = create_checkpoint(
            created_at=_now(),
            operator_percent=args.operator_percent,
            used_tokens=args.used_tokens,
            max_tokens=args.max_tokens,
            self_estimate=args.self_estimate,
        )
        if decision["status"] == "created":
            _persist_state_transition(
                lambda current: apply_checkpoint(
                    current if current is not None else _missing_state(),
                    decision,
                    updated_at=_now(),
                )
            )
        payload = decision
    else:
        raise AssertionError("unhandled state command")
    _emit(payload, json_output=args.json)
    return 0


def _loop(args: argparse.Namespace) -> int:
    checkpoint_id = require_safe_id(args.checkpoint, label="loop checkpoint")
    if args.loop_command == "plan":
        payload = _write_loop_new(
            checkpoint_id,
            args.formalization,
            lambda formalization: create_loop_contract(
                formalization=formalization,
                max_iterations=args.max_iterations,
                timeout_seconds=args.timeout_seconds,
                checkpoint_iteration=0,
                evidence=[args.evidence],
                started_at=_now(),
            ),
        )
    elif args.loop_command == "status":
        payload = _load_loop(checkpoint_id)
    else:
        if args.loop_command == "step":
            transition = lambda value, formalization: advance_loop_contract(
                value,
                formalization=formalization,
                checkpoint_iteration=value["checkpointIteration"],
                evidence=[args.evidence],
                advanced_at=_now(),
            )
        elif args.loop_command == "stop":
            transition = lambda value, formalization: stop_loop_contract(
                value,
                formalization=formalization,
                checkpoint_iteration=value["checkpointIteration"],
                reason=args.reason,
                evidence=[args.evidence],
                stopped_at=_now(),
            )
        else:
            raise AssertionError("unhandled loop command")
        payload = _update_loop(checkpoint_id, transition)
    _emit(payload, json_output=args.json)
    return 0


def _memory(args: argparse.Namespace) -> int:
    if args.memory_command == "search":
        payload = {
            "schemaVersion": "plzdo-local.memory-search.v1",
            "status": "ok",
            "sourceOfTruth": False,
            "items": search_memory(_load_memory(), args.query, limit=args.limit),
        }
    elif args.memory_command == "status":
        store = _load_memory()
        payload = {
            "schemaVersion": "plzdo-local.memory-status.v1",
            "status": "ok",
            "sourceOfTruth": False,
            "itemCount": len(store["items"]),
            "activeCount": sum(item["state"] == "active" for item in store["items"]),
        }
    elif args.memory_command == "export":
        name = require_safe_id(args.name, label="memory export name")
        store = _load_memory()
        destination = _state_path("exports", f"{name}.json")
        atomic_write_json(destination, store, allowed_root=resolve_state_root(), validator=validate_memory_store)
        payload = {"schemaVersion": "plzdo-local.memory-export.v1", "status": "exported", "name": name}
    else:
        def transition(store: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
            if args.memory_command == "add":
                updated = add_memory(
                    store,
                    label=args.label,
                    domain=args.domain,
                    summary=args.summary,
                    created_at=_now(),
                )
                result = updated["items"][-1]
            elif args.memory_command == "purge":
                updated, removed = purge_memory(
                    store,
                    purge_all=args.purge_all,
                    stable_key=args.stable_key,
                )
                result = {"removed": removed}
            else:
                raise AssertionError("unhandled memory command")
            return updated, result

        payload = _persist_memory_transition(transition)
    _emit(payload, json_output=args.json)
    return 0


def _findings(args: argparse.Namespace) -> int:
    if args.findings_command == "list":
        payload = {
            "schemaVersion": "plzdo-local.findings-list.v1",
            "status": "ok",
            "sourceOfTruth": False,
            "findings": list_findings(_load_findings(), include_terminal=args.include_terminal),
        }
    elif args.findings_command == "check":
        ledger = _load_findings()
        payload = {
            "schemaVersion": "plzdo-local.findings-status.v1",
            "status": "valid",
            "sourceOfTruth": False,
            "findingCount": len(ledger["findings"]),
        }
    else:
        def transition(ledger: dict[str, Any]) -> dict[str, Any]:
            if args.findings_command == "add":
                return add_finding(
                    ledger,
                    finding_id=args.finding_id,
                    severity=args.severity,
                    title=args.title,
                    evidence=args.evidence,
                    created_at=_now(),
                )
            if args.findings_command == "close":
                return close_finding(
                    ledger,
                    args.finding_id,
                    resolution=args.resolution,
                    evidence=args.evidence,
                    updated_at=_now(),
                )
            if args.findings_command == "accept-risk":
                return accept_finding_risk(
                    ledger,
                    args.finding_id,
                    resolution=args.resolution,
                    evidence=args.evidence,
                    updated_at=_now(),
                )
            raise AssertionError("unhandled findings command")

        ledger = _persist_findings_transition(transition)
        payload = ledger
    _emit(payload, json_output=args.json)
    return 0


def _metrics(args: argparse.Namespace) -> int:
    if args.metrics_command == "summary":
        payload = summarize_metrics(_load_metrics())
    else:
        record = build_metric(
            run_id=args.run_id,
            project_id=args.project,
            route=args.route,
            bounded_loop=args.bounded_loop,
            status=args.status,
            route_feedback=args.route_feedback,
            duration_ms=args.duration_ms,
            changed_file_count=args.changed_files,
            check_count=args.checks,
            finding_count=args.findings,
            recorded_at=_now(),
        )
        state_root = resolve_state_root()
        with exclusive_file_lock(_state_path("locks", "metrics.lock"), allowed_root=state_root):
            updated = append_metric(_load_metrics(), record)
            atomic_write_text(
                _metrics_path(),
                serialize_metrics(updated),
                allowed_root=state_root,
                validator=lambda text: parse_metrics(text),
            )
        payload = record
    _emit(payload, json_output=args.json)
    return 0


def _write_formalization_new(record: dict[str, Any]) -> None:
    state_root = resolve_state_root()
    path = _formalization_path(record["id"])
    with exclusive_file_lock(_formalizations_lock_path(), allowed_root=state_root):
        if path.exists() or path.is_symlink():
            raise DurableCommandError(f"formalization already exists: {record['id']}")
        atomic_write_json(path, record, allowed_root=state_root, validator=validate_formalization)


def _update_formalization(
    formalization_id: str,
    transition: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    state_root = resolve_state_root()
    path = _formalization_path(formalization_id)
    with exclusive_file_lock(_formalizations_lock_path(), allowed_root=state_root):
        current = _load_formalization(formalization_id)
        updated = transition(current)
        atomic_write_json(path, updated, allowed_root=state_root, validator=validate_formalization)
    return updated


def _load_formalization(formalization_id: str) -> dict[str, Any]:
    path = _formalization_path(formalization_id)
    if not path.exists():
        raise DurableCommandError(f"formalization not found: {formalization_id}")
    value = _read_json(path, label="formalization")
    validate_formalization(value)
    return value


def _list_formalizations() -> list[dict[str, Any]]:
    directory = _state_path("formalizations")
    if not directory.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.suffix != ".json":
            continue
        if path.is_symlink() or not path.is_file():
            raise DurableCommandError("formalization directory contains a non-regular JSON entry")
        record = _read_json(path, label="formalization")
        validate_formalization(record)
        records.append(record)
    return records


def _single_active_formalization(project_id: Optional[str]) -> Optional[dict[str, Any]]:
    active = [
        record
        for record in _list_formalizations()
        if record["status"] == "approved" and (project_id is None or record["projectId"] == project_id)
    ]
    return active[0] if len(active) == 1 else None


def _persist_state_transition(
    transition: Callable[[Optional[dict[str, Any]]], StateTransition],
) -> StateTransition:
    state_root = resolve_state_root()
    with exclusive_file_lock(_state_path("locks", "state.lock"), allowed_root=state_root):
        current = _load_state(required=False)
        result = transition(current)
        if result.archive is not None:
            validate_state_archive(result.archive)
            digest = hashlib.sha256(
                json.dumps(result.archive, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            archive_path = _state_path("state", "archives", f"state-{digest[:24]}.json")
            if archive_path.exists() or archive_path.is_symlink():
                existing = _read_json(archive_path, label="state archive")
                if existing != result.archive:
                    raise DurableCommandError("state archive digest collision")
            else:
                atomic_write_json(
                    archive_path,
                    result.archive,
                    allowed_root=state_root,
                    validator=validate_state_archive,
                )
        atomic_write_json(_state_document_path(), result.active, allowed_root=state_root, validator=validate_state)
    return result


def _load_state(*, required: bool) -> Optional[dict[str, Any]]:
    path = _state_document_path()
    if not path.exists():
        if required:
            raise DurableCommandError("work state does not exist")
        return None
    value = _read_json(path, label="work state")
    validate_state(value)
    return value


def _state_summary(value: Optional[dict[str, Any]]) -> dict[str, Any]:
    if value is None:
        return {
            "schemaVersion": "plzdo-local.state-status.v1",
            "status": "missing",
            "sourceOfTruth": False,
        }
    return {
        "schemaVersion": "plzdo-local.state-status.v1",
        "status": "ok",
        "sourceOfTruth": False,
        "workId": value["workId"],
        "current": value["current"],
        "next": value["next"],
        "evidenceCount": value["lastEvidenceCount"],
        "archivedEvidenceCount": value["archivedEvidenceCount"],
        "checkpointSource": value["contextCheckpoint"]["source"] if value["contextCheckpoint"] else None,
        "updatedAt": value["updatedAt"],
    }


def _write_loop_new(
    checkpoint_id: str,
    formalization_id: str,
    build: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    state_root = resolve_state_root()
    path = _loop_path(checkpoint_id)
    # Global order: formalization lifecycle first, then the checkpoint-specific loop.
    with exclusive_file_lock(_formalizations_lock_path(), allowed_root=state_root):
        with exclusive_file_lock(_loop_lock_path(checkpoint_id), allowed_root=state_root):
            if path.exists() or path.is_symlink():
                raise DurableCommandError(f"loop checkpoint already exists: {checkpoint_id}")
            formalization = require_approved_formalization(
                _load_formalization(formalization_id)
            )
            value = build(formalization)
            atomic_write_json(
                path,
                value,
                allowed_root=state_root,
                validator=validate_loop_contract,
            )
    return value


def _update_loop(
    checkpoint_id: str,
    transition: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    state_root = resolve_state_root()
    path = _loop_path(checkpoint_id)
    observed = _load_loop(checkpoint_id)
    formalization_id = observed["formalizationId"]
    # The preliminary read selects the first lock only. Both records are reread
    # and checked after the fixed formalization -> loop lock order is held.
    with exclusive_file_lock(_formalizations_lock_path(), allowed_root=state_root):
        with exclusive_file_lock(_loop_lock_path(checkpoint_id), allowed_root=state_root):
            current = _load_loop(checkpoint_id)
            if current["formalizationId"] != formalization_id:
                raise DurableCommandError("loop formalization binding changed while acquiring locks")
            formalization = require_approved_formalization(
                _load_formalization(current["formalizationId"])
            )
            if formalization["approval"]["approvalHash"] != current["approvalHash"]:
                raise DurableCommandError("loop approval binding no longer matches formalization")
            updated = transition(current, formalization)
            atomic_write_json(
                path,
                updated,
                allowed_root=state_root,
                validator=validate_loop_contract,
            )
    return updated


def _load_loop(checkpoint_id: str) -> dict[str, Any]:
    path = _loop_path(checkpoint_id)
    if not path.exists():
        raise DurableCommandError(f"loop checkpoint not found: {checkpoint_id}")
    value = _read_json(path, label="loop checkpoint")
    validate_loop_contract(value)
    return value


def _load_memory() -> dict[str, Any]:
    path = _memory_path()
    if not path.exists():
        return build_memory_store()
    value = _read_json(path, label="memory store")
    validate_memory_store(value)
    return value


def _persist_memory_transition(
    transition: Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]]
) -> dict[str, Any]:
    state_root = resolve_state_root()
    with exclusive_file_lock(_state_path("locks", "memory.lock"), allowed_root=state_root):
        updated, payload = transition(_load_memory())
        atomic_write_json(_memory_path(), updated, allowed_root=state_root, validator=validate_memory_store)
    return payload


def _load_findings() -> dict[str, Any]:
    path = _findings_path()
    if not path.exists():
        return build_findings_ledger()
    value = _read_json(path, label="findings ledger")
    validate_findings_ledger(value)
    return value


def _persist_findings_transition(
    transition: Callable[[dict[str, Any]], dict[str, Any]]
) -> dict[str, Any]:
    state_root = resolve_state_root()
    with exclusive_file_lock(_state_path("locks", "findings.lock"), allowed_root=state_root):
        updated = transition(_load_findings())
        atomic_write_json(_findings_path(), updated, allowed_root=state_root, validator=validate_findings_ledger)
    return updated


def _load_metrics() -> list[dict[str, Any]]:
    path = _metrics_path()
    if not path.exists():
        return []
    return parse_metrics(_read_regular_bytes(path, label="metrics").decode("utf-8"))


def _load_registry() -> dict[str, Any]:
    path = _state_path("registry", "registry.json")
    if not path.exists():
        return build_registry()
    value = _read_json(path, label="registry")
    validate_registry(value)
    return value


def _read_json(path: Path, *, label: str) -> Any:
    payload = _read_regular_bytes(path, label=label)
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=lambda pairs: _object_without_duplicates(pairs, label=label),
            parse_constant=lambda value: _reject_json_constant(value, label=label),
        )
    except UnicodeDecodeError as exc:
        raise DurableCommandError(f"{label} must be UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise DurableCommandError(f"{label} must be valid JSON") from exc


def _read_regular_bytes(path: Path, *, label: str) -> bytes:
    if path.is_symlink():
        raise DurableCommandError(f"{label} must not be a symlink")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise DurableCommandError(f"{label} is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise DurableCommandError(f"{label} must be a regular file")
        if metadata.st_size > MAX_LOCAL_DOCUMENT_BYTES:
            raise DurableCommandError(f"{label} exceeds {MAX_LOCAL_DOCUMENT_BYTES} bytes")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(65536, MAX_LOCAL_DOCUMENT_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_LOCAL_DOCUMENT_BYTES:
                raise DurableCommandError(f"{label} exceeds {MAX_LOCAL_DOCUMENT_BYTES} bytes")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _object_without_duplicates(pairs: list[tuple[str, Any]], *, label: str) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DurableCommandError(f"{label} contains duplicate key: {key}")
        value[key] = item
    return value


def _reject_json_constant(value: str, *, label: str) -> Any:
    raise DurableCommandError(f"{label} contains non-finite number: {value}")


def _derived_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _state_path(*parts: str) -> Path:
    root = resolve_state_root()
    return ensure_contained(root.joinpath(*parts), root, label="local state path")


def _formalization_path(formalization_id: str) -> Path:
    checked = require_safe_id(formalization_id, label="formalization id")
    return _state_path("formalizations", f"{checked}.json")


def _formalizations_lock_path() -> Path:
    return _state_path("locks", "formalizations.lock")


def _context_path() -> Path:
    return _state_path("context", "context.json")


def _state_document_path() -> Path:
    return _state_path("state", "state.json")


def _loop_path(checkpoint_id: str) -> Path:
    checked = require_safe_id(checkpoint_id, label="loop checkpoint")
    return _state_path("loops", f"{checked}.json")


def _loop_lock_path(checkpoint_id: str) -> Path:
    checked = require_safe_id(checkpoint_id, label="loop checkpoint")
    return _state_path("locks", f"loop-{checked}.lock")


def _memory_path() -> Path:
    return _state_path("memory", "knowledge.json")


def _findings_path() -> Path:
    return _state_path("findings", "findings.json")


def _metrics_path() -> Path:
    return _state_path("metrics", "runs.jsonl")


def _missing_state() -> Any:
    raise DurableCommandError("work state does not exist")


def _emit(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        return
    print(f"status: {payload.get('status', 'ok')}")
    for key, value in payload.items():
        if key not in {"schemaVersion", "status"}:
            print(f"{key}: {value}")
