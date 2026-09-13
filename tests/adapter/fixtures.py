"""Owned synthetic state for exercising the unmodified public core process."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys

from plzdo_local_code_adapter.cli import configure
from plzdo_local_code_adapter.codec import (GOVERNED_FIELDS, INPUT_PROTOCOL,
                                           REQUEST_SCHEMA, SCOPE_REQUEST_SCHEMA, MARKER_PREFIX, SCOPE_MARKER_PREFIX, digest, root_pin, request_timestamp)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def seal(request: dict) -> dict:
    request["requestSha256"] = digest({key: value for key, value in request.items()
                                      if key != "requestSha256"})
    return request


def fixture(root: Path, core: Path, *, configure_cli: bool = False) -> tuple[dict, Path]:
    root = root.resolve()
    state = root / "core-state"
    project = root / "project"
    runtime = root / "runtime-state"
    for directory in (state, project, runtime):
        directory.mkdir(mode=0o700)
    interpreter = root / 'fixture-python'
    shutil.copyfile(Path(sys.executable).resolve(), interpreter)
    interpreter.chmod(0o700)
    if configure_cli:
        result = subprocess.run([sys.executable, '-I', '-S', '-B', str(Path(__file__).resolve().parents[2] / 'bin' / 'plzdo_adapter_entry.py'), 'configure',
                                 '--core-root', str(core), '--core-python', str(interpreter),
                                 '--verifier-python', str(interpreter), '--state-root', str(state),
                                 '--project-root', str(project), '--project-id', 'fixture-project',
                                 '--formalization-id', 'fixture-goal', '--output', str(root / 'pins')],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15)
        if result.returncode != 0:
            raise AssertionError('Fixture configure CLI failed: ' + repr(result.stderr))
        configured = json.loads(result.stdout)
        if configured['verifierSha256'] != digest(json.loads((root / 'pins' / 'verifier.json').read_text())):
            raise AssertionError('Fixture configure descriptor digest mismatch')
    else:
        configure(core_root=core, core_python=interpreter, verifier_python=interpreter, state_root=state,
                  project_root=project, project_id="fixture-project", formalization_id="fixture-goal",
                  output=root / "pins")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    request = {
        "schemaVersion": REQUEST_SCHEMA, "id": "delegation-fixture",
        "preparedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiresAt": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runtimeState": root_pin(runtime), "policyFingerprint": "a" * 64,
        "parentReference": json.loads((root / "pins" / "parent-reference.json").read_text()),
        "verifier": json.loads((root / "pins" / "verifier.json").read_text()),
        "packet": {"id": "fixture-packet"}, "execution": {},
    }
    seal(request)
    write_json(state / "registry" / "registry.json", {
        "schemaVersion": "plzdo-local.registry.v1", "projects": [{
            "id": "fixture-project", "aliases": [], "domain": "software", "area": "tooling",
            "path": str(project), "repositoryId": None, "state": "active",
        }],
    })
    return {"protocol": INPUT_PROTOCOL, "operation": "prepare", "request": request}, root / "pins" / "adapter-config.json"


def formalization(request: dict, *, status: str = "approved", marker: bool = True) -> dict:
    parent = request["parentReference"]
    created = request_timestamp(request['preparedAt'], 'preparedAt').strftime('%Y-%m-%dT%H:%M:%SZ')
    decision = {"schemaVersion": "plzdo-local.project-resolution.v1", "decision": "attached",
                "projectId": parent["projectId"], "candidateIds": [parent["projectId"]],
                "ruleId": "registry-resolve-exact-id-v1", "reason": "Explicit synthetic project"}
    route = {"schemaVersion": "plzdo-local.execution-route.v1", "weight": "goal", "boundedLoop": False,
             "projectDecision": decision, "ruleIds": [decision["ruleId"], "route-weight-product-goal-v1",
                                                       "route-loop-none-v1"],
             "explanation": "Synthetic product goal", "formalizationRequired": True,
             "recommendedEvidence": ["approved-formalization", "full-verification"]}
    record = {"schemaVersion": "plzdo-local.formalization.v1", "id": parent["formalizationId"],
              "projectId": parent["projectId"], "status": status,
              "objective": "Synthetic local adapter test", "criteria": ["No provider calls"],
              "nonGoals": ["No external writes"], "constraints": ["Owned fixture state only"],
              "route": route, "plan": ["Verify fixture snapshot"],
              "evidenceContract": [(SCOPE_MARKER_PREFIX if request['schemaVersion'] == SCOPE_REQUEST_SCHEMA else MARKER_PREFIX) + request["requestSha256"]] if marker else ["Generic fixture evidence"],
              "approval": None, "completion": None, "supersession": None,
              "createdAt": created, "updatedAt": created}
    if status != "draft":
        record["approval"] = {"operatorConfirmed": True, "approvedAt": created,
                              "approvalHash": digest({key: record[key] for key in GOVERNED_FIELDS})}
    return record


def save_formalization(request: dict, record: dict) -> Path:
    parent = request["parentReference"]
    path = Path(parent["state"]["path"]) / "formalizations" / (parent["formalizationId"] + ".json")
    write_json(path, record)
    return path
