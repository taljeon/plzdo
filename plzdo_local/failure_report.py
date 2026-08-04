from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .atomic_io import atomic_write_json
from .validation import (
    ValidationError,
    require_exact_keys,
    require_non_negative_int,
    require_object,
    reject_sensitive_text,
    require_safe_id,
    require_string,
)


SCHEMA_VERSION = "plzdo-local.failure-report.v1"
MAX_DETAIL_IDS = 32
MAX_SERIALIZED_BYTES = 8192


def build_failure_report(
    *,
    operation: str,
    code: str,
    message: str,
    detail_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    details = list(detail_ids or [])
    if len(details) > MAX_DETAIL_IDS:
        raise ValidationError(f"detailIds must contain at most {MAX_DETAIL_IDS} items")
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "failed",
        "operation": require_safe_id(operation, label="operation"),
        "code": require_safe_id(code, label="code"),
        "message": require_string(message, label="message", maximum=300),
        "detailIds": details,
        "detailCount": len(details),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    validate_failure_report(report)
    return report


def validate_failure_report(value: Any) -> None:
    report = require_object(value, label="failure report")
    require_exact_keys(
        report,
        {
            "schemaVersion",
            "status",
            "operation",
            "code",
            "message",
            "detailIds",
            "detailCount",
            "createdAt",
        },
        label="failure report",
    )
    if report["schemaVersion"] != SCHEMA_VERSION or report["status"] != "failed":
        raise ValidationError("failure report schema or status is invalid")
    require_safe_id(report["operation"], label="operation")
    require_safe_id(report["code"], label="code")
    require_string(report["message"], label="message", maximum=300)
    reject_sensitive_text(report["message"], label="message")
    if not isinstance(report["detailIds"], list):
        raise ValidationError("detailIds must be an array")
    if len(report["detailIds"]) > MAX_DETAIL_IDS:
        raise ValidationError(f"detailIds must contain at most {MAX_DETAIL_IDS} items")
    for index, item in enumerate(report["detailIds"]):
        require_safe_id(item, label=f"detailIds[{index}]")
    count = require_non_negative_int(report["detailCount"], label="detailCount")
    if count != len(report["detailIds"]):
        raise ValidationError("detailCount does not match detailIds")
    created_at = require_string(report["createdAt"], label="createdAt", maximum=64)
    try:
        parsed = datetime.fromisoformat(created_at)
    except ValueError as exc:
        raise ValidationError("createdAt must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValidationError("createdAt must include a timezone")
    serialized = json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_SERIALIZED_BYTES:
        raise ValidationError(f"failure report exceeds {MAX_SERIALIZED_BYTES} bytes")


def write_failure_report(path: Path, report: dict[str, Any], *, allowed_root: Path) -> None:
    atomic_write_json(path, report, allowed_root=allowed_root, validator=validate_failure_report)
