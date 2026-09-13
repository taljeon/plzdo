"""Fixed, read-only PlzDo v0.3.0 CLI codec. Standard library only.

The trusted core status command validates its complete formalization schema. This
codec independently binds identity, lifecycle, time and the governed payload to
the delegation request. No runtime code is imported or invoked here.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

CONFIG_SCHEMA = "plzdo-parent-adapter.config.v2"
CORE_VERSION = "0.3.0"
REQUEST_SCHEMA = "plzdo.parent-request.v2"
SCOPE_REQUEST_SCHEMA = "plzdo.parent-scope-request.v2"
INPUT_PROTOCOL = "plzdo.parent-verifier-input.v2"
RESULT_PROTOCOL = "plzdo.parent-verifier.v2"
MARKER_PREFIX = "plzdo-delegation:v2:"
SCOPE_MARKER_PREFIX = "plzdo-scope-delegation:v2:"
DELEGATION_PREFIXES = (MARKER_PREFIX, SCOPE_MARKER_PREFIX,
                       "local-code-delegation:", "local-code-scope-delegation:",
                       "plzdo-delegation:", "plzdo-scope-delegation:")
MAX_INPUT = 4 * 1024 * 1024
MAX_CONFIG = 1024 * 1024
MAX_CORE_OUTPUT = 1024 * 1024
MAX_STDERR = 64 * 1024
MAX_CODE = 8 * 1024 * 1024
MAX_PYTHON = 128 * 1024 * 1024
CORE_TIMEOUT = 2.5
FILE_KEYS = {"path", "device", "inode", "sha256"}
ROOT_KEYS = {"path", "device", "inode"}
REQUEST_KEYS = {"schemaVersion", "id", "preparedAt", "expiresAt", "runtimeState",
                "policyFingerprint", "parentReference", "verifier", "packet",
                "execution", "requestSha256"}
VERIFIER_KEYS = {"python", "entrypoint", "codeFiles", "codeRoots", "config"}
PARENT_KEYS = {"state", "formalizationId", "projectId", "project"}
GOVERNED_FIELDS = ("objective", "criteria", "nonGoals", "constraints", "route",
                   "plan", "evidenceContract")
FORMALIZATION_KEYS = {"schemaVersion", "id", "projectId", "status", "approval",
                      "completion", "supersession", "createdAt", "updatedAt",
                      *GOVERNED_FIELDS}
SHA = re.compile(r"[a-f0-9]{64}\Z")
SAFE_ID = re.compile(r"[a-z][a-z0-9-]{1,63}\Z")
UTC_SECONDS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


class AdapterError(ValueError):
    """A fail-closed boundary error, with no private core diagnostics."""


def exact(value: Any, keys: set[str], label: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise AdapterError(f"{label}: unexpected shape")
    return value


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise AdapterError("invalid canonical JSON") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def decode(data: bytes, maximum: int, label: str = "JSON") -> dict:
    if not isinstance(data, bytes) or len(data) > maximum:
        raise AdapterError(f"{label}: size limit")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise AdapterError(f"{label}: duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise AdapterError(f"{label}: nonfinite JSON number")

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise AdapterError(f"{label}: invalid single JSON document") from exc
    if type(value) is not dict:
        raise AdapterError(f"{label}: object required")
    canonical(value)  # Also rejects escaped unpaired surrogates.
    return value


def timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not UTC_SECONDS.fullmatch(value):
        raise AdapterError(f"{label}: UTC seconds required")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise AdapterError(f"{label}: invalid timestamp") from exc


def request_timestamp(value: Any, label: str) -> datetime:
    # The standalone runtime's existing contracts accept either explicit UTC
    # suffix, with an optional fractional expiry. Core CLI timestamps stay Z.
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value):
        raise AdapterError(f"{label}: explicit UTC timestamp required")
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise AdapterError(f"{label}: invalid timestamp") from exc
    if label == "preparedAt" and parsed.microsecond:
        raise AdapterError("preparedAt must be floored to UTC seconds")
    return parsed


def safe_id(value: Any) -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise AdapterError("invalid public core identifier")
    return value


def safe_path(value: Any, *, directory: bool = False) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise AdapterError("invalid pinned path")
    path = Path(value)
    if not path.is_absolute() or str(path) != value or path == Path("/"):
        raise AdapterError("pinned path must be canonical and absolute")
    try:
        if path.resolve(strict=True) != path:
            raise AdapterError("pinned path crosses a symlink")
        for ancestor in [*path.parents, path]:
            if ancestor.is_symlink():
                raise AdapterError("pinned path crosses a symlink")
        info = path.lstat()
        if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
            raise AdapterError("pinned path has unsafe type")
        if info.st_uid not in {0, os.getuid()} or info.st_mode & 0o022:
            raise AdapterError("pinned path has unsafe ownership or permissions")
    except OSError as exc:
        raise AdapterError("pinned path unavailable") from exc
    return path


def read_bytes(path: Path, maximum: int) -> bytes:
    safe_path(str(path))
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
                raise AdapterError("file type or size rejected")
            payload = source.read(maximum + 1)
            after = os.fstat(source.fileno())
        current = path.lstat()
        fields = lambda item: (item.st_dev, item.st_ino, item.st_size,
                               item.st_mtime_ns, item.st_ctime_ns)
        if fields(before) != fields(after) or fields(after) != fields(current):
            raise AdapterError("file changed while reading")
        if len(payload) > maximum:
            raise AdapterError("file size limit")
        return payload
    except OSError as exc:
        raise AdapterError("pinned file unavailable") from exc


def root_pin(path: Path) -> dict:
    path = safe_path(str(path), directory=True)
    info = path.lstat()
    return {"path": str(path), "device": info.st_dev, "inode": info.st_ino}


def file_pin(path: Path, maximum: int = MAX_CODE) -> dict:
    payload = read_bytes(path, maximum)
    info = path.lstat()
    return {"path": str(path), "device": info.st_dev, "inode": info.st_ino,
            "sha256": hashlib.sha256(payload).hexdigest()}


def validate_pin(pin: Any, *, directory: bool = False, maximum: int = MAX_CODE) -> None:
    exact(pin, ROOT_KEYS if directory else FILE_KEYS, "identity pin")
    if any(type(pin[key]) is not int or pin[key] < 0 for key in ("device", "inode")):
        raise AdapterError("invalid identity numbers")
    observed = root_pin(Path(pin["path"])) if directory else file_pin(Path(pin["path"]), maximum)
    if observed != pin:
        raise AdapterError("pinned identity or content changed")


def closure(root: Path) -> list[Path]:
    safe_path(str(root), directory=True)
    found = []
    entries = 0
    for directory, children, files in os.walk(root, followlinks=False):
        for name in children + files:
            entries += 1
            if entries > 8192:
                raise AdapterError("code tree entry limit")
            path = Path(directory) / name
            if path.is_symlink():
                raise AdapterError("symlink in code closure")
        for name in children:
            safe_path(str(Path(directory) / name), directory=True)
        for name in files:
            path = safe_path(str(Path(directory) / name))
            found.append(path)
            if len(found) > 1024:
                raise AdapterError("code closure file limit")
    return sorted(found)


def core_roots(root: Path) -> list[Path]:
    """Exact closure roots: installed package or fixed source directories."""
    if root.name == "plzdo_local":
        # Installed resources live within this package, not site-packages.
        safe_path(str(root / "_bundled"), directory=True)
        return [root]
    return [root / name for name in ("plzdo_local", "schemas", "templates", "resources")]


def core_files(root: Path) -> list[Path]:
    files = [path for directory in core_roots(root) for path in closure(directory)]
    if root.name != "plzdo_local":
        files.extend([root / "VERSION", root / "bin" / "plzdo_entry.py"])
    if len(files) > 1024:
        raise AdapterError("core closure file limit")
    return sorted(files)


def validate_config(value: Any) -> dict:
    config = exact(value, {"schemaVersion", "coreRoot", "corePython", "coreCodeFiles",
                           "coreVersion"}, "adapter config")
    if config["schemaVersion"] != CONFIG_SCHEMA or config["coreVersion"] != CORE_VERSION:
        raise AdapterError("unsupported core or config version")
    validate_pin(config["coreRoot"], directory=True)
    validate_pin(config["corePython"], maximum=MAX_PYTHON)
    files = config["coreCodeFiles"]
    if type(files) is not list or not 1 <= len(files) <= 1024:
        raise AdapterError("invalid core closure")
    for item in files:
        validate_pin(item)
    if [item["path"] for item in files] != [str(path) for path in core_files(Path(config["coreRoot"]["path"]))]:
        raise AdapterError("core closure changed")
    return config


def validate_envelope(envelope: Any, config_path: Path) -> tuple[dict, str]:
    exact(envelope, {"protocol", "operation", "request"}, "verifier input")
    if envelope["protocol"] != INPUT_PROTOCOL or envelope["operation"] not in {"prepare", "verify"}:
        raise AdapterError("unsupported verifier operation")
    request = envelope["request"]
    scoped = isinstance(request, dict) and request.get("schemaVersion") == SCOPE_REQUEST_SCHEMA
    request = exact(request, REQUEST_KEYS - {"packet"} if scoped else REQUEST_KEYS, "prepared request")
    if request["schemaVersion"] not in {REQUEST_SCHEMA, SCOPE_REQUEST_SCHEMA}:
        raise AdapterError("unsupported request schema")
    if not isinstance(request["requestSha256"], str) or not SHA.fullmatch(request["requestSha256"]):
        raise AdapterError("invalid request hash")
    if digest({key: value for key, value in request.items() if key != "requestSha256"}) != request["requestSha256"]:
        raise AdapterError("request hash mismatch")
    request_timestamp(request["preparedAt"], "preparedAt")
    if request_timestamp(request["expiresAt"], "expiresAt") <= request_timestamp(request["preparedAt"], "preparedAt"):
        raise AdapterError("request expiry ordering")
    parent = exact(request["parentReference"], PARENT_KEYS, "parent reference")
    safe_id(parent["formalizationId"])
    safe_id(parent["projectId"])
    for pin in (request["runtimeState"], parent["state"], parent["project"]):
        validate_pin(pin, directory=True)
    verifier = exact(request["verifier"], VERIFIER_KEYS, "verifier")
    validate_pin(verifier["python"], maximum=MAX_PYTHON)
    validate_pin(verifier["config"], maximum=MAX_CONFIG)
    if verifier["config"]["path"] != str(config_path):
        raise AdapterError("unexpected adapter config path")
    validate_pin(verifier["entrypoint"])
    own_entrypoint = str(Path(__file__).parent / "verify_parent.py")
    if verifier["entrypoint"]["path"] != own_entrypoint:
        raise AdapterError("unexpected verifier entrypoint")
    roots = verifier["codeRoots"]
    files = verifier["codeFiles"]
    if type(roots) is not list or not 1 <= len(roots) <= 8 or type(files) is not list or not 1 <= len(files) <= 1024:
        raise AdapterError("invalid verifier closure")
    for pin in roots:
        validate_pin(pin, directory=True)
    for pin in files:
        validate_pin(pin)
    paths = [item["path"] for item in files]
    if paths != sorted(set(paths)):
        raise AdapterError("verifier files must be sorted and unique")
    for pin in roots:
        root = Path(pin["path"])
        actual = {str(item) for item in closure(root)}
        supplied = {path for path in paths if Path(path).is_relative_to(root)}
        if actual != supplied:
            raise AdapterError("verifier closure changed")
    if str(Path(__file__).parent) not in [item["path"] for item in roots]:
        raise AdapterError("adapter package must be a pinned code root")
    return request, envelope["operation"]


def bounded_process(argv: list[str], env: dict[str, str], *, timeout: float = CORE_TIMEOUT,
                    stdout_limit: int = MAX_CORE_OUTPUT, stderr_limit: int = MAX_STDERR,
                    new_session: bool = True) -> tuple[int, bytes, bytes]:
    """Run one fixed caller-built argv, bound both streams and the whole process tree."""
    deadline = time.monotonic() + timeout
    process = None
    selector = selectors.DefaultSelector()
    streams = {"stdout": bytearray(), "stderr": bytearray()}
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd="/", env=env, shell=False,
                                   close_fds=True, start_new_session=new_session)
        for name in streams:
            pipe = getattr(process, name)
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        while selector.get_map():
            left = deadline - time.monotonic()
            if left <= 0:
                raise AdapterError("core process deadline exceeded")
            for key, _ in selector.select(min(left, 0.1)):
                block = os.read(key.fileobj.fileno(), 65536)
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                output = streams[key.data]
                output.extend(block)
                limit = stdout_limit if key.data == "stdout" else stderr_limit
                if len(output) > limit:
                    raise AdapterError("core process output limit exceeded")
        left = deadline - time.monotonic()
        if left <= 0:
            raise AdapterError("core process deadline exceeded")
        try:
            code = process.wait(timeout=left)
        except subprocess.TimeoutExpired as exc:
            raise AdapterError("core process deadline exceeded") from exc
        return code, bytes(streams["stdout"]), bytes(streams["stderr"])
    except OSError as exc:
        raise AdapterError("core process unavailable") from exc
    finally:
        selector.close()
        if process is not None:
            # Under the runtime's dedicated verifier session, core inherits that
            # group so the runtime can kill every descendant even if this adapter
            # is interrupted. The outer runtime also cleans the group on success.
            # Standalone calls own and clean a separate core process group.
            try:
                if new_session:
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            process.wait()
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


def core_command(config: dict, parent: dict, command: str) -> dict | None:
    commands = {
        "version": ["version", "--json"],
        "state": ["state-root", "status", "--json"],
        "project": ["project", "show", safe_id(parent["projectId"]), "--json"],
        "formalization": ["formalize", "status", safe_id(parent["formalizationId"]), "--json"],
    }
    if command not in commands:
        raise AdapterError("unsupported core command")
    argv = [config["corePython"]["path"], "-I", "-B", "-S",
            str(Path(__file__).parent / "core_entry.py"),
            "--core-root", config["coreRoot"]["path"],
            *commands[command]]
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8",
           "PYTHONDONTWRITEBYTECODE": "1", "PLZDO_HOME": parent["state"]["path"]}
    dedicated_verifier_session = os.getsid(0) == os.getpid() and os.getpgrp() == os.getpid()
    code, stdout, stderr = bounded_process(argv, env, new_session=not dedicated_verifier_session)
    missing = f"plzdo: DurableCommandError: formalization not found: {parent['formalizationId']}\n".encode()
    if command == "formalization" and code == 2 and stdout == b"" and stderr == missing:
        return None
    if code != 0 or stderr:
        raise AdapterError(f"core {command} command rejected")
    return decode(stdout, MAX_CORE_OUTPUT, f"core {command} output")


def state_boundary(parent: dict) -> None:
    """Reject symlinks/nonregular files before core can read its control records."""
    validate_pin(parent["state"], directory=True)
    validate_pin(parent["project"], directory=True)
    root = Path(parent["state"]["path"])
    for directory, filename in (("registry", "registry.json"), ("catalog", "catalog.json")):
        folder = root / directory
        if folder.exists() or folder.is_symlink():
            safe_path(str(folder), directory=True)
            child = folder / filename
            if child.exists() or child.is_symlink():
                safe_path(str(child))
    formalizations = root / "formalizations"
    if formalizations.exists() or formalizations.is_symlink():
        safe_path(str(formalizations), directory=True)
        for index, child in enumerate(formalizations.iterdir()):
            if index >= 8192:
                raise AdapterError("formalization directory entry limit")
            if child.name.endswith(".json"):
                safe_path(str(child))


def decode_snapshot(record: dict | None, request: dict, operation: str, observed_at: str) -> dict:
    observed = timestamp(observed_at, "observedAt")
    prepared = request_timestamp(request["preparedAt"], "preparedAt")
    expires = request_timestamp(request["expiresAt"], "expiresAt")
    if not prepared <= observed < expires:
        raise AdapterError("request expired or observation precedes preparation")
    result = {"protocol": RESULT_PROTOCOL, "status": "absent",
              "requestSha256": request["requestSha256"], "parentApprovalHash": None,
              "parentCreatedAt": None, "parentApprovedAt": None,
              "observedAt": observed_at,
              "authorizationBasis": "operator-owned-local-record-snapshot", "atomicLease": False}
    if record is None:
        if operation != "prepare":
            raise AdapterError("parent formalization is missing")
        return result
    exact(record, FORMALIZATION_KEYS, "core formalization")
    parent = request["parentReference"]
    if record["schemaVersion"] != "plzdo-local.formalization.v1" or record["id"] != parent["formalizationId"] or record["projectId"] != parent["projectId"]:
        raise AdapterError("parent identity mismatch")
    if record["status"] not in {"draft", "approved"} or record["completion"] is not None or record["supersession"] is not None:
        raise AdapterError("parent is terminal or invalid")
    created = timestamp(record["createdAt"], "parentCreatedAt")
    updated = timestamp(record["updatedAt"], "parentUpdatedAt")
    if not prepared <= created <= updated <= observed:
        raise AdapterError("parent timestamp ordering")
    prefix = SCOPE_MARKER_PREFIX if request["schemaVersion"] == SCOPE_REQUEST_SCHEMA else MARKER_PREFIX
    marker = prefix + request["requestSha256"]
    evidence = record["evidenceContract"]
    if type(evidence) is not list or any(type(item) is not str for item in evidence):
        raise AdapterError("invalid parent evidence contract")
    markers = [item for item in evidence if any(prefix in item for prefix in DELEGATION_PREFIXES)]
    if markers != [marker]:
        raise AdapterError("parent delegation marker mismatch; use an unused goal id")
    route = record["route"]
    if type(route) is not dict or type(route.get("projectDecision")) is not dict or route["projectDecision"].get("projectId") != parent["projectId"] or route["projectDecision"].get("decision") != "attached":
        raise AdapterError("parent route project mismatch")
    if record["status"] == "draft":
        if record["approval"] is not None or operation != "prepare":
            raise AdapterError("parent approval is required")
        result["status"] = "prepared"
        return result
    approval = exact(record["approval"], {"operatorConfirmed", "approvedAt", "approvalHash"}, "parent approval")
    approved = timestamp(approval["approvedAt"], "parentApprovedAt")
    if approval["operatorConfirmed"] is not True or not created <= approved <= updated <= observed:
        raise AdapterError("invalid parent approval")
    if approval["approvalHash"] != digest({key: record[key] for key in GOVERNED_FIELDS}):
        raise AdapterError("parent governed payload hash mismatch")
    result.update(status="verified", parentApprovalHash=approval["approvalHash"],
                  parentCreatedAt=record["createdAt"], parentApprovedAt=approval["approvedAt"])
    return result


def verify(envelope: dict, config_path: Path) -> dict:
    request, operation = validate_envelope(envelope, config_path)
    config = validate_config(decode(read_bytes(config_path, MAX_CONFIG), MAX_CONFIG, "config"))
    verifier = request["verifier"]
    pinned_by_path = {item["path"]: item for item in verifier["codeFiles"]}
    if any(pinned_by_path.get(item["path"]) != item for item in config["coreCodeFiles"]):
        raise AdapterError("core code must be included in request verifier closure")
    adapter_root = Path(__file__).parent
    expected_roots = sorted(str(path) for path in
                            [adapter_root, *core_roots(Path(config["coreRoot"]["path"]))])
    if [item["path"] for item in verifier["codeRoots"]] != expected_roots:
        raise AdapterError("verifier roots must be exactly the core and adapter closure")
    core_paths = {item["path"] for item in config["coreCodeFiles"]}
    if any(path not in core_paths and not Path(path).is_relative_to(adapter_root)
           for path in pinned_by_path):
        raise AdapterError("file outside the fixed core and adapter closure")
    parent = request["parentReference"]
    state_boundary(parent)
    version = core_command(config, parent, "version")
    if version != {"schemaVersion": "plzdo-local.version-status.v1", "status": "ok", "version": CORE_VERSION}:
        raise AdapterError("unsupported core version output")
    state = core_command(config, parent, "state")
    exact(state, {"schemaVersion", "status", "path", "exists", "isSymlink"}, "state output")
    if state["schemaVersion"] != "plzdo-local.state-root-status.v1" or state["status"] != "configured" or state["path"] != parent["state"]["path"] or state["exists"] is not True or state["isSymlink"] is not False:
        raise AdapterError("core state root mismatch")
    project = core_command(config, parent, "project")
    exact(project, {"schemaVersion", "status", "project"}, "project output")
    row = exact(project["project"], {"id", "aliases", "domain", "area", "path", "repositoryId", "state"}, "project")
    if project["schemaVersion"] != "plzdo-local.project-show.v1" or project["status"] != "ok" or row["id"] != parent["projectId"] or row["path"] != parent["project"]["path"] or row["state"] != "active":
        raise AdapterError("core project mismatch")
    record = core_command(config, parent, "formalization")
    # Recheck the complete executable/config closure and roots after the reads.
    validate_envelope(envelope, config_path)
    validate_config(config)
    state_boundary(parent)
    observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return decode_snapshot(record, request, operation, observed_at)
