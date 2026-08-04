from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from .validation import (
    ValidationError,
    reject_sensitive_text,
    require_exact_keys,
    require_object,
    require_safe_id,
    require_string,
)


SCHEMA_VERSION = "plzdo-local.memory.v1"
ITEM_STATES = ("active", "superseded")
MAX_ITEMS = 256
MAX_SUMMARY_BYTES = 1_200
MAX_STORE_BYTES = 262_144
MAX_SEARCH_RESULTS = 20

_RAW_LOG_LINE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}|\[[A-Z]{3,8}\]|(?:TRACE|DEBUG|INFO|WARN|ERROR)\b)",
    re.MULTILINE,
)


class MemoryError(ValueError):
    pass


class MemoryValidationError(MemoryError):
    pass


class MemoryLookupError(MemoryError):
    pass


def build_memory_store() -> dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "sourceOfTruth": False, "items": []}


def add_memory(
    store: Any,
    *,
    label: str,
    domain: str,
    summary: str,
    created_at: str,
) -> dict[str, Any]:
    validate_memory_store(store)
    checked_label = _safe_memory_text(label, label="memory.label", maximum=80)
    checked_domain = _require_safe_id(domain, label="memory.domain")
    checked_summary = _safe_summary(summary)
    created = _normalize_timestamp(created_at, label="memory.createdAt")
    stable_key = stable_memory_key(checked_label, checked_domain)
    item_id = _memory_item_id(stable_key, checked_summary, created)

    updated = copy.deepcopy(store)
    superseded_id: Optional[str] = None
    for item in updated["items"]:
        if item["stableKey"] == stable_key and item["state"] == "active":
            item["state"] = "superseded"
            superseded_id = item["id"]
    item = {
        "id": item_id,
        "stableKey": stable_key,
        "label": checked_label,
        "domain": checked_domain,
        "summary": checked_summary,
        "state": "active",
        "supersedes": superseded_id,
        "createdAt": created,
        "sourceOfTruth": False,
    }
    if any(existing["id"] == item_id for existing in updated["items"]):
        raise MemoryValidationError("memory item already exists")
    updated["items"].append(item)
    updated["items"].sort(
        key=lambda value: (
            _parse_timestamp(value["createdAt"], label="memory.createdAt"),
            value["id"],
        )
    )
    validate_memory_store(updated)
    return updated


def search_memory(store: Any, query: str, *, limit: int = MAX_SEARCH_RESULTS) -> list[dict[str, Any]]:
    validate_memory_store(store)
    try:
        checked_query = require_string(query, label="memory query", maximum=200).strip().casefold()
    except ValidationError as exc:
        raise MemoryValidationError(str(exc)) from exc
    if not checked_query:
        raise MemoryValidationError("memory query must not be blank")
    if type(limit) is not int or limit < 1 or limit > MAX_SEARCH_RESULTS:
        raise MemoryValidationError(f"memory search limit must be between 1 and {MAX_SEARCH_RESULTS}")
    terms = tuple(dict.fromkeys(checked_query.split()))
    ranked: list[tuple[int, datetime, str, dict[str, Any]]] = []
    for item in store["items"]:
        if item["state"] != "active":
            continue
        searchable = " ".join((item["label"], item["domain"], item["summary"])).casefold()
        score = sum(1 for term in terms if term in searchable)
        if score:
            ranked.append(
                (
                    score,
                    _parse_timestamp(item["createdAt"], label="memory.createdAt"),
                    item["id"],
                    item,
                )
            )
    ranked.sort(key=lambda value: (-value[0], value[1], value[2]))
    return [copy.deepcopy(item) for _, _, _, item in ranked[:limit]]


