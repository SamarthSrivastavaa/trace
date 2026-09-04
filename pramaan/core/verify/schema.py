"""
The trust boundary's type system.

ALL MODEL OUTPUT IS UNTRUSTED INPUT. This module is the only place it becomes
typed, and every widening escape hatch is deliberately absent:
  - no Any, no bare dict, no free-form str where an enum fits
  - no float anywhere (no NaN, no Inf, no binary rounding)
  - money is integer minor units (paise), matching Razorpay's own wire format
  - percentages are Decimal with bounded scale

ARCHITECTURAL CHANGE vs killtest/validator.py
---------------------------------------------
That prototype let the model emit a dotted string path ("offers.ofr_A2.percent")
which was walked at runtime. That is a fabricated-path, path-traversal and
type-confusion surface all at once.

Here the locator is a CLOSED DISCRIMINATED UNION. The model cannot name a field
that does not exist, because field names are Literal enums checked at parse
time. The only free value it may supply is a record id, which must then be
found in the snapshot. Path traversal becomes unrepresentable rather than
defended against.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import (BaseModel, BeforeValidator, ConfigDict, Field,
                      StringConstraints, model_validator)

# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------

RecordId = Annotated[str, StringConstraints(
    pattern=r"^[A-Za-z0-9_]{1,40}$", strip_whitespace=True)]

# ISO-8601 with a REQUIRED offset. Naive timestamps are rejected at parse time
# so no comparison can silently assume a timezone.
IsoInstant = Annotated[str, StringConstraints(
    pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")]

def _no_bool(v: object) -> object:
    """bool is a subclass of int in Python, and pydantic's lax mode coerces
    True -> 1. Found by the adversarial test below: a model could smuggle a
    boolean into a quantity claim. isinstance() is useless here; check the
    concrete type.
    """
    if type(v) is bool:
        raise ValueError("bool is not a numeric value")
    return v


NoBool = BeforeValidator(_no_bool)

Minor = Annotated[int, NoBool, Field(ge=0, le=10**12)]     # money, minor units
Percent = Annotated[Decimal, NoBool, Field(ge=0, le=100, decimal_places=2)]
Count = Annotated[int, NoBool, Field(ge=0, le=10**9)]
Hours = Annotated[Decimal, NoBool, Field(ge=0, le=8760, decimal_places=2)]


class Strict(BaseModel):
    """Reject unknown keys; freeze after parse.

    Deliberately NOT strict=True. Model output arrives as JSON, where "40.00"
    is the legitimate wire form of a Decimal and "quantity" of an enum member;
    strict mode rejected valid input while adding no safety. The real defences
    are structural and still hold: closed enums, Literal field names,
    discriminated unions, bounded ranges, decimal_places, and extra="forbid".
    An explicit bool guard covers the one coercion pydantic still allows.
    """
    model_config = ConfigDict(extra="forbid", frozen=True,
                              str_strip_whitespace=True)


# --------------------------------------------------------------------------
# evidence locators - CLOSED union. Field names are Literals, not strings.
# --------------------------------------------------------------------------

class OfferRef(Strict):
    ref: Literal["offer"] = "offer"
    offer_id: RecordId
    field: Literal["percent", "flat_amount_minor", "valid_until", "active"]


class SubscriptionRef(Strict):
    ref: Literal["subscription"] = "subscription"
    field: Literal["status", "attempt_index", "max_attempts", "next_action"]


class PaymentRef(Strict):
    ref: Literal["payment"] = "payment"
    field: Literal["status", "amount_minor"]


class CartRef(Strict):
    ref: Literal["cart"] = "cart"
    field: Literal["item_count", "total_minor"]


class CustomerRef(Strict):
    ref: Literal["customer"] = "customer"
    field: Literal["tier", "opted_out"]


EvidenceRef = Annotated[
    Union[OfferRef, SubscriptionRef, PaymentRef, CartRef, CustomerRef],
    Field(discriminator="ref"),
]

# --------------------------------------------------------------------------
# claims
# --------------------------------------------------------------------------


class ClaimKind(str, Enum):
    DISCOUNT_PERCENT = "discount_percent"
    DISCOUNT_FLAT = "discount_flat"
    DEADLINE_WITHIN = "deadline_within"     # "expires in N hours"
    DEADLINE_PASSED = "deadline_passed"     # "your offer has expired"
    QUANTITY = "quantity"
    AMOUNT = "amount"
    ITEM_COUNT = "item_count"
    ATTEMPT_INDEX = "attempt_index"
    IS_FINAL_ATTEMPT = "is_final_attempt"
    STATUS_IS = "status_is"
    TIER_IS = "tier_is"


class Status(str, Enum):
    """Claim-level outcome. Only SUPPORTED is positive; everything else blocks.

    NOTE: UNCOVERED and AMBIGUOUS are deliberately NOT here.
      - UNCOVERED is a property of a SPAN with no claim, so it cannot be a
        claim status; it lives in the coverage report.
      - AMBIGUOUS collapsed into UNVERIFIABLE: both mean "the snapshot does not
        settle this", and a separate label bought no distinct behaviour.
    """
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNVERIFIABLE = "UNVERIFIABLE"
    MALFORMED = "MALFORMED"


# asserted value, one shape per kind - again closed, no bare dict
class PercentValue(Strict):
    kind: Literal["percent"] = "percent"
    value: Percent


class MinorValue(Strict):
    kind: Literal["minor"] = "minor"
    value: Minor
    currency: Literal["INR"] = "INR"


class CountValue(Strict):
    kind: Literal["count"] = "count"
    value: Count


class HoursValue(Strict):
    kind: Literal["hours"] = "hours"
    value: Hours


class TextValue(Strict):
    kind: Literal["text"] = "text"
    value: Annotated[str, StringConstraints(max_length=64)]


class BoolValue(Strict):
    kind: Literal["bool"] = "bool"
    value: bool


ClaimValue = Annotated[
    Union[PercentValue, MinorValue, CountValue, HoursValue, TextValue, BoolValue],
    Field(discriminator="kind"),
]

# which value shape each claim kind must carry - enforced below
_EXPECTED: dict[ClaimKind, str] = {
    ClaimKind.DISCOUNT_PERCENT: "percent",
    ClaimKind.DISCOUNT_FLAT: "minor",
    ClaimKind.DEADLINE_WITHIN: "hours",
    ClaimKind.DEADLINE_PASSED: "bool",
    ClaimKind.QUANTITY: "count",
    ClaimKind.AMOUNT: "minor",
    ClaimKind.ITEM_COUNT: "count",
    ClaimKind.ATTEMPT_INDEX: "count",
    ClaimKind.IS_FINAL_ATTEMPT: "bool",
    ClaimKind.STATUS_IS: "text",
    ClaimKind.TIER_IS: "text",
}


class ProposedClaim(Strict):
    """What the model is permitted to say. It may NOT state a verdict."""
    claim_id: Annotated[str, StringConstraints(pattern=r"^c[0-9]{1,3}$")]
    kind: ClaimKind
    span_start: Annotated[int, Field(ge=0, le=10_000)]
    span_end: Annotated[int, Field(ge=0, le=10_000)]
    asserted: ClaimValue
    evidence: EvidenceRef | None = None       # None => model believes unverifiable

    @model_validator(mode="after")
    def _consistent(self) -> "ProposedClaim":
        if self.span_end <= self.span_start:
            raise ValueError("span_end must exceed span_start")
        expected = _EXPECTED[self.kind]
        if self.asserted.kind != expected:
            raise ValueError(
                f"kind {self.kind.value} requires a {expected} value, "
                f"got {self.asserted.kind}")
        return self


class Proposal(Strict):
    """The complete, parsed model output. Nothing else crosses the boundary."""
    claims: Annotated[list[ProposedClaim], Field(max_length=40)]

    @model_validator(mode="after")
    def _unique_ids(self) -> "Proposal":
        ids = [c.claim_id for c in self.claims]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate claim_id")
        return self


# --------------------------------------------------------------------------
# adjudicated results - produced ONLY by core.verify, never by the model
# --------------------------------------------------------------------------

class Verdict(Strict):
    claim_id: str
    kind: ClaimKind
    status: Status
    reason_code: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9_]{3,40}$")]
    evidence: EvidenceRef | None
    observed: ClaimValue | None      # what the snapshot actually held
    asserted: ClaimValue


class Disposition(str, Enum):
    """REWRITE was removed in Phase 5: decide() never returned it and the
    proof table's CHECK constraint rejected it, so the enum admitted a value
    the database refused. A fake branch is worse than a missing feature."""
    SEND = "SEND"
    BLOCK = "BLOCK"                  # content unsupported, or policy denied
    ESCALATE = "ESCALATE"            # model or infrastructure unreliable


if __name__ == "__main__":
    from pydantic import ValidationError

    def expect_reject(label: str, payload: dict) -> None:
        try:
            ProposedClaim.model_validate(payload)
        except ValidationError as e:
            first = e.errors()[0]
            print(f"  REJECT  {label:<34} {first['type']}: {str(first['msg'])[:52]}")
        else:
            print(f"  !! ACCEPTED {label} - INVARIANT HOLE")

    ok = ProposedClaim.model_validate({
        "claim_id": "c1", "kind": "discount_percent",
        "span_start": 36, "span_end": 39,
        "asserted": {"kind": "percent", "value": "40.00"},
        "evidence": {"ref": "offer", "offer_id": "ofr_A2", "field": "percent"},
    })
    print(f"  ACCEPT  well-formed claim -> {ok.kind.value} {ok.asserted.value}%\n")

    expect_reject("unknown claim kind", {
        "claim_id": "c2", "kind": "vibes", "span_start": 0, "span_end": 3,
        "asserted": {"kind": "percent", "value": "40.00"}})
    expect_reject("path traversal in field", {
        "claim_id": "c3", "kind": "discount_percent", "span_start": 0, "span_end": 3,
        "asserted": {"kind": "percent", "value": "40.00"},
        "evidence": {"ref": "offer", "offer_id": "ofr_A2", "field": "../../secret"}})
    expect_reject("fabricated field name", {
        "claim_id": "c4", "kind": "discount_percent", "span_start": 0, "span_end": 3,
        "asserted": {"kind": "percent", "value": "40.00"},
        "evidence": {"ref": "offer", "offer_id": "ofr_A2", "field": "api_key"}})
    expect_reject("value shape mismatch", {
        "claim_id": "c5", "kind": "discount_percent", "span_start": 0, "span_end": 3,
        "asserted": {"kind": "count", "value": 40}})
    expect_reject("inverted span", {
        "claim_id": "c6", "kind": "quantity", "span_start": 20, "span_end": 5,
        "asserted": {"kind": "count", "value": 2}})
    expect_reject("unexpected extra key", {
        "claim_id": "c7", "kind": "status_is", "span_start": 0, "span_end": 3,
        "asserted": {"kind": "text", "value": "x"},
        "evidence": {"ref": "offer", "offer_id": "o1", "field": "valid_until"},
        "confidence": 0.99})
    expect_reject("bool smuggled as count", {
        "claim_id": "c10", "kind": "quantity", "span_start": 0, "span_end": 3,
        "asserted": {"kind": "count", "value": True}})
    expect_reject("offer_id with traversal chars", {
        "claim_id": "c11", "kind": "discount_percent", "span_start": 0, "span_end": 3,
        "asserted": {"kind": "percent", "value": "40.00"},
        "evidence": {"ref": "offer", "offer_id": "../../etc", "field": "percent"}})
    expect_reject("unknown evidence ref type", {
        "claim_id": "c12", "kind": "discount_percent", "span_start": 0, "span_end": 3,
        "asserted": {"kind": "percent", "value": "40.00"},
        "evidence": {"ref": "database", "query": "SELECT * FROM offers"}})
    expect_reject("percent out of range", {
        "claim_id": "c8", "kind": "discount_percent", "span_start": 0, "span_end": 3,
        "asserted": {"kind": "percent", "value": "410.00"}})
    expect_reject("model states a verdict", {
        "claim_id": "c9", "kind": "quantity", "span_start": 0, "span_end": 3,
        "asserted": {"kind": "count", "value": 2}, "status": "SUPPORTED"})

    try:
        Proposal.model_validate({"claims": [
            {"claim_id": "c1", "kind": "quantity", "span_start": 0, "span_end": 3,
             "asserted": {"kind": "count", "value": 2}},
            {"claim_id": "c1", "kind": "quantity", "span_start": 5, "span_end": 8,
             "asserted": {"kind": "count", "value": 3}}]})
        print("  !! ACCEPTED duplicate claim_id - INVARIANT HOLE")
    except ValidationError as e:
        print(f"  REJECT  {'duplicate claim_id':<34} {e.errors()[0]['msg'][:52]}")
