"""Configure optional delegation pins; core approval stays an operator action."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from . import __version__


def configure(*, core_root: Path, core_python: Path, state_root: Path,
              project_root: Path, project_id: str, formalization_id: str,
              output: Path, verifier_python: Path | None = None) -> dict:
    from .codec import (AdapterError, CONFIG_SCHEMA, CORE_VERSION, MAX_PYTHON, canonical, closure,
                        core_files, core_roots, digest, file_pin, root_pin, safe_id, safe_path)
    # Resolve only the interpreter executing this adapter. Caller supplied core,
    # state and project paths must already be canonical; no hidden pin refresh.
    adapter_root = Path(__file__).resolve().parent
    selected_python = verifier_python if verifier_python is not None else Path(sys.executable).resolve()
    interpreter_pin = file_pin(selected_python, MAX_PYTHON)
    config = {"schemaVersion": CONFIG_SCHEMA, "coreVersion": CORE_VERSION,
              "coreRoot": root_pin(core_root), "corePython": file_pin(core_python, MAX_PYTHON),
              "coreCodeFiles": [file_pin(path) for path in core_files(core_root)]}
    reference = {"state": root_pin(state_root), "formalizationId": safe_id(formalization_id),
                 "projectId": safe_id(project_id), "project": root_pin(project_root)}
    safe_path(str(output.parent), directory=True)
    if output.exists() or output.is_symlink():
        raise AdapterError("configuration output must be unused")
    # A new private directory is deliberately used. Partial configurations remain
    # visible and cannot be overwritten by a retry.
    output.mkdir(mode=0o700)

    def create(name, value):
        path = output / name
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as target:
            target.write(canonical(value) + b"\n")
            target.flush()
            os.fsync(target.fileno())
        return path

    config_path = create("adapter-config.json", config)
    package_files = [file_pin(path) for path in closure(adapter_root)]
    verifier = {"python": interpreter_pin,
                "entrypoint": file_pin(adapter_root / "verify_parent.py"),
                "codeFiles": sorted(package_files + config["coreCodeFiles"], key=lambda row: row["path"]),
                "codeRoots": sorted([root_pin(adapter_root), *[root_pin(path) for path in core_roots(core_root)]],
                                    key=lambda row: row['path']),
                "config": file_pin(config_path)}
    create("parent-reference.json", reference)
    create("verifier.json", verifier)
    return {"status": "configured", "parentReference": str(output / "parent-reference.json"),
            "verifier": str(output / "verifier.json"), "config": str(config_path),
            "verifierSha256": digest(verifier)}


def reference(*, state_root: Path, project_root: Path, project_id: str,
              formalization_id: str, output: Path) -> dict:
    """Create a new task reference while reusing the existing fixed verifier."""
    from .codec import canonical, root_pin, safe_id, safe_path
    value = {"state": root_pin(state_root), "project": root_pin(project_root),
             "projectId": safe_id(project_id), "formalizationId": safe_id(formalization_id)}
    safe_path(str(output.parent), directory=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as target:
        target.write(canonical(value) + b'\n')
        target.flush()
        os.fsync(target.fileno())
    return {"status": "referenced", "parentReference": str(output)}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="plzdo-local-code-adapter")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("configure", help="Write a new local pin bundle; no core/runtime invocation")
    setup.add_argument("--core-root", type=Path, required=True,
                       help="Canonical source checkout root or installed plzdo_local package directory")
    for flag in ("core-python", "state-root", "project-root", "output"):
        setup.add_argument("--" + flag, type=Path, required=True)
    setup.add_argument("--project-id", required=True)
    setup.add_argument("--verifier-python", type=Path,
                       help="Canonical trusted Python executable; default is this interpreter")
    setup.add_argument("--formalization-id", required=True, help="Proposed unused core goal ID")
    verify_parser = commands.add_parser("verify-parent", help="Read one runtime verifier envelope on stdin")
    verify_parser.add_argument("--config", type=Path, required=True)
    ref_parser = commands.add_parser('reference', help='Write a new task reference for the existing trusted verifier')
    for flag in ('state-root', 'project-root', 'output'):
        ref_parser.add_argument('--' + flag, type=Path, required=True)
    ref_parser.add_argument('--project-id', required=True)
    ref_parser.add_argument('--formalization-id', required=True)
    args = parser.parse_args(argv)
    if args.command == "verify-parent":
        from .verify_parent import main as verify_main
        return verify_main(["--config", str(args.config)])
    from .codec import AdapterError, canonical
    try:
        if args.command == 'reference':
            result = reference(state_root=args.state_root, project_root=args.project_root,
                               project_id=args.project_id, formalization_id=args.formalization_id,
                               output=args.output)
        else:
            result = configure(core_root=args.core_root, core_python=args.core_python,
                               state_root=args.state_root, project_root=args.project_root,
                               project_id=args.project_id, formalization_id=args.formalization_id,
                               output=args.output, verifier_python=args.verifier_python)
        sys.stdout.buffer.write(canonical(result) + b"\n")
        return 0
    except (AdapterError, OSError, ValueError, TypeError):
        print("plzdo-local-code-adapter: configuration rejected", file=sys.stderr)
        return 2