def purge_memory(
    store: Any,
    *,
    purge_all: bool = False,
    stable_key: Optional[str] = None,
) -> tuple[dict[str, Any], int]:
    validate_memory_store(store)
    if type(purge_all) is not bool:
        raise MemoryValidationError("purge_all must be a boolean")
    if purge_all == (stable_key is not None):
        raise MemoryValidationError("choose exactly one of purge_all or stable_key")
    if stable_key is not None:
        _require_safe_id(stable_key, label="memory stable key")
    updated = copy.deepcopy(store)
    before = len(updated["items"])
    updated["items"] = [] if purge_all else [item for item in updated["items"] if item["stableKey"] != stable_key]
    removed = before - len(updated["items"])
    validate_memory_store(updated)
    return updated, removed


def stable_memory_key(label: str, domain: str) -> str:
    checked_label = _safe_memory_text(label, label="memory.label", maximum=80)
    checked_domain = _require_safe_id(domain, label="memory.domain")
    digest = hashlib.sha256(f"{checked_domain}\0{checked_label.casefold()}".encode("utf-8")).hexdigest()[:20]
    return f"mem-{digest}"


def validate_memory_store(value: Any) -> None:
    try:
        store = require_object(value, label="memory store")
        require_exact_keys(store, {"schemaVersion", "sourceOfTruth", "items"}, label="memory store")
        if store["schemaVersion"] != SCHEMA_VERSION or store["sourceOfTruth"] is not False:
            raise MemoryValidationError("memory store schema or authority is invalid")
        items = store["items"]
        if not isinstance(items, list) or len(items) > MAX_ITEMS:
            raise MemoryValidationError(f"memory items must be an array of at most {MAX_ITEMS} items")
        ids: set[str] = set()
        active_keys: set[str] = set()
        all_keys: set[str] = set()
        order: list[tuple[datetime, str]] = []
        by_id: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(items):
            _validate_memory_item(item, label=f"memory.items[{index}]")
            if item["id"] in ids:
                raise MemoryValidationError("memory item ids must be unique")
            ids.add(item["id"])
            by_id[item["id"]] = item
            all_keys.add(item["stableKey"])
            if item["state"] == "active":
                if item["stableKey"] in active_keys:
                    raise MemoryValidationError("memory stable keys may have only one active item")
                active_keys.add(item["stableKey"])
            order.append((_parse_timestamp(item["createdAt"], label="memory.createdAt"), item["id"]))
        if order != sorted(order):
            raise MemoryValidationError("memory items must be ordered by createdAt and id")
        referenced: set[str] = set()
        for item in items:
            supersedes = item["supersedes"]
            if supersedes is None:
                continue
            previous = by_id.get(supersedes)
            if previous is None or previous["stableKey"] != item["stableKey"]:
                raise MemoryValidationError("memory supersedes must reference the same stable key")
            if previous["state"] != "superseded":
                raise MemoryValidationError("a superseded memory reference must point to a superseded item")
            if _parse_timestamp(
                previous["createdAt"], label="previous memory.createdAt"
            ) >= _parse_timestamp(item["createdAt"], label="memory.createdAt"):
                raise MemoryValidationError("memory supersession must move forward in time")
            if supersedes in referenced:
                raise MemoryValidationError("memory items may be superseded only once")
            referenced.add(supersedes)
        superseded_ids = {item["id"] for item in items if item["state"] == "superseded"}
        if referenced != superseded_ids:
            raise MemoryValidationError("every superseded memory item must have one successor")
        if active_keys != all_keys:
            raise MemoryValidationError("every memory stable key must have exactly one active item")
        _require_bounded_store(store)
    except ValidationError as exc:
        raise MemoryValidationError(str(exc)) from exc


