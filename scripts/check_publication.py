from __future__ import annotations

import os
import re
import selectors
import stat
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import check_release_leaks


PUBLIC_BASE_COMMIT = "60766096fb9ae8114c7891f0beca35872072954b"
GIT = Path("/usr/bin/git")
MAX_COMMITS = 512
MAX_REFS = 4096
MAX_REF_BYTES = 1024 * 1024
MAX_CONTROL_ENTRIES = 200_000
MAX_TREE_ENTRIES = 500_000
MAX_TREE_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_TOTAL_TREE_OUTPUT_BYTES = 256 * 1024 * 1024
MAX_BLOBS = 100_000
MAX_BLOB_BYTES = 4 * 1024 * 1024
MAX_UNIQUE_BLOB_BYTES = 256 * 1024 * 1024
MAX_LOGICAL_BLOB_BYTES = 2 * 1024 * 1024 * 1024
MAX_COMMIT_BYTES = 1024 * 1024
MAX_TOTAL_COMMIT_BYTES = 16 * 1024 * 1024
MAX_TAGS = 4096
MAX_TAG_BYTES = 1024 * 1024
MAX_TOTAL_TAG_BYTES = 16 * 1024 * 1024
MAX_STATUS_BYTES = 4 * 1024 * 1024
GIT_TIMEOUT_SECONDS = 30.0
OID = re.compile(r"[0-9a-f]{40}")
NOREPLY_EMAIL = re.compile(r"(?:[0-9]+\+)?[A-Za-z0-9_.-]+@users\.noreply\.github\.com", re.IGNORECASE)
ALLOWED_FILE_MODES = {"100644", "100755"}
RESERVED_TREE_NAMES = {".git", ".release-commit-metadata.txt"}


class PublicationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RefState:
    name: str
    oid: str
    object_type: str


@dataclass(frozen=True)
class RepositorySnapshot:
    head: str
    symbolic_head: str
    refs: tuple[RefState, ...]
    git_identity: tuple[int, int]


@dataclass
class ScanState:
    commit_count: int = 0
    commit_bytes: int = 0
    tag_count: int = 0
    tag_bytes: int = 0
    tree_entries: int = 0
    tree_output_bytes: int = 0
    logical_blob_bytes: int = 0
    unique_blob_bytes: int = 0


@dataclass(frozen=True)
class PublicationReport:
    commits: int
    refs: int
    tags: int
    tree_entries: int
    unique_blobs: int
    unique_blob_bytes: int


