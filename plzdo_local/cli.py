from __future__ import annotations

import argparse
import json
import os
import platform
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from . import __version__
from .atomic_io import atomic_write_json, exclusive_file_lock
from .catalog import CatalogError, build_catalog, get_repository, list_repositories, validate_catalog
from .durable_cli import HANDLED_ERRORS, dispatch as dispatch_durable, handles as handles_durable, install_parsers
from .local_ops_cli import (
    HANDLED_ERRORS as LOCAL_OPS_ERRORS,
    dispatch as dispatch_local_ops,
    handles as handles_local_ops,
    install_parsers as install_local_ops_parsers,
)
from .execution_rules import ExecutionRuleError, route_goal
from .paths import PathPolicyError, ensure_contained, repository_root, resolve_state_root
from .registry import (
    RegistryError,
    archive_project,
    build_project,
    build_registry,
    get_project,
    list_projects,
    register_project,
    resolve_project,
    validate_registry,
)
from .resource_cli import (
    HANDLED_ERRORS as RESOURCE_ERRORS,
    dispatch as dispatch_resources,
    handles as handles_resources,
    install_parsers as install_resource_parsers,
)
from .renderer import RendererError, inspect_project_frame, plan_project_frame
from .validation import require_safe_id


MIN_PYTHON = (3, 9)
MIN_GIT = (2, 30)
MIN_BASH = (3, 2)
MAX_CONTROL_DOCUMENT_BYTES = 2 * 1024 * 1024


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plzdo", description="PlzDo Local control plane")
    subparsers = parser.add_subparsers(dest="command", required=True)

    version_parser = subparsers.add_parser("version", help="Show the local release version")
    version_parser.add_argument("--json", action="store_true")

    doctor_parser = subparsers.add_parser("doctor", help="Inspect local prerequisites without writing")
    doctor_parser.add_argument("--json", action="store_true")

    state_root = subparsers.add_parser("state-root", help="Inspect the resolved local state root")
    state_subparsers = state_root.add_subparsers(dest="state_command", required=True)
    state_status = state_subparsers.add_parser("status", help="Show state root status without writing")
    state_status.add_argument("--json", action="store_true")

    init_parser = subparsers.add_parser("init", help="Plan a complete managed project frame")
    init_parser.add_argument("target")
    init_parser.add_argument("--id", dest="project_id")
    init_parser.add_argument("--name")
    init_parser.add_argument("--objective")
    init_parser.add_argument("--force", action="store_true")
    init_parser.add_argument("--json", action="store_true")

    check_parser = subparsers.add_parser("check", help="Validate an existing managed project frame")
    check_parser.add_argument("target", nargs="?", default=".")
    check_parser.add_argument("--id", dest="project_id")
    check_parser.add_argument("--json", action="store_true")

    catalog_parser = subparsers.add_parser("catalog", help="Read and validate repository profiles")
    catalog_subparsers = catalog_parser.add_subparsers(dest="catalog_command", required=True)
    catalog_validate = catalog_subparsers.add_parser("validate")
    _add_catalog_source_arguments(catalog_validate)
    catalog_list = catalog_subparsers.add_parser("list")
    _add_catalog_source_arguments(catalog_list)
    catalog_list.add_argument("--include-archived", action="store_true")
    catalog_show = catalog_subparsers.add_parser("show")
    catalog_show.add_argument("repository_id")
    _add_catalog_source_arguments(catalog_show)
    catalog_show.add_argument("--include-archived", action="store_true")

    project_parser = subparsers.add_parser("project", help="Manage the local project registry")
    project_subparsers = project_parser.add_subparsers(dest="project_command", required=True)
    project_register = project_subparsers.add_parser("register")
    project_register.add_argument("path")
    project_register.add_argument("--id", required=True, dest="project_id")
    project_register.add_argument("--alias", action="append", default=[])
    project_register.add_argument("--domain", required=True)
    project_register.add_argument("--area", required=True)
    project_register.add_argument("--repository")
    project_register.add_argument("--catalog")
    project_register.add_argument("--json", action="store_true")
    project_list = project_subparsers.add_parser("list")
    project_list.add_argument("--catalog")
    project_list.add_argument("--include-archived", action="store_true")
    project_list.add_argument("--json", action="store_true")
    project_show = project_subparsers.add_parser("show")
    project_show.add_argument("project_id")
    project_show.add_argument("--catalog")
    project_show.add_argument("--include-archived", action="store_true")
    project_show.add_argument("--json", action="store_true")
    project_archive = project_subparsers.add_parser("archive")
    project_archive.add_argument("project_id")
    project_archive.add_argument("--catalog")
    project_archive.add_argument("--json", action="store_true")
    project_resolve = project_subparsers.add_parser("resolve")
    project_resolve.add_argument("goal")
    project_resolve.add_argument("--id", dest="identifier")
    project_resolve.add_argument("--domain")
    project_resolve.add_argument("--area")
    project_resolve.add_argument("--catalog")
    project_resolve.add_argument("--json", action="store_true")

    route_parser = subparsers.add_parser("route", help="Resolve a project and classify execution rigor")
    route_parser.add_argument("goal")
    route_parser.add_argument("--project")
    route_parser.add_argument("--domain")
    route_parser.add_argument("--area")
    route_parser.add_argument("--catalog")
    route_parser.add_argument("--bounded-loop", action="store_true")
    route_parser.add_argument("--json", action="store_true")

    render_parser = subparsers.add_parser("render", help="Plan one catalog repository deterministically")
    render_parser.add_argument("--catalog", required=True)
    render_parser.add_argument("--repository")
    render_mode = render_parser.add_mutually_exclusive_group(required=True)
    render_mode.add_argument("--dry-run", action="store_true")
    render_mode.add_argument("--write", action="store_true")
    render_parser.add_argument("--force", action="store_true")
    render_parser.add_argument("--json", action="store_true")

    new_parser = subparsers.add_parser("new", help="Resolve or plan an explicitly described local project")
    new_parser.add_argument("goal")
    new_parser.add_argument("--path")
    new_parser.add_argument("--id", dest="project_id")
    new_parser.add_argument("--domain")
    new_parser.add_argument("--area")
    new_parser.add_argument("--catalog")
    new_parser.add_argument("--force", action="store_true")
    new_parser.add_argument("--json", action="store_true")
    install_parsers(subparsers)
    install_local_ops_parsers(subparsers)
    install_resource_parsers(subparsers)
    return parser