def _validate_memory_item(value: Any, *, label: str) -> None:
    item = require_object(value, label=label)
    require_exact_keys(
        item,
        {"id", "stableKey", "label", "domain", "summary", "state", "supersedes", "createdAt", "sourceOfTruth"},
        label=label,
    )
    require_safe_id(item["id"], label=f"{label}.id")
    require_safe_id(item["stableKey"], label=f"{label}.stableKey")
    checked_label = _safe_memory_text(item["label"], label=f"{label}.label", maximum=80)
    checked_domain = _require_safe_id(item["domain"], label=f"{label}.domain")
    checked_summary = _safe_summary(item["summary"])
    if item["label"] != checked_label or item["summary"] != checked_summary:
        raise MemoryValidationError(f"{label} text fields must be stored in canonical trimmed form")
    if item["state"] not in ITEM_STATES:
        raise MemoryValidationError(f"{label}.state is invalid")
    if item["supersedes"] is not None:
        require_safe_id(item["supersedes"], label=f"{label}.supersedes")
    created = _require_timestamp(item["createdAt"], label=f"{label}.createdAt")
    expected_stable_key = stable_memory_key(checked_label, checked_domain)
    if item["stableKey"] != expected_stable_key:
        raise MemoryValidationError(f"{label}.stableKey does not match label and domain")
    if item["id"] != _memory_item_id(expected_stable_key, checked_summary, created):
        raise MemoryValidationError(f"{label}.id does not match stable content")
    if item["sourceOfTruth"] is not False:
        raise MemoryValidationError(f"{label}.sourceOfTruth must be false")


def _safe_memory_text(value: Any, *, label: str, maximum: int) -> str:
    try:
        text = require_string(value, label=label, maximum=maximum).strip()
        reject_sensitive_text(text, label=label)
    except ValidationError as exc:
        raise MemoryValidationError(str(exc)) from exc
    if not text:
        raise MemoryValidationError(f"{label} must not be blank")
    return text


def _safe_summary(value: Any) -> str:
    text = _safe_memory_text(value, label="memory.summary", maximum=MAX_SUMMARY_BYTES)
    if len(text.encode("utf-8")) > MAX_SUMMARY_BYTES:
        raise MemoryValidationError(f"memory.summary exceeds {MAX_SUMMARY_BYTES} bytes")
    if text.count("\n") > 8 or len(_RAW_LOG_LINE.findall(text)) > 2:
        raise MemoryValidationError("memory.summary resembles a raw log or full document")
    if "Traceback (most recent call last)" in text:
        raise MemoryValidationError("memory.summary resembles sensitive raw output")
    return text


def _memory_item_id(stable_key: str, summary: str, created_at: str) -> str:
    digest = hashlib.sha256(f"{stable_key}\0{created_at}\0{summary}".encode("utf-8")).hexdigest()[:24]
    return f"note-{digest}"


def _normalize_timestamp(value: Any, *, label: str) -> str:
    try:
        text = require_string(value, label=label, maximum=64)
    except ValidationError as exc:
        raise MemoryValidationError(str(exc)) from exc
    parseable = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(parseable)
    except ValueError as exc:
        raise MemoryValidationError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MemoryValidationError(f"{label} must include a timezone")
    utc = parsed.astimezone(timezone.utc)
    timespec = "microseconds" if utc.microsecond else "seconds"
    return utc.isoformat(timespec=timespec).replace("+00:00", "Z")


def _require_timestamp(value: Any, *, label: str) -> str:
    normalized = _normalize_timestamp(value, label=label)
    if value != normalized:
        raise MemoryValidationError(f"{label} must be canonical UTC RFC 3339")
    return normalized


def _parse_timestamp(value: str, *, label: str) -> datetime:
    normalized = _require_timestamp(value, label=label)
    return datetime.fromisoformat(normalized[:-1] + "+00:00")


def _require_safe_id(value: Any, *, label: str) -> str:
    try:
        return require_safe_id(value, label=label)
    except ValidationError as exc:
        raise MemoryValidationError(str(exc)) from exc


def _require_bounded_store(store: dict[str, Any]) -> None:
    serialized = json.dumps(store, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(serialized) > MAX_STORE_BYTES:
        raise MemoryValidationError(f"memory store exceeds {MAX_STORE_BYTES} bytes")
