from __future__ import annotations

import ast
import builtins
import hashlib
import inspect
import json
import os
import re
import stat
import sys
import tempfile
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Callable, Type
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import plzdo_local.managed_install as managed_install_module
from plzdo_local.monitor import repo_preflight
from plzdo_local.review_bundle import (
    build_manifest as build_review_manifest,
    import_response as import_review_response,
    prepare_bundle as prepare_review_bundle,
)
from plzdo_local.managed_install import (
    MANAGED_INSTALL_SCHEMA_VERSION,
    MANAGED_MARKER,
    PUBLIC_AGENTS,
    PUBLIC_SKILLS,
    ManagedInstallError,
    ManagedInstallCollisionError,
    ManagedInstallDriftError,
    ManagedInstallPathError,
    StaticCatalogError,
    UnknownManagedResourceError,
    inspect_resource,
    install_agent,
    install_resource,
    install_skill,
    list_catalog_entries,
    list_public_agents,
    list_public_skills,
    load_static_catalog,
    search_static_catalog,
    show_static_catalog_entry,
    uninstall_agent,
    uninstall_resource,
    uninstall_skill,
    validate_managed_install_marker,
    validate_static_catalog,
    _parse_agent_descriptor,
    _require_safe_relative_path,
)
from plzdo_local.cli import build_parser, main as cli_main


def main() -> int:
    if sys.flags.optimize:
        print("FAIL Python optimization disables executable assertions")
        return 1
    checks = [
        ("public resources and marker schema are exact", check_public_resources),
        ("install and uninstall dry-runs write nothing", check_dry_run_purity),
        ("fresh destination roots support first local installation", check_fresh_destination_installation),
        ("unmanaged destinations always refuse collision", check_unmanaged_collision),
        ("managed drift blocks overwrite and exact-only removal", check_managed_drift),
        ("managed mutations bind quarantine snapshots and preserve rollback state", check_quarantine_transactions),
        ("managed inspection uses no-follow bounded traversal", check_bounded_descriptor_reads),
        ("all resources round-trip without changing unrelated state", check_roundtrip_restoration),
        ("static catalog operations use fixed local metadata", check_static_catalogs),
        ("marker schema and runtime constraints conform", check_marker_schema_conformance),
        ("runtime exposes no transport startup or arbitrary-source path", check_local_only_surface),
        ("resource operations remain local when transport and process APIs are blocked", check_local_only_runtime),
        ("destination and resource paths reject unsafe identities", check_path_and_name_safety),
        ("CLI exposes bounded resource and static-catalog operations", check_cli_surface),
    ]
    failures = []
    for label, check in checks:
        try:
            check()
        except Exception as exc:
            failures.append("%s: %s: %s" % (label, type(exc).__name__, exc))
    if failures:
        for failure in failures:
            print("FAIL " + failure)
        return 1
    print("phase5 check passed: %d checks" % len(checks))
    return 0


