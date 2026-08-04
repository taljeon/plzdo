from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any, Iterable

from .validation import (
    ValidationError,
    reject_sensitive_text,
    require_exact_keys,
    require_object,
    require_safe_id,
    require_string,
)


SCHEMA_VERSION = "plzdo-local.findings.v1"
STATUSES = ("open", "closed", "accepted-risk")
SEVERITIES = ("low", "medium", "high", "blocking")
MAX_FINDINGS = 512
MAX_EVIDENCE = 32
MAX_LEDGER_BYTES = 524_288


class FindingsError(ValueError):
    pass


class FindingsValidationError(FindingsError):
    pass


class FindingLookupError(FindingsError):
    pass


class FindingTransitionError(FindingsError):
    pass


def build_findings_ledger() -> dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "sourceOfTruth": False, "findings": []}


def add_finding(
    ledger: Any,
    *,
    finding_id: str,
    severity: str,
    title: str,
    evidence: Iterable[str],
    created_at: str,
) -> dict[str, Any]:
    validate_findings_ledger(ledger)
    checked_id = _require_safe_id(finding_id, label="finding.id")
    if any(item["id"] == checked_id for item in ledger["findings"]):
        raise FindingTransitionError(f"finding already exists: {checked_id}")
    checked_title = _safe_text(title, label="finding.title", maximum=160)
    checked_evidence = _evidence_array(evidence, label="finding.evidence", require_nonempty=True)
    _require_timestamp(created_at, label="finding.createdAt")
    if severity not in SEVERITIES:
        raise FindingsValidationError(f"finding.severity must be one of {list(SEVERITIES)}")
    updated = copy.deepcopy(ledger)
    updated["findings"].append(
        {
            "id": checked_id,
            "severity": severity,
            "title": checked_title,
            "status": "open",
            "evidence": checked_evidence,
            "resolution": None,
            "createdAt": created_at,
            "updatedAt": created_at,
            "sourceOfTruth": False,
        }
    )
    updated["findings"].sort(key=lambda item: item["id"])
    validate_findings_transition(ledger, updated)
    return updated


def close_finding(
    ledger: Any,
    finding_id: str,
    *,
    resolution: str,
    evidence: Iterable[str],
    updated_at: str,
) -> dict[str, Any]:
    return _resolve_finding(
        ledger,
        finding_id,
        status="closed",
        resolution=resolution,
        evidence=evidence,
        updated_at=updated_at,
    )


def accept_finding_risk(
    ledger: Any,
    finding_id: str,
    *,
    resolution: str,
    evidence: Iterable[str],
    updated_at: str,
) -> dict[str, Any]:
    return _resolve_finding(
        ledger,
        finding_id,
        status="accepted-risk",
        resolution=resolution,
        evidence=evidence,
        updated_at=updated_at,
    )


def list_findings(ledger: Any, *, include_terminal: bool = False) -> list[dict[str, Any]]:
    validate_findings_ledger(ledger)
    return [
        copy.deepcopy(item)
        for item in ledger["findings"]
        if include_terminal or item["status"] == "open"
    ]


def validate_findings_transition(previous: Any, current: Any) -> None:
    validate_findings_ledger(previous)
    validate_findings_ledger(current)
    before = {item["id"]: item for item in previous["findings"]}
    after = {item["id"]: item for item in current["findings"]}
    missing = sorted(set(before) - set(after))
    if missing:
        raise FindingTransitionError(f"findings may not disappear: {missing}")
    for finding_id in sorted(set(after) - set(before)):
        item = after[finding_id]
        if (
            item["status"] != "open"
            or item["resolution"] is not None
            or item["updatedAt"] != item["createdAt"]
        ):
            raise FindingTransitionError(f"new finding must start open: {finding_id}")
    for finding_id, old in before.items():
        new = after[finding_id]
        if old["status"] in {"closed", "accepted-risk"} and new != old:
            raise FindingTransitionError(f"terminal finding is immutable: {finding_id}")
        if old["status"] == "open":
            unchanged = new == old
            valid_terminal = (
                new["status"] in {"closed", "accepted-risk"}
                and new["id"] == old["id"]
                and new["severity"] == old["severity"]
                and new["title"] == old["title"]
                and new["createdAt"] == old["createdAt"]
                and new["sourceOfTruth"] is False
                and new["resolution"] is not None
                and len(new["evidence"]) > len(old["evidence"])
                and new["evidence"][: len(old["evidence"])] == old["evidence"]
                and _require_timestamp(
                    new["updatedAt"], label=f"finding {finding_id}.updatedAt"
                )
                >= _require_timestamp(
                    old["updatedAt"], label=f"previous finding {finding_id}.updatedAt"
                )
            )
            if not unchanged and not valid_terminal:
                raise FindingTransitionError(f"invalid finding transition: {finding_id}")


