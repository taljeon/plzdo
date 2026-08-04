from __future__ import annotations

import ast
import copy
import re
import stat
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent
REQUIRED_FILES = {
    ".github/workflows/verify.yml",
    ".gitignore",
    "AGENTS.md",
    "CHANGELOG.md",
    "CHECKS.md",
    "CONTRIBUTING.md",
    "FINDINGS.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "TASKS/current.md",
    "VERSION",
    "bin/plzdo",
    "bin/plzdo_entry.py",
    "docs/architecture.md",
    "docs/command-reference.md",
    "docs/data-and-privacy.md",
    "docs/local-only-boundary.md",
    "docs/portability.md",
    "docs/real-apply.md",
    "docs/state-and-memory.md",
    "docs/what-not-to-automate.md",
    "examples/basic-project/AGENTS.md",
    "examples/basic-project/CHECKS.md",
    "examples/basic-project/README.md",
    "examples/basic-project/TASKS/current.md",
    "examples/basic-project/docs/requirements.md",
    "examples/basic-project/docs/technical-design.md",
    "examples/basic-project/scripts/verify",
    "examples/operational-apply-project/README.md",
    "examples/operational-apply-project/catalog.template.json",
    "examples/operational-apply-project/project.template.json",
    "plzdo_local/__init__.py",
    "plzdo_local/__main__.py",
    "plzdo_local/apply_cli.py",
    "plzdo_local/apply_gate.py",
    "plzdo_local/atomic_io.py",
    "plzdo_local/catalog.py",
    "plzdo_local/cli.py",
    "plzdo_local/context.py",
    "plzdo_local/durable_cli.py",
    "plzdo_local/execution_rules.py",
    "plzdo_local/failure_report.py",
    "plzdo_local/findings.py",
    "plzdo_local/formalization.py",
    "plzdo_local/local_memory.py",
    "plzdo_local/local_ops_cli.py",
    "plzdo_local/managed_install.py",
    "plzdo_local/metrics.py",
    "plzdo_local/monitor.py",
    "plzdo_local/paths.py",
    "plzdo_local/registry.py",
    "plzdo_local/renderer.py",
    "plzdo_local/resource_cli.py",
    "plzdo_local/review_bundle.py",
    "plzdo_local/state.py",
    "plzdo_local/validation.py",
    "review/IMPLEMENTATION-REVIEW.md",
    "schemas/context.schema.json",
    "schemas/apply-plan.schema.json",
    "schemas/findings.schema.json",
    "schemas/formalization.schema.json",
    "schemas/memory.schema.json",
    "schemas/metric.schema.json",
    "schemas/managed-install.schema.json",
    "scripts/release-manifest",
    "scripts/release_manifest.py",
    "scripts/check-release-leaks",
    "scripts/check_publication.py",
    "scripts/check_release_leaks.py",
    "scripts/check-publication",
    "scripts/export_worktree.py",
    "scripts/verify",
    "schemas/catalog.schema.json",
    "schemas/registry.schema.json",
    "schemas/state.schema.json",
    "templates/project-harness/AGENTS.md",
    "templates/project-harness/CHECKS.md",
    "templates/project-harness/TASKS/current.md",
    "templates/project-harness/docs/requirements.md",
    "templates/project-harness/docs/technical-design.md",
    "templates/project-harness/scripts/verify",
    "tests/contract_check.py",
    "tests/phase2_check.py",
    "tests/phase3_check.py",
    "tests/phase4_check.py",
    "tests/phase5_check.py",
    "tests/local_ops_check.py",
    "tests/release_check.py",
    "tests/smoke_check.py",
}
EXECUTABLE_FILES = {
    "bin/plzdo",
    "scripts/check-release-leaks",
    "scripts/check-publication",
    "scripts/release-manifest",
    "scripts/verify",
    "templates/project-harness/scripts/verify",
    "examples/basic-project/scripts/verify",
}
FORBIDDEN_RUNTIME_IMPORTS = {
    "aiohttp",
    "ftplib",
    "http",
    "importlib",
    "paramiko",
    "requests",
    "smtplib",
    "socket",
    "urllib",
    "webbrowser",
}
PROCESS_APIS = {
    "Popen",
    "call",
    "check_call",
    "check_output",
    "create_subprocess_exec",
    "create_subprocess_shell",
    "getoutput",
    "getstatusoutput",
    "posix_spawn",
    "posix_spawnp",
    "run",
    "spawn",
    "os.popen",
    "os.system",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.getoutput",
    "subprocess.getstatusoutput",
}
PROCESS_API_PREFIXES = ("asyncio.create_subprocess", "os.exec", "os.posix_spawn", "os.spawn", "subprocess.")
ALLOWED_SUBPROCESS_CALLS = {
    ("plzdo_local/cli.py", ("/usr/bin/git", "--version")),
    ("plzdo_local/cli.py", ("/bin/bash", "--version")),
}
ALLOWED_VERIFICATION_PROCESS_HEADS = {
    "tests/smoke_check.py": {
        "python:plzdo-entry",
        "root:bin/plzdo",
        "root:scripts/check-release-leaks",
        "root:scripts/verify",
    },
    "tests/phase2_check.py": {"python:plzdo-entry", "root:templates/project-harness/scripts/verify"},
    "tests/release_check.py": {"root:scripts/check-publication"},
}
ALLOWED_GIT_POPEN_FUNCTION = ("plzdo_local/apply_gate.py", "_run_git")
ALLOWED_PUBLICATION_GIT_POPEN_FUNCTION = ("scripts/check_publication.py", "_run_git")
ALLOWED_BOUNDED_PROCESS_FUNCTIONS = {
    ("tests/phase4_check.py", "fixture_git"),
    ("tests/release_check.py", "git"),
}
FORBIDDEN_POPEN_KEYWORDS = {"cwd", "executable", "preexec_fn", "shell"}
EXPECTED_GIT_SUFFIXES = {
    "root": ("rev-parse", "--show-toplevel"),
    "git-dir": ("rev-parse", "--absolute-git-dir"),
    "git-common-dir": ("rev-parse", "--git-common-dir"),
    "head": ("rev-parse", "--verify", "HEAD"),
    "config-keys": ("config", "--local", "--no-includes", "--name-only", "--null", "--list"),
    "index-entries": ("ls-files", "--stage", "-z"),
    "all-paths": ("ls-files", "-z", "--cached", "--others", "--exclude-standard"),
    "ignored-paths": ("ls-files", "-z", "--others", "--ignored", "--exclude-standard"),
    "status": ("status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=all"),
}
FORBIDDEN_DYNAMIC_BUILTINS = {"__import__", "compile", "eval", "exec"}
FORBIDDEN_SHELL_WORDS = re.compile(
    r"\b(?:agbrowse|apt|apt-get|browser|chatgpt|chromium|cron|crontab|curl|fetch|gh|grok|launchctl|nohup|npm|npx|open|osascript|pip|pipx|playwright|pnpm|scp|ssh|systemctl|wget|yarn)\b"
)
ALLOWED_SHELL_ABSOLUTE_PATHS = {
    "bin/plzdo": {
        "/bin/sh",
        "/opt/homebrew/bin/python3",
        "/usr/bin/python3",
        "/usr/local/bin/python3",
    },
    "scripts/verify": {
        "/bin",
        "/bin/sh",
        "/opt/homebrew/bin",
        "/opt/homebrew/bin/python3",
        "/usr/bin",
        "/usr/bin/python3",
        "/usr/local/bin",
        "/usr/local/bin/python3",
    },
    "scripts/check-release-leaks": {
        "/bin/sh",
        "/opt/homebrew/bin/python3",
        "/usr/bin/python3",
        "/usr/local/bin/python3",
    },
    "scripts/check-publication": {
        "/bin/sh",
        "/opt/homebrew/bin/python3",
        "/usr/bin/python3",
        "/usr/local/bin/python3",
    },
    "scripts/release-manifest": {
        "/bin/sh",
        "/opt/homebrew/bin/python3",
        "/usr/bin/python3",
        "/usr/local/bin/python3",
    },
}