def check_public_resources() -> None:
    require(list_public_skills() == tuple(sorted(PUBLIC_SKILLS)), "skill allowlist order")
    require(list_public_agents() == tuple(sorted(PUBLIC_AGENTS)), "agent allowlist order")
    require(
        set(PUBLIC_SKILLS) == {"plzdo-project-harness", "project-start", "leak-check", "ponytail"},
        "public skill allowlist",
    )
    require(
        set(PUBLIC_AGENTS)
        == {"explorer", "code-reviewer", "tester", "technical-writer", "reality-checker"},
        "public agent allowlist",
    )

    for name in PUBLIC_SKILLS:
        path = ROOT / "resources" / "public-skills" / name / "SKILL.md"
        require(path.is_file() and not path.is_symlink(), "missing public skill: " + name)
        text = path.read_text(encoding="utf-8")
        require(text.startswith("---\nname: " + name + "\n"), "skill frontmatter identity: " + name)
    for name in PUBLIC_AGENTS:
        path = ROOT / "resources" / "public-agents" / (name + ".toml")
        require(path.is_file() and not path.is_symlink(), "missing public agent: " + name)
        text = path.read_text(encoding="utf-8")
        descriptor = _parse_agent_descriptor(text, expected_name=name)
        require(set(descriptor) == {"schema_version", "name", "description", "instructions"}, "agent keys: " + name)
        require(descriptor["schema_version"] == "plzdo-local.agent.v1", "agent schema identity: " + name)
        require(descriptor["name"] == name, "agent name identity: " + name)
        with mock.patch.object(managed_install_module, "tomllib", None):
            fallback = _parse_agent_descriptor(text, expected_name=name)
        require(fallback == descriptor, "agent Python 3.9 TOML fallback: " + name)
        expect_error(
            ManagedInstallPathError,
            lambda value=text, resource=name: _parse_agent_descriptor(
                value + 'provider = "remote"\n',
                expected_name=resource,
            ),
        )

    slash = chr(92)
    escaped_descriptor = (
        'schema_version = "plzdo-local.agent.v1"\n'
        'name = "explorer"\n'
        'description = "quoted '
        + slash
        + '"value'
        + slash
        + '" and unicode '
        + slash
        + 'u0041"\n'
        + 'instructions = """\nline'
        + slash
        + 'tvalue\n"""\n'
    )
    native_descriptor = _parse_agent_descriptor(escaped_descriptor, expected_name="explorer")
    with mock.patch.object(managed_install_module, "tomllib", None):
        fallback_descriptor = _parse_agent_descriptor(escaped_descriptor, expected_name="explorer")
    require(fallback_descriptor == native_descriptor, "restricted TOML valid-escape parity")

    malformed_escape = (
        'schema_version = "plzdo-local.agent.v1"\n'
        'name = "explorer"\n'
        'description = "bad'
        + slash
        + 'q"\n'
        + 'instructions = """\nbounded\n"""\n'
    )
    raw_del = (
        'schema_version = "plzdo-local.agent.v1"\n'
        'name = "explorer"\n'
        'description = "bad'
        + chr(127)
        + 'value"\n'
        + 'instructions = """\nbounded\n"""\n'
    )
    expect_error(
        ManagedInstallPathError,
        lambda: _parse_agent_descriptor(malformed_escape, expected_name="explorer"),
    )
    with mock.patch.object(managed_install_module, "tomllib", None):
        for invalid_descriptor in (malformed_escape, raw_del):
            expect_error(
                ManagedInstallPathError,
                lambda value=invalid_descriptor: _parse_agent_descriptor(value, expected_name="explorer"),
            )
    expect_error(
        ManagedInstallPathError,
        lambda: _parse_agent_descriptor(raw_del, expected_name="explorer"),
    )
    if sys.version_info[:2] == (3, 9):
        require(managed_install_module.tomllib is None, "Python 3.9 did not activate restricted TOML fallback")
        for invalid_descriptor in (malformed_escape, raw_del):
            expect_error(
                ManagedInstallPathError,
                lambda value=invalid_descriptor: _parse_agent_descriptor(value, expected_name="explorer"),
            )

    schema = json.loads((ROOT / "schemas" / "managed-install.schema.json").read_text(encoding="utf-8"))
    require(schema["additionalProperties"] is False, "managed schema must be exact-key")
    require(
        schema["properties"]["schemaVersion"]["const"] == MANAGED_INSTALL_SCHEMA_VERSION,
        "managed schema version",
    )
    require(
        schema["properties"]["resourceDigest"]["pattern"] == r"^[0-9a-f]{64}(?![\s\S])$",
        "digest schema",
    )


def check_dry_run_purity() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-phase5-dry-") as temporary:
        base = Path(temporary).resolve()
        skills = base / "missing-skills-root"
        before = tree_snapshot(base)
        install_plan = install_skill("plzdo-project-harness", skills, dry_run=True)
        require(install_plan["operation"] == "create" and install_plan["changed"], "skill dry-run plan")
        require(install_plan["dryRun"] is True, "skill dry-run flag")
        require(tree_snapshot(base) == before and not skills.exists(), "skill dry-run wrote destination")

        agents = base / "missing-agents-root"
        agent_plan = install_agent("explorer", agents, dry_run=True)
        require(agent_plan["operation"] == "create", "agent dry-run plan")
        require(tree_snapshot(base) == before and not agents.exists(), "agent dry-run wrote destination")

        absent_plan = uninstall_resource("skill", "project-start", skills, dry_run=True)
        require(absent_plan["operation"] == "absent" and not absent_plan["changed"], "absent removal plan")
        require(tree_snapshot(base) == before, "absent uninstall dry-run wrote destination")


def check_fresh_destination_installation() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-phase5-fresh-root-") as temporary:
        base = Path(temporary).resolve()
        skills = base / "codex" / "skills"
        agents = base / "codex" / "agents"

        skill_result = install_skill("plzdo-project-harness", skills)
        require(skill_result["operation"] == "create", "fresh skill installation did not create")
        require(inspect_resource("skill", "plzdo-project-harness", skills)["status"] == "managed", "fresh skill installation")

        agent_result = install_agent("explorer", agents)
        require(agent_result["operation"] == "create", "fresh agent installation did not create")
        require(inspect_resource("agent", "explorer", agents)["status"] == "managed", "fresh agent installation")

        uninstall_agent("explorer", agents)
        uninstall_skill("plzdo-project-harness", skills)
        require(inspect_resource("agent", "explorer", agents)["status"] == "absent", "fresh agent removal")
        require(inspect_resource("skill", "plzdo-project-harness", skills)["status"] == "absent", "fresh skill removal")

    with tempfile.TemporaryDirectory(prefix="plzdo-phase5-fresh-root-race-") as temporary:
        base = Path(temporary).resolve()
        outside = base / "outside"
        outside.mkdir()
        agents = base / "codex" / "agents"

        def replace_parent(event: str, paths: object) -> None:
            if event == "before-root-create":
                (base / "codex").symlink_to(outside, target_is_directory=True)

        with mock.patch.object(managed_install_module, "_TEST_OPERATION_HOOK", replace_parent):
            expect_error(ManagedInstallPathError, lambda: install_agent("explorer", agents))
        require(not (outside / "agents").exists(), "fresh-root race wrote through a replaced parent")
        require(not (outside / "explorer.toml").exists(), "fresh-root race published an agent")


