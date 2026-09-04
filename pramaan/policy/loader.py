"""Policy loading and content identity.

Identity is derived from the VALIDATED, canonicalised policy - never from raw
file bytes. Reformatting a policy document (whitespace, key order) must not
change what the policy IS; changing a bound must.

Canonicalisation reuses pramaan.core.verify.canonical so there is exactly one
canonical-identity implementation in the repository.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

from pydantic import ValidationError

from ..core.verify.canonical import canonicalise
from .schema import Policy

DEFAULT_POLICY_PATH = pathlib.Path(__file__).parent / "default_policy.json"


class PolicyError(Exception):
    """Base for policy loading failures."""


class InvalidPolicy(PolicyError):
    """The document is not a valid policy."""


class PolicyNotFound(PolicyError):
    """No policy document at the requested location."""


def canonical_policy(policy: Policy) -> str:
    """The exact string whose bytes define this policy's identity."""
    return canonicalise(policy.model_dump(mode="json"))


def policy_hash(policy: Policy) -> str:
    return hashlib.sha256(canonical_policy(policy).encode("utf-8")).hexdigest()


def policy_identity(policy: Policy) -> str:
    """Human-readable label bound to content hash. The hash is the identity;
    the label is a convenience that cannot drift away from it."""
    return f"{policy.policy_id}@{policy.label}+{policy_hash(policy)[:16]}"


def parse_policy(raw: object) -> Policy:
    """Validate an already-decoded document into the closed representation."""
    if not isinstance(raw, dict):
        raise InvalidPolicy(f"policy must be an object, got {type(raw).__name__}")
    try:
        return Policy.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        raise InvalidPolicy(f"{loc}: {first['msg']}") from exc


def load_policy(path: str | pathlib.Path | None = None,
                base_dir: pathlib.Path | None = None) -> Policy:
    """Load and validate a policy document.

    When `base_dir` is given, `path` is confined beneath it - policy paths may
    come from configuration, and `../../etc/passwd` must not resolve.
    """
    target = pathlib.Path(path) if path is not None else DEFAULT_POLICY_PATH

    if base_dir is not None:
        root = pathlib.Path(base_dir).resolve()
        resolved = (root / target).resolve() if not target.is_absolute() else target.resolve()
        if root != resolved and root not in resolved.parents:
            raise InvalidPolicy(
                f"policy path escapes base directory: {target}")
        target = resolved

    if not target.is_file():
        raise PolicyNotFound(f"no policy document at {target}")

    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InvalidPolicy(f"{target.name}: malformed JSON: {exc}") from exc

    return parse_policy(raw)


def load_default_policy() -> Policy:
    return load_policy(DEFAULT_POLICY_PATH)
