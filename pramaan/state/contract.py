"""The authoritative-state boundary.

External data becomes ordinary primitives HERE and nowhere later. No SDK
objects, no ORM rows, no custom classes reach canonicalisation or adjudication
- a crafted object with an overloaded __eq__ once executed inside the trusted
comparison path, and this boundary is one of the places that stays closed.

A provider FETCHES state. It never decides what the state supports.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from .errors import MalformedProviderState

PRIMITIVES = (str, int, bool, type(None))
MAX_DEPTH = 12


class StateSource(str, Enum):
    """Provenance. Closed set - fixture state must never be labelled live."""
    SIMULATED = "SIMULATED"
    LIVE = "LIVE"


@dataclass(frozen=True)
class StateRequest:
    """Only what is genuinely needed to retrieve state. No speculative fields."""
    merchant_id: str
    customer_id: str
    scenario: str | None = None      # fixture selector; ignored by live providers


@dataclass(frozen=True)
class AuthoritativeState:
    """What a provider returns. `state` is plain JSON-like primitives."""
    state: dict
    source: StateSource
    provider: str                     # stable identifier, recorded in the proof
    retrieved_at: str                 # ISO-8601 with offset; audit metadata only

    def __post_init__(self) -> None:
        require_primitive_state(self.state)


@runtime_checkable
class AuthoritativeStateProvider(Protocol):
    """One operation. Deliberately not a plugin system."""

    name: str

    def get_state(self, request: StateRequest) -> AuthoritativeState:
        ...


def require_primitive_state(value: Any, _depth: int = 0, _path: str = "state") -> None:
    """Reject anything that is not JSON-like primitives, before it can reach
    canonicalisation or a comparison.

    float is rejected here as well as in canonical.py: money is integer minor
    units and percentages are decimal strings, so a float in authoritative
    state is always a bug rather than a value we should try to hash.
    """
    if _depth > MAX_DEPTH:
        raise MalformedProviderState(f"{_path}: nesting deeper than {MAX_DEPTH}")

    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return
    if isinstance(value, float):
        raise MalformedProviderState(
            f"{_path}: float is not permitted in authoritative state; use "
            "integer minor units for money and decimal strings for percentages")
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise MalformedProviderState(f"{_path}: non-string key {k!r}")
            require_primitive_state(v, _depth + 1, f"{_path}.{k}")
        return
    if isinstance(value, list):
        for i, v in enumerate(value):
            require_primitive_state(v, _depth + 1, f"{_path}[{i}]")
        return
    raise MalformedProviderState(
        f"{_path}: {type(value).__name__} is not a permitted state type")
