"""Deterministic, credential-free authoritative state.

The default provider for tests, the demo and local development. Everything it
returns is labelled SIMULATED and must be shown that way.
"""

import copy
import json
from datetime import datetime, timezone

from .contract import AuthoritativeState, StateRequest, StateSource
from .errors import StateUnavailable

# Scenario name -> zero-argument factory returning primitive state.
# Imported lazily inside the default builder so importing this module never
# drags in anything heavier than the stdlib.


def _default_scenarios() -> dict:
    from ..fixtures import scenarios as fx
    return {
        "final_attempt": fx.state_final_attempt,
        "first_attempt": fx.state_first_attempt,
    }


class FixtureStateProvider:
    """Serves hand-written state. Never touches a network."""

    name = "fixture"

    def __init__(self, scenarios: dict | None = None,
                 retrieved_at: str | None = None):
        self._scenarios = dict(scenarios) if scenarios is not None else _default_scenarios()
        # Fixed by default so two evaluations of the same scenario are
        # byte-identical, which the snapshot-identity tests depend on.
        self._retrieved_at = retrieved_at

    def available(self) -> list[str]:
        return sorted(self._scenarios)

    def get_state(self, request: StateRequest) -> AuthoritativeState:
        key = request.scenario
        if key not in self._scenarios:
            raise StateUnavailable(
                f"no fixture scenario {key!r}; available: {self.available()}")

        produced = self._scenarios[key]
        state = produced() if callable(produced) else produced

        # Deep copy on the way out. A caller mutating the returned dict must not
        # be able to change what the next read sees.
        state = copy.deepcopy(state)

        stamp = self._retrieved_at or datetime.now(timezone.utc).isoformat()
        return AuthoritativeState(state=state, source=StateSource.SIMULATED,
                                  provider=self.name, retrieved_at=stamp)


class RecordingProvider:
    """Wraps a provider and counts calls.

    Used by the tests that enforce ONE state acquisition per evaluation. Kept in
    the package rather than the test file so the pipeline's single-fetch
    invariant can be checked from anywhere, including the demo scripts.
    """

    def __init__(self, inner):
        self._inner = inner
        self.calls = 0
        self.name = f"recording({getattr(inner, 'name', '?')})"

    def get_state(self, request: StateRequest) -> AuthoritativeState:
        self.calls += 1
        return self._inner.get_state(request)


class SequenceProvider:
    """Returns a different state on each successive call.

    If the pipeline ever fetched twice, evidence resolution would silently use
    the second state. This provider makes that failure visible instead: the
    proof must reflect only the FIRST state.
    """

    name = "sequence"

    def __init__(self, states: list[dict]):
        self._states = [copy.deepcopy(s) for s in states]
        self.calls = 0

    def get_state(self, request: StateRequest) -> AuthoritativeState:
        if self.calls >= len(self._states):
            raise StateUnavailable("sequence exhausted")
        state = copy.deepcopy(self._states[self.calls])
        self.calls += 1
        return AuthoritativeState(state=state, source=StateSource.SIMULATED,
                                  provider=self.name,
                                  retrieved_at="2026-09-04T10:00:00+00:00")


def state_fingerprint(state: dict) -> str:
    """Stable string for asserting which state a proof actually used."""
    return json.dumps(state, sort_keys=True, separators=(",", ":"))