def validate_findings_ledger(value: Any) -> None:
    try:
        ledger = require_object(value, label="findings ledger")
        require_exact_keys(ledger, {"schemaVersion", "sourceOfTruth", "findings"}, label="findings ledger")
        if ledger["schemaVersion"] != SCHEMA_VERSION or ledger["sourceOfTruth"] is not False:
            raise FindingsValidationError("findings ledger schema or authority is invalid")
        findings = ledger["findings"]
        if not isinstance(findings, list) or len(findings) > MAX_FINDINGS:
            raise FindingsValidationError(f"findings must be an array of at most {MAX_FINDINGS} items")
        ids: list[str] = []
        for index, finding in enumerate(findings):
            _validate_finding(finding, label=f"findings[{index}]")
            ids.append(finding["id"])
        if ids != sorted(set(ids)):
            raise FindingsValidationError("finding ids must be sorted and unique")
        serialized = json.dumps(ledger, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(serialized) > MAX_LEDGER_BYTES:
            raise FindingsValidationError(f"findings ledger exceeds {MAX_LEDGER_BYTES} bytes")
    except ValidationError as exc:
        raise FindingsValidationError(str(exc)) from exc


def _resolve_finding(
    ledger: Any,
    finding_id: str,
    *,
    status: str,
    resolution: str,
    evidence: Iterable[str],
    updated_at: str,
) -> dict[str, Any]:
    validate_findings_ledger(ledger)
    checked_id = _require_safe_id(finding_id, label="finding id")
    checked_resolution = _safe_text(resolution, label="finding.resolution", maximum=500)
    additions = _evidence_array(evidence, label="finding resolution evidence", require_nonempty=True)
    _require_timestamp(updated_at, label="finding.updatedAt")
    updated = copy.deepcopy(ledger)
    for item in updated["findings"]:
        if item["id"] != checked_id:
            continue
        if item["status"] != "open":
            raise FindingTransitionError(f"finding is already terminal: {checked_id}")
        merged = item["evidence"] + additions
        if len(merged) > MAX_EVIDENCE:
            raise FindingsValidationError(f"finding evidence may contain at most {MAX_EVIDENCE} items")
        item["status"] = status
        item["resolution"] = checked_resolution
        item["evidence"] = merged
        item["updatedAt"] = updated_at
        validate_findings_transition(ledger, updated)
        return updated
    raise FindingLookupError(f"finding not found: {checked_id}")


def _validate_finding(value: Any, *, label: str) -> None:
    item = require_object(value, label=label)
    require_exact_keys(
        item,
        {"id", "severity", "title", "status", "evidence", "resolution", "createdAt", "updatedAt", "sourceOfTruth"},
        label=label,
    )
    require_safe_id(item["id"], label=f"{label}.id")
    if item["severity"] not in SEVERITIES:
        raise FindingsValidationError(f"{label}.severity is invalid")
    _safe_text(item["title"], label=f"{label}.title", maximum=160)
    if item["status"] not in STATUSES:
        raise FindingsValidationError(f"{label}.status is invalid")
    _evidence_array(item["evidence"], label=f"{label}.evidence", require_nonempty=True)
    if item["status"] == "open":
        if item["resolution"] is not None:
            raise FindingsValidationError(f"{label}.resolution must be null while open")
    else:
        _safe_text(item["resolution"], label=f"{label}.resolution", maximum=500)
    created = _require_timestamp(item["createdAt"], label=f"{label}.createdAt")
    updated = _require_timestamp(item["updatedAt"], label=f"{label}.updatedAt")
    if updated < created:
        raise FindingsValidationError(f"{label}.updatedAt precedes createdAt")
    if item["sourceOfTruth"] is not False:
        raise FindingsValidationError(f"{label}.sourceOfTruth must be false")


def _evidence_array(values: Iterable[str], *, label: str, require_nonempty: bool) -> list[str]:
    if isinstance(values, (str, bytes)):
        raise FindingsValidationError(f"{label} must be an array")
    items = [_safe_text(value, label=f"{label}[{index}]", maximum=300) for index, value in enumerate(values)]
    if require_nonempty and not items:
        raise FindingsValidationError(f"{label} must not be empty")
    if len(items) > MAX_EVIDENCE or len(items) != len(set(items)):
        raise FindingsValidationError(f"{label} must contain at most {MAX_EVIDENCE} unique items")
    return items


def _safe_text(value: Any, *, label: str, maximum: int) -> str:
    try:
        text = require_string(value, label=label, maximum=maximum).strip()
        reject_sensitive_text(text, label=label)
    except ValidationError as exc:
        raise FindingsValidationError(str(exc)) from exc
    if not text:
        raise FindingsValidationError(f"{label} must not be blank")
    return text


def _require_timestamp(value: Any, *, label: str) -> datetime:
    try:
        text = require_string(value, label=label, maximum=64)
    except ValidationError as exc:
        raise FindingsValidationError(str(exc)) from exc
    parseable = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(parseable)
    except ValueError as exc:
        raise FindingsValidationError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise FindingsValidationError(f"{label} must include a timezone")
    return parsed


def _require_safe_id(value: Any, *, label: str) -> str:
    try:
        return require_safe_id(value, label=label)
    except ValidationError as exc:
        raise FindingsValidationError(str(exc)) from exc