def check_unmanaged_collision() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-phase5-collision-") as temporary:
        root = Path(temporary).resolve()
        skill = root / "plzdo-project-harness"
        skill.mkdir()
        (skill / "SKILL.md").write_text("operator owned\n", encoding="utf-8")
        before = tree_snapshot(root)
        expect_error(
            ManagedInstallCollisionError,
            lambda: install_skill("plzdo-project-harness", root),
        )
        expect_error(
            ManagedInstallCollisionError,
            lambda: install_skill("plzdo-project-harness", root, force=True),
        )
        expect_error(
            ManagedInstallCollisionError,
            lambda: uninstall_skill("plzdo-project-harness", root),
        )
        require(tree_snapshot(root) == before, "unmanaged skill collision changed bytes")

        descriptor = root / "explorer.toml"
        descriptor.write_text("operator owned\n", encoding="utf-8")
        before_agent = tree_snapshot(root)
        expect_error(ManagedInstallCollisionError, lambda: install_agent("explorer", root, force=True))
        require(tree_snapshot(root) == before_agent, "unmanaged agent collision changed bytes")


def check_managed_drift() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-phase5-drift-") as temporary:
        root = Path(temporary).resolve()
        install_skill("plzdo-project-harness", root)
        skill = root / "plzdo-project-harness"
        marker = json.loads((skill / MANAGED_MARKER).read_text(encoding="utf-8"))
        content = (skill / "SKILL.md").read_bytes()
        require(marker["files"][0]["sha256"] == hashlib.sha256(content).hexdigest(), "marker content hash")
        require(marker["resourceDigest"] and len(marker["resourceDigest"]) == 64, "marker resource hash")

        drifted = skill / "SKILL.md"
        drifted.write_text("operator changed this managed file\n", encoding="utf-8")
        require(inspect_resource("skill", "plzdo-project-harness", root)["status"] == "drifted", "drift status")
        before = tree_snapshot(root)
        expect_error(ManagedInstallDriftError, lambda: install_skill("plzdo-project-harness", root))
        expect_error(
            ManagedInstallDriftError,
            lambda: uninstall_skill("plzdo-project-harness", root),
        )
        require(tree_snapshot(root) == before, "drift refusal changed managed content")

        extra = skill / "operator-note.txt"
        extra.write_text("keep\n", encoding="utf-8")
        before_extra = tree_snapshot(root)
        expect_error(
            ManagedInstallCollisionError,
            lambda: install_skill("plzdo-project-harness", root, force=True),
        )
        require(tree_snapshot(root) == before_extra, "force removed an untracked skill file")
        extra.unlink()
        repaired = install_skill("plzdo-project-harness", root, force=True)
        require(repaired["operation"] == "repair", "managed repair operation")
        require(inspect_resource("skill", "plzdo-project-harness", root)["status"] == "managed", "repair status")
        uninstall_skill("plzdo-project-harness", root)

        install_agent("explorer", root)
        descriptor = root / "explorer.toml"
        descriptor.chmod(0o600)
        require(inspect_resource("agent", "explorer", root)["status"] == "drifted", "agent mode drift")
        before_agent = tree_snapshot(root)
        expect_error(ManagedInstallDriftError, lambda: uninstall_agent("explorer", root))
        require(tree_snapshot(root) == before_agent, "drifted agent was removed")

        descriptor.chmod(0o644)
        agent_marker = root / (".explorer.toml" + MANAGED_MARKER)
        marker_value = json.loads(agent_marker.read_text(encoding="utf-8"))
        agent_marker.write_text(json.dumps(marker_value, sort_keys=True) + "\n", encoding="utf-8")
        require(inspect_resource("agent", "explorer", root)["status"] == "drifted", "marker byte drift")
        expect_error(ManagedInstallDriftError, lambda: uninstall_agent("explorer", root))


