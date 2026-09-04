"""The pure adjudicator.

Includes the regression for the crafted-__eq__ vulnerability reproduced
against the retired killtest/validator.py, where attacker code executed inside
the trusted comparison path and drove a false claim to SUPPORTED.
"""

from decimal import Decimal

import pytest

from pramaan.core.verify.rules import NonPrimitiveValue, adjudicate, _require_primitive
from pramaan.core.verify.schema import ClaimKind, ProposedClaim, Status
from pramaan.fixtures import scenarios as fx


def claim(kind, asserted, evidence=None, cid="c1"):
    return ProposedClaim.model_validate(
        {"claim_id": cid, "kind": kind, "span_start": 0, "span_end": 3,
         "asserted": asserted, "evidence": evidence})


OFFER = {"ref": "offer", "offer_id": "ofr_A1", "field": "percent"}
UNTIL = {"ref": "offer", "offer_id": "ofr_A1", "field": "valid_until"}
ATTEMPT = {"ref": "subscription", "field": "attempt_index"}


def test_percent_match_and_mismatch():
    s = fx.state_final_attempt()
    ok = adjudicate(claim("discount_percent", {"kind": "percent", "value": "15.00"}, OFFER), s)
    bad = adjudicate(claim("discount_percent", {"kind": "percent", "value": "40.00"}, OFFER), s)
    assert ok.status is Status.SUPPORTED
    assert bad.status is Status.CONTRADICTED
    assert bad.observed.value == Decimal("15")


def test_absent_record_is_malformed_not_supported():
    s = fx.state_final_attempt()
    v = adjudicate(claim("discount_percent", {"kind": "percent", "value": "15.00"},
                         {"ref": "offer", "offer_id": "ofr_ZZ9", "field": "percent"}), s)
    assert v.status is Status.MALFORMED
    assert v.reason_code == "EVIDENCE_ABSENT"


def test_quantity_is_always_unverifiable():
    """Razorpay holds no inventory. The limitation is visible, not hidden."""
    v = adjudicate(claim("quantity", {"kind": "count", "value": 2}), fx.state_final_attempt())
    assert v.status is Status.UNVERIFIABLE
    assert v.reason_code == "NO_INVENTORY_SOURCE"


def test_is_final_attempt_flips_on_one_field():
    c = claim("is_final_attempt", {"kind": "bool", "value": True}, ATTEMPT)
    assert adjudicate(c, fx.state_final_attempt()).status is Status.SUPPORTED
    assert adjudicate(c, fx.state_first_attempt()).status is Status.CONTRADICTED


def test_deadline_within_boundaries():
    s = fx.state_final_attempt()          # valid_until is 20h after now
    within = claim("deadline_within", {"kind": "hours", "value": "24.00"}, UNTIL)
    tight = claim("deadline_within", {"kind": "hours", "value": "2.00"}, UNTIL)
    assert adjudicate(within, s).status is Status.SUPPORTED
    assert adjudicate(tight, s).status is Status.CONTRADICTED


def test_expired_offer_is_not_within():
    s = fx.state_final_attempt()
    s["offers"][0]["valid_until"] = "2026-09-01T00:00:00+05:30"
    v = adjudicate(claim("deadline_within", {"kind": "hours", "value": "24.00"}, UNTIL), s)
    assert v.status is Status.CONTRADICTED


def test_naive_timestamp_is_unverifiable_not_supported():
    s = fx.state_final_attempt()
    s["offers"][0]["valid_until"] = "2026-09-05T06:00:00"      # no offset
    v = adjudicate(claim("deadline_within", {"kind": "hours", "value": "24.00"}, UNTIL), s)
    assert v.status is Status.UNVERIFIABLE
    assert v.reason_code == "BAD_TIMESTAMP"


def test_text_comparison_is_casefolded():
    s = fx.state_final_attempt()
    s["customer"]["tier"] = "Gold"
    v = adjudicate(claim("tier_is", {"kind": "text", "value": "gold"},
                         {"ref": "customer", "field": "tier"}), s)
    assert v.status is Status.SUPPORTED


def test_crafted_object_cannot_reach_comparison():
    """Regression for the retired validator's operator-overload hole."""
    class Evil:
        def __eq__(self, other):
            raise AssertionError("attacker code executed in the trust boundary")

    with pytest.raises(NonPrimitiveValue):
        _require_primitive(Evil(), "snapshot value")


def test_snapshot_with_crafted_value_is_rejected():
    s = fx.state_final_attempt()

    class Evil:
        def __eq__(self, other):
            raise AssertionError("attacker code executed in the trust boundary")

    s["offers"][0]["percent"] = Evil()
    with pytest.raises(NonPrimitiveValue):
        adjudicate(claim("discount_percent", {"kind": "percent", "value": "15.00"}, OFFER), s)


def test_adjudication_is_deterministic():
    c = claim("is_final_attempt", {"kind": "bool", "value": True}, ATTEMPT)
    s = fx.state_final_attempt()
    dumps = {adjudicate(c, s).model_dump_json() for _ in range(200)}
    assert len(dumps) == 1


def test_unrelated_snapshot_field_does_not_change_verdict():
    c = claim("is_final_attempt", {"kind": "bool", "value": True}, ATTEMPT)
    base = adjudicate(c, fx.state_final_attempt())
    s = fx.state_final_attempt()
    s["customer"]["tier"] = "platinum"
    assert adjudicate(c, s).status is base.status
