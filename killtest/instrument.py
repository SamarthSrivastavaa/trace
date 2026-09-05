"""Per-call accounting for the kill test.

Pure observability. Nothing here feeds back into inference, alters a prompt,
reorders cases, or changes any arm's output - a CallRecord is written after the
call has already returned.

A metric the provider does not supply is recorded as None and reported as
UNAVAILABLE. It is never estimated.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field


@dataclass
class CallRecord:
    arm: str
    case_id: str
    split: str
    model: str
    ok: bool
    failure_class: str = ""          # "" | PARSE | SCHEMA | TRANSPORT | TIMEOUT | NOT_CONFIGURED
    failure_detail: str = ""
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    # The Anthropic SDK retries internally (default max_retries=2) and does not
    # expose an attempt count on the response, so this stays None -> UNAVAILABLE
    # rather than being guessed.
    retries: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens


class Ledger:
    """Collects CallRecords and writes them out verbatim."""

    def __init__(self):
        self.records: list[CallRecord] = []

    def add(self, record: CallRecord) -> CallRecord:
        self.records.append(record)
        return record

    def for_arm(self, arm: str) -> list[CallRecord]:
        return [r for r in self.records if r.arm == arm]

    def latencies(self, arm: str) -> list[float]:
        return [r.latency_ms for r in self.for_arm(arm)
                if r.latency_ms is not None]

    def token_total(self, arm: str, field_name: str) -> int | None:
        vals = [getattr(r, field_name) for r in self.for_arm(arm)
                if getattr(r, field_name) is not None]
        return sum(vals) if vals else None

    def write(self, path) -> None:
        payload = [asdict(r) | {"total_tokens": r.total_tokens}
                   for r in self.records]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)


class RecordingTransport:
    """Wraps a production Transport and records accounting for each call.

    It forwards system/user through UNCHANGED and returns the response
    UNCHANGED, so the wrapped arm behaves exactly as it would unwrapped.
    """

    def __init__(self, inner, ledger: Ledger, arm: str):
        self._inner, self._ledger, self._arm = inner, ledger, arm
        self.name = getattr(inner, "name", "unknown")
        self.model = getattr(inner, "model", "")
        self.case_id = ""
        self.split = ""

    def send(self, system: str, user: str):
        started = time.monotonic()
        try:
            response = self._inner.send(system, user)
        except Exception as exc:
            self._ledger.add(CallRecord(
                arm=self._arm, case_id=self.case_id, split=self.split,
                model=self.model, ok=False,
                failure_class=classify(exc), failure_detail=f"{type(exc).__name__}",
                latency_ms=(time.monotonic() - started) * 1000.0))
            raise
        self._ledger.add(CallRecord(
            arm=self._arm, case_id=self.case_id, split=self.split,
            model=response.model or self.model, ok=True,
            latency_ms=response.latency_ms if response.latency_ms is not None
            else (time.monotonic() - started) * 1000.0,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens))
        return response


def classify(exc: Exception) -> str:
    """Map a proposer exception to a failure class.

    Keeps model-output failures separate from infrastructure failures - the
    whole point of the taxonomy in attest.llm.errors.
    """
    from attest.llm.errors import (ProposerMalformedOutput,
                                    ProposerNotConfigured,
                                    ProposerSchemaViolation, ProposerTimeout,
                                    ProposerTransportFailure)
    if isinstance(exc, ProposerSchemaViolation):
        return "SCHEMA"
    if isinstance(exc, ProposerMalformedOutput):
        return "PARSE"
    if isinstance(exc, ProposerTimeout):
        return "TIMEOUT"
    if isinstance(exc, ProposerNotConfigured):
        return "NOT_CONFIGURED"
    if isinstance(exc, ProposerTransportFailure):
        return "TRANSPORT"
    return "OTHER"


def summarise(values: list[float]) -> dict:
    """median / mean / p95. p95 is UNAVAILABLE below 20 samples, where a single
    observation would move it by more than 5 percentage points."""
    if not values:
        return {"n": 0, "median": None, "mean": None, "p95": None}
    ordered = sorted(values)
    n = len(ordered)
    median = (ordered[n // 2] if n % 2
              else (ordered[n // 2 - 1] + ordered[n // 2]) / 2)
    p95 = ordered[min(n - 1, int(round(0.95 * n)) - 1)] if n >= 20 else None
    return {"n": n, "median": median, "mean": sum(ordered) / n, "p95": p95}