class GitRepository:
    def __init__(self, root: Path, git_dir: Path):
        self.root = root
        self.git_dir = git_dir

    @classmethod
    def bind(cls, candidate: Path) -> "GitRepository":
        try:
            root = candidate.expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise PublicationError("root-unavailable") from exc
        if not root.is_dir():
            raise PublicationError("root-is-not-directory")
        git_dir = root / ".git"
        try:
            metadata = git_dir.lstat()
        except OSError as exc:
            raise PublicationError("root-git-directory-missing") from exc
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise PublicationError("root-git-directory-invalid")
        try:
            if git_dir.resolve(strict=True) != git_dir:
                raise PublicationError("root-git-directory-redirected")
        except (OSError, RuntimeError) as exc:
            raise PublicationError("root-git-directory-invalid") from exc
        _validate_git_control_directory(git_dir)
        repository = cls(root, git_dir)
        top_level = repository.run(("rev-parse", "--show-toplevel"), maximum=4096).rstrip(b"\n")
        common_dir = repository.run(("rev-parse", "--git-common-dir"), maximum=4096).rstrip(b"\n")
        if _decode_git_path(top_level) != str(root):
            raise PublicationError("worktree-root-mismatch")
        if _decode_git_path(common_dir) != str(git_dir):
            raise PublicationError("git-common-directory-mismatch")
        return repository

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        maximum: int,
        allowed_codes: tuple[int, ...] = (0,),
    ) -> bytes:
        command = (
            str(GIT),
            "--no-optional-locks",
            "--no-replace-objects",
            f"--git-dir={self.git_dir}",
            f"--work-tree={self.root}",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            "-c",
            "core.attributesFile=/dev/null",
            "-c",
            "core.excludesFile=/dev/null",
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            "-c",
            "protocol.allow=never",
            *arguments,
        )
        return _run_git(command, maximum=maximum, allowed_codes=allowed_codes)

    def object_type(self, oid: str) -> str:
        output = self.run(("cat-file", "-t", oid), maximum=32).strip()
        try:
            object_type = output.decode("ascii")
        except UnicodeDecodeError as exc:
            raise PublicationError("invalid-object-type") from exc
        if object_type not in {"blob", "commit", "tag", "tree"}:
            raise PublicationError("invalid-object-type")
        return object_type

    def object_size(self, oid: str) -> int:
        output = self.run(("cat-file", "-s", oid), maximum=32).strip()
        if not output.isdigit():
            raise PublicationError("invalid-object-size")
        return int(output)

    def object_bytes(self, oid: str, object_type: str, maximum: int) -> bytes:
        size = self.object_size(oid)
        if size > maximum:
            raise PublicationError(f"{object_type}-exceeds-byte-bound")
        data = self.run(("cat-file", object_type, oid), maximum=maximum)
        if len(data) != size:
            raise PublicationError("object-size-drift")
        return data

    def snapshot(self) -> RepositorySnapshot:
        head = _parse_single_oid(self.run(("rev-parse", "--verify", "HEAD"), maximum=128), "head")
        if self.object_type(head) != "commit":
            raise PublicationError("head-is-not-commit")
        symbolic_bytes = self.run(
            ("symbolic-ref", "-q", "HEAD"),
            maximum=4096,
            allowed_codes=(0, 1),
        ).rstrip(b"\n")
        symbolic_head = _decode_ref_name(symbolic_bytes) if symbolic_bytes else ""
        raw_refs = self.run(
            ("for-each-ref", "--format=%(refname)%09%(objectname)%09%(objecttype)"),
            maximum=MAX_REF_BYTES,
        )
        refs = _parse_refs(raw_refs)
        metadata = self.git_dir.stat()
        return RepositorySnapshot(
            head=head,
            symbolic_head=symbolic_head,
            refs=refs,
            git_identity=(metadata.st_dev, metadata.st_ino),
        )


def scan_publication(
    root: Path,
    private_denylist: Path,
    *,
    expected_baseline: str = PUBLIC_BASE_COMMIT,
    before_final_check: Optional[Callable[[], None]] = None,
) -> PublicationReport:
    return audit_repository(
        root,
        expected_baseline,
        private_denylist,
        before_final_check=before_final_check,
    )


def audit_repository(
    root: Path,
    expected_baseline: str,
    private_denylist: Path,
    *,
    before_final_check: Optional[Callable[[], None]] = None,
) -> PublicationReport:
    if not OID.fullmatch(expected_baseline):
        raise PublicationError("invalid-baseline-pin")
    repository = GitRepository.bind(root)
    try:
        terms = check_release_leaks.load_private_denylist(private_denylist, repository.root)
    except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
        raise PublicationError("private-denylist-invalid") from exc

    initial = repository.snapshot()
    pending_error: Optional[PublicationError] = None
    report: Optional[PublicationReport] = None
    try:
        report = _scan_bound_repository(repository, initial, terms, expected_baseline)
    except PublicationError as exc:
        pending_error = exc

    if before_final_check is not None:
        before_final_check()

    try:
        final = repository.snapshot()
        final_status = _worktree_status(repository)
    except PublicationError as exc:
        raise PublicationError("repository-ref-drift") from exc
    if final != initial:
        raise PublicationError("repository-ref-drift")
    if final_status:
        raise PublicationError("worktree-drift-during-scan")
    if pending_error is not None:
        raise pending_error
    if report is None:
        raise PublicationError("publication-scan-incomplete")
    return report