def check_quarantine_transactions() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-phase5-race-") as temporary:
        root = Path(temporary).resolve()
        install_skill("project-start", root)
        skill_file = root / "project-start" / "SKILL.md"
        raced_bytes = b"concurrent operator edit\n"

        def mutate_before_quarantine(event: str, paths: object) -> None:
            if event == "before-quarantine":
                skill_file.write_bytes(raced_bytes)

        with mock.patch.object(managed_install_module, "_TEST_OPERATION_HOOK", mutate_before_quarantine):
            expect_error(ManagedInstallDriftError, lambda: uninstall_skill("project-start", root))
        require(skill_file.read_bytes() == raced_bytes, "uninstall race deleted concurrent bytes")
        require((root / "project-start" / MANAGED_MARKER).is_file(), "uninstall race lost marker")
        require(not tuple(root.glob(".plzdo-quarantine-*")), "restored race left quarantine")

    with tempfile.TemporaryDirectory(prefix="plzdo-phase5-rollback-") as temporary:
        root = Path(temporary).resolve()
        install_skill("ponytail", root)
        baseline = tree_snapshot(root)
        source = (ROOT / "resources/public-skills/ponytail/SKILL.md").read_bytes()

        def fail_after_publish(event: str, paths: object) -> None:
            if event == "after-publish":
                raise RuntimeError("injected post-publish failure")

        with mock.patch.object(
            managed_install_module,
            "_load_source_files",
            return_value={"SKILL.md": source + b"\nupgrade fixture\n"},
        ), mock.patch.object(managed_install_module, "_TEST_OPERATION_HOOK", fail_after_publish):
            expect_error(RuntimeError, lambda: install_skill("ponytail", root))
        require(tree_snapshot(root) == baseline, "failed upgrade did not restore exact old tree")

        def fail_after_first_component(event: str, paths: object) -> None:
            if event == "after-publish-component":
                raise RuntimeError("injected partial agent publish")

        before_agent = tree_snapshot(root)
        with mock.patch.object(managed_install_module, "_TEST_OPERATION_HOOK", fail_after_first_component):
            expect_error(RuntimeError, lambda: install_agent("explorer", root))
        require(tree_snapshot(root) == before_agent, "partial agent publish did not roll back")

    with tempfile.TemporaryDirectory(prefix="plzdo-phase5-upgrade-race-") as temporary:
        root = Path(temporary).resolve()
        install_skill("ponytail", root)
        skill_file = root / "ponytail" / "SKILL.md"
        source = (ROOT / "resources/public-skills/ponytail/SKILL.md").read_bytes()
        concurrent = b"concurrent upgrade edit\n"

        def race_upgrade(event: str, paths: object) -> None:
            if event == "before-quarantine":
                skill_file.write_bytes(concurrent)

        with mock.patch.object(
            managed_install_module,
            "_load_source_files",
            return_value={"SKILL.md": source + b"\nupgrade fixture\n"},
        ), mock.patch.object(managed_install_module, "_TEST_OPERATION_HOOK", race_upgrade):
            expect_error(ManagedInstallDriftError, lambda: install_skill("ponytail", root))
        require(skill_file.read_bytes() == concurrent, "upgrade race lost concurrent bytes")
        require((root / "ponytail" / MANAGED_MARKER).is_file(), "upgrade race lost old marker")
        require(not tuple(root.glob(".plzdo-quarantine-*")), "upgrade race left quarantine")
        require(not tuple(root.glob(".plzdo-install-*")), "upgrade race left owned stage")

    with tempfile.TemporaryDirectory(prefix="plzdo-phase5-cleanup-") as temporary:
        root = Path(temporary).resolve()
        install_skill("project-start", root)

        def fail_partial_cleanup(relative: str) -> None:
            if relative.endswith("/" + MANAGED_MARKER):
                raise OSError("injected partial quarantine cleanup")

        with mock.patch.object(managed_install_module, "_TEST_CLEANUP_HOOK", fail_partial_cleanup):
            expect_error(ManagedInstallError, lambda: uninstall_skill("project-start", root))
        require(not (root / "project-start").exists(), "partial cleanup restored corrupt live content")
        quarantines = tuple(root.glob(".plzdo-quarantine-*"))
        require(len(quarantines) == 1, "partial cleanup did not preserve one quarantine remnant")
        require(
            (quarantines[0] / "project-start" / "SKILL.md").is_file(),
            "partial cleanup lost remaining quarantine evidence",
        )

    with tempfile.TemporaryDirectory(prefix="plzdo-phase5-agent-collision-") as temporary:
        root = Path(temporary).resolve()
        marker = root / (".explorer.toml" + MANAGED_MARKER)
        collision = b"concurrent marker collision\n"
        injected = [False]

        def collide_with_second_component(event: str, paths: object) -> None:
            if event == "after-publish-component" and not injected[0]:
                marker.write_bytes(collision)
                injected[0] = True

        with mock.patch.object(
            managed_install_module,
            "_TEST_OPERATION_HOOK",
            collide_with_second_component,
        ):
            expect_error(ManagedInstallCollisionError, lambda: install_agent("explorer", root))
        require(not (root / "explorer.toml").exists(), "agent rollback retained its first component")
        require(marker.read_bytes() == collision, "agent rollback replaced a concurrent collision")
        require(not tuple(root.glob(".plzdo-install-*")), "agent collision rollback left an owned stage")

    for action in ("install", "uninstall"):
        with tempfile.TemporaryDirectory(prefix="plzdo-phase5-root-swap-") as temporary:
            base = Path(temporary).resolve()
            root = base / "managed-root"
            outside = base / "outside-root"
            root.mkdir()
            outside.mkdir()
            install_skill("ponytail", root)
            install_skill("ponytail", outside)
            outside_before = tree_snapshot(outside)
            displaced = base / "displaced-root"
            swapped = [False]

            def swap_root_before_cleanup(event: str, paths: object) -> None:
                if event == "before-cleanup" and not swapped[0]:
                    root.rename(displaced)
                    root.symlink_to(outside, target_is_directory=True)
                    swapped[0] = True

            try:
                with mock.patch.object(
                    managed_install_module,
                    "_TEST_OPERATION_HOOK",
                    swap_root_before_cleanup,
                ):
                    if action == "install":
                        source = (ROOT / "resources/public-skills/ponytail/SKILL.md").read_bytes()
                        with mock.patch.object(
                            managed_install_module,
                            "_load_source_files",
                            return_value={"SKILL.md": source + b"\nroot swap fixture\n"},
                        ):
                            expect_error(ManagedInstallDriftError, lambda: install_skill("ponytail", root))
                    else:
                        expect_error(ManagedInstallDriftError, lambda: uninstall_skill("ponytail", root))
            finally:
                if root.is_symlink():
                    root.unlink()
                if displaced.exists():
                    displaced.rename(root)
            require(swapped[0], "destination-root swap hook did not execute")
            require(tree_snapshot(outside) == outside_before, "root swap touched the outside managed tree")
            require(
                inspect_resource("skill", "ponytail", root)["status"] == "managed",
                "root swap did not restore the retained managed tree",
            )


