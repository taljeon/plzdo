from __future__ import annotations

import re
from typing import Any, Iterable


class ValidationError(ValueError):
    pass


SAFE_ID = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
URL = re.compile(r"\b(?:https?|file|ftp)://", re.IGNORECASE)
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
HOSTNAME = re.compile(r"\b(?:[A-Za-z0-9-]+\.)+(?:corp|internal|lan|local)\b", re.IGNORECASE)
ABSOLUTE_POSIX_PATH = re.compile(r"(?<!/)/(?!/)")
ABSOLUTE_WINDOWS_PATH = re.compile(r"[A-Za-z]:\\")
SENSITIVE_TOKEN_PATTERNS = (
    re.compile(r"\b" + "sk" + r"-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b" + "ghp" + r"_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub" + r"_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\b(?:" + "AK" + r"IA|" + "AS" + r"IA)[0-9A-Z]{16}\b"),
)
_CREDENTIAL_FIELD = re.compile(
    r"^(?:api[_-]?(?:key|token)|access[_-]?(?:key|token)|"
    r"auth[_-]?token|authorization|proxy[_-]?authorization|jwt|token|"
    r"client[_-]?secret|secret(?:[_-]?key)?|password|passwd|pwd|credentials?|"
    r"cookie|set[_-]?cookie|private[_-]?key|session(?:[_-]?(?:id|token))?|"
    r"aws[_-]?(?:access[_-]?key[_-]?id|secret[_-]?access[_-]?key|session[_-]?token)|"
    r"github[_-]?(?:pat|token))$",
    re.IGNORECASE,
)
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?<![A-Za-z0-9_])(?:export[ \t]+)?"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_-]{0,127})[ \t]*(?:=|:)[ \t]*[^\s,;]+",
    re.IGNORECASE,
)
_AUTHORIZATION_HEADER = re.compile(
    r"(?im)^\s*(?:authorization|proxy-authorization|x-api-key)\s*:"
)
_BEARER_TOKEN = re.compile(r"(?i)\bbearer[ \t]+[A-Za-z0-9._~+/=-]{8,}")
_JWT_TOKEN = re.compile(
    r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"
)
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN[ \t]+(?:[A-Z0-9]+[ \t]+)*PRIVATE[ \t]+KEY-----",
    re.IGNORECASE,
)


def require_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    return value


def require_exact_keys(value: dict[str, Any], keys: Iterable[str], *, label: str) -> None:
    expected = set(keys)
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValidationError(f"{label} keys mismatch: missing={missing}, extra={extra}")


def require_string(value: Any, *, label: str, minimum: int = 1, maximum: int = 500) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be a string")
    if len(value) < minimum or len(value) > maximum:
        raise ValidationError(f"{label} length must be between {minimum} and {maximum}")
    if "\x00" in value or any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValidationError(f"{label} contains a forbidden control character")
    return value


def require_safe_id(value: Any, *, label: str) -> str:
    text = require_string(value, label=label, maximum=64)
    if not SAFE_ID.fullmatch(text):
        raise ValidationError(f"{label} must match {SAFE_ID.pattern}")
    reject_credential_shapes(text, label=label)
    return text


def require_non_negative_int(value: Any, *, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValidationError(f"{label} must be a non-negative integer")
    return value


def is_credential_field_name(value: Any) -> bool:
    return isinstance(value, str) and _CREDENTIAL_FIELD.fullmatch(value) is not None


def reject_credential_shapes(value: str, *, label: str) -> None:
    """Reject common credential material without retaining or rendering it."""

    if not isinstance(value, str):
        raise ValidationError(f"{label} must be a string")
    if _PRIVATE_KEY_BLOCK.search(value):
        raise ValidationError(f"{label} contains a private-key shape")
    if any(pattern.search(value) for pattern in SENSITIVE_TOKEN_PATTERNS):
        raise ValidationError(f"{label} contains a credential shape")
    if _AUTHORIZATION_HEADER.search(value) or _BEARER_TOKEN.search(value) or _JWT_TOKEN.search(value):
        raise ValidationError(f"{label} contains a credential shape")
    if any(is_credential_field_name(match.group("key")) for match in _CREDENTIAL_ASSIGNMENT.finditer(value)):
        raise ValidationError(f"{label} contains a credential assignment")


def reject_credential_shapes_deep(value: Any, *, label: str) -> None:
    """Reject credential text and populated credential fields in nested JSON-like values."""

    _reject_credential_shapes_deep(value, label=label, seen=set())


def _reject_credential_shapes_deep(value: Any, *, label: str, seen: set[int]) -> None:
    if isinstance(value, str):
        reject_credential_shapes(value, label=label)
        return
    if not isinstance(value, (dict, list)):
        return
    identity = id(value)
    if identity in seen:
        raise ValidationError(f"{label} contains a recursive value")
    seen.add(identity)
    try:
        if isinstance(value, list):
            for index, item in enumerate(value):
                _reject_credential_shapes_deep(item, label=f"{label}[{index}]", seen=seen)
            return
        for index, (key, item) in enumerate(value.items()):
            if is_credential_field_name(key) and item is not None and item is not False and item != "":
                raise ValidationError(f"{label} contains a populated credential field")
            _reject_credential_shapes_deep(item, label=f"{label}.field[{index}]", seen=seen)
    finally:
        seen.remove(identity)


def reject_sensitive_text(value: str, *, label: str) -> None:
    reject_credential_shapes(value, label=label)
    private_paths = (
        "/" + "Users/",
        "/" + "home/",
        "C:" + "\\Users\\",
    )
    if any(marker in value for marker in private_paths):
        raise ValidationError(f"{label} contains a private path shape")
    if EMAIL.search(value):
        raise ValidationError(f"{label} contains an email shape")
    if URL.search(value) or IPV4.search(value) or HOSTNAME.search(value):
        raise ValidationError(f"{label} contains a network location shape")
    if ABSOLUTE_POSIX_PATH.search(value) or ABSOLUTE_WINDOWS_PATH.search(value):
        raise ValidationError(f"{label} contains an absolute path shape")
