from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Dict, Optional, Type


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_publication
import check_release_leaks
import check_acceptance
import export_worktree
import release_manifest


GIT = Path("/usr/bin/git")
NOREPLY = "169621860+fixture@users.noreply.github.com"
PRIVATE_TERM = "PrivateAliasFixture"


def main() -> int:
    checks = [
        ("release manifest is deterministic and excludes only root control files", check_release_manifest),
        ("release manifest rejects nested metadata caches temporary files and unsafe paths", check_manifest_negatives),
        ("worktree export excludes only root Git metadata", check_worktree_export),
        ("publication audit reads exact objects despite archive attributes", check_exact_object_audit),
        ("publication audit rejects metadata collisions and non-file tree entries", check_metadata_collision_and_symlink),
        ("publication audit neutralizes injected Git environment", check_git_environment_isolation),
        ("publication audit scans tags refs and full metadata identities", check_tag_ref_and_email_audit),
        ("publication audit detects ref drift before success", check_ref_drift),
        ("release scanner covers path and credential classes without echoing private values", check_scanner_coverage),
        ("publication wrapper starts under isolated Python", check_publication_isolated_bootstrap),
        ("acceptance binds a clean tree to one full commit", check_acceptance_binding),
        ("local acceptance path binds manifest PR evidence and documented writes", check_local_acceptance_path),
        ("release ceremony stays in maintainer documentation", check_release_document_separation),
        ("public usage has no optional prefix installer", check_installer_removed),
    ]
    failures = []  # type: list[str]
    for label, check in checks:
        try:
            check()
        except Exception as exc:
            failures.append(f"{label}: {type(exc).__name__}: {exc}")
    if failures:
        for failure in failures:
            print("FAIL " + failure)
        return 1
    print(f"release integration check passed: {len(checks)} checks")
    return 0


def check_release_manifest() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-manifest-valid-") as temporary:
        root = Path(temporary).resolve() / "release"
        (root / ".git").mkdir(parents=True)
        (root / "nested").mkdir()
        (root / "SHA256SUMS").write_text("stale\n", encoding="utf-8")
        (root / "nested/file.txt").write_text("fixture\n", encoding="utf-8")
        first = release_manifest.render_manifest(root)
        second = release_manifest.render_manifest(root)
        require(first == second, "release manifest changed without tree mutation")
        text = first.decode("utf-8")
        require("  SHA256SUMS\n" not in text, "release manifest includes itself")
        require("/.git/" not in text and "  .git" not in text, "root Git metadata entered manifest")
        require("  nested/file.txt\n" in text, "regular release file missing")


def check_manifest_negatives() -> None:
    def rejected(mutator: Callable[[Path], None]) -> None:
        with tempfile.TemporaryDirectory(prefix="plzdo-manifest-negative-") as temporary:
            root = Path(temporary).resolve() / "release"
            root.mkdir()
            (root / "safe.txt").write_text("safe\n", encoding="utf-8")
            mutator(root)
            expect_error(release_manifest.ManifestError, lambda: release_manifest.render_manifest(root))

    rejected(lambda root: (root / "nested/.git").mkdir(parents=True))
    rejected(lambda root: (root / "nested").mkdir() or (root / "nested/.git").write_text("gitdir: elsewhere\n", encoding="utf-8"))
    rejected(lambda root: (root / "__pycache__").mkdir())
    rejected(lambda root: (root / "cache").mkdir())
    rejected(lambda root: (root / "artifact.pyc").write_bytes(b"fixture"))
    rejected(lambda root: (root / "artifact.tmp").write_text("fixture\n", encoding="utf-8"))
    rejected(lambda root: (root / "bad\nname").write_text("fixture\n", encoding="utf-8"))
    rejected(lambda root: (root / "link").symlink_to("safe.txt"))
    rejected(lambda root: (root / "SHA256SUMS").symlink_to("safe.txt"))

    def fifo(root: Path) -> None:
        os.mkfifo(root / "fixture-pipe")

    rejected(fifo)


def check_worktree_export() -> None:
    with tempfile.TemporaryDirectory(prefix="plzdo-export-test-") as temporary:
        base = Path(temporary).resolve()
        source = base / "source"
        destination = base / "destination"
        (source / ".git").mkdir(parents=True)
        (source / "nested/.git").mkdir(parents=True)
        (source / "nested/file.txt").write_text("fixture\n", encoding="utf-8")
        (source / "link").symlink_to("nested/file.txt")
        export_worktree.export_worktree(source, destination)
        require(not (destination / ".git").exists(), "root Git metadata entered the export")
        require((destination / "nested/.git").is_dir(), "nested Git metadata was hidden")
        require((destination / "link").is_symlink(), "release symlink was silently dereferenced")