def check_bounded_descriptor_reads() -> None:
    source = (ROOT / "plzdo_local/managed_install.py").read_text(encoding="utf-8")
    require("O_NOFOLLOW" in source and "os.fstat" in source and "os.read(" in source, "descriptor read primitives")
    tree = ast.parse(source, filename="managed_install.py", feature_version=(3, 9))
    forbidden_methods = {"read_bytes", "rglob", "walk"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            require(node.func.attr not in forbidden_methods, "unbounded/path-based read call: " + node.func.attr)

    with tempfile.TemporaryDirectory(prefix="plzdo-phase5-bounded-") as temporary:
        root = Path(temporary).resolve()
        outside = root / "outside.txt"
        outside.write_text("outside bytes\n", encoding="utf-8")
        install_skill("project-start", root)
        managed = root / "project-start" / "SKILL.md"
        managed.unlink()
        managed.symlink_to(outside)
        require(inspect_resource("skill", "project-start", root)["status"] == "drifted", "nofollow symlink drift")
        managed.unlink()
        managed.write_text("replacement\n", encoding="utf-8")
        consumed: list[str] = []
        with mock.patch.object(managed_install_module, "_MAX_DRIFT_ENTRIES", 1), mock.patch.object(
            managed_install_module,
            "_TEST_SCANDIR_OBSERVER",
            consumed.append,
        ):
            inspected = inspect_resource("skill", "project-start", root)
        require(inspected["status"] == "drifted", "bounded traversal did not fail closed")
        require("entry limit" in (inspected["reason"] or ""), "bounded traversal reason")
        require(len(consumed) == 2, "managed traversal consumed beyond limit plus one")


def check_roundtrip_restoration() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-phase5-roundtrip-") as temporary:
        root = Path(temporary).resolve()
        unrelated = root / "unrelated"
        unrelated.mkdir()
        (unrelated / "keep.txt").write_text("preserve exact bytes\n", encoding="utf-8")
        (unrelated / "keep.txt").chmod(0o640)
        private_named = root / ("adaptive" + "-project-harness")
        private_named.mkdir()
        (private_named / "SKILL.md").write_text("separate operator-owned skill\n", encoding="utf-8")
        baseline = tree_snapshot(root)

        previous_umask = os.umask(0o077)
        try:
            for name in PUBLIC_SKILLS:
                result = install_skill(name, root)
                require(result["operation"] == "create", "skill create: " + name)
                require(inspect_resource("skill", name, root)["status"] == "managed", "skill managed: " + name)
                require(stat.S_IMODE((root / name).stat().st_mode) == 0o755, "skill directory mode: " + name)
                unchanged = install_skill(name, root)
                require(unchanged["operation"] == "unchanged" and not unchanged["changed"], "skill idempotence: " + name)
            for name in PUBLIC_AGENTS:
                install_agent(name, root)
                require(inspect_resource("agent", name, root)["status"] == "managed", "agent managed: " + name)
        finally:
            os.umask(previous_umask)

        for name in reversed(PUBLIC_AGENTS):
            uninstall_agent(name, root)
        for name in reversed(PUBLIC_SKILLS):
            uninstall_skill(name, root)
        require(tree_snapshot(root) == baseline, "install-uninstall did not restore exact root state")


def check_static_catalogs() -> None:
    catalog_root = ROOT / "resources" / "catalogs"
    before = tree_snapshot(catalog_root)
    for catalog_name in ("sources", "design"):
        value = load_static_catalog(catalog_name)
        validate_static_catalog(value, expected_catalog=catalog_name)
        entries = list_catalog_entries(catalog_name)
        require(entries and [entry["id"] for entry in entries] == sorted(entry["id"] for entry in entries), "catalog order")
        for entry in entries:
            require(entry["sourceUrl"].startswith("https://"), "catalog source URL")
            require(entry["licenseStatus"] in ("verified-open", "review-required"), "catalog license status")
            require(
                entry["revisionKind"] in ("commit", "digest", "spec-version", "tag", "unversioned"),
                "catalog revision kind",
            )
            require(entry["reviewedRevision"] and entry["reviewedDate"], "catalog revision evidence")
            require(entry["decision"] in ("adopt", "reference", "exclude"), "catalog decision")
            require(
                entry["revisionKind"] != "unversioned" or entry["licenseStatus"] == "review-required",
                "unpinned catalog entry claimed verified-open: " + entry["id"],
            )
        selected = show_static_catalog_entry(catalog_name, entries[0]["id"])
        require(selected["id"] == entries[0]["id"], "catalog show")
    require(search_static_catalog("sources", "schema validation"), "source catalog search")
    require(search_static_catalog("design", "accessibility"), "design catalog search")

    invalid_head = json.loads(json.dumps(load_static_catalog("sources")))
    invalid_head["entries"][0]["revisionKind"] = "tag"
    invalid_head["entries"][0]["reviewedRevision"] = "HEAD"
    expect_error(StaticCatalogError, lambda: validate_static_catalog(invalid_head, expected_catalog="sources"))

    for branch_revision in (
        "refs/remotes/origin/release",
        "origin/release",
        "refs/heads/release",
        "branch",
    ):
        branch_entry = json.loads(json.dumps(load_static_catalog("sources")))
        branch_entry["entries"][0]["revisionKind"] = "tag"
        branch_entry["entries"][0]["reviewedRevision"] = branch_revision
        expect_error(
            StaticCatalogError,
            lambda value=branch_entry: validate_static_catalog(value, expected_catalog="sources"),
        )

    verified_tag = json.loads(json.dumps(load_static_catalog("sources")))
    verified_tag["entries"][0]["licenseStatus"] = "verified-open"
    verified_tag["entries"][0]["revisionKind"] = "tag"
    verified_tag["entries"][0]["reviewedRevision"] = "v1.0.0"
    expect_error(
        StaticCatalogError,
        lambda: validate_static_catalog(verified_tag, expected_catalog="sources"),
    )

    git_spec = json.loads(json.dumps(load_static_catalog("sources")))
    git_spec["entries"][1]["sourceUrl"] = "https://github.com/example/project"
    expect_error(
        StaticCatalogError,
        lambda: validate_static_catalog(git_spec, expected_catalog="sources"),
    )

    unpinned_verified = json.loads(json.dumps(load_static_catalog("sources")))
    unpinned_verified["entries"][0]["licenseStatus"] = "verified-open"
    expect_error(
        StaticCatalogError,
        lambda: validate_static_catalog(unpinned_verified, expected_catalog="sources"),
    )
    require(tree_snapshot(catalog_root) == before, "static catalog read changed repository resources")


def check_marker_schema_conformance() -> None:
    schema = json.loads((ROOT / "schemas/managed-install.schema.json").read_text(encoding="utf-8"))
    properties = schema["properties"]
    file_schema = properties["files"]
    path_schema = file_schema["items"]["properties"]["path"]
    path_pattern = re.compile(path_schema["pattern"])
    release_pattern = re.compile(properties["releaseVersion"]["pattern"])
    require("uniqueItems" not in file_schema, "structural schema claimed semantic file uniqueness")
    require(
        schema["x-plzdo-semanticValidator"]
        == "plzdo_local.managed_install.validate_managed_install_marker",
        "managed marker semantic validator identity",
    )
    require("Structural validation only" in schema["$comment"], "managed schema boundary documentation")
    require(path_schema["maxLength"] == 240, "schema path bound")
    require(path_pattern.pattern == managed_install_module._SAFE_RELATIVE_PATH.pattern, "schema/runtime path regex drift")

    for value in ("SKILL.md", "nested/file.txt", ".well-known/policy.json", "a_b/c-d.e"):
        require(path_pattern.fullmatch(value) is not None, "schema rejected runtime-safe path: " + value)
        require(_require_safe_relative_path(value) == value, "runtime rejected schema-safe path: " + value)
    for value in (
        "../file",
        "./file",
        "a//file",
        "a/../file",
        "a b/file",
        "unicode-\u30d1\u30b9",
        "back\\slash",
        MANAGED_MARKER,
        MANAGED_MARKER + "/nested",
    ):
        require(path_pattern.fullmatch(value) is None, "schema accepted runtime-unsafe path: " + value)
        expect_error(ManagedInstallDriftError, lambda item=value: _require_safe_relative_path(item))

    with tempfile.TemporaryDirectory(prefix="plzdo-phase5-schema-") as temporary:
        root = Path(temporary).resolve()
        install_agent("explorer", root)
        marker_path = root / (".explorer.toml" + MANAGED_MARKER)
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        validate_managed_install_marker(marker, resource_type="agent", resource_name="explorer")
        invalid_release = json.loads(json.dumps(marker))
        invalid_release["releaseVersion"] = "bad\nrelease"
        require(release_pattern.fullmatch(invalid_release["releaseVersion"]) is None, "schema accepted control text")
        expect_error(
            ManagedInstallDriftError,
            lambda: validate_managed_install_marker(
                invalid_release,
                resource_type="agent",
                resource_name="explorer",
            ),
        )
        duplicate = json.loads(json.dumps(marker))
        second = dict(duplicate["files"][0])
        second["sha256"] = "0" * 64
        second["sizeBytes"] += 1
        duplicate["files"].append(second)
        require(duplicate["files"][0] != duplicate["files"][1], "duplicate-path corpus is structurally distinct")

        digest_mismatch = json.loads(json.dumps(marker))
        digest_mismatch["resourceDigest"] = "0" * 64
        wrong_destination = json.loads(json.dumps(marker))
        wrong_destination["files"][0]["path"] = "tester.toml"
        semantic_corpus = (
            ("duplicate path", duplicate),
            ("resource digest", digest_mismatch),
            ("fixed agent destination", wrong_destination),
        )
        for label, invalid_marker in semantic_corpus:
            expect_error(
                ManagedInstallDriftError,
                lambda value=invalid_marker: validate_managed_install_marker(
                    value,
                    resource_type="agent",
                    resource_name="explorer",
                ),
            )


def check_local_only_surface() -> None:
    module_paths = (
        ROOT / "plzdo_local" / "managed_install.py",
        ROOT / "plzdo_local" / "review_bundle.py",
        ROOT / "plzdo_local" / "monitor.py",
        ROOT / "plzdo_local" / "local_ops_cli.py",
        ROOT / "plzdo_local" / "resource_cli.py",
    )
    forbidden_imports = {
        "aiohttp",
        "asyncio",
        "ctypes",
        "ftplib",
        "http",
        "importlib",
        "multiprocessing",
        "pty",
        "requests",
        "smtplib",
        "socket",
        "socketserver",
        "ssl",
        "subprocess",
        "telnetlib",
        "urllib",
        "webbrowser",
        "xmlrpc",
    }
    forbidden_builtins = {"compile", "eval", "exec", "__import__"}
    forbidden_os_calls = {"fork", "forkpty", "popen", "posix_spawn", "posix_spawnp", "system"}
    transport_objects = {"http", "requests", "socket", "subprocess", "urllib", "webbrowser"}
    for module_path in module_paths:
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path), feature_version=(3, 9))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    require(alias.name.split(".")[0] not in forbidden_imports, "transport import: " + alias.name)
            if isinstance(node, ast.ImportFrom) and node.module:
                require(node.module.split(".")[0] not in forbidden_imports, "transport import: " + node.module)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                require(node.func.id not in forbidden_builtins, "dynamic execution call: " + node.func.id)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
            ):
                require(
                    node.func.attr not in forbidden_os_calls
                    and not node.func.attr.startswith("exec")
                    and not node.func.attr.startswith("spawn"),
                    "process startup call: os." + node.func.attr,
                )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
            ):
                require(
                    node.func.value.id not in transport_objects,
                    "transport or process call: " + node.func.value.id + "." + node.func.attr,
                )

    for function in (install_resource, uninstall_resource):
        parameters = set(inspect.signature(function).parameters)
        require("source" not in parameters and "source_path" not in parameters, "arbitrary source parameter")
    require("force" not in inspect.signature(uninstall_resource).parameters, "uninstall retained force parameter")

    owned_paths = list(module_paths) + [
        ROOT / "tests" / "phase5_check.py",
        ROOT / "tests" / "local_ops_check.py",
        ROOT / "schemas" / "managed-install.schema.json",
        ROOT / "docs" / "data-and-privacy.md",
        ROOT / "docs" / "command-reference.md",
    ]
    owned_paths.extend(sorted((ROOT / "resources" / "public-skills").rglob("*")))
    owned_paths.extend(sorted((ROOT / "resources" / "public-agents").rglob("*")))
    owned_paths.extend(sorted((ROOT / "resources" / "catalogs").rglob("*")))
    private_skill_name = "adaptive" + "-project-harness"
    forbidden_startup = (".bash" + "rc", ".zsh" + "rc", "." + "profile", ".git/" + "hooks")
    for path in owned_paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        require(private_skill_name not in text, "private skill namespace leaked: " + path.name)
        for token in forbidden_startup:
            require(token not in text, "startup mutation surface: " + path.name)


