from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from .apply_gate import (
    MAX_PLAN_BYTES,
    ApplyGateError,
    apply_report_path,
    apply_status,
    authorize_apply,
    execute_apply,
    plan_apply,
    rollback_apply,
    validate_apply_plan,
)
from .atomic_io import atomic_write_json
from .catalog import CatalogError, validate_catalog


MAX_INPUT_BYTES = MAX_PLAN_BYTES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plzdo-apply", description="Foreground-only P5 real apply")
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan", help="Create a non-writing apply plan")
    plan.add_argument("--catalog", required=True)
    plan.add_argument("--project", required=True)
    plan.add_argument("--repository", required=True)
    plan.add_argument("--output", required=True)
    plan.add_argument("--force", action="store_true")

    authorize = commands.add_parser("authorize", help="Authorize one exact plan from the foreground TTY")
    authorize.add_argument("--catalog", required=True)
    authorize.add_argument("--plan", required=True)

    execute = commands.add_parser("execute", help="Consume authorization and execute one exact plan")
    execute.add_argument("--catalog", required=True)
    execute.add_argument("--plan", required=True)

    status = commands.add_parser("status", help="Inspect canonical MACed apply evidence")
    status.add_argument("--catalog", required=True)
    status.add_argument("--report", required=True)

    rollback = commands.add_parser("rollback", help="Resume exact rollback from the foreground TTY")
    rollback.add_argument("--catalog", required=True)
    rollback.add_argument("--report", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        catalog = _read_json(Path(args.catalog), label="catalog")
        validate_catalog(catalog)
        if args.command == "plan":
            project = _read_json(Path(args.project), label="project input")
            plan = plan_apply(catalog, args.repository, project, force=args.force)
            output = _write_plan(Path(args.output), plan)
            _emit(
                {
                    "schemaVersion": "plzdo-local.apply-cli-result.v1",
                    "status": "planned",
                    "planId": plan["planId"],
                    "planFingerprint": plan["planFingerprint"],
                    "target": plan["target"]["root"],
                    "output": str(output),
                }
            )
            return 0
        if args.command == "authorize":
            plan = _load_plan(Path(args.plan))
            grant = authorize_apply(plan, catalog)
            _emit(
                {
                    "schemaVersion": "plzdo-local.apply-cli-result.v1",
                    "status": "authorized",
                    "planFingerprint": grant["planFingerprint"],
                    "expiresAt": grant["expiresAt"],
                }
            )
            return 0
        if args.command == "execute":
            plan = _load_plan(Path(args.plan))
            report = execute_apply(plan, catalog)
            _emit(
                {
                    "schemaVersion": "plzdo-local.apply-cli-result.v1",
                    "status": report["status"],
                    "planFingerprint": plan["planFingerprint"],
                    "report": str(apply_report_path(plan)),
                }
            )
            return 0
        if args.command == "status":
            _emit(apply_status(Path(args.report), catalog))
            return 0
        if args.command == "rollback":
            report = rollback_apply(Path(args.report), catalog)
            _emit(
                {
                    "schemaVersion": "plzdo-local.apply-cli-result.v1",
                    "status": report["status"],
                    "planFingerprint": report["plan"]["planFingerprint"],
                    "report": str(Path(args.report).resolve(strict=False)),
                }
            )
            return 0
    except (ApplyGateError, CatalogError, OSError, UnicodeError, ValueError) as exc:
        message = " ".join(str(exc).split())[:500] or type(exc).__name__
        print(f"plzdo-apply: {type(exc).__name__}: {message}", file=sys.stderr)
        return 2
    raise AssertionError("unhandled apply command")


def _load_plan(path: Path) -> dict[str, Any]:
    plan = _read_json(path, label="apply plan")
    validate_apply_plan(plan)
    return plan


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{label} path must be absolute and must not be a symlink")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_INPUT_BYTES:
            raise ValueError(f"{label} must be a bounded regular file")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(65536, MAX_INPUT_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_INPUT_BYTES:
                raise ValueError(f"{label} exceeds the byte limit")
    finally:
        os.close(descriptor)
    value = json.loads(b"".join(chunks).decode("utf-8"), object_pairs_hook=_reject_duplicates)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _write_plan(path: Path, plan: dict[str, Any]) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("plan output path must be absolute and must not be a symlink")
    parent = path.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError("plan output parent must be a directory")
    destination = parent / path.name
    atomic_write_json(destination, plan, allowed_root=parent, validator=validate_apply_plan)
    return destination


def _reject_duplicates(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