def main() -> int:
    failures: list[str] = []
    check_required_files(failures)
    check_executable_bits(failures)
    check_executable_inventory(failures)
    check_no_symlinks(failures)
    check_version_parity(failures)
    check_runtime_ast(failures)
    check_shell_runtime(failures)
    check_guard_self_tests(failures)
    check_bootstrap_contract(failures)
    check_review_bindings(failures)
    check_phase2_bindings(failures)
    check_phase3_bindings(failures)
    check_phase4_bindings(failures)
    check_phase5_bindings(failures)
    check_local_ops_bindings(failures)
    check_release_bindings(failures)
    check_no_git_metadata(failures)
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print("integrated contract check passed")
    return 0


def check_required_files(failures: list[str]) -> None:
    for relative in sorted(REQUIRED_FILES):
        if not (ROOT / relative).is_file():
            failures.append(f"required-file-missing:{relative}")


def check_executable_bits(failures: list[str]) -> None:
    for relative in sorted(EXECUTABLE_FILES):
        path = ROOT / relative
        if path.is_file() and not path.stat().st_mode & stat.S_IXUSR:
            failures.append(f"executable-bit-missing:{relative}")


def check_executable_inventory(failures: list[str]) -> None:
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            relative = path.relative_to(ROOT).as_posix()
            if relative not in EXECUTABLE_FILES:
                failures.append(f"unexpected-executable:{relative}")


def check_no_symlinks(failures: list[str]) -> None:
    for path in ROOT.rglob("*"):
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            failures.append(f"release-symlink:{path.relative_to(ROOT).as_posix()}")


def check_version_parity(failures: list[str]) -> None:
    disk = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    source = (ROOT / "plzdo_local/__init__.py").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', source, re.MULTILINE)
    if match is None or match.group(1) != disk:
        failures.append("version-parity")
    if re.search(rf"^## {re.escape(disk)}$", changelog, re.MULTILINE) is None:
        failures.append("version-changelog-parity")


def check_runtime_ast(failures: list[str]) -> None:
    runtime_paths = sorted((ROOT / "plzdo_local").rglob("*.py")) + [
        ROOT / "bin/plzdo_entry.py",
        ROOT / "scripts/check_publication.py",
        ROOT / "scripts/check_release_leaks.py",
        ROOT / "scripts/export_worktree.py",
        ROOT / "scripts/release_manifest.py",
    ]
    verification_paths = sorted((ROOT / "tests").rglob("*.py"))
    for path in runtime_paths + verification_paths:
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative, feature_version=(3, 9))
        aliases = _import_aliases(tree)
        function_map = _function_map(tree)
        if relative == ALLOWED_GIT_POPEN_FUNCTION[0]:
            _check_apply_gate_git_process_contract(tree, relative, failures)
        if relative == ALLOWED_PUBLICATION_GIT_POPEN_FUNCTION[0]:
            _check_publication_git_process_contract(tree, relative, failures)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in FORBIDDEN_RUNTIME_IMPORTS:
                        failures.append(f"forbidden-runtime-import:{relative}:{alias.name}")
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in FORBIDDEN_RUNTIME_IMPORTS:
                    failures.append(f"forbidden-runtime-import:{relative}:{node.module}")
            if not isinstance(node, ast.Call):
                continue
            call_name = _resolved_call_name(node.func, aliases)
            function_name = function_map.get(node, "")
            if path in runtime_paths:
                _check_runtime_process_call(node, relative, aliases, failures, function_name=function_name)
            if path in verification_paths and _is_process_api(call_name):
                if call_name != "subprocess.run":
                    failures.append(f"verification-process-api:{relative}:{getattr(node, 'lineno', 0)}")
                elif (relative, function_name) in ALLOWED_BOUNDED_PROCESS_FUNCTIONS:
                    _check_bounded_process_call(node, relative, function_name, failures)
                else:
                    _check_verification_subprocess(node, relative, failures)


def check_shell_runtime(failures: list[str]) -> None:
    for relative in sorted(EXECUTABLE_FILES):
        source = (ROOT / relative).read_text(encoding="utf-8")
        if not source.startswith(("#!/bin/sh", "#!/usr/bin/env bash", "#!/bin/bash")):
            continue
        failures.extend(_shell_source_failures(relative, source))