def _add_catalog_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--file", dest="catalog_file")
    parser.add_argument("--json", action="store_true")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "version":
            return _version(json_output=args.json)
        if args.command == "doctor":
            return _doctor(json_output=args.json)
        if args.command == "state-root" and args.state_command == "status":
            return _state_root_status(json_output=args.json)
        if args.command == "init":
            return _init(args)
        if args.command == "check":
            return _check(args)
        if args.command == "catalog":
            return _catalog(args)
        if args.command == "project":
            return _project(args)
        if args.command == "route":
            return _route(args)
        if args.command == "render":
            return _render(args)
        if args.command == "new":
            return _new(args)
        if handles_durable(args):
            return dispatch_durable(args)
        if handles_local_ops(args):
            return dispatch_local_ops(args)
        if handles_resources(args):
            return dispatch_resources(args)
    except (
        CatalogError,
        ExecutionRuleError,
        RegistryError,
        RendererError,
        PathPolicyError,
        UnicodeError,
        json.JSONDecodeError,
        OSError,
        *HANDLED_ERRORS,
        *LOCAL_OPS_ERRORS,
        *RESOURCE_ERRORS,
    ) as exc:
        message = " ".join(str(exc).split())[:500] or type(exc).__name__
        print(f"plzdo: {type(exc).__name__}: {message}", file=sys.stderr)
        return 2
    raise AssertionError("unhandled command")


def _version(*, json_output: bool) -> int:
    disk_version = (repository_root() / "VERSION").read_text(encoding="utf-8").strip()
    status = "ok" if disk_version == __version__ else "version-drift"
    payload = {"schemaVersion": "plzdo-local.version-status.v1", "status": status, "version": __version__}
    _emit(payload, json_output=json_output)
    return 0 if status == "ok" else 1


