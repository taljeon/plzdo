from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any, Iterable, Optional

from .validation import (
    ValidationError,
    require_exact_keys,
    require_non_negative_int,
    require_object,
    require_safe_id,
    require_string,
)


SCHEMA_VERSION = "plzdo-local.metric.v1"
STATUSES = ("succeeded", "failed", "skipped", "blocked")
ROUTES = ("quick", "plan", "goal")
ROUTE_FEEDBACK = ("correct", "under-routed", "over-routed")
MAX_RECORDS = 2_048
MAX_SERIALIZED_BYTES = 1_048_576
MAX_DURATION_MS = 7 * 24 * 60 * 60 * 1000


class MetricsError(ValueError):
    pass


class MetricsValidationError(MetricsError):
    pass


def build_metric(
    *,
    run_id: str,
    project_id: Optional[str],
    route: str,
    bounded_loop: bool,
    status: str,
    route_feedback: str,
    duration_ms: int,
    changed_file_count: int,
    check_count: int,
    finding_count: int,
    recorded_at: str,
) -> dict[str, Any]:
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run_id,
        "projectId": project_id,
        "route": route,
        "boundedLoop": bounded_loop,
        "status": status,
        "routeFeedback": route_feedback,
        "durationMs": duration_ms,
        "changedFileCount": changed_file_count,
        "checkCount": check_count,
        "findingCount": finding_count,
        "recordedAt": recorded_at,
        "sourceOfTruth": False,
    }
    validate_metric(record)
    return record


def validate_metric(value: Any) -> None:
    try:
        record = require_object(value, label="metric")
        require_exact_keys(
            record,
            {
                "schemaVersion",
                "runId",
                "projectId",
                "route",
                "boundedLoop",
                "status",
                "routeFeedback",
                "durationMs",
                "changedFileCount",
                "checkCount",
                "findingCount",
                "recordedAt",
                "sourceOfTruth",
            },
            label="metric",
        )
        if record["schemaVersion"] != SCHEMA_VERSION or record["sourceOfTruth"] is not False:
            raise MetricsValidationError("metric schema or authority is invalid")
        require_safe_id(record["runId"], label="metric.runId")
        if record["projectId"] is not None:
            require_safe_id(record["projectId"], label="metric.projectId")
        if record["route"] not in ROUTES:
            raise MetricsValidationError(f"metric.route must be one of {list(ROUTES)}")
        if type(record["boundedLoop"]) is not bool:
            raise MetricsValidationError("metric.boundedLoop must be a boolean")
        if record["status"] not in STATUSES:
            raise MetricsValidationError(f"metric.status must be one of {list(STATUSES)}")
        if record["routeFeedback"] not in ROUTE_FEEDBACK:
            raise MetricsValidationError(f"metric.routeFeedback must be one of {list(ROUTE_FEEDBACK)}")
        duration = require_non_negative_int(record["durationMs"], label="metric.durationMs")
        if duration > MAX_DURATION_MS:
            raise MetricsValidationError(f"metric.durationMs exceeds {MAX_DURATION_MS}")
        for field in ("changedFileCount", "checkCount", "findingCount"):
            count = require_non_negative_int(record[field], label=f"metric.{field}")
            if count > 100_000:
                raise MetricsValidationError(f"metric.{field} exceeds 100000")
        _require_timestamp(record["recordedAt"], label="metric.recordedAt")
    except ValidationError as exc:
        raise MetricsValidationError(str(exc)) from exc


def serialize_metrics(records: Iterable[dict[str, Any]]) -> str:
    items = [copy.deepcopy(record) for record in records]
    _validate_record_set(items)
    text = "".join(json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n" for record in items)
    if len(text.encode("utf-8")) > MAX_SERIALIZED_BYTES:
        raise MetricsValidationError(f"metrics stream exceeds {MAX_SERIALIZED_BYTES} bytes")
    return text


def parse_metrics(text: str) -> list[dict[str, Any]]:
    if not isinstance(text, str):
        raise MetricsValidationError("metrics stream must be text")
    if len(text.encode("utf-8")) > MAX_SERIALIZED_BYTES:
        raise MetricsValidationError(f"metrics stream exceeds {MAX_SERIALIZED_BYTES} bytes")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line:
            raise MetricsValidationError(f"metrics line {line_number} is blank")
        try:
            value = json.loads(line, object_pairs_hook=_json_object_without_duplicates)
        except (json.JSONDecodeError, MetricsValidationError) as exc:
            raise MetricsValidationError(f"metrics line {line_number} is invalid") from exc
        validate_metric(value)
        records.append(value)
    _validate_record_set(records)
    return records


def append_metric(records: Iterable[dict[str, Any]], record: dict[str, Any]) -> list[dict[str, Any]]:
    current = [copy.deepcopy(item) for item in records]
    _validate_record_set(current)
    validate_metric(record)
    updated = current + [copy.deepcopy(record)]
    _validate_record_set(updated)
    serialize_metrics(updated)
    return updated


def summarize_metrics(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = [copy.deepcopy(item) for item in records]
    _validate_record_set(items)
    status_counts = {status: 0 for status in STATUSES}
    route_counts = {route: 0 for route in ROUTES}
    feedback_counts = {feedback: 0 for feedback in ROUTE_FEEDBACK}
    total_duration = 0
    for item in items:
        status_counts[item["status"]] += 1
        route_counts[item["route"]] += 1
        feedback_counts[item["routeFeedback"]] += 1
        total_duration += item["durationMs"]
    return {
        "schemaVersion": "plzdo-local.metrics-summary.v1",
        "sourceOfTruth": False,
        "runCount": len(items),
        "statusCounts": status_counts,
        "routeCounts": route_counts,
        "routeFeedbackCounts": feedback_counts,
        "totalDurationMs": total_duration,
    }


def _validate_record_set(records: list[dict[str, Any]]) -> None:
    if len(records) > MAX_RECORDS:
        raise MetricsValidationError(f"metrics may contain at most {MAX_RECORDS} records")
    run_ids: set[str] = set()
    order: list[tuple[datetime, str]] = []
    for record in records:
        validate_metric(record)
        if record["runId"] in run_ids:
            raise MetricsValidationError("metric run ids must be unique")
        run_ids.add(record["runId"])
        order.append((_require_timestamp(record["recordedAt"], label="metric.recordedAt"), record["runId"]))
    if order != sorted(order):
        raise MetricsValidationError("metrics must be ordered by recordedAt and runId")


def _json_object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise MetricsValidationError("metric JSON contains a duplicate key")
        value[key] = item
    return value


def _require_timestamp(value: Any, *, label: str) -> datetime:
    text = require_string(value, label=label, maximum=64)
    parseable = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(parseable)
    except ValueError as exc:
        raise MetricsValidationError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise MetricsValidationError(f"{label} must include a timezone")
    return parsed