def check_exact_object_audit() -> None:
    with publication_fixture() as fixture:
        repository, base_commit, denylist = fixture
        check_publication.scan_publication(repository, denylist, expected_baseline=base_commit)
        (repository / ".gitattributes").write_text(
            "hidden.txt export-ignore\nmetadata.txt export-subst\n",
            encoding="utf-8",
        )
        (repository / "hidden.txt").write_text(PRIVATE_TERM + "\n", encoding="utf-8")
        (repository / "metadata.txt").write_text("$Format:%ae$\n", encoding="utf-8")
        commit(repository, "archive attributes cannot hide this blob")
        expect_publication("leak-private-term", lambda: check_publication.scan_publication(repository, denylist, expected_baseline=base_commit))

    with publication_fixture() as fixture:
        repository, base_commit, denylist = fixture
        (repository / ".gitattributes").write_text("metadata.txt export-subst\n", encoding="utf-8")
        (repository / "metadata.txt").write_text("$Format:%ae$\n", encoding="utf-8")
        commit(repository, "personal metadata fixture", email="person@" + "invalid.example")
        expect_publication(
            "commit-author-email-not-noreply",
            lambda: check_publication.scan_publication(repository, denylist, expected_baseline=base_commit),
        )

    with publication_fixture() as fixture:
        repository, base_commit, denylist = fixture
        git(repository, "commit", "--allow-empty", "-m", PRIVATE_TERM)
        expect_publication(
            "leak-private-term",
            lambda: check_publication.scan_publication(repository, denylist, expected_baseline=base_commit),
        )

    with publication_fixture() as fixture:
        repository, base_commit, denylist = fixture
        git(repository, "checkout", "-b", "hidden-history")
        (repository / "hidden-history.txt").write_text("fixture\n", encoding="utf-8")
        commit(repository, "hidden history fixture")
        git(repository, "checkout", "main")
        expect_publication(
            "non-head-reachable-history",
            lambda: check_publication.scan_publication(repository, denylist, expected_baseline=base_commit),
        )


def check_metadata_collision_and_symlink() -> None:
    with publication_fixture() as fixture:
        repository, base_commit, denylist = fixture
        outside = repository.parent / "outside.txt"
        outside.write_text("operator-owned\n", encoding="utf-8")
        (repository / ".release-commit-metadata.txt").symlink_to(outside)
        commit(repository, "metadata collision fixture")
        expect_publication("reserved-tree-path", lambda: check_publication.scan_publication(repository, denylist, expected_baseline=base_commit))
        require(outside.read_text(encoding="utf-8") == "operator-owned\n", "metadata audit changed external bytes")

    with publication_fixture() as fixture:
        repository, base_commit, denylist = fixture
        (repository / "release-link").symlink_to("README.md")
        commit(repository, "symlink fixture")
        expect_publication("symlink-tree-entry", lambda: check_publication.scan_publication(repository, denylist, expected_baseline=base_commit))

    with publication_fixture() as fixture:
        repository, base_commit, denylist = fixture
        git(repository, "update-index", "--add", "--cacheinfo", f"160000,{base_commit},vendor")
        git(repository, "commit", "-m", "gitlink fixture")
        expect_publication("gitlink-tree-entry", lambda: check_publication.scan_publication(repository, denylist, expected_baseline=base_commit))