def _scan_bound_repository(
    repository: GitRepository,
    snapshot: RepositorySnapshot,
    terms: list[check_release_leaks.PrivateTerm],
    expected_baseline: str,
) -> PublicationReport:
    if _worktree_status(repository):
        raise PublicationError("worktree-is-not-clean")
    if snapshot.symbolic_head and not snapshot.symbolic_head.startswith("refs/heads/"):
        raise PublicationError("head-symbolic-ref-invalid")
    if len(snapshot.refs) > MAX_REFS:
        raise PublicationError("ref-count-exceeds-bound")

    commits = _oid_lines(
        repository.run(("rev-list", "--reverse", "HEAD"), maximum=MAX_COMMITS * 41),
        maximum=MAX_COMMITS,
        label="head-history",
    )
    all_commits = _oid_lines(
        repository.run(("rev-list", "--all"), maximum=MAX_COMMITS * 41),
        maximum=MAX_COMMITS,
        label="all-history",
    )
    if not commits:
        raise PublicationError("history-is-empty")
    if set(all_commits) != set(commits) or len(all_commits) != len(commits):
        raise PublicationError("non-head-reachable-history")
    roots = _oid_lines(
        repository.run(("rev-list", "--max-parents=0", "HEAD"), maximum=(MAX_COMMITS + 1) * 41),
        maximum=MAX_COMMITS,
        label="root-history",
    )
    if roots != (expected_baseline,):
        raise PublicationError("public-baseline-drift")

    state = ScanState()
    commit_set = set(commits)
    scanned_blobs: set[str] = set()
    for commit in commits:
        _scan_commit(repository, commit, terms, state, scanned_blobs)
    _scan_refs_and_tags(repository, snapshot.refs, terms, commit_set, state)
    return PublicationReport(
        commits=len(commits),
        refs=len(snapshot.refs),
        tags=state.tag_count,
        tree_entries=state.tree_entries,
        unique_blobs=len(scanned_blobs),
        unique_blob_bytes=state.unique_blob_bytes,
    )


def _scan_commit(
    repository: GitRepository,
    commit: str,
    terms: list[check_release_leaks.PrivateTerm],
    state: ScanState,
    scanned_blobs: set[str],
) -> None:
    raw_commit = repository.object_bytes(commit, "commit", MAX_COMMIT_BYTES)
    state.commit_count += 1
    state.commit_bytes += len(raw_commit)
    if state.commit_count > MAX_COMMITS or state.commit_bytes > MAX_TOTAL_COMMIT_BYTES:
        raise PublicationError("commit-metadata-exceeds-bound")
    _validate_commit_emails(raw_commit)
    _raise_for_leaks(check_release_leaks.scan_sensitive_bytes("<commit-metadata>", raw_commit, terms)[0])

    listing = repository.run(
        ("ls-tree", "-r", "-t", "-z", "--full-tree", commit),
        maximum=MAX_TREE_OUTPUT_BYTES,
    )
    state.tree_output_bytes += len(listing)
    if state.tree_output_bytes > MAX_TOTAL_TREE_OUTPUT_BYTES:
        raise PublicationError("tree-output-bytes-exceed-bound")
    seen_paths: set[str] = set()
    for mode, object_type, oid, relative in _parse_tree_listing(listing):
        state.tree_entries += 1
        if state.tree_entries > MAX_TREE_ENTRIES:
            raise PublicationError("tree-entry-count-exceeds-bound")
        if relative in seen_paths:
            raise PublicationError("duplicate-tree-path")
        seen_paths.add(relative)
        _validate_tree_path(relative)
        path_findings, _ = check_release_leaks.scan_release_path(relative, terms)
        _raise_for_leaks(path_findings)
        if object_type == "tree":
            if mode != "040000":
                raise PublicationError("unsupported-tree-mode")
            continue
        if mode == "120000":
            raise PublicationError("symlink-tree-entry")
        if mode == "160000" or object_type == "commit":
            raise PublicationError("gitlink-tree-entry")
        if object_type != "blob" or mode not in ALLOWED_FILE_MODES:
            raise PublicationError("unsupported-tree-mode")
        size = repository.object_size(oid)
        if size > MAX_BLOB_BYTES:
            raise PublicationError("blob-exceeds-byte-bound")
        state.logical_blob_bytes += size
        if state.logical_blob_bytes > MAX_LOGICAL_BLOB_BYTES:
            raise PublicationError("logical-blob-bytes-exceed-bound")
        if oid in scanned_blobs:
            continue
        if len(scanned_blobs) >= MAX_BLOBS:
            raise PublicationError("blob-count-exceeds-bound")
        data = repository.object_bytes(oid, "blob", MAX_BLOB_BYTES)
        state.unique_blob_bytes += len(data)
        if state.unique_blob_bytes > MAX_UNIQUE_BLOB_BYTES:
            raise PublicationError("unique-blob-bytes-exceed-bound")
        findings, _ = check_release_leaks.scan_sensitive_bytes(relative, data, terms)
        _raise_for_leaks(findings)
        scanned_blobs.add(oid)


