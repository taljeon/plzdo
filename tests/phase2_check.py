from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from plzdo_local.catalog import (
    CatalogValidationError,
    build_catalog,
    build_repository,
    list_repositories,
    validate_catalog,
)
from plzdo_local.execution_rules import route_goal, validate_execution_route
from plzdo_local.registry import (
    RegistryCatalogError,
    RegistryRegistrationError,
    archive_project,
    build_project,
    build_registry,
    register_project,
    resolve_project,
)
from plzdo_local.renderer import (
    FILE_MODES,
    PROJECT_FRAME_PATHS,
    RendererError,
    inspect_project_frame,
    plan_project_frame,
    render_project_frame,
)


def main() -> int:
    if sys.flags.optimize:
        print("FAIL Python optimization disables executable assertions")
        return 1
    checks = [
        ("phase2 schemas and catalog contracts execute", check_catalog_contract),
        ("registry resolution is deterministic and non-writing", check_registry_resolution),
        ("execution route covers quick plan goal and bounded loop", check_execution_routes),
        ("project rendering is deterministic and dry-run only", check_renderer_determinism),
        ("fixture materialization validates exact managed bytes", check_renderer_fixture_materialization),
        ("project templates remain product specific and examples match exact renders", check_project_templates_are_product_specific),
        ("generated verifier anchors reads to no-follow descriptors", check_generated_verifier_descriptor_reads),
        ("renderer rejects partial and symlinked control frames", check_renderer_safety),
        ("init and new commands plan without target writes", check_cli_plan_only),
        ("catalog commands are read-only and deterministic", check_cli_catalog),
        ("registry lifecycle requires a validated rendered frame", check_cli_registry_lifecycle),
        ("render write stays blocked before the P5 gate", check_cli_render_write_blocked),
        ("hostile target files are never executed", check_hostile_target_is_data),
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
    print(f"phase2 check passed: {len(checks)} checks")
    return 0


def check_catalog_contract() -> None:
    for relative in ("schemas/catalog.schema.json", "schemas/registry.schema.json"):
        schema = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        require(schema["additionalProperties"] is False, f"{relative} is not exact-key")
    with tempfile.TemporaryDirectory(prefix="plzdo-catalog-") as temporary:
        root = Path(temporary).resolve()
        alpha = root / "alpha"
        beta = root / "beta"
        alpha.mkdir()
        beta.mkdir()
        catalog = build_catalog(
            [
                build_repository(repository_id="beta-repo", path=beta, path_must_exist=True),
                build_repository(repository_id="alpha-repo", path=alpha, path_must_exist=True),
            ]
        )
        require([item["id"] for item in catalog["repositories"]] == ["alpha-repo", "beta-repo"], "catalog order")
        require(len(list_repositories(catalog)) == 2, "catalog list count")
        malformed = dict(catalog)
        malformed["unexpected"] = True
        expect_error(CatalogValidationError, lambda: validate_catalog(malformed))
        unsafe = json.loads(json.dumps(catalog))
        unsafe["repositories"][0]["path"] = "relative/path"
        expect_error(CatalogValidationError, lambda: validate_catalog(unsafe))


def check_registry_resolution() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-registry-") as temporary:
        root = Path(temporary).resolve()
        paths = [root / name for name in ("alpha", "beta", "gamma")]
        for path in paths:
            path.mkdir()
        alpha = build_project(
            project_id="alpha-app",
            aliases=["alpha-ui"],
            domain="product",
            area="frontend",
            path=paths[0],
            path_must_exist=True,
        )
        beta = build_project(
            project_id="beta-app",
            domain="product",
            area="frontend",
            path=paths[1],
            path_must_exist=True,
        )
        gamma = build_project(
            project_id="gamma-api",
            domain="platform",
            area="backend",
            path=paths[2],
            path_must_exist=True,
        )
        registry = build_registry([gamma, beta, alpha])
        exact = resolve_project(registry, "fix alpha-ui")
        require(exact["decision"] == "attached" and exact["projectId"] == "alpha-app", "alias attach")
        ambiguous = resolve_project(registry, "product frontend work")
        require(ambiguous["decision"] == "ask", "domain+area ambiguity")
        require(ambiguous["candidateIds"] == ["alpha-app", "beta-app"], "ambiguous candidates")
        create = resolve_project(registry, "unmatched work")
        require(create["decision"] == "create", "unmatched create decision")
        archived = archive_project(registry, "gamma-api")
        inactive = resolve_project(archived, "gamma-api")
        require(inactive["decision"] == "ask", "archived project auto-attached")
        expect_error(
            RegistryRegistrationError,
            lambda: register_project(registry, gamma, render_succeeded=False),
        )


def check_execution_routes() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-routes-") as temporary:
        path = Path(temporary).resolve() / "alpha"
        path.mkdir()
        project = build_project(
            project_id="alpha-app",
            domain="product",
            area="frontend",
            path=path,
            path_must_exist=True,
        )
        registry = build_registry([project])
        cases = (
            ("quick fix alpha-app", "quick", False),
            ("implement parser in alpha-app", "plan", False),
            ("production migration for alpha-app", "goal", False),
            ("repeat checks until clean for alpha-app", "plan", True),
        )
        for goal, expected_weight, expected_loop in cases:
            route = route_goal(goal, registry)
            validate_execution_route(route)
            require(route["weight"] == expected_weight, f"weight mismatch for {goal}")
            require(route["boundedLoop"] is expected_loop, f"loop mismatch for {goal}")
            require(route["formalizationRequired"] is (expected_weight == "goal" or expected_loop), "formalization")

        beta_path = Path(temporary).resolve() / "beta"
        secure_path = Path(temporary).resolve() / "secure"
        beta_path.mkdir()
        secure_path.mkdir()
        beta = build_project(
            project_id="beta-service",
            domain="product",
            area="frontend",
            path=beta_path,
            path_must_exist=True,
        )
        secure = build_project(
            project_id="security-platform",
            domain="platform",
            area="backend",
            path=secure_path,
            path_must_exist=True,
        )
        expanded = build_registry([project, beta, secure])
        ambiguous = route_goal("quick fix alpha-app beta-service", expanded)
        require(ambiguous["projectDecision"]["decision"] == "ask", "identity ambiguity")
        require(ambiguous["weight"] == "plan", "ambiguous candidate identity contaminated weight")
        archived = archive_project(expanded, "security-platform")
        inactive = route_goal("quick fix security-platform", archived)
        require(inactive["projectDecision"]["decision"] == "ask", "archived route decision")
        require(inactive["weight"] == "plan", "archived identity contaminated weight")


def check_renderer_determinism() -> None:
    first = render_project_frame("alpha-app", objective="Deliver a deterministic fixture.")
    second = render_project_frame("alpha-app", objective="Deliver a deterministic fixture.")
    require(first == second, "unchanged renders differ")
    require(tuple(first) == PROJECT_FRAME_PATHS, "frame path order")
    with tempfile.TemporaryDirectory(prefix="plzdo-render-plan-") as temporary:
        target = Path(temporary).resolve() / "alpha-app"
        before = tree_digest(Path(temporary))
        plan = plan_project_frame(target, "alpha-app")
        after = tree_digest(Path(temporary))
        require(before == after, "dry-run changed target bytes")
        require(plan.writes_required, "empty target did not require a plan")
        require(not target.exists(), "dry-run created target")


def check_renderer_fixture_materialization() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-render-write-") as temporary:
        target = Path(temporary).resolve() / "alpha-app"
        materialize_fixture_frame(target, "alpha-app")
        status = inspect_project_frame(target, expected_project_id="alpha-app")
        require(status["status"] == "managed", "written frame did not validate")
        require((target / "scripts/verify").stat().st_mode & 0o777 == 0o755, "fixture verifier mode")
        verifier_text = (target / "scripts/verify").read_text(encoding="utf-8")
        for token in ("dir_fd=parent_fd", "O_NOFOLLOW", "_read_regular_at", "--self-test"):
            require(token in verifier_text, f"generated verifier misses descriptor guard: {token}")


def check_project_templates_are_product_specific() -> None:
    agents = (ROOT / "templates/project-harness/AGENTS.md").read_text(encoding="utf-8")
    requirements = (ROOT / "templates/project-harness/docs/requirements.md").read_text(encoding="utf-8")
    design = (ROOT / "templates/project-harness/docs/technical-design.md").read_text(encoding="utf-8")
    require("Keep default checks local and network-independent" in agents, "local safety boundary missing")
    require("## User Outcomes" in requirements and "## Functional Requirements" in requirements, "requirements scaffold is not product specific")
    require("## Components And Interfaces" in design and "## Data And State" in design, "design scaffold is not product specific")
    require("## Functional Baseline" not in requirements, "generic control-plane requirements survived")
    require("## Control Flow" not in design, "generic harness control flow survived")
    for policy_phrase in (
        "Protect secrets",
        "Keep default checks local",
        "Reject unsafe paths",
        "This frame does not grant",
    ):
        require(policy_phrase not in requirements, f"harness policy leaked into requirements: {policy_phrase}")
    for policy_phrase in ("Validate complete bytes", "Keep checks local"):
        require(policy_phrase not in design, f"harness policy leaked into technical design: {policy_phrase}")

    rendered = render_project_frame(
        "basic-project",
        objective="Demonstrate a local, evidence-backed project frame.",
    )
    require(tuple(rendered) == PROJECT_FRAME_PATHS, "rendered project frame inventory changed")
    for relative, expected in rendered.items():
        actual = (ROOT / "examples/basic-project" / relative).read_bytes()
        require(actual == expected, f"example drifted from renderer: {relative}")


def check_generated_verifier_descriptor_reads() -> None:
    result = subprocess.run(
        [str(ROOT / "templates/project-harness/scripts/verify"), "--self-test"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=test_environment(),
        timeout=10,
    )
    require(result.returncode == 0, result.stdout + result.stderr)
    require("descriptor" not in result.stderr.lower(), "descriptor self-test emitted a failure")
    require("self-test passed" in result.stdout, "descriptor self-test evidence missing")


def check_renderer_safety() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-render-safety-") as temporary:
        root = Path(temporary).resolve()
        partial = root / "partial"
        partial.mkdir()
        (partial / "AGENTS.md").write_text("partial\n", encoding="utf-8")
        expect_error(RendererError, lambda: plan_project_frame(partial, "partial-app", force=True))

        linked = root / "linked"
        linked.mkdir()
        outside = root / "outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        (linked / "AGENTS.md").symlink_to(outside)
        expect_error(ValueError, lambda: plan_project_frame(linked, "linked-app", force=True))

        managed = root / "managed"
        materialize_fixture_frame(managed, "managed-app")
        agents = managed / "AGENTS.md"
        agents.write_text("- Project ID: `spoof-app`\n" + agents.read_text(encoding="utf-8"), encoding="utf-8")
        status = inspect_project_frame(managed, expected_project_id="managed-app")
        require(status["projectId"] == "managed-app", "manual-region project id spoofed registration")
        expect_error(RendererError, lambda: inspect_project_frame(managed, expected_project_id="spoof-app"))

        verifier = managed / "scripts/verify"
        original_verifier = verifier.read_bytes()
        verifier.write_text(
            "#!/usr/bin/env python3\n"
            "# BEGIN PLZDO-LOCAL:project-frame.verify.v1\n"
            "printf '%s\\n' 'tampered'\n"
            "# END PLZDO-LOCAL:project-frame.verify.v1\n",
            encoding="utf-8",
        )
        verifier.chmod(0o755)
        expect_error(RendererError, lambda: inspect_project_frame(managed, expected_project_id="managed-app"))
        verifier.write_bytes(original_verifier)
        verifier.chmod(0o755)

        tasks = managed / "TASKS/current.md"
        original_tasks = tasks.read_text(encoding="utf-8")
        tasks.write_text(original_tasks.replace("Deliver the project", "Change the project", 1), encoding="utf-8")
        expect_error(RendererError, lambda: inspect_project_frame(managed, expected_project_id="managed-app"))
        tasks.write_text(original_tasks, encoding="utf-8")

        verifier.chmod(0o644)
        expect_error(RendererError, lambda: inspect_project_frame(managed, expected_project_id="managed-app"))


def check_cli_plan_only() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-cli-plan-") as temporary:
        root = Path(temporary).resolve()
        state = root / "state"
        target = root / "alpha-app"
        init_result = run_cli("init", str(target), "--id", "alpha-app", "--json", state_root=state)
        require(init_result.returncode == 0, init_result.stdout + init_result.stderr)
        init_payload = json.loads(init_result.stdout)
        require(init_payload["status"] == "planned", "init did not return a plan")
        require(init_payload["writesPerformed"] is False, "init claimed a write")
        require(not target.exists() and not state.exists(), "init wrote target or state")

        ask_result = run_cli("new", "build a new tool", "--json", state_root=state)
        require(ask_result.returncode == 0, ask_result.stdout + ask_result.stderr)
        ask = json.loads(ask_result.stdout)
        require(ask["status"] == "ask", "underspecified new did not ask")
        require(not target.exists() and not state.exists(), "underspecified new persisted state")

        planned_result = run_cli(
            "new",
            "build a new tool",
            "--path",
            str(target),
            "--id",
            "alpha-app",
            "--domain",
            "product",
            "--area",
            "frontend",
            "--json",
            state_root=state,
        )
        require(planned_result.returncode == 0, planned_result.stdout + planned_result.stderr)
        planned = json.loads(planned_result.stdout)
        require(planned["status"] == "planned" and planned["writesPerformed"] is False, "new plan status")
        require(not target.exists() and not state.exists(), "planned new wrote target or registry")


def check_cli_catalog() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-cli-catalog-") as temporary:
        root = Path(temporary).resolve()
        repository_path = root / "alpha"
        repository_path.mkdir()
        catalog = build_catalog(
            [build_repository(repository_id="alpha-repo", path=repository_path, path_must_exist=True)]
        )
        catalog_path = root / "catalog.json"
        catalog_path.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        before = tree_digest(root)
        validate_result = run_cli("catalog", "validate", "--file", str(catalog_path), "--json", state_root=root / "state")
        list_result = run_cli("catalog", "list", "--file", str(catalog_path), "--json", state_root=root / "state")
        show_result = run_cli(
            "catalog", "show", "alpha-repo", "--file", str(catalog_path), "--json", state_root=root / "state"
        )
        require(validate_result.returncode == list_result.returncode == show_result.returncode == 0, "catalog CLI failed")
        require(json.loads(list_result.stdout)["repositories"][0]["id"] == "alpha-repo", "catalog list")
        require(json.loads(show_result.stdout)["repository"]["id"] == "alpha-repo", "catalog show")
        require(before == tree_digest(root), "catalog read command wrote state")
        duplicate = root / "duplicate.json"
        duplicate.write_text('{"schemaVersion":"plzdo-local.catalog.v1","repositories":[],"repositories":[]}\n', encoding="utf-8")
        duplicate_result = run_cli("catalog", "validate", "--file", str(duplicate), "--json", state_root=root / "state")
        require(duplicate_result.returncode == 2, "duplicate JSON keys were accepted")
        require("duplicate key" in duplicate_result.stderr and "Traceback" not in duplicate_result.stderr, "duplicate-key evidence")
        fifo = root / "catalog.fifo"
        os.mkfifo(fifo)
        fifo_result = run_cli("catalog", "validate", "--file", str(fifo), "--json", state_root=root / "state")
        require(fifo_result.returncode == 2, "FIFO catalog did not fail closed")
        require("regular file" in fifo_result.stderr and "Traceback" not in fifo_result.stderr, "FIFO evidence")


def check_cli_registry_lifecycle() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-cli-registry-") as temporary:
        root = Path(temporary).resolve()
        state = root / "state"
        target = root / "alpha-app"
        materialize_fixture_frame(target, "alpha-app")
        target_before = tree_digest(target)
        register = run_cli(
            "project",
            "register",
            str(target),
            "--id",
            "alpha-app",
            "--alias",
            "alpha-ui",
            "--domain",
            "product",
            "--area",
            "frontend",
            "--json",
            state_root=state,
        )
        require(register.returncode == 0, register.stdout + register.stderr)
        require(json.loads(register.stdout)["status"] == "registered", "register status")
        require(target_before == tree_digest(target), "registration changed target")

        registry_path = state / "registry" / "registry.json"
        registry_before_reads = registry_path.read_bytes()
        resolved = run_cli("project", "resolve", "fix alpha-ui", "--json", state_root=state)
        route = run_cli("route", "quick fix alpha-app", "--json", state_root=state)
        require(json.loads(resolved.stdout)["projectId"] == "alpha-app", "CLI resolution")
        require(json.loads(route.stdout)["weight"] == "quick", "CLI route")
        require(registry_path.read_bytes() == registry_before_reads, "resolve or route persisted state")

        tampered = root / "tampered-app"
        materialize_fixture_frame(tampered, "tampered-app")
        verifier = tampered / "scripts/verify"
        verifier.write_text(
            "#!/usr/bin/env python3\n"
            "# BEGIN PLZDO-LOCAL:project-frame.verify.v1\n"
            "printf '%s\\n' 'tampered'\n"
            "# END PLZDO-LOCAL:project-frame.verify.v1\n",
            encoding="utf-8",
        )
        verifier.chmod(0o755)
        tampered_result = run_cli(
            "project",
            "register",
            str(tampered),
            "--id",
            "tampered-app",
            "--domain",
            "product",
            "--area",
            "frontend",
            "--json",
            state_root=state,
        )
        require(tampered_result.returncode == 2, "tampered managed frame registered")
        require(registry_path.read_bytes() == registry_before_reads, "tampered registration changed registry")

        beta = root / "beta-app"
        materialize_fixture_frame(beta, "beta-app")
        beta_register = run_cli(
            "project",
            "register",
            str(beta),
            "--id",
            "beta-app",
            "--domain",
            "product",
            "--area",
            "frontend",
            "--json",
            state_root=state,
        )
        require(beta_register.returncode == 0, beta_register.stdout + beta_register.stderr)
        registry_before_ask = registry_path.read_bytes()
        ambiguous_new = run_cli(
            "new",
            "product frontend work",
            "--domain",
            "product",
            "--area",
            "frontend",
            "--json",
            state_root=state,
        )
        require(json.loads(ambiguous_new.stdout)["status"] == "ask", "ambiguous new did not ask")
        underspecified_new = run_cli("new", "unmatched project work", "--json", state_root=state)
        require(json.loads(underspecified_new.stdout)["status"] == "ask", "underspecified existing-state new did not ask")
        require(registry_path.read_bytes() == registry_before_ask, "ask/new flow changed existing registry")

        archived = run_cli("project", "archive", "alpha-app", "--json", state_root=state)
        require(archived.returncode == 0, archived.stdout + archived.stderr)
        after = run_cli("project", "resolve", "alpha-app", "--json", state_root=state)
        require(json.loads(after.stdout)["decision"] == "ask", "archived CLI project attached")

        catalog_root = root / "catalog-root"
        linked_target = catalog_root / "linked-app"
        linked_target.mkdir(parents=True)
        linked_repository = build_repository(
            repository_id="linked-repo",
            path=catalog_root,
            state="archived",
            path_must_exist=True,
        )
        catalog = build_catalog([linked_repository])
        linked_project = build_project(
            project_id="linked-app",
            domain="product",
            area="frontend",
            path=linked_target,
            repository_id="linked-repo",
            path_must_exist=True,
        )
        linked_registry = build_registry([linked_project], catalog=catalog)
        expect_error(RegistryCatalogError, lambda: build_registry(linked_registry["projects"]))
        linked_state = root / "linked-state"
        registry_file = linked_state / "registry" / "registry.json"
        registry_file.parent.mkdir(parents=True)
        registry_file.write_text(json.dumps(linked_registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        catalog_file = root / "linked-catalog.json"
        catalog_file.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        missing_catalog = run_cli("route", "quick fix linked-app", "--json", state_root=linked_state)
        require(missing_catalog.returncode == 2, "missing catalog bypassed repository policy")
        with_catalog = run_cli(
            "route",
            "quick fix linked-app",
            "--catalog",
            str(catalog_file),
            "--json",
            state_root=linked_state,
        )
        require(with_catalog.returncode == 0, with_catalog.stdout + with_catalog.stderr)
        require(json.loads(with_catalog.stdout)["projectDecision"]["decision"] == "ask", "archived repository attached")


def check_cli_render_write_blocked() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-cli-render-") as temporary:
        root = Path(temporary).resolve()
        target = root / "alpha-repo"
        catalog = build_catalog([build_repository(repository_id="alpha-repo", path=target)])
        catalog_path = root / "catalog.json"
        catalog_path.write_text(json.dumps(catalog, sort_keys=True) + "\n", encoding="utf-8")
        result = run_cli("render", "--catalog", str(catalog_path), "--write", "--json", state_root=root / "state")
        require(result.returncode == 2, "render --write was not blocked")
        require("P5 apply gate" in result.stderr, "typed P5 block reason missing")
        require(not target.exists(), "blocked render created the target")


def check_hostile_target_is_data() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-hostile-target-") as temporary:
        root = Path(temporary).resolve()
        target = root / "hostile-app"
        target.mkdir()
        marker = root / "executed.txt"
        hostile = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
        (target / "sitecustomize.py").write_text(hostile, encoding="utf-8")
        (target / "setup.py").write_text(hostile, encoding="utf-8")
        before = tree_digest(target)
        result = run_cli(
            "init",
            str(target),
            "--id",
            "hostile-app",
            "--force",
            "--json",
            state_root=root / "state",
        )
        require(result.returncode == 0, result.stdout + result.stderr)
        require(not marker.exists(), "target code executed")
        require(before == tree_digest(target), "hostile target bytes changed")

        state = root / "state"
        check_result = run_cli("check", str(target), "--json", state_root=state)
        require(check_result.returncode == 2, "unmanaged hostile target passed check")
        register_result = run_cli(
            "project",
            "register",
            str(target),
            "--id",
            "hostile-app",
            "--domain",
            "product",
            "--area",
            "frontend",
            "--json",
            state_root=state,
        )
        require(register_result.returncode == 2, "unmanaged hostile target registered")
        new_result = run_cli(
            "new",
            "build hostile-app",
            "--path",
            str(target),
            "--id",
            "hostile-app",
            "--domain",
            "product",
            "--area",
            "frontend",
            "--force",
            "--json",
            state_root=state,
        )
        require(new_result.returncode == 0, new_result.stdout + new_result.stderr)
        require(json.loads(new_result.stdout)["writesPerformed"] is False, "new wrote hostile target")
        catalog = build_catalog([build_repository(repository_id="hostile-app", path=target, path_must_exist=True)])
        catalog_path = root / "catalog.json"
        catalog_path.write_text(json.dumps(catalog, sort_keys=True) + "\n", encoding="utf-8")
        render_result = run_cli(
            "render",
            "--catalog",
            str(catalog_path),
            "--dry-run",
            "--force",
            "--json",
            state_root=state,
        )
        require(render_result.returncode == 0, render_result.stdout + render_result.stderr)
        require(not marker.exists(), "a read-only CLI executed hostile target code")
        require(before == tree_digest(target), "read-only CLI changed hostile target bytes")


def materialize_fixture_frame(
    target: Path,
    project_id: str,
    *,
    project_name: Optional[str] = None,
    objective: Optional[str] = None,
) -> None:
    outputs = render_project_frame(project_id, project_name=project_name, objective=objective)
    target.mkdir(parents=True)
    for relative in PROJECT_FRAME_PATHS:
        destination = target.joinpath(*relative.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(outputs[relative])
        destination.chmod(FILE_MODES[relative])


def run_cli(*args: str, state_root: Path) -> subprocess.CompletedProcess[str]:
    environment = test_environment()
    environment["PLZDO_HOME"] = str(state_root)
    return subprocess.run(
        [sys.executable, "-B", "-I", str(ROOT / "bin/plzdo_entry.py"), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )


def test_environment() -> dict[str, str]:
    return {
        "HOME": os.environ.get("HOME", "/nonexistent"),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        if path.is_symlink():
            digest.update(b"L")
            digest.update(os.readlink(path).encode("utf-8"))
        elif path.is_file():
            digest.update(b"F")
            digest.update(path.read_bytes())
        else:
            digest.update(b"D")
    return digest.hexdigest()


def expect_error(error_type: type[BaseException], action: object) -> None:
    try:
        action()  # type: ignore[operator]
    except error_type:
        return
    raise AssertionError(f"expected {error_type.__name__}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