def check_local_only_runtime() -> None:
    blocked = AssertionError("local-only resource operation attempted transport or process startup")
    real_import = builtins.__import__
    attempted_imports: list[str] = []
    forbidden_imports = {
        "aiohttp",
        "asyncio",
        "ctypes",
        "ftplib",
        "http",
        "importlib",
        "multiprocessing",
        "pty",
        "requests",
        "smtplib",
        "socket",
        "socketserver",
        "ssl",
        "subprocess",
        "telnetlib",
        "urllib",
        "webbrowser",
        "xmlrpc",
    }
    attempted_audits: list[str] = []
    audit_active = [False]

    def audit_hook(event: str, args: tuple[object, ...]) -> None:
        del args
        if not audit_active[0]:
            return
        if event in {"os.system", "os.fork", "os.forkpty", "os.posix_spawn", "subprocess.Popen"} or event.startswith(
            ("socket.", "urllib.", "http.client.", "webbrowser.", "pty.spawn")
        ):
            attempted_audits.append(event)
            raise blocked

    sys.addaudithook(audit_hook)
    audit_active[0] = True
    expect_error(AssertionError, lambda: sys.audit("socket.connect", None))
    require(attempted_audits == ["socket.connect"], "audit hook did not block synthetic transport event")
    attempted_audits.clear()

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name.split(".")[0] in forbidden_imports:
            attempted_imports.append(name)
            raise blocked
        return real_import(name, *args, **kwargs)

    with tempfile.TemporaryDirectory(prefix="plzdo-phase5-local-only-") as temporary:
        root = Path(temporary).resolve()
        review_source = root / "review.txt"
        review_source.write_text("bounded local evidence\n", encoding="utf-8")
        baseline = tree_snapshot(root)
        output = StringIO()
        try:
            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(builtins, "__import__", side_effect=guarded_import))
                for name in dir(os):
                    if name in {"fork", "forkpty", "popen", "posix_spawn", "posix_spawnp", "system"} or name.startswith(
                        ("exec", "spawn")
                    ):
                        candidate = getattr(os, name)
                        if callable(candidate):
                            stack.enter_context(mock.patch.object(os, name, side_effect=blocked))
                stack.enter_context(redirect_stdout(output))
                require(cli_main(["skills", "list", "--json"]) == 0, "blocked-runtime skill list")
                require(
                    cli_main(["agents", "install", "tester", "--root", str(root), "--json"]) == 0,
                    "blocked-runtime agent install",
                )
                require(
                    cli_main(["agents", "uninstall", "tester", "--root", str(root), "--json"]) == 0,
                    "blocked-runtime agent uninstall",
                )
                require(cli_main(["sources", "list", "--json"]) == 0, "blocked-runtime catalog list")
                manifest = build_review_manifest(purpose="Review bounded local evidence.", files=["review.txt"])
                bundle = prepare_review_bundle(root, manifest, created_at="2026-08-05T10:00:00Z")
                imported = import_review_response(
                    bundle,
                    b"advisory local response\n",
                    imported_at="2026-08-05T10:01:00Z",
                )
                require(imported["toolAuthority"] is False, "blocked-runtime review authority")
                require(repo_preflight(root)["targetMutated"] is False, "blocked-runtime monitor preflight")
                require(
                    cli_main(["repo-preflight", str(root), "--json"]) == 0,
                    "blocked-runtime local operations CLI",
                )
        finally:
            audit_active[0] = False
        require(not attempted_imports, "local-only runtime attempted forbidden import")
        require(not attempted_audits, "local-only runtime attempted audited transport or process startup")
        require(tree_snapshot(root) == baseline, "local-only runtime round-trip changed local fixture")