def check_guard_self_tests(failures: list[str]) -> None:
    shell_probes = ("/usr/bin/" + "curl https://example.invalid", "tool=" + "curl; $tool https://example.invalid")
    for index, source in enumerate(shell_probes, 1):
        if not _shell_source_failures("fixture", source):
            failures.append(f"shell-guard-self-test:{index}")
    for name in ("subprocess.getoutput", "run", "os.posix_spawn", "asyncio.create_subprocess_exec"):
        if not _is_process_api(name):
            failures.append(f"process-guard-self-test:{name}")
    if _shell_source_failures("scripts/verify", '"$root/scripts/release-manifest" --check'):
        failures.append("shell-owned-release-gate-self-test")
    if not _shell_source_failures("scripts/verify", '"$root/scripts/unreviewed-tool"'):
        failures.append("shell-variable-command-self-test")
    python_probes = (
        "from subprocess import run as alias\nalias(['/usr/bin/git', '--version'])\n",
        "import subprocess as child\nchild.getoutput('true')\n",
        "getattr(__import__('subprocess'), 'run')(['/usr/bin/git', '--version'])\n",
    )
    for index, source in enumerate(python_probes, 1):
        tree = ast.parse(source, feature_version=(3, 9))
        aliases = _import_aliases(tree)
        probe_failures: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                _check_runtime_process_call(node, "fixture.py", aliases, probe_failures, function_name="")
        if not probe_failures:
            failures.append(f"python-process-guard-self-test:{index}")
    _check_git_popen_guard_self_test(failures)
    if not _shell_source_failures("fixture", "#!/bin/sh\n/usr/bin/python3 -V\n"):
        failures.append("shell-file-scope-guard-self-test")
    verification_probes = (
        "subprocess.run([target_script])",
        "subprocess.run([str(target / 'scripts/verify')])",
        "subprocess.run([Path('/tmp/tool')])",
        "subprocess.run(['/tmp/tool'])",
        "subprocess.run([sys.executable, '-B', '-I', str(target / 'evil.py')])",
    )
    for index, source in enumerate(verification_probes, 1):
        tree = ast.parse(source, feature_version=(3, 9))
        probe_failures: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node.func) == "subprocess.run":
                _check_verification_subprocess(node, "tests/phase2_check.py", probe_failures)
        if not probe_failures:
            failures.append(f"verification-process-guard-self-test:{index}")


def check_bootstrap_contract(failures: list[str]) -> None:
    wrapper = (ROOT / "bin/plzdo").read_text(encoding="utf-8")
    scanner = (ROOT / "scripts/check-release-leaks").read_text(encoding="utf-8")
    verify = (ROOT / "scripts/verify").read_text(encoding="utf-8")
    publication = (ROOT / "scripts/check-publication").read_text(encoding="utf-8")
    for label, source in (("cli", wrapper), ("scanner", scanner), ("publication", publication)):
        if 'exec "$python_bin" -B -I ' not in source:
            failures.append(f"isolated-bootstrap-missing:{label}")
        for variable in ("PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE"):
            if variable not in source:
                failures.append(f"bootstrap-unset-missing:{label}:{variable}")
    for variable in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY"):
        if variable not in publication:
            failures.append(f"publication-git-environment-unset-missing:{variable}")
    required_verify_invocations = (
        '"$root/scripts/release-manifest" --check',
        '"$python_bin" -B -I "$root/tests/contract_check.py"',
        '"$python_bin" -B -I "$root/tests/smoke_check.py"',
        '"$python_bin" -B -I "$root/tests/phase2_check.py"',
        '"$python_bin" -B -I "$root/tests/phase3_check.py"',
        '"$python_bin" -B -I "$root/tests/phase4_check.py"',
        '"$python_bin" -B -I "$root/tests/phase5_check.py"',
        '"$python_bin" -B -I "$root/tests/local_ops_check.py"',
        '"$python_bin" -B -I "$root/tests/release_check.py"',
    )
    for invocation in required_verify_invocations:
        if invocation not in verify:
            failures.append("isolated-verify-invocation-missing")
    if "PYTHONUSERBASE" not in verify or "PYTHONPATH" not in verify:
        failures.append("verify-python-environment-not-cleared")


def check_review_bindings(failures: list[str]) -> None:
    review = (ROOT / "review/IMPLEMENTATION-REVIEW.md").read_text(encoding="utf-8")
    required = {
        "review-authority": "Review authority: advisory",
        "review-source-of-truth": "Source of truth: false",
        "private-denylist": "Private denylist: external-only",
        "runtime-provider-send": "Provider sends: none in runtime",
        "publication-status": "Publication status:",
        "external-review-status": "External advisory review:",
        "p5-focused-review": "P5 focused review: PASS",
    }
    for label, token in required.items():
        if token not in review:
            failures.append(f"review-binding-missing:{label}")
    if "Expected verdict" in review:
        failures.append("review-verdict-anchoring")


