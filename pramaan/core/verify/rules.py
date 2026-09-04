"""The pure adjudicator - the trust boundary.

Contract, enforced by tests/test_boundary.py:
  - no network, no database, no model, no clock, no randomness
  - imports nothing beyond the stdlib and .schema
  - a pure function of (claim, snapshot); same inputs, same output, forever

Every value that reaches a comparison is asserted primitive first. A crafted
object with an overloaded __eq__ previously executed attacker code inside this
path and drove a false claim to SUPPORTED (reproduced against the retired
killtest/validator.py, 2026-09-04). That cannot happen through the schema, but
the guard is cheap and the failure mode is severe.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from .schema import (BoolValue, ClaimKind, ClaimValue, CountValue, EvidenceRef,
                     HoursValue, MinorValue, PercentValue, ProposedClaim,
                     Status, TextValue, Verdict)

_PRIMITIVE = (int, str, bool, Decimal)


class NonPrimitiveValue(TypeError):
    """A non-primitive reached the comparison path."""


def _require_primitive(value: Any, where: str) -> None:
    if not isinstance(value, _PRIMITIVE):
        raise NonPrimitiveValue(
            f"{where}: {type(value).__name__} is not a primitive; only "
            "int, str, bool and Decimal may reach a comparison")


def _parse_instant(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else None      # naive is rejected


def resolve(evidence: EvidenceRef, snapshot: dict) -> tuple[bool, Any]:
    """Look up the cited field. Returns (found, value).

    The model cannot name a field that does not exist - field names are Literal
    enums checked at parse time - so the only fabricable part is a record id.
    """
    ref = evidence.ref
    if ref == "offer":
        for offer in snapshot.get("offers", []):
            if isinstance(offer, dict) and offer.get("offer_id") == evidence.offer_id:
                if evidence.field not in offer or offer[evidence.field] is None:
                    return False, None
                return True, offer[evidence.field]
        return False, None

    record = snapshot.get({"subscription": "subscription", "payment": "payment",
                           "cart": "cart", "customer": "customer"}[ref])
    if not isinstance(record, dict):
        return False, None
    if evidence.field not in record or record[evidence.field] is None:
        return False, None
    return True, record[evidence.field]


def _observed(kind: ClaimKind, value: Any) -> ClaimValue | None:
    """Wrap the stored value in the same shape as the assertion, for the proof."""
    try:
        if kind in (ClaimKind.DISCOUNT_PERCENT,):
            return PercentValue(value=Decimal(str(value)))
        if kind in (ClaimKind.DISCOUNT_FLAT, ClaimKind.AMOUNT):
            return MinorValue(value=int(value))
        if kind in (ClaimKind.QUANTITY, ClaimKind.ITEM_COUNT,
                    ClaimKind.ATTEMPT_INDEX):
            return CountValue(value=int(value))
        if kind in (ClaimKind.STATUS_IS, ClaimKind.TIER_IS):
            return TextValue(value=str(value))
        if kind in (ClaimKind.IS_FINAL_ATTEMPT, ClaimKind.DEADLINE_PASSED):
            return BoolValue(value=bool(value))
        if kind is ClaimKind.DEADLINE_WITHIN:
            return HoursValue(value=Decimal(str(value)))
    except Exception:
        return None
    return None


def _verdict(claim: ProposedClaim, status: Status, reason: str,
             observed: ClaimValue | None = None) -> Verdict:
    return Verdict(claim_id=claim.claim_id, kind=claim.kind, status=status,
                   reason_code=reason, evidence=claim.evidence,
                   observed=observed, asserted=claim.asserted)


def _text_eq(a: Any, b: Any) -> bool:
    return str(a).casefold() == str(b).casefold()


def adjudicate(claim: ProposedClaim, snapshot: dict) -> Verdict:
    """Decide one claim against one snapshot. Total over ClaimKind."""
    kind = claim.kind

    # Razorpay holds no inventory. Scarcity is honestly unverifiable, and
    # keeping the kind makes the limitation visible in the proof.
    if kind is ClaimKind.QUANTITY:
        return _verdict(claim, Status.UNVERIFIABLE, "NO_INVENTORY_SOURCE")

    if claim.evidence is None:
        return _verdict(claim, Status.UNVERIFIABLE, "NO_EVIDENCE_CITED")

    found, stored = resolve(claim.evidence, snapshot)
    if not found:
        # The model cited a record or field that is not in this snapshot. That
        # is a malformed CITATION, not an unverifiable CLAIM - the distinction
        # matters because it routes to ESCALATE (the model is unreliable)
        # rather than BLOCK (this message is unsupported).
        return _verdict(claim, Status.MALFORMED, "EVIDENCE_ABSENT")

    _require_primitive(stored, "snapshot value")
    _require_primitive(claim.asserted.value, "asserted value")
    observed = _observed(kind, stored)

    if kind is ClaimKind.DISCOUNT_PERCENT:
        ok = Decimal(str(stored)) == claim.asserted.value
    elif kind in (ClaimKind.DISCOUNT_FLAT, ClaimKind.AMOUNT,
                  ClaimKind.ITEM_COUNT, ClaimKind.ATTEMPT_INDEX):
        ok = int(stored) == int(claim.asserted.value)
    elif kind in (ClaimKind.STATUS_IS, ClaimKind.TIER_IS):
        ok = _text_eq(stored, claim.asserted.value)

    elif kind is ClaimKind.DEADLINE_WITHIN:
        now = _parse_instant(snapshot.get("now"))
        until = _parse_instant(stored)
        if now is None or until is None:
            return _verdict(claim, Status.UNVERIFIABLE, "BAD_TIMESTAMP", observed)
        hours = Decimal(str((until - now).total_seconds() / 3600))
        observed = HoursValue(value=max(Decimal("0"), hours.quantize(Decimal("0.01"))))
        ok = Decimal("0") <= hours <= claim.asserted.value

    elif kind is ClaimKind.DEADLINE_PASSED:
        now = _parse_instant(snapshot.get("now"))
        until = _parse_instant(stored)
        if now is None or until is None:
            return _verdict(claim, Status.UNVERIFIABLE, "BAD_TIMESTAMP", observed)
        observed = BoolValue(value=until < now)
        ok = (until < now) == bool(claim.asserted.value)

    elif kind is ClaimKind.IS_FINAL_ATTEMPT:
        # Needs a second field from the SAME record. The citation points at
        # attempt_index; max_attempts is read alongside it and both appear in
        # the proof, so the two-fields-one-citation ambiguity is explicit.
        sub = snapshot.get("subscription")
        if not isinstance(sub, dict) or sub.get("max_attempts") is None:
            return _verdict(claim, Status.UNVERIFIABLE, "EVIDENCE_ABSENT", observed)
        _require_primitive(sub["max_attempts"], "max_attempts")
        is_final = int(stored) >= int(sub["max_attempts"])
        observed = BoolValue(value=is_final)
        ok = is_final == bool(claim.asserted.value)

    else:
        # Unreachable while the dispatch stays total over ClaimKind. If a kind
        # is ever added without a rule, it fails closed rather than silently.
        return _verdict(claim, Status.MALFORMED, "NO_RULE_FOR_KIND", observed)

    return _verdict(claim, Status.SUPPORTED if ok else Status.CONTRADICTED,
                    "MATCH" if ok else "VALUE_MISMATCH", observed)


def adjudicate_all(claims: list[ProposedClaim], snapshot: dict) -> list[Verdict]:
    return [adjudicate(c, snapshot) for c in claims]
