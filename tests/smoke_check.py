from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from plzdo_local.atomic_io import atomic_write_json, atomic_write_text, exclusive_file_lock
from plzdo_local.failure_report import build_failure_report, validate_failure_report, write_failure_report
from plzdo_local.paths import PathPolicyError, ensure_contained, resolve_state_root
from plzdo_local.validation import ValidationError


def main() -> int:
    if sys.flags.optimize:
        print("FAIL Python optimization disables executable assertions")
        return 1
    checks = [
        ("version command is consistent", check_version_command),
        ("doctor is local and supported", check_doctor),
        ("state root resolution is explicit", check_state_root),
        ("atomic writes stay contained", check_atomic_writes),
        ("failure reports reject sensitive shapes", check_failure_reports),
        ("release scanner self-test is executable", check_scanner_self_test),
        ("private denylist detects without disclosure", check_private_denylist),
        ("private denylist must stay outside release", check_private_denylist_location),
        ("hostile Python startup state is ignored", check_hostile_python_startup),
    ]
    failures: list[str] = []
    for label, check in checks:
        try:
            check()
        except Exception as exc:  # evidence wrapper; individual checks enforce exact behavior
            failures.append(f"{label}: {type(exc).__name__}: {exc}")
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(f"phase1 smoke check passed: {len(checks)} checks")
    return 0


def check_version_command() -> None:
    result = run_cli("version", "--json")
    require(result.returncode == 0, result.stderr)
    payload = json.loads(result.stdout)
    require(payload["status"] == "ok", "version status was not ok")
    require(payload["version"] == (ROOT / "VERSION").read_text(encoding="utf-8").strip(), "version drift")
    with tempfile.TemporaryDirectory(prefix="plzdo-wrapper-") as temporary:
        fixture = Path(temporary)
        fake_package = fixture / "plzdo_local"
        fake_package.mkdir()
        marker = fixture / "imported.txt"
        (fake_package / "__init__.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n",
            encoding="utf-8",
        )
        fake_bin = fixture / "bin"
        fake_bin.mkdir()
        for command in ("git", "bash"):
            executable = fake_bin / command
            executable.write_text(f"#!/bin/sh\necho bad > {str(marker)!r}\n", encoding="utf-8")
            executable.chmod(0o755)
        wrapper = run_wrapper(
            "doctor",
            "--json",
            cwd=fixture,
            extra_env={"PYTHONPATH": str(fixture), "PATH": str(fake_bin)},
        )
        require(wrapper.returncode == 0, wrapper.stdout + wrapper.stderr)
        require(not marker.exists(), "wrapper loaded caller-controlled code or executable")
        require(not any(ROOT.rglob("__pycache__")), "wrapper created a Python cache")
        require(not any(ROOT.rglob("*.pyc")), "wrapper created bytecode beside source")