def _doctor(*, json_output: bool) -> int:
    python_ok = sys.version_info >= MIN_PYTHON
    git_text = _git_version()
    bash_text = _bash_version()
    git_version = _parse_version(git_text)
    bash_version = _parse_version(bash_text)
    git_ok = git_version >= MIN_GIT if git_version is not None else False
    bash_ok = bash_version >= MIN_BASH if bash_version is not None else False
    state_root = resolve_state_root()
    release_version = (repository_root() / "VERSION").read_text(encoding="utf-8").strip()
    version_ok = release_version == __version__
    checks = {
        "python": python_ok,
        "git": git_ok,
        "bash": bash_ok,
        "version": version_ok,
        "supportedPlatform": platform.system() in {"Darwin", "Linux"},
    }
    payload = {
        "schemaVersion": "plzdo-local.doctor.v1",
        "status": "ok" if all(checks.values()) else "unsupported",
        "checks": checks,
        "platform": platform.system() or "unknown",
        "python": platform.python_version(),
        "git": git_text.splitlines()[0] if git_text else "unavailable",
        "bash": bash_text.splitlines()[0] if bash_text else "unavailable",
        "stateRoot": str(state_root),
        "version": __version__,
    }
    _emit(payload, json_output=json_output)
    return 0 if payload["status"] == "ok" else 1


def _state_root_status(*, json_output: bool) -> int:
    state_root = resolve_state_root()
    payload = {
        "schemaVersion": "plzdo-local.state-root-status.v1",
        "status": "configured",
        "path": str(state_root),
        "exists": state_root.exists(),
        "isSymlink": state_root.is_symlink(),
    }
    _emit(payload, json_output=json_output)
    return 0


def _init(args: argparse.Namespace) -> int:
    target = Path(args.target)
    project_id = args.project_id or _project_id_from_target(target)
    plan = plan_project_frame(
        target,
        project_id,
        project_name=args.name,
        objective=args.objective,
        force=args.force,
    )
    payload = _plan_payload(plan)
    payload.update(
        {
            "schemaVersion": "plzdo-local.init-plan.v1",
            "status": "planned",
            "projectId": project_id,
            "writesPerformed": False,
            "nextGate": "p5-apply",
        }
    )
    _emit(payload, json_output=args.json)
    return 0


def _check(args: argparse.Namespace) -> int:
    payload = inspect_project_frame(Path(args.target), expected_project_id=args.project_id)
    _emit(payload, json_output=args.json)
    return 0


def _catalog(args: argparse.Namespace) -> int:
    catalog = _load_catalog(args.catalog_file, allow_missing=args.catalog_file is None)
    if args.catalog_command == "validate":
        payload = {
            "schemaVersion": "plzdo-local.catalog-status.v1",
            "status": "valid",
            "repositoryCount": len(catalog["repositories"]),
        }
    elif args.catalog_command == "list":
        payload = {
            "schemaVersion": "plzdo-local.catalog-list.v1",
            "status": "ok",
            "repositories": list_repositories(catalog, include_archived=args.include_archived),
        }
    elif args.catalog_command == "show":
        payload = {
            "schemaVersion": "plzdo-local.catalog-show.v1",
            "status": "ok",
            "repository": get_repository(
                catalog,
                args.repository_id,
                include_archived=args.include_archived,
            ),
        }
    else:
        raise AssertionError("unhandled catalog command")
    _emit(payload, json_output=args.json)
    return 0


