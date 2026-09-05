"""The pure policy gate.

CONTRACT (enforced by tests/test_gate.py and the AST boundary test):
  - pure: same context + same policy -> same result, always
  - no network, no database, no vendor, no model imports
  - no clock: `now` is injected in GateContext, never read here

Rules are DATA. This module contains dispatch over closed rule types and the
comparison each type defines - it contains no policy constants. Changing a
cooldown window is a change to default_policy.json, not to this file.
"""

from __future__ import annotations

from datetime import datetime

from .schema import (AttemptLimitRule, CooldownRule, GateContext, GateDecision,
                     GateResult, Policy, Stage, SuppressionRule)

ALLOWED = "ALLOWED"
SUPPRESSED = "CUSTOMER_SUPPRESSED"
COOLDOWN = "COOLDOWN_NOT_ELAPSED"
ATTEMPT_CAP = "ATTEMPT_LIMIT_EXCEEDED"
BAD_TIMESTAMP = "GATE_TIMESTAMP_UNPARSEABLE"
MISSING_STATE = "GATE_STATE_FIELD_ABSENT"


def _instant(raw: str) -> datetime | None:
    """Parse an offset-bearing ISO-8601 instant. Naive input is rejected: a
    naive timestamp must never be silently treated as authoritative."""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return dt if dt.tzinfo is not None else None


def _allow() -> GateResult:
    return GateResult(decision=GateDecision.ALLOW, reason_code=ALLOWED)


def _deny(code: str, rule_id: str, detail: str = "") -> GateResult:
    return GateResult(decision=GateDecision.DENY, reason_code=code,
                      rule_id=rule_id, detail=detail)


def evaluate_pre_state(context: GateContext, policy: Policy) -> GateResult:
    """Runs BEFORE any authoritative state acquisition.

    A DENY here means the pipeline must not call the state provider and must
    not call the model. That is enforced by control flow in pipeline.evaluate.
    """
    for rule in policy.enabled_rules(Stage.PRE_STATE):
        if isinstance(rule, SuppressionRule):
            if context.suppressed:
                return _deny(SUPPRESSED, rule.id,
                             "customer is on the suppression list")

        elif isinstance(rule, CooldownRule):
            if context.last_send_at is None:
                continue                      # never contacted; nothing to cool
            now, last = _instant(context.now), _instant(context.last_send_at)
            if now is None or last is None:
                # Fail closed. An unparseable timestamp must not read as
                # "cooldown elapsed".
                return _deny(BAD_TIMESTAMP, rule.id,
                             "now or last_send_at is not an offset-bearing instant")
            elapsed = (now - last).total_seconds()
            if elapsed < rule.min_seconds_between_sends:
                return _deny(COOLDOWN, rule.id,
                             f"{int(elapsed)}s elapsed of "
                             f"{rule.min_seconds_between_sends}s required")

    return _allow()


def evaluate_post_state(snapshot_state: dict, policy: Policy) -> GateResult:
    """Runs AFTER acquisition, for rules that genuinely need authoritative state.

    attempt_index lives in the subscription record, so an attempt cap cannot be
    a pre-state rule without acquiring state first - which would defeat the
    zero-acquisition guarantee. It is therefore declared post_state.
    """
    for rule in policy.enabled_rules(Stage.POST_STATE):
        if isinstance(rule, AttemptLimitRule):
            sub = snapshot_state.get("subscription")
            if not isinstance(sub, dict) or "attempt_index" not in sub:
                continue                      # rule does not apply to this state
            attempt = sub["attempt_index"]
            if type(attempt) is bool or not isinstance(attempt, int):
                return _deny(MISSING_STATE, rule.id,
                             "attempt_index is not an integer")
            if attempt > rule.max_attempts:
                return _deny(ATTEMPT_CAP, rule.id,
                             f"attempt {attempt} exceeds cap {rule.max_attempts}")

    return _allow()