def check_phase2_bindings(failures: list[str]) -> None:
    cli_source = (ROOT / "plzdo_local/cli.py").read_text(encoding="utf-8")
    registry_source = (ROOT / "plzdo_local/registry.py").read_text(encoding="utf-8")
    route_source = (ROOT / "plzdo_local/execution_rules.py").read_text(encoding="utf-8")
    renderer_source = (ROOT / "plzdo_local/renderer.py").read_text(encoding="utf-8")
    verifier_source = (ROOT / "templates/project-harness/scripts/verify").read_text(encoding="utf-8")
    semantic_pins = {
        "p5-render-block": "render --write is unsupported; use the separate default-disabled P5 apply gate entry point",
        "render-before-register": "project registration requires a successful render",
        "identity-not-weight": "_without_project_identity_terms",
        "managed-frame-inspection": "inspect_project_frame",
        "descriptor-relative-verifier": "dir_fd=parent_fd",
    }
    combined = "\n".join((cli_source, registry_source, route_source, renderer_source, verifier_source))
    for label, token in semantic_pins.items():
        if token not in combined:
            failures.append(f"phase2-semantic-pin-missing:{label}")
    if "def write_project_frame" in renderer_source:
        failures.append("phase2-pre-p5-writer-present")

    for path in sorted((ROOT / "plzdo_local").rglob("*.py")):
        if path.name == "renderer.py":
            continue
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative, feature_version=(3, 9))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node.func).endswith("write_project_frame"):
                failures.append(f"phase2-target-write-call:{relative}:{getattr(node, 'lineno', 0)}")

    test_tree = ast.parse(
        (ROOT / "tests/phase2_check.py").read_text(encoding="utf-8"),
        filename="tests/phase2_check.py",
        feature_version=(3, 9),
    )
    bound_checks: set[str] = set()
    for node in ast.walk(test_tree):
        if not isinstance(node, ast.List):
            continue
        for item in node.elts:
            if (
                isinstance(item, ast.Tuple)
                and len(item.elts) == 2
                and isinstance(item.elts[0], ast.Constant)
                and isinstance(item.elts[1], ast.Name)
            ):
                bound_checks.add(item.elts[1].id)
    required_checks = {
        "check_catalog_contract",
        "check_registry_resolution",
        "check_execution_routes",
        "check_renderer_determinism",
        "check_renderer_fixture_materialization",
        "check_generated_verifier_descriptor_reads",
        "check_renderer_safety",
        "check_cli_plan_only",
        "check_cli_catalog",
        "check_cli_registry_lifecycle",
        "check_cli_render_write_blocked",
        "check_hostile_target_is_data",
    }
    for name in sorted(required_checks - bound_checks):
        failures.append(f"phase2-executable-check-unbound:{name}")
    functions = {
        node.name: node
        for node in test_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for name in sorted(required_checks):
        function = functions.get(name)
        if function is None:
            failures.append(f"phase2-executable-check-missing:{name}")
            continue
        assertions = sum(
            1
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and _call_name(node.func) in {"require", "expect_error"}
        )
        if assertions < 2:
            failures.append(f"phase2-executable-check-inert:{name}")
    main_function = functions.get("main")
    if main_function is None or not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "check"
        for node in ast.walk(main_function)
    ):
        failures.append("phase2-executable-runner-inert")