def _scan_refs_and_tags(
    repository: GitRepository,
    refs: tuple[RefState, ...],
    terms: list[check_release_leaks.PrivateTerm],
    commits: set[str],
    state: ScanState,
) -> None:
    tag_targets: dict[str, tuple[str, str]] = {}
    for ref in refs:
        if ref.name.startswith("refs/replace/"):
            raise PublicationError("replacement-ref-is-not-allowed")
        findings, _ = check_release_leaks.scan_release_path(ref.name, terms)
        _raise_for_leaks(findings)
        target_oid = ref.oid
        target_type = ref.object_type
        chain: set[str] = set()
        while target_type == "tag":
            if target_oid in chain:
                raise PublicationError("annotated-tag-cycle")
            chain.add(target_oid)
            if target_oid not in tag_targets:
                if len(tag_targets) >= MAX_TAGS:
                    raise PublicationError("tag-count-exceeds-bound")
                raw_tag = repository.object_bytes(target_oid, "tag", MAX_TAG_BYTES)
                state.tag_count += 1
                state.tag_bytes += len(raw_tag)
                if state.tag_bytes > MAX_TOTAL_TAG_BYTES:
                    raise PublicationError("tag-metadata-exceeds-bound")
                _validate_tag_email(raw_tag)
                _raise_for_leaks(check_release_leaks.scan_sensitive_bytes("<annotated-tag>", raw_tag, terms)[0])
                tag_targets[target_oid] = _tag_target(raw_tag)
            target_oid, declared_type = tag_targets[target_oid]
            target_type = repository.object_type(target_oid)
            if target_type != declared_type:
                raise PublicationError("annotated-tag-type-mismatch")
        if target_type != "commit" or target_oid not in commits:
            raise PublicationError("ref-target-is-not-head-history")


def _worktree_status(repository: GitRepository) -> bytes:
    return repository.run(
        ("status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=all"),
        maximum=MAX_STATUS_BYTES,
    )


def _validate_commit_emails(raw_commit: bytes) -> None:
    try:
        text = raw_commit.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublicationError("commit-metadata-is-not-utf8") from exc
    headers = text.split("\n\n", 1)[0]
    for label in ("author", "committer"):
        matches = re.findall(rf"^{label} .* <([^<>\r\n]+)> [0-9]+ [+-][0-9]{{4}}$", headers, re.MULTILINE)
        if len(matches) != 1 or NOREPLY_EMAIL.fullmatch(matches[0]) is None:
            raise PublicationError(f"commit-{label}-email-not-noreply")


def _validate_tag_email(raw_tag: bytes) -> None:
    try:
        text = raw_tag.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublicationError("tag-metadata-is-not-utf8") from exc
    headers = text.split("\n\n", 1)[0]
    matches = re.findall(r"^tagger .* <([^<>\r\n]+)> [0-9]+ [+-][0-9]{4}$", headers, re.MULTILINE)
    if len(matches) != 1 or NOREPLY_EMAIL.fullmatch(matches[0]) is None:
        raise PublicationError("tagger-email-is-not-noreply")