def _project(args: argparse.Namespace) -> int:
    catalog = _optional_catalog(args.catalog)
    if args.project_command == "register":
        frame = inspect_project_frame(Path(args.path), expected_project_id=args.project_id)
        if args.repository is not None and catalog is None:
            raise RegistryError("--repository requires an existing --catalog document")
        project = build_project(
            project_id=args.project_id,
            aliases=args.alias,
            domain=args.domain,
            area=args.area,
            path=args.path,
            repository_id=args.repository,
            path_must_exist=True,
        )

        def frame_precondition() -> None:
            current = inspect_project_frame(Path(args.path), expected_project_id=args.project_id)
            if current["frameSha256"] != frame["frameSha256"]:
                raise RendererError("managed project frame changed during registration")

        registry = _persist_registry_transition(
            lambda current: register_project(current, project, render_succeeded=True, catalog=catalog),
            catalog=catalog,
            precondition=frame_precondition,
        )
        payload = {
            "schemaVersion": "plzdo-local.project-register-result.v1",
            "status": "registered",
            "project": get_project(registry, args.project_id, catalog=catalog),
            "frame": frame,
        }
    elif args.project_command == "list":
        registry = _load_registry(catalog=catalog)
        payload = {
            "schemaVersion": "plzdo-local.project-list.v1",
            "status": "ok",
            "projects": list_projects(registry, include_archived=args.include_archived, catalog=catalog),
        }
    elif args.project_command == "show":
        registry = _load_registry(catalog=catalog)
        payload = {
            "schemaVersion": "plzdo-local.project-show.v1",
            "status": "ok",
            "project": get_project(
                registry,
                args.project_id,
                include_archived=args.include_archived,
                catalog=catalog,
            ),
        }
    elif args.project_command == "archive":
        registry = _persist_registry_transition(
            lambda current: archive_project(current, args.project_id, catalog=catalog),
            catalog=catalog,
        )
        payload = {
            "schemaVersion": "plzdo-local.project-archive-result.v1",
            "status": "archived",
            "project": get_project(registry, args.project_id, include_archived=True, catalog=catalog),
        }
    elif args.project_command == "resolve":
        registry = _load_registry(catalog=catalog)
        payload = resolve_project(
            registry,
            args.goal,
            identifier=args.identifier,
            domain=args.domain,
            area=args.area,
            catalog=catalog,
        )
    else:
        raise AssertionError("unhandled project command")
    _emit(payload, json_output=args.json)
    return 0


def _route(args: argparse.Namespace) -> int:
    catalog = _optional_catalog(args.catalog)
    registry = _load_registry(catalog=catalog)
    payload = route_goal(
        args.goal,
        registry,
        catalog=catalog,
        identifier=args.project,
        domain=args.domain,
        area=args.area,
        bounded_loop_requested=args.bounded_loop,
    )
    _emit(payload, json_output=args.json)
    return 0


def _render(args: argparse.Namespace) -> int:
    if args.write:
        raise RendererError("render --write is unsupported; use the separate default-disabled P5 apply gate entry point")
    catalog = _load_catalog(args.catalog, allow_missing=False)
    repository = _select_render_repository(catalog, args.repository)
    plan = plan_project_frame(repository["path"], repository["id"], force=args.force)
    payload = _plan_payload(plan)
    payload.update({"status": "planned", "writesPerformed": False, "nextGate": "p5-apply"})
    _emit(payload, json_output=args.json)
    return 0


def _new(args: argparse.Namespace) -> int:
    catalog = _optional_catalog(args.catalog)
    registry = _load_registry(catalog=catalog)
    route = route_goal(
        args.goal,
        registry,
        catalog=catalog,
        identifier=args.project_id,
        domain=args.domain,
        area=args.area,
    )
    if route["projectDecision"]["decision"] != "create":
        payload = {
            "schemaVersion": "plzdo-local.new-result.v1",
            "status": route["projectDecision"]["decision"],
            "route": route,
            "writesPerformed": False,
        }
        _emit(payload, json_output=args.json)
        return 0

    required = {"path": args.path, "id": args.project_id, "domain": args.domain, "area": args.area}
    missing = sorted(key for key, value in required.items() if value is None)
    if missing:
        payload = {
            "schemaVersion": "plzdo-local.new-result.v1",
            "status": "ask",
            "route": route,
            "writesPerformed": False,
            "missingInputs": missing,
        }
        _emit(payload, json_output=args.json)
        return 0

    plan = plan_project_frame(args.path, args.project_id, objective=args.goal, force=args.force)
    payload = {
        "schemaVersion": "plzdo-local.new-result.v1",
        "status": "planned",
        "route": route,
        "writesPerformed": False,
        "projectDraft": {
            "id": args.project_id,
            "domain": args.domain,
            "area": args.area,
            "path": str(plan.target),
        },
        "plan": _plan_payload(plan),
        "nextGate": "p5-apply",
    }
    _emit(payload, json_output=args.json)
    return 0


def _project_id_from_target(target: Path) -> str:
    name = target.expanduser().name
    try:
        return require_safe_id(name, label="target directory name")
    except ValueError as exc:
        raise RendererError("target directory name is not a safe project id; pass --id") from exc