def check_phase3_bindings(failures: list[str]) -> None:
    combined = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "plzdo_local/context.py",
            "plzdo_local/durable_cli.py",
            "plzdo_local/findings.py",
            "plzdo_local/formalization.py",
            "plzdo_local/local_memory.py",
            "plzdo_local/metrics.py",
            "plzdo_local/state.py",
        )
    )
    semantic_pins = {
        "approval-hash": "approvalHash",
        "terminal-immutability": "formalization is immutable",
        "fixed-context-sources": "PROJECT_CONTROL_PATHS",
        "archive-first": "Archive-first values",
        "checkpoint-provenance": "checkpoint requires exactly one provenance input branch",
        "checkpoint-no-background": "checkpoint is not permitted with unattended environment marker",
        "skipped-no-write": "evidence-only and must not be applied",
        "loop-tracking-only": '"trackingOnly": True',
        "memory-non-sot": '"sourceOfTruth": False',
        "findings-no-disappearance": "findings may not disappear",
    }
    for label, token in semantic_pins.items():
        if token not in combined:
            failures.append(f"phase3-semantic-pin-missing:{label}")

    test_tree = ast.parse(
        (ROOT / "tests/phase3_check.py").read_text(encoding="utf-8"),
        filename="tests/phase3_check.py",
        feature_version=(3, 9),
    )
    bound_checks: set[str] = set()
    for node in ast.walk(test_tree):
        if not isinstance(node, ast.List):
            continue
        for item in node.elts:
            if (
                isinstance(item, ast.Tuple)
                and len(item.elts) == 2
                and isinstance(item.elts[0], ast.Constant)
                and isinstance(item.elts[1], ast.Name)
            ):
                bound_checks.add(item.elts[1].id)
    required_checks = {
        "check_phase3_schemas",
        "check_formalization",
        "check_state_compaction",
        "check_checkpoints",
        "check_bounded_loops",
        "check_context_pack_contract",
        "check_durable_cli",
        "check_local_memory",
        "check_findings_ledger",
        "check_metrics",
    }
    for name in sorted(required_checks - bound_checks):
        failures.append(f"phase3-executable-check-unbound:{name}")
    functions = {
        node.name: node
        for node in test_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for name in sorted(required_checks):
        function = functions.get(name)
        if function is None:
            failures.append(f"phase3-executable-check-missing:{name}")
            continue
        assertions = sum(
            1
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and _call_name(node.func) in {"require", "expect_error"}
        )
        if assertions < 2:
            failures.append(f"phase3-executable-check-inert:{name}")


def check_phase4_bindings(failures: list[str]) -> None:
    source = (ROOT / "plzdo_local/apply_gate.py").read_text(encoding="utf-8")
    for label, token in {
        "operator-only": 'policy["operatorOnly"] is not True',
        "clean-git": "target Git worktree must be clean",
        "backup-first": "backup report could not be persisted before target writes",
        "no-arbitrary-command": "unsupported Git operation",
        "rollback": "failed-rolled-back",
        "gitlink-refusal": "Gitlinks and submodules are forbidden for real apply",
        "git-identity": "Git worktree or metadata directory identity changed after planning",
        "journaled-target-temp": "plzdo-local.target-temporary-artifact.v1",
        "stored-process-group": "os.killpg(process_group_id, signal.SIGKILL)",
        "directory-identity": '"device": metadata.st_dev',
    }.items():
        if token not in source:
            failures.append(f"phase4-semantic-pin-missing:{label}")
    schema_source = (ROOT / "schemas/apply-plan.schema.json").read_text(encoding="utf-8")
    test_source = (ROOT / "tests/phase4_check.py").read_text(encoding="utf-8")
    for label, token, bound_source in (
        ("schema-runtime-boundary", '"x-runtime-semantic-validator"', schema_source),
        ("schema-prefix-order", '"prefixItems"', schema_source),
        ("shared-schema-corpus", '"runtime-hash"', test_source),
        ("real-process-termination", "os.WIFSIGNALED", test_source),
        ("descendant-termination", "descendant survived after the Git leader exited", test_source),
    ):
        if token not in bound_source:
            failures.append(f"phase4-semantic-pin-missing:{label}")
    _check_named_test_functions(
        "tests/phase4_check.py",
        {
            "check_schema_and_plan_bytes",
            "check_negative_policy_gates",
            "check_clean_git_and_confirmation",
            "check_fingerprint_drift",
            "check_symlink_substitution",
            "check_successful_apply_and_rollback",
            "check_existing_byte_backup",
            "check_mid_write_rollback",
        },
        "phase4",
        failures,
    )


def check_phase5_bindings(failures: list[str]) -> None:
    source = (ROOT / "plzdo_local/managed_install.py").read_text(encoding="utf-8")
    for label, token in {
        "unmanaged-collision": "destination exists without a valid managed marker",
        "drift-refusal": "uninstall requires exact managed content",
        "fixed-resources": "PUBLIC_SKILLS",
        "local-static-catalog": "this function has no transport path",
    }.items():
        if token not in source:
            failures.append(f"phase5-semantic-pin-missing:{label}")
    _check_named_test_functions(
        "tests/phase5_check.py",
        {
            "check_public_resources",
            "check_dry_run_purity",
            "check_unmanaged_collision",
            "check_managed_drift",
            "check_roundtrip_restoration",
            "check_static_catalogs",
            "check_local_only_surface",
            "check_path_and_name_safety",
            "check_cli_surface",
        },
        "phase5",
        failures,
    )


def check_local_ops_bindings(failures: list[str]) -> None:
    _check_named_test_functions(
        "tests/local_ops_check.py",
        {"check_review_prepare", "check_review_import", "check_monitor_read_only"},
        "local-ops",
        failures,
    )


def check_release_bindings(failures: list[str]) -> None:
    _check_named_test_functions(
        "tests/release_check.py",
        {
            "check_exact_object_audit",
            "check_git_environment_isolation",
            "check_integrated_release_path",
            "check_installer_removed",
            "check_manifest_negatives",
            "check_metadata_collision_and_symlink",
            "check_publication_isolated_bootstrap",
            "check_ref_drift",
            "check_release_manifest",
            "check_scanner_coverage",
            "check_tag_ref_and_email_audit",
            "check_worktree_export",
        },
        "release",
        failures,
    )
    publication = (ROOT / "scripts/check_publication.py").read_text(encoding="utf-8")
    for token in (
        "PUBLIC_BASE_COMMIT",
        "GIT_NO_REPLACE_OBJECTS",
        "MAX_COMMITS",
        "MAX_LOGICAL_BLOB_BYTES",
        "cat-file",
        "for-each-ref",
        "ls-tree",
        "repository-ref-drift",
    ):
        if token not in publication:
            failures.append(f"release-publication-pin-missing:{token}")
    if "git archive" in publication or "git archive" in (ROOT / "scripts/check-publication").read_text(encoding="utf-8"):
        failures.append("release-publication-archive-trust")
    verify = (ROOT / "scripts/verify").read_text(encoding="utf-8")
    if '"$root/scripts/release-manifest" --check' not in verify:
        failures.append("release-integrated-manifest-check-missing")
    workflow = (ROOT / ".github/workflows/verify.yml").read_text(encoding="utf-8")
    if 'scripts/export_worktree.py . "${RUNNER_TEMP}/plzdo-export"' not in workflow:
        failures.append("release-ci-export-missing")
    if workflow.count("working-directory: ${{ runner.temp }}/plzdo-export") != 3:
        failures.append("release-ci-export-binding")
    command_reference = (ROOT / "docs/command-reference.md").read_text(encoding="utf-8")
    if "project register` and `project archive` update the local registry" not in command_reference:
        failures.append("release-project-write-doc-missing")
    for relative in ("scripts/install-local", "scripts/install_local.py"):
        if (ROOT / relative).exists() or (ROOT / relative).is_symlink():
            failures.append(f"release-prefix-installer-present:{relative}")


def _check_named_test_functions(
    relative: str,
    required: set[str],
    label: str,
    failures: list[str],
) -> None:
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative, feature_version=(3, 9))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    main = functions.get("main")
    bound: set[str] = set()
    if main is not None:
        for node in ast.walk(main):
            if isinstance(node, ast.Name) and node.id in required:
                bound.add(node.id)
    for name in sorted(required - bound):
        failures.append(f"{label}-executable-check-unbound:{name}")
    for name in sorted(required):
        function = functions.get(name)
        if function is None:
            failures.append(f"{label}-executable-check-missing:{name}")
            continue
        assertion_calls = {"require", "expect_error"}
        if label == "release":
            assertion_calls.update({"expect_publication", "rejected"})
        assertions = sum(
            1
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and _call_name(node.func) in assertion_calls
        )
        if assertions < 2:
            failures.append(f"{label}-executable-check-inert:{name}")


def check_no_git_metadata(failures: list[str]) -> None:
    for path in ROOT.rglob(".git"):
        failures.append(f"git-metadata-present-before-phase7:{path.relative_to(ROOT).as_posix()}")


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                aliases[item.asname or item.name] = f"{node.module}.{item.name}"
    return aliases


def _resolved_call_name(node: ast.expr, aliases: dict[str, str]) -> str:
    name = _call_name(node)
    head, separator, tail = name.partition(".")
    resolved = aliases.get(head, head)
    return f"{resolved}.{tail}" if separator else resolved


def _function_map(tree: ast.AST) -> dict[ast.AST, str]:
    owners: dict[ast.AST, str] = {}
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(function):
            owners.setdefault(node, function.name)
    return owners


def _is_process_api(name: str) -> bool:
    return name in PROCESS_APIS or any(name.startswith(prefix) for prefix in PROCESS_API_PREFIXES)