def check_git_environment_isolation() -> None:
    with publication_fixture() as fixture, publication_fixture() as hostile_fixture:
        repository, base_commit, denylist = fixture
        hostile, _hostile_base, _hostile_denylist = hostile_fixture
        previous = {name: os.environ.get(name) for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_CONFIG_GLOBAL")}
        os.environ["GIT_DIR"] = str(hostile / ".git")
        os.environ["GIT_WORK_TREE"] = str(hostile)
        os.environ["GIT_CONFIG_GLOBAL"] = str(hostile / "hostile-config")
        try:
            result = check_publication.scan_publication(repository, denylist, expected_baseline=base_commit)
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        require(result.commits == 1, "injected Git environment selected a different repository")
        require(result.refs == 1, "injected Git environment changed the audited refs")


def check_tag_ref_and_email_audit() -> None:
    with publication_fixture() as fixture:
        repository, base_commit, denylist = fixture
        git(repository, "branch", PRIVATE_TERM)
        expect_publication("leak-private-term", lambda: check_publication.scan_publication(repository, denylist, expected_baseline=base_commit))

    with publication_fixture() as fixture:
        repository, base_commit, denylist = fixture
        git(
            repository,
            "tag",
            "-a",
            "v-fixture",
            "-m",
            "annotated fixture",
            identity_email="person@" + "invalid.example",
        )
        expect_publication("tagger-email-is-not-noreply", lambda: check_publication.scan_publication(repository, denylist, expected_baseline=base_commit))

    with publication_fixture() as fixture:
        repository, base_commit, denylist = fixture
        git(repository, "tag", "-a", "v-fixture", "-m", PRIVATE_TERM)
        expect_publication("leak-private-term", lambda: check_publication.scan_publication(repository, denylist, expected_baseline=base_commit))


def check_ref_drift() -> None:
    with publication_fixture() as fixture:
        repository, base_commit, denylist = fixture
        callback_ran = []  # type: list[bool]

        def drift() -> None:
            callback_ran.append(True)
            git(repository, "branch", "late-audit-ref")

        expect_publication(
            "repository-ref-drift",
            lambda: check_publication.scan_publication(
                repository,
                denylist,
                expected_baseline=base_commit,
                before_final_check=drift,
            ),
        )
        require(callback_ran == [True], "ref drift callback did not run exactly once")


def check_scanner_coverage() -> None:
    output = io.StringIO()
    errors = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        result = check_release_leaks.run_self_test()
    require(result == 0, "release scanner self-test failed")
    rendered = output.getvalue() + errors.getvalue()
    require(PRIVATE_TERM not in rendered, "release scanner printed a private denylist value")

    with tempfile.TemporaryDirectory(prefix="plzdo-scanner-private-") as temporary:
        base = Path(temporary).resolve()
        release = base / "release"
        release.mkdir()
        (release / ".gitignore").write_text(".env\n", encoding="utf-8")
        denylist = write_denylist(base)
        terms = check_release_leaks.load_private_denylist(denylist, release)
        (release / "source.txt").write_text(PRIVATE_TERM + "\n", encoding="utf-8")
        findings, _warnings = check_release_leaks.scan_root(release, terms)
        evidence = "\n".join(f"{finding.path}:{finding.rule}" for finding in findings)
        require("private-term:private-alias-fixture" in evidence, "private term was not detected")
        require(PRIVATE_TERM not in evidence, "private value entered scanner evidence")


def check_publication_isolated_bootstrap() -> None:
    completed = subprocess.run(
        [str(ROOT / "scripts/check-publication")],
        env={"HOME": "/dev/null", "LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    require(completed.returncode == 1, "publication wrapper did not reject missing arguments")
    require(
        completed.stderr.endswith(b"FAIL publication-history:usage---private-denylist-absolute-path\n")
        and b"Traceback" not in completed.stderr
        and b"ModuleNotFoundError" not in completed.stderr,
        "publication wrapper did not reach the isolated Python entry point",
    )


def check_acceptance_binding() -> None:
    with publication_fixture() as fixture:
        repository, base_commit, _denylist = fixture
        require(check_acceptance.check_acceptance(repository, base_commit) == base_commit, "clean acceptance")
        expect_error(
            check_acceptance.AcceptanceError,
            lambda: check_acceptance.check_acceptance(repository, "0" * len(base_commit)),
        )

    with publication_fixture() as fixture:
        repository, base_commit, _denylist = fixture
        (repository / "README.md").write_text("unstaged fixture\n", encoding="utf-8")
        expect_error(
            check_acceptance.AcceptanceError,
            lambda: check_acceptance.check_acceptance(repository, base_commit),
        )

    with publication_fixture() as fixture:
        repository, base_commit, _denylist = fixture
        (repository / "README.md").write_text("staged fixture\n", encoding="utf-8")
        git(repository, "add", "README.md")
        expect_error(
            check_acceptance.AcceptanceError,
            lambda: check_acceptance.check_acceptance(repository, base_commit),
        )

    with publication_fixture() as fixture:
        repository, base_commit, _denylist = fixture
        (repository / "untracked.txt").write_text("untracked fixture\n", encoding="utf-8")
        expect_error(
            check_acceptance.AcceptanceError,
            lambda: check_acceptance.check_acceptance(repository, base_commit),
        )


def check_local_acceptance_path() -> None:
    verify = (ROOT / "scripts/verify").read_text(encoding="utf-8")
    require(
        '"$root/scripts/release-manifest" --check' in verify,
        "integrated gate does not verify the frozen manifest",
    )
    require("--acceptance" in verify, "integrated gate has no exact-commit acceptance mode")
    require(verify.count("scripts/check_acceptance.py") == 3, "acceptance is not checked before export and after verification")

    workflow_root = ROOT / ".github/workflows"
    require(
        not workflow_root.exists() or not any(path.is_file() for path in workflow_root.rglob("*")),
        "hosted workflow is bundled despite local-only acceptance",
    )

    pull_request = (ROOT / ".github/PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
    for token in ("./scripts/verify", "Exact commit", "Skipped checks", "Residual risk"):
        require(token in pull_request, f"pull request template missing local evidence field: {token}")

    restricted = " ".join(
        (ROOT / "docs/restricted-environment.md").read_text(encoding="utf-8").split()
    )
    for token in ("no package download", "approved remote", "local acceptance contract"):
        require(token in restricted, f"restricted setup contract missing: {token}")

    command_reference = (ROOT / "docs/command-reference.md").read_text(encoding="utf-8")
    require(
        "project register` and `project archive` update the local registry" in command_reference,
        "project registry writes are not documented",
    )


def check_release_document_separation() -> None:
    checks = (ROOT / "CHECKS.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    releasing = (ROOT / "docs/releasing.md").read_text(encoding="utf-8")
    task = (ROOT / "TASKS/current.md").read_text(encoding="utf-8")
    for token in ("--private-denylist", "five complete integrated-gate runs", "explicit operator authorization"):
        require(token in releasing, f"maintainer release procedure missing: {token}")
        require(token not in checks, f"maintainer ceremony leaked into contributor checks: {token}")
        require(token not in contributing, f"maintainer ceremony leaked into contributing guide: {token}")
    require("scripts/export_worktree.py" in releasing, "release privacy gate does not export a Git-free tree")
    require('--root "$export_root"' in releasing, "release privacy gate does not scan the exported tree")
    require("--root ." not in releasing, "release privacy gate still scans the Git checkout directly")
    require("release candidate" not in task, "current task still claims a released version is a candidate")
    require("Current release:" not in task and "v0.2.0" not in task, "current task duplicates VERSION")
    require("docs/releasing.md" in checks and "docs/releasing.md" in task, "release documentation pointer missing")
    require(
        "hosted ci" in checks.casefold() and "hosted ci" in contributing.casefold(),
        "local acceptance boundary is not documented",
    )


def check_installer_removed() -> None:
    require(not (ROOT / "scripts/install-local").exists(), "optional prefix installer wrapper still exists")
    require(not (ROOT / "scripts/install_local.py").exists(), "optional prefix installer module still exists")
    for path in (ROOT / "docs/portability.md", ROOT / "CONTRIBUTING.md", ROOT / "SECURITY.md"):
        text = path.read_text(encoding="utf-8")
        require("scripts/install-local" not in text and "install_local.py" not in text, "owned docs reference installer")


class publication_fixture:
    def __init__(self) -> None:
        self.temporary: Optional[tempfile.TemporaryDirectory[str]] = None

    def __enter__(self) -> tuple[Path, str, Path]:
        self.temporary = tempfile.TemporaryDirectory(prefix="plzdo-publication-fixture-")
        base = Path(self.temporary.name).resolve()
        repository = base / "repository"
        repository.mkdir()
        git(repository, "init", "-b", "main")
        (repository / ".gitignore").write_text(".env\n", encoding="utf-8")
        (repository / "README.md").write_text("# Fixture\n", encoding="utf-8")
        commit(repository, "initial public fixture")
        base_commit = git(repository, "rev-parse", "HEAD").strip()
        denylist = write_denylist(base)
        return repository, base_commit, denylist

    def __exit__(self, *_args: object) -> None:
        if self.temporary is not None:
            self.temporary.cleanup()


def write_denylist(base: Path) -> Path:
    path = base / "private-denylist.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": check_release_leaks.SCHEMA_VERSION,
                "terms": [
                    {"id": "private-alias-fixture", "value": PRIVATE_TERM, "caseSensitive": False}
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def commit(repository: Path, message: str, *, email: str = NOREPLY) -> None:
    git(repository, "add", "-A")
    git(repository, "commit", "-m", message, identity_email=email)


def git(
    repository: Path,
    *arguments: str,
    identity_email: str = NOREPLY,
) -> str:
    environment: Dict[str, str] = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(repository.parent / "fixture-home"),
        "LC_ALL": "C",
        "LANG": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_AUTHOR_NAME": "Fixture Author",
        "GIT_AUTHOR_EMAIL": identity_email,
        "GIT_COMMITTER_NAME": "Fixture Committer",
        "GIT_COMMITTER_EMAIL": identity_email,
        "GIT_TERMINAL_PROMPT": "0",
    }
    completed = subprocess.run(
        [str(GIT), "-C", str(repository)] + list(arguments),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    if completed.returncode != 0:
        raise AssertionError(f"fixture Git command failed: {arguments[0]}")
    return completed.stdout.decode("utf-8")


def expect_publication(code: str, function: Callable[[], object]) -> None:
    try:
        function()
    except check_publication.PublicationError as exc:
        require(exc.code.startswith(code), f"unexpected publication error: {exc.code}")
        return
    raise AssertionError(f"expected publication failure: {code}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def expect_error(error_type: Type[BaseException], function: Callable[[], object]) -> None:
    try:
        function()
    except error_type:
        return
    raise AssertionError(f"expected {error_type.__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