def check_path_and_name_safety() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-phase5-paths-") as temporary:
        root = Path(temporary).resolve()
        outside = root / "outside"
        outside.mkdir()
        linked_root = root / "linked-root"
        linked_root.symlink_to(outside, target_is_directory=True)
        expect_error(
            ManagedInstallPathError,
            lambda: install_skill("project-start", linked_root),
        )
        require(tree_snapshot(outside) == (), "linked destination root was written")

        outside_marker = outside / MANAGED_MARKER
        outside_marker.write_text("outside marker must not grant ownership\n", encoding="utf-8")
        linked_skill = root / "project-start"
        linked_skill.symlink_to(outside, target_is_directory=True)
        outside_before = tree_snapshot(outside)
        expect_error(
            ManagedInstallCollisionError,
            lambda: install_skill("project-start", root, force=True),
        )
        require(tree_snapshot(outside) == outside_before, "linked skill destination was changed")

        before = tree_snapshot(root)
        private_name = "adaptive" + "-project-harness"
        for unsafe in ("../project-start", "unknown", "PLZDO-project", private_name):
            expect_error(
                UnknownManagedResourceError,
                lambda value=unsafe: install_resource("skill", value, root),
            )
        expect_error(UnknownManagedResourceError, lambda: install_resource("plugin", "project-start", root))
        require(tree_snapshot(root) == before, "unknown resource changed destination")


