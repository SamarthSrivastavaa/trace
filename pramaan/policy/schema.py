"""Typed, closed policy representation.

Policy files are UNTRUSTED CONFIGURATION until validated here. Nothing in a
policy document can execute: there is no eval, no dynamic import, no embedded
expression language. A policy is data describing which closed rule types are
enabled and with what integer bounds.

THE STAGE DISTINCTION IS ARCHITECTURAL, NOT COSMETIC
----------------------------------------------------
A pre-state rule may only read request-local facts and Pramaan's own local
records. It runs BEFORE any authoritative state acquisition, which is what
makes "a gated request costs zero provider calls and zero model calls"
enforceable by control flow.

A rule needing authoritative state (attempt_index lives in the subscription
record) CANNOT be pre-state without acquiring state first - which would break
that invariant. Such rules are declared post_state and run after the snapshot.

The schema enforces the split: each rule type has exactly one legal stage, and
a document declaring the wrong one fails to load.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import (BaseModel, BeforeValidator, ConfigDict, Field,
                      StringConstraints, model_validator)


def _no_bool(v: object) -> object:
    """bool is a subclass of int and pydantic's lax mode coerces True -> 1.
    A policy bound of `true` must be a load error, not a silent cap of 1."""
    if type(v) is bool:
        raise ValueError("bool is not an integer bound")
    return v


NoBool = BeforeValidator(_no_bool)
PositiveInt = Annotated[int, NoBool, Field(ge=1, le=10**9)]
RuleId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,40}$")]


class Stage(str, Enum):
    PRE_STATE = "pre_state"      # request-local facts only; runs before acquisition
    POST_STATE = "post_state"    # needs the authoritative snapshot


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True,
                              str_strip_whitespace=True)


class SuppressionRule(Strict):
    """Never contact a customer who has opted out."""
    type: Literal["suppression"] = "suppression"
    id: RuleId
    stage: Literal[Stage.PRE_STATE] = Stage.PRE_STATE
    enabled: bool = True


class CooldownRule(Strict):
    """Reject if the previous send is more recent than the cooldown window.

    Boundary is EXPLICIT: elapsed < min_seconds_between_sends blocks; elapsed
    exactly equal to it is allowed.
    """
    type: Literal["cooldown"] = "cooldown"
    id: RuleId
    stage: Literal[Stage.PRE_STATE] = Stage.PRE_STATE
    enabled: bool = True
    min_seconds_between_sends: PositiveInt


class AttemptLimitRule(Strict):
    """Cap retry attempts. POST_STATE: attempt_index is authoritative state.

    Boundary is EXPLICIT: attempt_index <= max_attempts is allowed, so with
    max_attempts=4, attempt 4 of 4 is permitted and attempt 5 is blocked.
    """
    type: Literal["attempt_limit"] = "attempt_limit"
    id: RuleId
    stage: Literal[Stage.POST_STATE] = Stage.POST_STATE
    enabled: bool = True
    max_attempts: PositiveInt


Rule = Annotated[
    Union[SuppressionRule, CooldownRule, AttemptLimitRule],
    Field(discriminator="type"),
]


class Policy(Strict):
    policy_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_\-]{1,60}$")]
    label: Annotated[str, StringConstraints(max_length=40)]
    rules: Annotated[list[Rule], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def _coherent(self) -> "Policy":
        ids = [r.id for r in self.rules]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate rule id")
        types = [r.type for r in self.rules]
        if len(set(types)) != len(types):
            # Two cooldowns with different windows is a contradictory policy;
            # there is no defined precedence, so refuse to load it.
            raise ValueError("contradictory policy: duplicate rule type")
        return self

    def enabled_rules(self, stage: Stage) -> list:
        return [r for r in self.rules if r.enabled and r.stage is stage]


class GateDecision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class GateResult(Strict):
    """What the pure gate returns. Deterministic and fully explainable."""
    decision: GateDecision
    reason_code: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9_]{2,48}$")]
    rule_id: str = ""
    detail: Annotated[str, StringConstraints(max_length=200)] = ""

    @property
    def allowed(self) -> bool:
        return self.decision is GateDecision.ALLOW


class GateContext(Strict):
    """Primitive-only gate inputs.

    `now` and `last_send_at` are injected ISO-8601 instants WITH offset. The
    gate never reads a clock: a cooldown that consulted datetime.now() could
    not be replayed.
    """
    merchant_id: str
    customer_id: str
    now: Annotated[str, StringConstraints(
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")]
    suppressed: bool = False
    last_send_at: str | None = None
