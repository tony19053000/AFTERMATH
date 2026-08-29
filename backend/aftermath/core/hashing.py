"""Canonical serialization and content hashing.

Evidence integrity depends on two traces that mean the same thing hashing the
same, and two that differ hashing differently. That requires a canonical form:
sorted keys, no incidental whitespace, and a fixed representation for every
scalar type.

Wall-clock values are deliberately *excluded* from semantic hashes by the trace
layer (see `core.trace`), because re-running the same scenario with the same
seed produces identical content at different times. A hash that changed with the
clock would be useless for verifying replay fidelity in P4.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

HASH_PREFIX = "sha256:"


def _default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=repr)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"cannot canonicalize {type(value).__name__}")


def canonical_json(payload: Any) -> str:
    """Serialize to a stable, canonical JSON string.

    Keys are sorted and separators are tight, so logically identical payloads
    always produce byte-identical output.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_default,
    )


def content_hash(payload: Any) -> str:
    """Return ``sha256:<hex>`` over the canonical form of ``payload``."""
    encoded = canonical_json(payload).encode("utf-8")
    return HASH_PREFIX + hashlib.sha256(encoded).hexdigest()


def hash_file(path: str) -> str:
    """Return ``sha256:<hex>`` over a file's bytes, read incrementally."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return HASH_PREFIX + digest.hexdigest()