def check_cli_surface() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-phase5-cli-") as temporary:
        root = Path(temporary).resolve()
        output = StringIO()
        with redirect_stdout(output):
            require(cli_main(["skills", "list", "--json"]) == 0, "skills list CLI")
            require(
                cli_main(["skills", "install", "ponytail", "--root", str(root), "--dry-run", "--json"]) == 0,
                "skills install dry-run CLI",
            )
            require(cli_main(["sources", "search", "schema", "--json"]) == 0, "sources search CLI")
            require(cli_main(["design", "show", "wcag-2-2", "--json"]) == 0, "design show CLI")
        values = output.getvalue()
        require("ponytail" in values and "json-schema-2020-12" in values, "CLI output content")
        require(tree_snapshot(root) == (), "CLI dry-run changed destination")
        with redirect_stderr(StringIO()):
            expect_error(
                SystemExit,
                lambda: build_parser().parse_args(
                    ["skills", "uninstall", "ponytail", "--root", str(root), "--force"]
                ),
            )


def tree_snapshot(root: Path) -> tuple:
    if not root.exists():
        return ()
    entries = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_symlink():
            entries.append((relative, "symlink", mode, os.readlink(path)))
        elif path.is_dir():
            entries.append((relative, "directory", mode, ""))
        elif path.is_file():
            entries.append((relative, "file", mode, hashlib.sha256(path.read_bytes()).hexdigest()))
        else:
            entries.append((relative, "special", mode, ""))
    return tuple(entries)


def expect_error(error_type: Type[BaseException], action: Callable[[], object]) -> None:
    try:
        action()
    except error_type:
        return
    raise AssertionError("expected " + error_type.__name__)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
