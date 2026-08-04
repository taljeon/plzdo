from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

from .atomic_io import atomic_write_json, exclusive_file_lock
from .durable_cli import (
    _emit,
    _load_registry,
    _now,
    _read_json,
    _read_regular_bytes,
    _state_path,
)
from .monitor import MonitorError, monitor_snapshot, repo_preflight
from .paths import resolve_state_root
from .registry import get_project
from .review_bundle import (
    ReviewBundleError,
    import_response,
    prepare_bundle,
    validate_bundle,
    validate_import,
    validate_manifest,
)
from .validation import ValidationError, require_safe_id


HANDLED_ERRORS = (MonitorError, ReviewBundleError, ValidationError)


def install_parsers(subparsers: argparse._SubParsersAction[Any]) -> None:
    review = subparsers.add_parser("review", help="Prepare and import local advisory review artifacts")
    review_sub = review.add_subparsers(dest="review_command", required=True)
    prepare = review_sub.add_parser("prepare")
    prepare.add_argument("--manifest", required=True)
    prepare.add_argument("--root", required=True)
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--json", action="store_true")
    validate = review_sub.add_parser("validate")
    validate.add_argument("bundle")
    validate.add_argument("--json", action="store_true")
    imported = review_sub.add_parser("import")
    imported.add_argument("--bundle", required=True)
    imported.add_argument("--response", required=True)
    imported.add_argument("--json", action="store_true")

    monitor = subparsers.add_parser("monitor", help="Write a manual read-only local snapshot")
    monitor_sub = monitor.add_subparsers(dest="monitor_command", required=True)
    snapshot = monitor_sub.add_parser("snapshot")
    snapshot.add_argument("--project", required=True)
    snapshot.add_argument("--json", action="store_true")

    preflight = subparsers.add_parser("repo-preflight", help="Observe a repository without repairing it")
    preflight.add_argument("path", nargs="?", default=".")
    preflight.add_argument("--json", action="store_true")


def handles(args: argparse.Namespace) -> bool:
    return args.command in {"review", "monitor", "repo-preflight"}


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "review":
        return _review(args)
    if args.command == "monitor":
        return _monitor(args)
    if args.command == "repo-preflight":
        payload = repo_preflight(Path(args.path))
        _emit(payload, json_output=args.json)
        return 0
    raise AssertionError("unhandled local operation")


def _review(args: argparse.Namespace) -> int:
    state_root = resolve_state_root()
    if args.review_command == "prepare":
        manifest = _read_json(Path(args.manifest), label="review manifest")
        validate_manifest(manifest)
        bundle = prepare_bundle(Path(args.root), manifest, created_at=_now())
        output = require_safe_id(args.output, label="review bundle output")
        path = _state_path("review", "bundles", f"{output}.json")
        with exclusive_file_lock(_state_path("locks", "review.lock"), allowed_root=state_root):
            if path.exists() or path.is_symlink():
                raise ReviewBundleError(f"review bundle already exists: {output}")
            atomic_write_json(path, bundle, allowed_root=state_root, validator=validate_bundle)
        payload = {
            "schemaVersion": "plzdo-local.review-prepare-result.v1",
            "status": "prepared",
            "bundleId": output,
            "fileCount": len(bundle["manifest"]),
            "redactionCount": bundle["redactionCount"],
            "egressPerformed": False,
        }
    elif args.review_command == "validate":
        bundle = _read_json(Path(args.bundle), label="review bundle")
        validate_bundle(bundle)
        payload = {
            "schemaVersion": "plzdo-local.review-validation.v1",
            "status": "valid",
            "sourceOfTruth": False,
            "notInstructions": True,
            "toolAuthority": False,
            "egressPerformed": False,
            "fileCount": len(bundle["manifest"]),
        }
    elif args.review_command == "import":
        bundle = _read_json(Path(args.bundle), label="review bundle")
        validate_bundle(bundle)
        response = _read_regular_bytes(Path(args.response), label="review response")
        record = import_response(bundle, response, imported_at=_now())
        identifier = hashlib.sha256(
            (record["bundleSha256"] + record["responseSha256"]).encode("ascii")
        ).hexdigest()[:24]
        path = _state_path("review", "imports", f"review-{identifier}.json")
        with exclusive_file_lock(_state_path("locks", "review.lock"), allowed_root=state_root):
            if path.exists() or path.is_symlink():
                existing = _read_json(path, label="review import")
                validate_import(existing)
                if existing != record:
                    raise ReviewBundleError("review import digest collision")
            else:
                atomic_write_json(path, record, allowed_root=state_root, validator=validate_import)
        payload = {
            "schemaVersion": "plzdo-local.review-import-result.v1",
            "status": "imported",
            "reviewId": f"review-{identifier}",
            "sourceOfTruth": False,
            "notInstructions": True,
            "toolAuthority": False,
            "redactionCount": record["redactionCount"],
        }
    else:
        raise AssertionError("unhandled review command")
    _emit(payload, json_output=args.json)
    return 0


def _monitor(args: argparse.Namespace) -> int:
    if args.monitor_command != "snapshot":
        raise AssertionError("unhandled monitor command")
    project = get_project(_load_registry(), args.project)
    snapshot = monitor_snapshot(project, captured_at=_now())
    state_root = resolve_state_root()
    path = _state_path("monitor", f"{project['id']}.json")
    with exclusive_file_lock(_state_path("locks", "monitor.lock"), allowed_root=state_root):
        atomic_write_json(path, snapshot, allowed_root=state_root)
    _emit(snapshot, json_output=args.json)
    return 0
