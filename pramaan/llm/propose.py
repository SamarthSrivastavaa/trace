"""The LLM proposal adapter.

The model is an UNTRUSTED proposal generator. It never decides SUPPORTED,
CONTRADICTED, UNVERIFIABLE, MALFORMED, SEND, BLOCK or ESCALATE - it cannot
even represent them, because `status` is not a field on ProposedClaim.

This module contains NO verdict logic and NO second schema. It extracts a JSON
object from the response and hands it to the PRODUCTION `Proposal` model, which
is the sole authority on what a valid proposal is. There is no repair step: a
payload that fails validation raises, and a failed call never fabricates a
proposal or falls back to the mock.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from ..core.verify.schema import Proposal
from .client import AnthropicTransport, Transport
from .errors import ProposerMalformedOutput, ProposerSchemaViolation
from .prompt import SYSTEM_PROMPT, prompt_identity, render_user_message


def extract_json_object(text: str) -> dict:
    """Pull the JSON object out of a model response.

    Tolerates surrounding prose and ```json fences, because those are transport
    noise rather than a claim about content. It does NOT repair the object's
    contents - shape is the production schema's business.
    """
    if not isinstance(text, str) or not text.strip():
        raise ProposerMalformedOutput("empty response")

    body = text.strip()
    if "```" in body:
        parts = body.split("```")
        for part in parts:
            candidate = part[4:] if part.lower().startswith("json") else part
            if "{" in candidate:
                body = candidate
                break

    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise ProposerMalformedOutput(
            f"no JSON object in response (first 120 chars: {text[:120]!r})")
    try:
        parsed = json.loads(body[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ProposerMalformedOutput(f"response is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ProposerMalformedOutput(
            f"expected a JSON object, got {type(parsed).__name__}")
    return parsed


def to_proposal(payload: dict) -> Proposal:
    """The production schema is the final authority. No second validator."""
    try:
        return Proposal.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        raise ProposerSchemaViolation(f"{loc}: {first['msg']}") from exc


class ClaudeProposer:
    """Production proposer. Callable as (draft, state) -> Proposal.

    Matches the existing pipeline proposer contract, so it drops into the same
    slot as the fixture mock with no pipeline change.
    """

    name = "claude"

    def __init__(self, transport: Transport | None = None):
        # Constructing the default transport validates credentials, so an
        # unconfigured environment fails here with a typed error rather than
        # at request time.
        self.transport = transport or AnthropicTransport()

    @property
    def identity(self) -> dict:
        return {"proposer": self.name,
                "transport": getattr(self.transport, "name", "unknown"),
                "model": getattr(self.transport, "model", ""),
                "prompt": prompt_identity()}

    def __call__(self, draft: str, state: dict) -> Proposal:
        # Sorted keys so the same state produces the same prompt bytes.
        state_json = json.dumps(state, sort_keys=True, indent=2)
        user = render_user_message(draft, state_json)
        response = self.transport.send(SYSTEM_PROMPT, user)
        return to_proposal(extract_json_object(response.text))
