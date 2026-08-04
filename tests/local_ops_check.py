from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
import sys

sys.path.insert(0, str(ROOT))

import plzdo_local.monitor as monitor_module
from plzdo_local.cli import main as cli_main
from plzdo_local.monitor import MonitorError, monitor_snapshot, repo_preflight
from plzdo_local.review_bundle import (
    ReviewBundleError,
    build_manifest,
    import_response,
    prepare_bundle,
    sanitize_review_text,
    sensitive_path_reason,
    validate_bundle,
    validate_import,
)


def main() -> int:
    checks = [
        ("review preparation reads only explicit files and sanitizes before persistence", check_review_prepare),
        ("review sanitization covers high-confidence secrets and sensitive paths", check_review_sensitive_shapes),
        ("review import remains advisory and contains no provider send path", check_review_import),
        ("monitor and preflight observe without mutating targets", check_monitor_read_only),
        ("monitor rejects traversal faults and detects credential filenames", check_monitor_fail_closed),
        ("malformed review CLI inputs exit two without traceback", check_review_cli_errors),
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
    print(f"local operations check passed: {len(checks)} checks")
    return 0


def check_review_prepare() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-review-") as temporary:
        root = Path(temporary).resolve() / "project"
        root.mkdir()
        visible = root / "visible.txt"
        hidden = root / "not-listed.txt"
        credential = "sk" + "-" + "abcdefghijklmnop"
        synthetic_email = "person" + "@" + "example.invalid"
        synthetic_home = "/" + "Users/" + "example/private"
        visible.write_text(
            "Contact " + synthetic_email + "\nPath " + synthetic_home + "\nToken " + credential + "\n",
            encoding="utf-8",
        )
        hidden.write_text("must not be included\n", encoding="utf-8")
        manifest = build_manifest(purpose="Review the explicit fixture.", files=["visible.txt"])
        bundle = prepare_bundle(root, manifest, created_at="2026-08-05T09:00:00Z")
        validate_bundle(bundle)
        require(set(bundle["files"]) == {"visible.txt"}, "unlisted file entered bundle")
        require("must not be included" not in json.dumps(bundle), "unlisted bytes entered bundle")
        require(credential not in bundle["files"]["visible.txt"], "credential was not redacted")
        require("/Users/" not in bundle["files"]["visible.txt"], "private path was not redacted")
        require(bundle["egressPerformed"] is False, "prepare claimed egress")
        require(bundle["manifest"][0]["sourceSha256"] == hashlib.sha256(visible.read_bytes()).hexdigest(), "source digest")

        outside = root.parent / "outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        link = root / "link.txt"
        link.symlink_to(outside)
        linked = build_manifest(purpose="Reject a symlink.", files=["link.txt"])
        expect_error(ReviewBundleError, lambda: prepare_bundle(root, linked, created_at="2026-08-05T09:00:00Z"))


def check_review_sensitive_shapes() -> None:
    private_key = (
        "-----BEGIN "
        + "PRIVATE KEY-----\n"
        + "c3ludGhldGljLWtleS1ieXRlcw==\n"
        + "-----END "
        + "PRIVATE KEY-----"
    )
    jwt = "eyJhbGciOiJIUzI1NiJ9." + ("a" * 16) + "." + ("b" * 16)
    short_jwt = "e" + "30.e" + "30.e" + "30"
    basic_value = "dXN" + "lcjpwYXNz"
    bearer_value = "synthetic" + "-bearer-value"
    credentials = [
        "sk" + "-" + ("a" * 20),
        "ghp" + "_" + ("b" * 24),
        "AK" + "IA" + ("C" * 16),
        "AI" + "za" + ("d" * 35),
        "xox" + "b-" + ("1" * 12),
        "sk" + "_live_" + ("e" * 20),
        "npm" + "_" + ("f" * 36),
        "glpat" + "-" + ("g" * 20),
        "hf" + "_" + ("h" * 20),
    ]
    assignment_value = "assignment-secret-value"
    assignment_values = [
        "js-object-value",
        "json-value",
        "header-value",
        "cookie-value",
        "token-value",
    ]
    assignment_sources = [
        "const config = {\"api" + "Key\": \"" + assignment_values[0] + "\"};",
        "{\"nested\":{\"client" + "Secret\":\"" + assignment_values[1] + "\"}}",
        "request.headers = {\"Authori" + "zation\": \"Basic " + assignment_values[2] + "\"};",
        "curl -H 'Coo" + "kie: session=" + assignment_values[3] + "' local.invalid",
        "window.settings.refresh" + "Token = `" + assignment_values[4] + "`;",
        "headers['Authori" + "zation'] = 'Basic " + basic_value + "';",
        "client.setRequestHeader('Authori"
        + "zation', 'Bearer "
        + bearer_value
        + "');",
        "scheme fixture: Basic " + basic_value,
    ]
    source = (
        private_key
        + "\nOPENAI_"
        + "API_KEY="
        + assignment_value
        + "\nJWT "
        + jwt
        + "\nSHORT JWT "
        + short_jwt
        + "\nTOKENS "
        + " ".join(credentials)
        + "\n"
        + "\n".join(assignment_sources)
        + "\n"
    )
    sanitized, count = sanitize_review_text(source)
    require(count >= len(credentials) + len(assignment_values) + 7, "sensitive-shape redaction count")
    for sensitive in [private_key, jwt, short_jwt, basic_value, bearer_value, assignment_value] + credentials + assignment_values:
        require(sensitive not in sanitized, "sensitive value survived sanitization")
    require("[REDACTED-PRIVATE-KEY]" in sanitized, "private key block was not redacted")
    expect_error(
        ReviewBundleError,
        lambda: sanitize_review_text("-----BEGIN " + "PRIVATE KEY-----\ntruncated"),
    )

    sensitive_paths = (
        ".env",
        ".env.local",
        "fixtures/.env.local/value",
        "config/.npmrc",
        "keys/id_rsa",
        "keys/id_" + "ed25519.backup",
        "credentials.json",
        ".ssh/config",
        "certificates/private.pem",
        ".git" + "-credentials",
        ".git" + "-credentials.bak",
        "kube" + "config",
        "kube" + "config.old",
        ".net" + "rc",
        ".net" + "rc~",
        ".py" + "pirc",
        ".py" + "pirc.orig",
        "config/service-" + "account.json",
        "config/service_" + "account.json.backup",
        "config/application_" + "default_credentials.json",
        "reports/person" + "@" + "example.invalid.txt",
        "bad" + chr(10) + "name.txt",
        "cache/" + credentials[0] + ".txt",
        "cache/" + short_jwt + ".txt",
        "exports/" + "token=" + assignment_value,
    )
    for path in sensitive_paths:
        require(sensitive_path_reason(path) is not None, "shared classifier missed sensitive path")
        expect_error(
            ReviewBundleError,
            lambda value=path: build_manifest(purpose="Review a fixture.", files=[value]),
        )

    with tempfile.TemporaryDirectory(prefix="plzdo-review-sensitive-") as temporary:
        root = Path(temporary).resolve()
        (root / "input.txt").write_text(source, encoding="utf-8")
        bundle = prepare_bundle(
            root,
            build_manifest(purpose="Review a synthetic fixture.", files=["input.txt"]),
            created_at="2026-08-05T09:05:00Z",
        )
        validate_bundle(bundle)
        forged = copy.deepcopy(bundle)
        forged["files"]["input.txt"] = "PASS" + "WORD=" + assignment_value + "\n"
        encoded = forged["files"]["input.txt"].encode("utf-8")
        forged["manifest"][0]["sanitizedBytes"] = len(encoded)
        forged["manifest"][0]["sanitizedSha256"] = hashlib.sha256(encoded).hexdigest()
        expect_error(ValueError, lambda: validate_bundle(forged))


def check_review_import() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-review-import-") as temporary:
        root = Path(temporary).resolve()
        (root / "input.txt").write_text("bounded evidence\n", encoding="utf-8")
        manifest = build_manifest(purpose="Review bounded evidence.", files=["input.txt"])
        bundle = prepare_bundle(root, manifest, created_at="2026-08-05T09:10:00Z")
        response = ("Advisory only. Contact reviewer" + "@" + "example.invalid.").encode("utf-8")
        imported = import_response(bundle, response, imported_at="2026-08-05T09:11:00Z")
        validate_import(imported)
        require(imported["sourceOfTruth"] is False, "review became source of truth")
        require(imported["notInstructions"] is True, "review became instructions")
        require(imported["toolAuthority"] is False, "review gained tool authority")
        require("example.invalid" not in imported["response"], "response email was not redacted")
        forged = copy.deepcopy(imported)
        forged["toolAuthority"] = True
        expect_error(ReviewBundleError, lambda: validate_import(forged))

    cli_source = (ROOT / "plzdo_local/cli.py").read_text(encoding="utf-8")
    local_ops_source = (ROOT / "plzdo_local/local_ops_cli.py").read_text(encoding="utf-8")
    require("review send" not in cli_source + local_ops_source, "provider send command exists")
    require("provider" not in local_ops_source.lower(), "provider adapter entered local operations")


def check_monitor_read_only() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-monitor-") as temporary:
        root = Path(temporary).resolve() / "project"
        root.mkdir()
        (root / "AGENTS.md").write_text("# Agent\n", encoding="utf-8")
        (root / "CHECKS.md").write_text("# Checks\n", encoding="utf-8")
        tasks = root / "TASKS"
        tasks.mkdir()
        (tasks / "current.md").write_text("# Task\n", encoding="utf-8")
        git_metadata = root / ".git"
        git_metadata.mkdir()
        (git_metadata / "volatile").write_text("ignored repository metadata\n", encoding="utf-8")
        before = tree_digest(root)
        preflight = repo_preflight(root)
        snapshot = monitor_snapshot(
            {"id": "fixture-project", "path": str(root)},
            captured_at="2026-08-05T09:20:00Z",
        )
        after = tree_digest(root)
        require(before == after, "monitor changed target bytes")
        require(preflight["targetMutated"] is False, "preflight claimed mutation")
        require(preflight["gitMetadataPresent"] is True, "git metadata presence was not reported")
        require(preflight["fileCount"] == 3, "git metadata entered project file counts")
        require(snapshot["recommendationOnly"] is True, "monitor is not recommendation-only")
        require(str(root) not in json.dumps(snapshot), "monitor persisted a raw local path")


def check_monitor_fail_closed() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-monitor-risky-") as temporary:
        root = Path(temporary).resolve()
        risky_names = (
            ".env.local",
            ".env-production",
            ".envrc",
            ".npmrc",
            "id_rsa",
            "id_" + "ed25519.old",
            "credentials.json",
            ".git" + "-credentials.bak",
            "kube" + "config",
            ".net" + "rc.backup",
            ".py" + "pirc~",
            "service-" + "account.json",
            "application_" + "default_credentials.json.old",
        )
        for name in risky_names:
            (root / name).write_text("synthetic fixture\n", encoding="utf-8")
        observed = repo_preflight(root)
        require(observed["riskyNameCount"] == len(risky_names), "risky filename detection")
        require(
            monitor_module.sensitive_path_reason is sensitive_path_reason,
            "monitor does not use the shared sensitive-path classifier",
        )

        with mock.patch.object(monitor_module.os, "scandir", side_effect=PermissionError("injected traversal denial")):
            expect_error(MonitorError, lambda: repo_preflight(root))

        consumed: list[str] = []
        with mock.patch.object(monitor_module, "MAX_ENTRIES", 2), mock.patch.object(
            monitor_module,
            "_TEST_SCANDIR_OBSERVER",
            consumed.append,
        ):
            expect_error(MonitorError, lambda: repo_preflight(root))
        require(len(consumed) == 3, "monitor traversal consumed beyond limit plus one")


def check_review_cli_errors() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-review-cli-") as temporary:
        base = Path(temporary).resolve()
        project = base / "project"
        project.mkdir()
        (project / "input.txt").write_text("bounded fixture\n", encoding="utf-8")
        valid_manifest = base / "manifest.json"
        valid_manifest.write_text(
            json.dumps(build_manifest(purpose="Review a fixture.", files=["input.txt"])),
            encoding="utf-8",
        )
        malformed = base / "malformed.json"
        malformed.write_text("{not json", encoding="utf-8")
        wrong_shape = base / "wrong-shape.json"
        wrong_shape.write_text("[]\n", encoding="utf-8")

        commands = (
            ["review", "prepare", "--manifest", str(malformed), "--root", str(project), "--output", "bundle"],
            ["review", "prepare", "--manifest", str(wrong_shape), "--root", str(project), "--output", "bundle"],
            ["review", "prepare", "--manifest", str(valid_manifest), "--root", str(project), "--output", "INVALID"],
            ["review", "validate", str(wrong_shape)],
            ["review", "import", "--bundle", str(wrong_shape), "--response", str(project / "input.txt")],
        )
        with mock.patch.dict(os.environ, {"PLZDO_HOME": str(base / "state")}, clear=False):
            for command in commands:
                stdout = StringIO()
                stderr = StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    result = cli_main(command)
                require(result == 2, "malformed review command did not return exit 2")
                require("Traceback" not in stderr.getvalue(), "malformed review command emitted traceback")
                require(stderr.getvalue().startswith("plzdo: "), "malformed review command lacked handled error")


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative + b"\0")
        if path.is_symlink():
            digest.update(b"link:" + str(path.readlink()).encode("utf-8"))
        elif path.is_file():
            digest.update(path.read_bytes())
        else:
            digest.update(b"dir")
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def expect_error(error_type: type[BaseException], function: object) -> None:
    try:
        function()  # type: ignore[operator]
    except error_type:
        return
    raise AssertionError(f"expected {error_type.__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
