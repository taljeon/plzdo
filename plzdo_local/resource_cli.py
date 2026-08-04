from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .managed_install import (
    ManagedInstallError,
    StaticCatalogError,
    install_agent,
    install_skill,
    list_catalog_entries,
    list_public_agents,
    list_public_skills,
    search_static_catalog,
    show_static_catalog_entry,
    uninstall_agent,
    uninstall_skill,
)


HANDLED_ERRORS = (ManagedInstallError, StaticCatalogError)
RESOURCE_COMMANDS = {"skills", "agents", "sources", "design"}


def install_parsers(subparsers: argparse._SubParsersAction) -> None:
    for command, kind in (("skills", "skill"), ("agents", "agent")):
        parser = subparsers.add_parser(command, help=f"Manage repository-owned public {command}")
        actions = parser.add_subparsers(dest=f"{kind}_command", required=True)
        list_parser = actions.add_parser("list")
        list_parser.add_argument("--json", action="store_true")
        install = actions.add_parser("install")
        install.add_argument("name")
        install.add_argument("--root")
        install.add_argument("--dry-run", action="store_true")
        install.add_argument("--force", action="store_true")
        install.add_argument("--json", action="store_true")
        uninstall = actions.add_parser("uninstall")
        uninstall.add_argument("name")
        uninstall.add_argument("--root")
        uninstall.add_argument("--dry-run", action="store_true")
        uninstall.add_argument("--json", action="store_true")

    for command in ("sources", "design"):
        parser = subparsers.add_parser(command, help=f"Read the bundled {command} catalog")
        actions = parser.add_subparsers(dest="static_catalog_command", required=True)
        list_parser = actions.add_parser("list")
        list_parser.add_argument("--json", action="store_true")
        search = actions.add_parser("search")
        search.add_argument("query")
        search.add_argument("--json", action="store_true")
        show = actions.add_parser("show")
        show.add_argument("entry_id")
        show.add_argument("--json", action="store_true")


def handles(args: argparse.Namespace) -> bool:
    return getattr(args, "command", None) in RESOURCE_COMMANDS


def dispatch(args: argparse.Namespace) -> int:
    if args.command in {"skills", "agents"}:
        return _managed_resource(args)
    return _static_catalog(args)


def _managed_resource(args: argparse.Namespace) -> int:
    kind = "skill" if args.command == "skills" else "agent"
    action = getattr(args, f"{kind}_command")
    if action == "list":
        names = list_public_skills() if kind == "skill" else list_public_agents()
        _emit({"schemaVersion": "plzdo-local.resource-list.v1", "resourceType": kind, "items": list(names)}, args.json)
        return 0

    root = Path(args.root).expanduser() if args.root else _default_resource_root(kind)
    if action == "install":
        function = install_skill if kind == "skill" else install_agent
        result = function(args.name, root, dry_run=args.dry_run, force=args.force)
    else:
        function = uninstall_skill if kind == "skill" else uninstall_agent
        result = function(args.name, root, dry_run=args.dry_run)
    _emit(result, args.json)
    return 0


def _static_catalog(args: argparse.Namespace) -> int:
    catalog = args.command
    action = args.static_catalog_command
    if action == "list":
        items = list_catalog_entries(catalog)
    elif action == "search":
        items = search_static_catalog(catalog, args.query)
    else:
        _emit(show_static_catalog_entry(catalog, args.entry_id), args.json)
        return 0
    _emit(
        {"schemaVersion": "plzdo-local.static-catalog-result.v1", "catalog": catalog, "items": list(items)},
        args.json,
    )
    return 0


def _default_resource_root(kind: str) -> Path:
    configured = os.environ.get("CODEX_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return base / ("skills" if kind == "skill" else "agents")


def _emit(value: Any, json_output: bool) -> None:
    if json_output:
        print(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True))
        return
    if isinstance(value, dict) and isinstance(value.get("items"), list):
        for item in value["items"]:
            print(item if isinstance(item, str) else f"{item['id']}: {item['name']} [{item['decision']}]")
        return
    print(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True))
