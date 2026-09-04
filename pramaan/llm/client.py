"""The narrowest possible transport seam.

Everything above this file is testable without credentials, because the only
thing that touches the network is `AnthropicTransport.send`, which any fake can
replace.

The SDK is imported LAZILY inside send(). Importing this module requires no
`anthropic` package and no API key - tests/test_llm_adapter.py asserts that.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Protocol

from .errors import (ProposerNotConfigured, ProposerTimeout,
                     ProposerTransportFailure)

# Model and request defaults.
#
# NOTE ON temperature: Claude Opus 5 REMOVED the sampling parameters -
# temperature / top_p / top_k return a 400. Determinism is not something this
# adapter can request; it is obtained downstream, by making every verdict a
# deterministic function of the proposal rather than by pinning a sampler.
MODEL = "claude-opus-5"
MAX_TOKENS = 8000
EFFORT = "medium"
TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class TransportResponse:
    """What a transport returns: raw text plus provenance and accounting.

    The token/latency fields are OBSERVABILITY only - nothing downstream reads
    them, so they cannot influence inference or an arm's output. `None` means
    the provider did not supply the figure and must be reported as UNAVAILABLE;
    it is never estimated.
    """
    text: str
    model: str
    stop_reason: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None


class Transport(Protocol):
    """Replaceable seam. Fakes implement exactly this."""

    name: str

    def send(self, system: str, user: str) -> TransportResponse:
        ...


class AnthropicTransport:
    """Live Anthropic transport. Constructing it validates configuration."""

    name = "anthropic"

    def __init__(self, model: str = MODEL, max_tokens: int = MAX_TOKENS,
                 effort: str = EFFORT, timeout: float = TIMEOUT_SECONDS,
                 api_key: str | None = None):
        self.model, self.max_tokens = model, max_tokens
        self.effort, self.timeout = effort, timeout
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self._api_key:
            raise ProposerNotConfigured(
                "ANTHROPIC_API_KEY is not set. Use the fixture proposer for "
                "offline runs; the live proposer is opt-in.")

    def request_params(self, system: str, user: str) -> dict:
        """Built separately from sending so a test can assert the request shape
        without a network call or an API key."""
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            # Opus 5 runs adaptive thinking by default. budget_tokens is
            # rejected with a 400 on this model, so it is deliberately absent.
            "output_config": {"effort": self.effort},
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }

    def send(self, system: str, user: str) -> TransportResponse:
        try:
            import anthropic
        except ImportError as exc:                       # pragma: no cover
            raise ProposerNotConfigured(
                "the `anthropic` package is not installed; "
                "pip install anthropic") from exc

        client = anthropic.Anthropic(api_key=self._api_key, timeout=self.timeout)
        started = time.monotonic()
        try:
            response = client.messages.create(**self.request_params(system, user))
        except anthropic.APITimeoutError as exc:
            raise ProposerTimeout(f"model call timed out: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise ProposerTransportFailure(f"connection error: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise ProposerTransportFailure(f"rate limited: {exc}") from exc
        except anthropic.AuthenticationError as exc:
            raise ProposerNotConfigured(f"authentication failed: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise ProposerTransportFailure(
                f"api error {exc.status_code}: {exc.message}") from exc

        if response.stop_reason == "refusal":
            raise ProposerTransportFailure(
                "the model declined the request; no proposal was produced")

        latency_ms = (time.monotonic() - started) * 1000.0
        usage = getattr(response, "usage", None)
        text = "".join(b.text for b in response.content if b.type == "text")
        return TransportResponse(
            text=text, model=response.model,
            stop_reason=response.stop_reason or "",
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            latency_ms=latency_ms)