def check_doctor() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-doctor-") as temporary:
        state_root = Path(temporary) / "state"
        result = run_cli("doctor", "--json", extra_env={"PLZDO_HOME": str(state_root)})
        require(result.returncode == 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        require(payload["status"] == "ok", "doctor status was not ok")
        require(Path(payload["stateRoot"]) == state_root.resolve(strict=False), "doctor state root mismatch")
        require(not state_root.exists(), "doctor must not create state")


def check_state_root() -> None:
    root = resolve_state_root(environ={"PLZDO_HOME": "/tmp/plzdo-fixture-state"})
    require(root == Path("/tmp/plzdo-fixture-state").resolve(strict=False), "explicit state root mismatch")
    try:
        resolve_state_root(environ={"PLZDO_HOME": "relative/state"})
    except PathPolicyError:
        pass
    else:
        raise AssertionError("relative PLZDO_HOME was accepted")
    with tempfile.TemporaryDirectory(prefix="plzdo-state-root-") as temporary:
        state_root = Path(temporary) / "state"
        result = run_cli("state-root", "status", "--json", extra_env={"PLZDO_HOME": str(state_root)})
        require(result.returncode == 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        require(payload["path"] == str(state_root.resolve(strict=False)), "state-root command path mismatch")
        require(payload["exists"] is False, "state-root status unexpectedly created state")
        require(not state_root.exists(), "state-root status must not write")


def check_atomic_writes() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-atomic-") as temporary:
        root = Path(temporary) / "allowed"
        root.mkdir()
        target = root / "nested" / "value.json"
        atomic_write_json(target, {"b": 2, "a": 1}, allowed_root=root)
        require(target.read_text(encoding="utf-8") == '{\n  "a": 1,\n  "b": 2\n}\n', "atomic JSON mismatch")
        atomic_write_text(root / "plain.txt", "ok\n", allowed_root=root)
        preserved = root / "preserved.txt"
        preserved.write_text("before\n", encoding="utf-8")
        try:
            atomic_write_text(
                preserved,
                "after\n",
                allowed_root=root,
                validator=lambda _: (_ for _ in ()).throw(ValidationError("synthetic rejection")),
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("validator rejection was ignored")
        require(preserved.read_text(encoding="utf-8") == "before\n", "validation failure replaced destination")
        try:
            atomic_write_text(root.parent / "outside.txt", "bad\n", allowed_root=root)
        except PathPolicyError:
            pass
        else:
            raise AssertionError("outside write was accepted")
        outside = root.parent / "outside"
        outside.mkdir()
        link = root / "escape"
        link.symlink_to(outside, target_is_directory=True)
        try:
            ensure_contained(link / "file.txt", root, label="fixture")
        except PathPolicyError:
            pass
        else:
            raise AssertionError("symlink escape was accepted")
        in_root_target = root / "in-root-target.txt"
        in_root_target.write_text("preserve\n", encoding="utf-8")
        in_root_link = root / "in-root-link.txt"
        in_root_link.symlink_to(in_root_target)
        try:
            atomic_write_text(in_root_link, "redirected\n", allowed_root=root)
        except PathPolicyError:
            pass
        else:
            raise AssertionError("in-root output symlink was accepted")
        require(in_root_target.read_text(encoding="utf-8") == "preserve\n", "in-root symlink target changed")
        lock_target = root / "real.lock"
        lock_target.write_text("", encoding="utf-8")
        lock_link = root / "linked.lock"
        lock_link.symlink_to(lock_target)
        try:
            with exclusive_file_lock(lock_link, allowed_root=root):
                raise AssertionError("symlinked lock unexpectedly opened")
        except (PathPolicyError, OSError, ValueError):
            pass


def check_failure_reports() -> None:
    report = build_failure_report(
        operation="phase-one",
        code="fixture-failure",
        message="Synthetic bounded failure",
        detail_ids=["detail-one"],
    )
    validate_failure_report(report)
    with tempfile.TemporaryDirectory(prefix="plzdo-failure-") as temporary:
        root = Path(temporary)
        destination = root / "report.json"
        write_failure_report(destination, report, allowed_root=root)
        require(json.loads(destination.read_text(encoding="utf-8"))["code"] == "fixture-failure", "failure report mismatch")
    private_path = "/" + "Users/" + "fixture/private"
    try:
        build_failure_report(operation="phase-one", code="unsafe-message", message=private_path)
    except ValidationError:
        pass
    else:
        raise AssertionError("sensitive failure message was accepted")
    provider_token = "sk" + "-abcdefghijklmnop1234"
    try:
        build_failure_report(operation="phase-one", code="unsafe-token", message=provider_token)
    except ValidationError:
        pass
    else:
        raise AssertionError("credential-shaped failure message was accepted")
    try:
        build_failure_report(
            operation="phase-one",
            code="unsafe-location",
            message="See https://private.invalid/failure",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("network-location failure message was accepted")
    private_locations = (
        "root=/",
        "path=/" + "Volumes/SyntheticDrive/private.txt",
        "root='/'" + "home/synthetic/private.txt'",
        "target=C:" + "\\Users\\synthetic\\private.txt",
        "paths=[/" + "home/synthetic/private.txt]",
        "paths={C:" + "\\Users\\synthetic\\private.txt}",
    )
    for message in private_locations:
        try:
            build_failure_report(operation="phase-one", code="unsafe-path", message=message)
        except ValidationError:
            pass
        else:
            raise AssertionError("assignment or quoted absolute path was accepted")
    try:
        build_failure_report(
            operation="phase-one",
            code="too-many-details",
            message="Synthetic bounded failure",
            detail_ids=[f"detail-{index}" for index in range(33)],
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("oversized detailIds array was accepted")


def check_scanner_self_test() -> None:
    result = subprocess.run(
        [str(ROOT / "scripts/check-release-leaks"), "--self-test"],
        check=False,
        capture_output=True,
        text=True,
        env=test_environment(),
    )
    require(result.returncode == 0, result.stdout + result.stderr)
    require(result.stdout.strip() == "release leak scanner self-test passed", "scanner self-test output mismatch")


def check_private_denylist() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-private-deny-") as temporary:
        base = Path(temporary).resolve()
        release = base / "release"
        release.mkdir()
        (release / ".gitignore").write_text(".env\n", encoding="utf-8")
        private_value = "SyntheticPrivateCodename"
        (release / "README.md").write_text(f"contains {private_value}\n", encoding="utf-8")
        denylist = base / "denylist.json"
        write_denylist(denylist, private_value)
        result = run_scanner(release, denylist)
        require(result.returncode == 1, "private content term was not rejected")
        require("private-term:private-codename" in result.stdout, "private finding id missing")
        require(private_value not in result.stdout + result.stderr, "private value was disclosed")
        private_directory = release / private_value
        private_directory.mkdir()
        (private_directory / "cookies.json").write_text("{}\n", encoding="utf-8")
        path_result = run_scanner(release, denylist)
        require(path_result.returncode == 1, "private path term was not rejected")
        require("<private-path:private-codename>" in path_result.stdout, "private path was not redacted")
        require(private_value not in path_result.stdout + path_result.stderr, "private path value was disclosed")
        empty_private_directory = release / f"{private_value}-empty"
        empty_private_directory.mkdir()
        empty_path_result = run_scanner(release, denylist)
        require(empty_path_result.returncode == 1, "empty private directory was not rejected")
        require(private_value not in empty_path_result.stdout + empty_path_result.stderr, "empty private path was disclosed")
        unreadable = private_directory / "unreadable.txt"
        unreadable.write_text("synthetic\n", encoding="utf-8")
        unreadable.chmod(0)
        try:
            unreadable_result = run_scanner(release, denylist)
        finally:
            unreadable.chmod(0o600)
        require(unreadable_result.returncode == 1, "unreadable private file did not fail closed")
        require("Traceback" not in unreadable_result.stderr, "scanner emitted a traceback")
        require(private_value not in unreadable_result.stdout + unreadable_result.stderr, "scan error disclosed private path")
        normalized_value = "Caf\u00e9Private"
        normalized_denylist = base / "normalized.json"
        write_denylist(normalized_denylist, normalized_value)
        normalized_directory = release / "Cafe\u0301Private"
        normalized_directory.mkdir()
        (normalized_directory / "README.md").write_text("synthetic\n", encoding="utf-8")
        normalized_result = run_scanner(release, normalized_denylist)
        require(normalized_result.returncode == 1, "Unicode-equivalent private path passed")
        require(normalized_value not in normalized_result.stdout + normalized_result.stderr, "normalized private value was disclosed")


def check_private_denylist_location() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-private-location-") as temporary:
        base = Path(temporary).resolve()
        release = base / "release"
        release.mkdir()
        (release / ".gitignore").write_text(".env\n", encoding="utf-8")
        denylist = release / "private-denylist.json"
        write_denylist(denylist, "SyntheticPrivateCodename")
        result = run_scanner(release, denylist)
        require(result.returncode == 1, "in-tree denylist was not rejected")
        require("<private-denylist>" in result.stdout, "in-tree denylist evidence missing")
        required = subprocess.run(
            [
                str(ROOT / "scripts/check-release-leaks"),
                "--root",
                str(release),
                "--require-private-denylist",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=test_environment(),
        )
        require(required.returncode == 1, "required denylist absence passed")
        require("required private denylist is missing" in required.stdout, "missing denylist evidence absent")
        malformed = base / "malformed.json"
        malformed.write_text("{}\n", encoding="utf-8")
        malformed_result = run_scanner(release, malformed)
        require(malformed_result.returncode == 1, "malformed denylist passed")
        require("<private-denylist>: ValueError" in malformed_result.stdout, "malformed denylist evidence absent")
        empty = base / "empty.json"
        empty.write_text(
            json.dumps({"schemaVersion": "plzdo-local.private-denylist.v1", "terms": []}),
            encoding="utf-8",
        )
        empty_result = run_scanner(release, empty)
        require(empty_result.returncode == 1, "empty denylist passed")
        valid = base / "valid.json"
        write_denylist(valid, "SyntheticPrivateCodename")
        linked = base / "linked.json"
        linked.symlink_to(valid)
        linked_result = run_scanner(release, linked)
        require(linked_result.returncode == 1, "symlinked denylist passed")
        require("<private-denylist>: ValueError" in linked_result.stdout, "symlink denylist evidence absent")
        relative = subprocess.run(
            [
                str(ROOT / "scripts/check-release-leaks"),
                "--root",
                str(release),
                "--private-denylist",
                "relative.json",
            ],
            cwd=base,
            check=False,
            capture_output=True,
            text=True,
            env=test_environment(),
        )
        require(relative.returncode == 1, "relative denylist path passed")
        parent = base / "linked-parent"
        real_parent = base / "real-parent"
        real_parent.mkdir()
        parent.symlink_to(real_parent, target_is_directory=True)
        parent_denylist = real_parent / "denylist.json"
        write_denylist(parent_denylist, "SyntheticPrivateCodename")
        parent_link_result = run_scanner(release, parent / "denylist.json")
        require(parent_link_result.returncode == 1, "denylist below symlinked parent passed")
        if Path("/tmp").is_symlink():
            with tempfile.TemporaryDirectory(prefix="plzdo-root-alias-", dir="/tmp") as alias_temporary:
                alias_denylist = Path(alias_temporary) / "denylist.json"
                write_denylist(alias_denylist, "SyntheticPrivateCodename")
                alias_result = run_scanner(release, alias_denylist)
                require(alias_result.returncode == 1, "denylist below root-level symlink passed")


def check_hostile_python_startup() -> None:
    if os.environ.get("PLZDO_HOSTILE_BOOTSTRAP_CHILD") == "1":
        return
    with tempfile.TemporaryDirectory(prefix="plzdo-python-startup-") as temporary:
        base = Path(temporary).resolve()
        userbase = base / "userbase"
        marker = base / "sitecustomize-loaded"
        source = f'from pathlib import Path\nPath({str(marker)!r}).write_text("loaded")\n'
        for minor in range(9, 15):
            site_packages = userbase / "lib" / f"python3.{minor}" / "site-packages"
            site_packages.mkdir(parents=True)
            (site_packages / "sitecustomize.py").write_text(source, encoding="utf-8")
        hostile = {"PYTHONUSERBASE": str(userbase)}
        wrapper = run_wrapper("version", "--json", cwd=base, extra_env=hostile)
        require(wrapper.returncode == 0, wrapper.stdout + wrapper.stderr)
        scanner_environment = test_environment()
        scanner_environment.update(hostile)
        scanner = subprocess.run(
            [str(ROOT / "scripts/check-release-leaks"), "--self-test"],
            cwd=base,
            check=False,
            capture_output=True,
            text=True,
            env=scanner_environment,
        )
        require(scanner.returncode == 0, scanner.stdout + scanner.stderr)
        nested_environment = test_environment()
        nested_environment.update(hostile)
        nested_environment["PLZDO_HOSTILE_BOOTSTRAP_CHILD"] = "1"
        nested = subprocess.run(
            [str(ROOT / "scripts/verify")],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=nested_environment,
        )
        require(nested.returncode == 0, nested.stdout + nested.stderr)
        require(not marker.exists(), "Python user startup code executed")


def write_denylist(path: Path, value: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "plzdo-local.private-denylist.v1",
                "terms": [{"id": "private-codename", "value": value, "caseSensitive": False}],
            }
        ),
        encoding="utf-8",
    )


def run_scanner(release: Path, denylist: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(ROOT / "scripts/check-release-leaks"),
            "--root",
            str(release),
            "--private-denylist",
            str(denylist),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=test_environment(),
    )


def run_cli(*args: str, extra_env: Optional[dict[str, str]] = None) -> subprocess.CompletedProcess[str]:
    environment = test_environment()
    environment.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-B", "-I", str(ROOT / "bin/plzdo_entry.py"), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def run_wrapper(
    *args: str,
    cwd: Path,
    extra_env: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    environment = test_environment()
    environment.update(extra_env or {})
    return subprocess.run(
        [str(ROOT / "bin/plzdo"), *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_environment() -> dict[str, str]:
    environment = {
        "HOME": os.environ.get("HOME", "/nonexistent"),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }
    if "PLZDO_HOME" in os.environ:
        environment["PLZDO_HOME"] = os.environ["PLZDO_HOME"]
    return environment


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