def _check_runtime_process_call(
    node: ast.Call,
    relative: str,
    aliases: dict[str, str],
    failures: list[str],
    *,
    function_name: str,
) -> None:
    call_name = _resolved_call_name(node.func, aliases)
    if call_name in FORBIDDEN_DYNAMIC_BUILTINS:
        failures.append(f"forbidden-dynamic-code-api:{relative}:{getattr(node, 'lineno', 0)}")
    if isinstance(node.func, ast.Call):
        inner_name = _resolved_call_name(node.func.func, aliases)
        if inner_name == "getattr":
            failures.append(f"forbidden-dynamic-call:{relative}:{getattr(node, 'lineno', 0)}")
    if call_name == "subprocess.Popen":
        if (relative, function_name) == ALLOWED_GIT_POPEN_FUNCTION:
            _check_git_popen_call(node, relative, failures)
        elif (relative, function_name) == ALLOWED_PUBLICATION_GIT_POPEN_FUNCTION:
            _check_publication_git_popen_call(node, relative, failures)
        else:
            failures.append(f"forbidden-process-api:{relative}:{getattr(node, 'lineno', 0)}")
        return
    if _is_process_api(call_name) and call_name != "subprocess.run":
        failures.append(f"forbidden-process-api:{relative}:{getattr(node, 'lineno', 0)}")
    if call_name == "subprocess.run":
        if any(keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value for keyword in node.keywords):
            failures.append(f"subprocess-shell-true:{relative}:{getattr(node, 'lineno', 0)}")
        if (relative, function_name) in ALLOWED_BOUNDED_PROCESS_FUNCTIONS:
            _check_bounded_process_call(node, relative, function_name, failures)
            return
        argv = _literal_argv(node.args[0] if node.args else None)
        if argv is None or (relative, argv) not in ALLOWED_SUBPROCESS_CALLS:
            failures.append(f"unapproved-subprocess:{relative}:{getattr(node, 'lineno', 0)}")


def _check_git_popen_call(node: ast.Call, relative: str, failures: list[str]) -> None:
    line = getattr(node, "lineno", 0)
    dangerous = sorted(
        keyword.arg
        for keyword in node.keywords
        if keyword.arg is not None and keyword.arg in FORBIDDEN_POPEN_KEYWORDS
    )
    if dangerous:
        failures.append(f"git-popen-dangerous-keyword:{relative}:{line}:{','.join(dangerous)}")
    valid = (
        _call_name(node.func) == "subprocess.Popen"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "argv"
        and len(node.keywords) == 1
        and node.keywords[0].arg is None
        and isinstance(node.keywords[0].value, ast.Name)
        and node.keywords[0].value.id == "popen_kwargs"
    )
    if not valid:
        failures.append(f"git-popen-call-shape:{relative}:{line}")


def _check_publication_git_popen_call(node: ast.Call, relative: str, failures: list[str]) -> None:
    line = getattr(node, "lineno", 0)
    expected_keywords = {
        "stdin": "subprocess.DEVNULL",
        "stdout": "subprocess.PIPE",
        "stderr": "subprocess.PIPE",
        "cwd": '"/"',
        "env": "environment",
        "close_fds": "True",
    }
    actual = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg is not None}
    valid_argument = (
        len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "command"
    )
    if not valid_argument or set(actual) != set(expected_keywords):
        failures.append(f"publication-git-popen-call-shape:{relative}:{line}")
        return
    for name, expected in expected_keywords.items():
        if not _expression_matches(actual[name], expected):
            failures.append(f"publication-git-popen-keyword:{relative}:{line}:{name}")


