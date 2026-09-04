"""Deterministic snapshot identity.

Canonicalisation follows RFC 8785 (JSON Canonicalization Scheme) in the parts
that matter here: keys sorted, no insignificant whitespace, UTF-8 output.
Two deliberate additions:

  - every string is NFC-normalised before hashing, so visually identical text
    cannot hash differently;
  - floats are REJECTED outright. Money is integer minor units and percentages
    are decimal strings, which sidesteps RFC 8785's number-formatting rules
    entirely - they are the fragile part of any canonicalisation scheme.

Lists keep source order. Order is meaningful, so callers sort at capture time
(offers by offer_id) rather than relying on the hasher to do it.
"""

import hashlib
import json
import unicodedata
from typing import Any


class NonCanonicalisable(TypeError):
    """A value that has no stable canonical form reached the hasher."""


def _canon(value: Any) -> Any:
    if isinstance(value, float):
        raise NonCanonicalisable(
            "float is not canonicalisable; use integer minor units for money "
            "and decimal strings for percentages")
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        for k in value:
            if not isinstance(k, str):
                raise NonCanonicalisable(f"non-string object key: {k!r}")
        return {unicodedata.normalize("NFC", k): _canon(v)
                for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    raise NonCanonicalisable(f"unsupported type in snapshot: {type(value).__name__}")


def canonicalise(obj: Any) -> str:
    """Return the exact string whose bytes are hashed. Store this verbatim -
    replay must never re-serialise, only re-read."""
    return json.dumps(_canon(obj), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def snapshot_hash(obj: Any) -> str:
    return hashlib.sha256(canonicalise(obj).encode("utf-8")).hexdigest()


def content_hash(text: str) -> str:
    return hashlib.sha256(
        unicodedata.normalize("NFC", text).encode("utf-8")).hexdigest()