def _select_render_repository(catalog: dict[str, Any], repository_id: Optional[str]) -> dict[str, Any]:
    if repository_id is not None:
        return get_repository(catalog, repository_id)
    active = list_repositories(catalog)
    if len(active) != 1:
        raise CatalogError("render requires --repository unless the catalog has exactly one active repository")
    return active[0]


def _plan_payload(plan: Any) -> dict[str, object]:
    payload = plan.as_dict()
    payload["mode"] = "dry-run"
    return payload


def _catalog_state_path() -> Path:
    root = resolve_state_root()
    return ensure_contained(root / "catalog" / "catalog.json", root, label="catalog state path")


def _registry_state_path() -> Path:
    root = resolve_state_root()
    return ensure_contained(root / "registry" / "registry.json", root, label="registry state path")


def _load_catalog(configured: Optional[str], *, allow_missing: bool) -> dict[str, Any]:
    path = Path(configured).expanduser() if configured is not None else _catalog_state_path()
    if not path.exists():
        if allow_missing:
            return build_catalog()
        raise CatalogError("catalog document does not exist")
    value = _read_json_document(path, label="catalog")
    validate_catalog(value)
    return value


def _optional_catalog(configured: Optional[str]) -> Optional[dict[str, Any]]:
    if configured is not None:
        return _load_catalog(configured, allow_missing=False)
    path = _catalog_state_path()
    if not path.exists():
        return None
    return _load_catalog(None, allow_missing=False)


def _load_registry(*, catalog: Optional[dict[str, Any]]) -> dict[str, Any]:
    path = _registry_state_path()
    if not path.exists():
        return build_registry(catalog=catalog)
    value = _read_json_document(path, label="registry")
    validate_registry(value, catalog=catalog)
    return value


def _persist_registry_transition(
    transition: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    catalog: Optional[dict[str, Any]],
    precondition: Optional[Callable[[], None]] = None,
) -> dict[str, Any]:
    state_root = resolve_state_root()
    path = _registry_state_path()
    lock = ensure_contained(state_root / "locks" / "registry.lock", state_root, label="registry lock")
    with exclusive_file_lock(lock, allowed_root=state_root):
        current = _load_registry(catalog=catalog)
        updated = transition(current)
        validate_registry(updated, catalog=catalog)
        if precondition is not None:
            precondition()
        atomic_write_json(
            path,
            updated,
            allowed_root=state_root,
            validator=lambda value: validate_registry(value, catalog=catalog),
        )
    return updated


def _read_json_document(path: Path, *, label: str) -> Any:
    if path.is_symlink():
        raise PathPolicyError(f"{label} document must not be a symlink")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise PathPolicyError(f"{label} document must be a regular file")
        if metadata.st_size > MAX_CONTROL_DOCUMENT_BYTES:
            raise PathPolicyError(f"{label} document exceeds the byte limit")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(65536, MAX_CONTROL_DOCUMENT_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_CONTROL_DOCUMENT_BYTES:
                raise PathPolicyError(f"{label} document exceeds the byte limit")
    finally:
        os.close(descriptor)
    return json.loads(
        b"".join(chunks).decode("utf-8"),
        object_pairs_hook=lambda pairs: _json_object_without_duplicates(pairs, label=label),
    )


def _json_object_without_duplicates(pairs: list[tuple[str, Any]], *, label: str) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PathPolicyError(f"{label} document contains a duplicate key")
        value[key] = item
    return value


def _git_version() -> str:
    try:
        completed = subprocess.run(["/usr/bin/git", "--version"], check=False, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() or completed.stderr.strip()


def _bash_version() -> str:
    try:
        completed = subprocess.run(["/bin/bash", "--version"], check=False, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() or completed.stderr.strip()


def _parse_version(text: str) -> Optional[tuple[int, int]]:
    match = re.search(r"(\d+)\.(\d+)", text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _emit(payload: dict[str, object], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        return
    print(f"status: {payload.get('status', 'ok')}")
    for key, value in payload.items():
        if key not in {"schemaVersion", "status"}:
            print(f"{key}: {value}")