def _check_publication_git_process_contract(
    tree: ast.AST,
    relative: str,
    failures: list[str],
) -> None:
    functions = [
        node
        for node in getattr(tree, "body", [])
        if isinstance(node, ast.FunctionDef) and node.name == "_run_git"
    ]
    if len(functions) != 1:
        failures.append(f"publication-git-function-binding:{relative}")
        return
    function = functions[0]
    popen_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and _call_name(node.func) == "subprocess.Popen"
    ]
    if len(popen_calls) != 1:
        failures.append(f"publication-git-popen-count:{relative}")
    for call in popen_calls:
        _check_publication_git_popen_call(call, relative, failures)

    module_pins = {
        "GIT": 'Path("/usr/bin/git")',
        "MAX_COMMITS": "512",
        "MAX_REF_BYTES": "1024 * 1024",
        "MAX_BLOB_BYTES": "4 * 1024 * 1024",
        "GIT_TIMEOUT_SECONDS": "30.0",
    }
    for name, expected in module_pins.items():
        value = _unique_assignment_value(tree, name, top_level=True)
        if value is None or not _expression_matches(value, expected):
            failures.append(f"publication-git-module-pin:{relative}:{name}")

    environment_node = _unique_assignment_value(function, "environment")
    try:
        environment = ast.literal_eval(environment_node) if environment_node is not None else None
    except (TypeError, ValueError):
        environment = None
    required_environment = {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": "/dev/null",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }
    if not isinstance(environment, dict) or any(environment.get(key) != value for key, value in required_environment.items()):
        failures.append(f"publication-git-environment-pin:{relative}")

    call_names = [
        _call_name(node.func)
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    ]
    for required in ("os.read", "process.kill", "process.wait", "selector.select", "time.monotonic"):
        if required not in call_names:
            failures.append(f"publication-git-bound-missing:{relative}:{required}")
    source = ast.unparse(tree) if hasattr(ast, "unparse") else (ROOT / relative).read_text(encoding="utf-8")
    for token in ("--git-dir=", "--work-tree=", "--no-replace-objects", "core.hooksPath=/dev/null", "core.fsmonitor=false"):
        if token not in source:
            failures.append(f"publication-git-command-pin:{relative}:{token}")
    if "os.environ" in source or "git archive" in source:
        failures.append(f"publication-git-environment-or-archive-trust:{relative}")


def _check_apply_gate_git_process_contract(
    tree: ast.AST,
    relative: str,
    failures: list[str],
) -> None:
    functions = [
        node
        for node in getattr(tree, "body", [])
        if isinstance(node, ast.FunctionDef) and node.name == "_run_git"
    ]
    if len(functions) != 1:
        failures.append(f"git-popen-function-binding:{relative}")
        return
    function = functions[0]

    module_pins = {
        "_git_path": 'shutil.which("git", path=os.defpath)',
        "GIT_EXECUTABLE": 'str(Path(_git_path).resolve()) if _git_path else ""',
        "MAX_GIT_OUTPUT_BYTES": "1024 * 1024",
        "GIT_TIMEOUT_SECONDS": "15",
    }
    for name, expected in module_pins.items():
        value = _unique_assignment_value(tree, name, top_level=True)
        if value is None or not _expression_matches(value, expected):
            failures.append(f"git-popen-module-pin:{relative}:{name}")
        if _name_context_count(tree, name, ast.Store) != 1:
            failures.append(f"git-popen-module-rebind:{relative}:{name}")

    suffixes = _unique_assignment_value(function, "suffixes")
    try:
        suffix_value = ast.literal_eval(suffixes) if suffixes is not None else None
    except (TypeError, ValueError):
        suffix_value = None
    if suffix_value != EXPECTED_GIT_SUFFIXES:
        failures.append(f"git-popen-operation-map:{relative}")

    function_pins = {
        "argv": """[
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
        ]""",
        "environment": """{
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
        }""",
        "popen_kwargs": """{
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": environment,
        }""",
        "overflow": "threading.Event()",
        "stdout_thread": """threading.Thread(
            target=_drain_bounded_stream,
            args=(process.stdout, stdout_parts, overflow),
            daemon=True,
        )""",
        "stderr_thread": """threading.Thread(
            target=_drain_bounded_stream,
            args=(process.stderr, stderr_parts, overflow),
            daemon=True,
        )""",
        "deadline": "time.monotonic() + GIT_TIMEOUT_SECONDS",
        "process_group_id": 'process.pid if os.name == "posix" else None',
    }
    for name, expected in function_pins.items():
        value = _unique_assignment_value(function, name)
        if value is None or not _expression_matches(value, expected):
            failures.append(f"git-popen-function-pin:{relative}:{name}")

    expected_loads = {
        "argv": 1,
        "environment": 1,
        "popen_kwargs": 3,
        "process_group_id": 5,
        "suffixes": 2,
    }
    for name, expected_count in expected_loads.items():
        if _name_context_count(function, name, ast.Store) != 1:
            failures.append(f"git-popen-function-rebind:{relative}:{name}")
        if _name_context_count(function, name, ast.Load) != expected_count:
            failures.append(f"git-popen-function-use:{relative}:{name}")

    expected_condition = ast.parse(
        """if os.name == "posix":
    popen_kwargs["start_new_session"] = True
elif os.name == "nt":
    popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
""",
        feature_version=(3, 9),
    ).body[0]
    matching_conditions = [
        statement
        for statement in function.body
        if isinstance(statement, ast.If) and _ast_equal(statement, expected_condition)
    ]
    mutations = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "popen_kwargs"
        and isinstance(node.ctx, (ast.Store, ast.Del))
    ]
    mutation_keys = sorted(_constant_subscript_key(node) for node in mutations)
    if len(matching_conditions) != 1 or mutation_keys != ["creationflags", "start_new_session"]:
        failures.append(f"git-popen-process-group-shape:{relative}")

    popen_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and _call_name(node.func) == "subprocess.Popen"
    ]
    if len(popen_calls) != 1:
        failures.append(f"git-popen-call-count:{relative}")
    for node in popen_calls:
        _check_git_popen_call(node, relative, failures)

    call_names = [
        _call_name(node.func)
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    ]
    required_counts = {
        "threading.Thread": 2,
        "_kill_process_group": 5,
        "process.poll": 1,
        "process.wait": 2,
        "stdout_thread.start": 1,
        "stderr_thread.start": 1,
        "stdout_thread.join": 2,
        "stderr_thread.join": 2,
    }
    for name, expected_count in required_counts.items():
        if call_names.count(name) != expected_count:
            failures.append(f"git-popen-bounds-pin:{relative}:{name}")
    for name in ("GIT_TIMEOUT_SECONDS", "MAX_GIT_OUTPUT_BYTES"):
        if _name_context_count(function, name, ast.Load) == 0:
            failures.append(f"git-popen-bound-missing:{relative}:{name}")


def _check_git_popen_guard_self_test(failures: list[str]) -> None:
    relative = ALLOWED_GIT_POPEN_FUNCTION[0]
    source = (ROOT / relative).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=relative, feature_version=(3, 9))
    baseline_failures: list[str] = []
    _check_apply_gate_git_process_contract(tree, relative, baseline_failures)
    if baseline_failures:
        failures.append("git-popen-guard-self-test:baseline")
        return

    call_mutation = copy.deepcopy(tree)
    call = next(
        (
            node
            for node in ast.walk(call_mutation)
            if isinstance(node, ast.Call) and _call_name(node.func) == "subprocess.Popen"
        ),
        None,
    )
    if call is None:
        failures.append("git-popen-guard-self-test:missing-call")
        return
    call.keywords.insert(0, ast.keyword(arg="shell", value=ast.Constant(value=True)))

    kwargs_mutation = copy.deepcopy(tree)
    function = next(
        node
        for node in kwargs_mutation.body
        if isinstance(node, ast.FunctionDef) and node.name == "_run_git"
    )
    kwargs = _unique_assignment_value(function, "popen_kwargs")
    if not isinstance(kwargs, ast.Dict):
        failures.append("git-popen-guard-self-test:missing-kwargs")
        return
    kwargs.keys.append(ast.Constant(value="cwd"))
    kwargs.values.append(ast.Name(id="target", ctx=ast.Load()))

    for label, mutated in (("call-shape", call_mutation), ("dangerous-kwarg", kwargs_mutation)):
        probe_failures: list[str] = []
        _check_apply_gate_git_process_contract(mutated, relative, probe_failures)
        if not probe_failures:
            failures.append(f"git-popen-guard-self-test:{label}")


def _unique_assignment_value(
    scope: ast.AST,
    name: str,
    *,
    top_level: bool = False,
) -> Optional[ast.expr]:
    nodes = getattr(scope, "body", []) if top_level else ast.walk(scope)
    values: list[ast.expr] = []
    for node in nodes:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
        ):
            values.append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            if node.value is not None:
                values.append(node.value)
    return values[0] if len(values) == 1 else None


