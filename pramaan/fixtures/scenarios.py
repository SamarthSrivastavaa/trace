"""SIMULATED merchant state and a deterministic stand-in for the model.

Nothing here has ever touched the Razorpay API. Every snapshot below is a
hand-written fixture and must be labelled SIMULATED wherever it is shown.

The two snapshots differ in EXACTLY ONE field (subscription.attempt_index).
tests/test_demo_beats.py asserts that, so the state-flip demo cannot quietly
become a two-variable change.
"""

from copy import deepcopy

NOW = "2026-09-04T10:00:00+05:30"

DRAFT = ("This is our final attempt. Your 15% offer expires in 24 hours.")

_BASE = {
    "now": NOW,
    "offers": [
        {"offer_id": "ofr_A1", "percent": 15, "flat_amount_minor": None,
         "valid_until": "2026-09-05T06:00:00+05:30", "active": True},
    ],
    "subscription": {"status": "active", "attempt_index": 4,
                     "max_attempts": 4, "next_action": "cancel"},
    "customer": {"tier": "standard", "opted_out": False},
}


def state_final_attempt() -> dict:
    """attempt_index 4 of 4 - the message is true."""
    return deepcopy(_BASE)


def state_first_attempt() -> dict:
    """Identical except attempt_index = 1. The same sentence is now false."""
    s = deepcopy(_BASE)
    s["subscription"]["attempt_index"] = 1
    return s


# --- deterministic stand-in for the model ----------------------------------
# Spans are offsets into the NFC-normalised DRAFT. Computed at import time from
# the draft itself so they cannot drift out of sync with the text.

def _span(needle: str) -> tuple[int, int]:
    i = DRAFT.index(needle)
    return i, i + len(needle)


def honest_proposal() -> dict:
    """What a well-behaved model returns for DRAFT."""
    fa, fb = _span("final attempt")
    pa, pb = _span("15%")
    da, db = _span("24 hours")
    return {"claims": [
        {"claim_id": "c1", "kind": "is_final_attempt",
         "span_start": fa, "span_end": fb,
         "asserted": {"kind": "bool", "value": True},
         "evidence": {"ref": "subscription", "field": "attempt_index"}},
        {"claim_id": "c2", "kind": "discount_percent",
         "span_start": pa, "span_end": pb,
         "asserted": {"kind": "percent", "value": "15.00"},
         "evidence": {"ref": "offer", "offer_id": "ofr_A1", "field": "percent"}},
        {"claim_id": "c3", "kind": "deadline_within",
         "span_start": da, "span_end": db,
         "asserted": {"kind": "hours", "value": "24.00"},
         "evidence": {"ref": "offer", "offer_id": "ofr_A1", "field": "valid_until"}},
    ]}


def forged_evidence_proposal() -> dict:
    """Beat B: a well-formed but nonexistent offer id."""
    p = honest_proposal()
    p["claims"][1]["evidence"]["offer_id"] = "ofr_ZZ9"
    return p


def omitted_deadline_proposal() -> dict:
    """Beat C: the model silently drops the '24 hours' claim."""
    p = honest_proposal()
    p["claims"] = [c for c in p["claims"] if c["claim_id"] != "c3"]
    return p


def mock_model(draft: str, snapshot: dict, proposal: dict | None = None) -> dict:
    """Stands in for the one model call. Deterministic by construction."""
    return proposal if proposal is not None else honest_proposal()