def _parse_refs(raw: bytes) -> tuple[RefState, ...]:
    if len(raw) > MAX_REF_BYTES:
        raise PublicationError("ref-bytes-exceed-bound")
    refs: list[RefState] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        fields = line.split(b"\t")
        if len(fields) != 3:
            raise PublicationError("invalid-ref-record")
        name = _decode_ref_name(fields[0])
        if name in seen or not name.startswith("refs/"):
            raise PublicationError("invalid-ref-name")
        oid = _parse_oid_bytes(fields[1], "ref")
        try:
            object_type = fields[2].decode("ascii")
        except UnicodeDecodeError as exc:
            raise PublicationError("invalid-ref-object-type") from exc
        if object_type not in {"blob", "commit", "tag", "tree"}:
            raise PublicationError("invalid-ref-object-type")
        seen.add(name)
        refs.append(RefState(name, oid, object_type))
        if len(refs) > MAX_REFS:
            raise PublicationError("ref-count-exceeds-bound")
    return tuple(refs)


def _parse_tree_listing(raw: bytes) -> Iterable[tuple[str, str, str, str]]:
    records = raw.split(b"\0")
    if records[-1] != b"":
        raise PublicationError("tree-listing-is-not-nul-terminated")
    for record in records[:-1]:
        metadata, separator, raw_path = record.partition(b"\t")
        fields = metadata.split(b" ")
        if not separator or len(fields) != 3 or not raw_path:
            raise PublicationError("invalid-tree-record")
        try:
            mode = fields[0].decode("ascii")
            object_type = fields[1].decode("ascii")
            relative = raw_path.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PublicationError("tree-path-is-not-utf8") from exc
        oid = _parse_oid_bytes(fields[2], "tree")
        yield mode, object_type, oid, relative


def _validate_tree_path(relative: str) -> None:
    if not relative or relative.startswith("/") or "\\" in relative:
        raise PublicationError("unsafe-tree-path")
    try:
        encoded = relative.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise PublicationError("unsafe-tree-path") from exc
    if len(encoded) > 4096 or unicodedata.normalize("NFC", relative) != relative:
        raise PublicationError("unsafe-tree-path")
    components = relative.split("/")
    if any(not component or component in {".", ".."} for component in components):
        raise PublicationError("unsafe-tree-path")
    for component in components:
        if len(component.encode("utf-8")) > 255:
            raise PublicationError("unsafe-tree-path")
        if component.casefold() in RESERVED_TREE_NAMES:
            raise PublicationError("reserved-tree-path")
        if component != component.strip() or component.endswith("."):
            raise PublicationError("unsafe-tree-path")
        if any(ord(character) < 32 or ord(character) == 127 for character in component):
            raise PublicationError("unsafe-tree-path")


def _tag_target(raw_tag: bytes) -> tuple[str, str]:
    header = raw_tag.split(b"\n\n", 1)[0]
    object_lines = [line[7:] for line in header.splitlines() if line.startswith(b"object ")]
    type_lines = [line[5:] for line in header.splitlines() if line.startswith(b"type ")]
    if len(object_lines) != 1 or len(type_lines) != 1:
        raise PublicationError("invalid-annotated-tag")
    oid = _parse_oid_bytes(object_lines[0], "tag")
    try:
        object_type = type_lines[0].decode("ascii")
    except UnicodeDecodeError as exc:
        raise PublicationError("invalid-annotated-tag") from exc
    if object_type not in {"blob", "commit", "tag", "tree"}:
        raise PublicationError("invalid-annotated-tag")
    return oid, object_type


def _oid_lines(raw: bytes, *, maximum: int, label: str) -> tuple[str, ...]:
    values = tuple(_parse_oid_bytes(line, label) for line in raw.splitlines() if line)
    if len(values) > maximum or len(set(values)) != len(values):
        raise PublicationError(f"{label}-exceeds-bound")
    return values


def _parse_single_oid(raw: bytes, label: str) -> str:
    lines = raw.splitlines()
    if len(lines) != 1:
        raise PublicationError(f"invalid-{label}-oid")
    return _parse_oid_bytes(lines[0], label)


def _parse_oid_bytes(raw: bytes, label: str) -> str:
    try:
        value = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise PublicationError(f"invalid-{label}-oid") from exc
    if OID.fullmatch(value) is None:
        raise PublicationError(f"invalid-{label}-oid")
    return value


def _decode_ref_name(raw: bytes) -> str:
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublicationError("invalid-ref-name") from exc
    if not value or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise PublicationError("invalid-ref-name")
    return value