def _expression_matches(value: ast.expr, expected_source: str) -> bool:
    expected = ast.parse(expected_source, mode="eval", feature_version=(3, 9)).body
    return _ast_equal(value, expected)


def _ast_equal(left: ast.AST, right: ast.AST) -> bool:
    return ast.dump(left, include_attributes=False) == ast.dump(right, include_attributes=False)


def _name_context_count(scope: ast.AST, name: str, context: type[ast.expr_context]) -> int:
    return sum(
        1
        for node in ast.walk(scope)
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, context)
    )


def _constant_subscript_key(node: ast.Subscript) -> str:
    return node.slice.value if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str) else ""


def _check_bounded_process_call(
    node: ast.Call,
    relative: str,
    function_name: str,
    failures: list[str],
) -> None:
    argument = node.args[0] if node.args else None
    if relative == "tests/phase4_check.py" and function_name == "fixture_git":
        valid_argument = (
            isinstance(argument, ast.Subscript)
            and isinstance(argument.value, ast.Name)
            and argument.value.id == "commands"
        )
        required_keywords = {"check", "capture_output", "text", "timeout", "env"}
    elif relative == "tests/release_check.py" and function_name == "git":
        valid_argument = _expression_matches(
            argument,
            '[str(GIT), "-C", str(repository)] + list(arguments)',
        )
        required_keywords = {"check", "env", "stdin", "stdout", "stderr", "timeout"}
    else:
        valid_argument = False
        required_keywords = set()
    keyword_names = {keyword.arg for keyword in node.keywords if keyword.arg is not None}
    if not valid_argument or keyword_names != required_keywords:
        failures.append(f"bounded-process-shape:{relative}:{getattr(node, 'lineno', 0)}")
    shell_keyword = next((keyword for keyword in node.keywords if keyword.arg == "shell"), None)
    if shell_keyword is not None:
        failures.append(f"bounded-process-shell:{relative}:{getattr(node, 'lineno', 0)}")


def _shell_source_failures(relative: str, source: str) -> list[str]:
    failures: list[str] = []
    allowed_paths = ALLOWED_SHELL_ABSOLUTE_PATHS.get(relative, set())
    for line_number, line in enumerate(source.splitlines(), 1):
        if FORBIDDEN_SHELL_WORDS.search(line):
            failures.append(f"forbidden-shell-command:{relative}:{line_number}")
        if re.search(r"\b(?:eval|source)\b|`", line):
            failures.append(f"forbidden-shell-dynamic-execution:{relative}:{line_number}")
        if re.search(r"\b(?:ba)?sh\s+-c\b|(?:python[^\s]*|\$python_bin)\s+-c\b", line):
            failures.append(f"forbidden-shell-inline-code:{relative}:{line_number}")
        variable_command = re.search(r"(?:^|[;&|]\s*)[\"']?\$(?:\{)?([A-Za-z_][A-Za-z0-9_]*)", line)
        if variable_command:
            variable = variable_command.group(1)
            root_owned_gate = variable == "root" and line.lstrip().startswith(
                ('"$root/scripts/check-release-leaks"', '"$root/scripts/release-manifest" --check')
            )
            if variable != "python_bin" and not root_owned_gate:
                failures.append(f"unapproved-shell-variable-command:{relative}:{line_number}")
        for match in re.finditer(r"(?<![A-Za-z0-9_$])(/[A-Za-z0-9._/-]+)", line):
            absolute = match.group(1).rstrip("/") or "/"
            if absolute not in allowed_paths:
                failures.append(f"unapproved-shell-absolute-path:{relative}:{line_number}")
    return failures


def _literal_argv(node: Optional[ast.expr]) -> Optional[tuple[str, ...]]:
    if not isinstance(node, (ast.List, ast.Tuple)) or not node.elts:
        return None
    values: list[str] = []
    for item in node.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            return None
        values.append(item.value)
    return tuple(values)


def _check_verification_subprocess(node: ast.Call, relative: str, failures: list[str]) -> None:
    if any(keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value for keyword in node.keywords):
        failures.append(f"verification-subprocess-shell-true:{relative}:{getattr(node, 'lineno', 0)}")
    argument = node.args[0] if node.args else None
    head = _verification_process_head(argument)
    allowed = ALLOWED_VERIFICATION_PROCESS_HEADS.get(relative, set())
    if head is None or head not in allowed:
        failures.append(f"verification-process-not-allowlisted:{relative}:{getattr(node, 'lineno', 0)}")


def _verification_process_head(node: Optional[ast.expr]) -> Optional[str]:
    if not isinstance(node, (ast.List, ast.Tuple)) or not node.elts:
        return None
    first = node.elts[0]
    if (
        isinstance(first, ast.Attribute)
        and isinstance(first.value, ast.Name)
        and first.value.id == "sys"
        and first.attr == "executable"
    ):
        if len(node.elts) < 4:
            return None
        flags = node.elts[1:3]
        if not all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in flags):
            return None
        if [item.value for item in flags] != ["-B", "-I"]:
            return None
        entry = node.elts[3]
        if not (
            isinstance(entry, ast.Call)
            and isinstance(entry.func, ast.Name)
            and entry.func.id == "str"
            and len(entry.args) == 1
            and _root_relative_ast_path(entry.args[0]) == "bin/plzdo_entry.py"
        ):
            return None
        return "python:plzdo-entry"
    if (
        isinstance(first, ast.Call)
        and isinstance(first.func, ast.Name)
        and first.func.id == "str"
        and len(first.args) == 1
    ):
        relative = _root_relative_ast_path(first.args[0])
        if relative is not None:
            return f"root:{relative}"
    return None


def _root_relative_ast_path(node: ast.expr) -> Optional[str]:
    if isinstance(node, ast.Name) and node.id == "ROOT":
        return ""
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
        return None
    prefix = _root_relative_ast_path(node.left)
    if prefix is None or not isinstance(node.right, ast.Constant) or not isinstance(node.right.value, str):
        return None
    value = node.right.value
    if not value or value.startswith(("/", "\\")) or ".." in value.split("/"):
        return None
    return "/".join(part for part in (prefix, value) if part)


if __name__ == "__main__":
    raise SystemExit(main())