def _decode_git_path(raw: bytes) -> str:
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublicationError("git-path-is-not-utf8") from exc
    if not value or "\n" in value or "\r" in value or "\x00" in value:
        raise PublicationError("git-path-is-invalid")
    return value


def _raise_for_leaks(findings: list[check_release_leaks.Finding]) -> None:
    if findings:
        raise PublicationError(f"leak-{findings[0].rule}")


def _validate_git_control_directory(git_dir: Path) -> None:
    forbidden = (
        git_dir / "commondir",
        git_dir / "shallow",
        git_dir / "info/grafts",
        git_dir / "objects/info/alternates",
        git_dir / "refs/replace",
    )
    if any(path.exists() or path.is_symlink() for path in forbidden):
        raise PublicationError("redirected-or-hidden-git-history")
    count = 0

    def on_error(error: OSError) -> None:
        raise PublicationError("git-control-read-error") from error

    for directory, names, files in os.walk(git_dir, followlinks=False, onerror=on_error):
        base = Path(directory)
        for name in names + files:
            count += 1
            if count > MAX_CONTROL_ENTRIES:
                raise PublicationError("git-control-entry-count-exceeds-bound")
            candidate = base / name
            try:
                metadata = candidate.lstat()
            except OSError as exc:
                raise PublicationError("git-control-read-error") from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise PublicationError("git-control-symlink")
            if name in names and not stat.S_ISDIR(metadata.st_mode):
                raise PublicationError("git-control-special-file")
            if name in files and not stat.S_ISREG(metadata.st_mode):
                raise PublicationError("git-control-special-file")


def _run_git(command: tuple[str, ...], *, maximum: int, allowed_codes: tuple[int, ...]) -> bytes:
    if not GIT.is_file() or not os.access(GIT, os.X_OK):
        raise PublicationError("fixed-git-binary-missing")
    environment = {
        "GIT_ALLOW_PROTOCOL": "file",
        "GIT_ASKPASS": "/bin/false",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_PROTOCOL_FROM_USER": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
        "HOME": "/dev/null",
        "LANG": "C",
        "LC_ALL": "C",
        "PAGER": "cat",
        "PATH": "/usr/bin:/bin",
        "SSH_ASKPASS": "/bin/false",
    }
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd="/",
            env=environment,
            close_fds=True,
        )
    except OSError as exc:
        raise PublicationError("git-process-start-failed") from exc
    if process.stdout is None or process.stderr is None:
        process.kill()
        process.wait()
        raise PublicationError("git-process-pipe-failed")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {"stdout": maximum, "stderr": 16 * 1024}
    deadline = time.monotonic() + GIT_TIMEOUT_SECONDS
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PublicationError("git-command-timeout")
            events = selector.select(remaining)
            if not events:
                raise PublicationError("git-command-timeout")
            for key, _ in events:
                chunk = os.read(key.fd, 64 * 1024)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                target = buffers[key.data]
                target.extend(chunk)
                if len(target) > limits[key.data]:
                    raise PublicationError(f"git-{key.data}-exceeds-bound")
        return_code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
    except (OSError, subprocess.TimeoutExpired, PublicationError) as exc:
        process.kill()
        process.wait()
        if isinstance(exc, PublicationError):
            raise
        raise PublicationError("git-command-failed") from exc
    finally:
        selector.close()
    if return_code not in allowed_codes:
        raise PublicationError("git-command-failed")
    return bytes(buffers["stdout"])


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "--private-denylist":
        print("FAIL publication-history:usage---private-denylist-absolute-path", file=sys.stderr)
        return 1
    denylist = Path(argv[2])
    if not denylist.is_absolute():
        print("FAIL publication-history:private-denylist-must-be-absolute", file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parent.parent
    try:
        report = scan_publication(root, denylist)
    except PublicationError as exc:
        print(f"FAIL publication-history:{exc.code}", file=sys.stderr)
        return 1
    print(
        "publication history check passed: "
        f"{report.commits} commits, {report.refs} refs, {report.unique_blobs} blobs scanned"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
