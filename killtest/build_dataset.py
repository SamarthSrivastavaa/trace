"""
PRAMAAN kill-test dataset builder.

Design constraints (from the brief):
  - Paired truth-dependent cases: IDENTICAL message text, different authoritative
    state, DIFFERENT correct label. This is the core of the experiment.
  - Three-way labels. UNVERIFIABLE is a correct answer, not a cop-out.
  - No constant-label categories, no category leakage, no ID-predictable labels,
    no duplicate templates.
  - Pairs never straddle the dev/held-out split.
  - Authored by hand, not model-generated, to avoid generator/judge contamination.

Labels:
  SUPPORTED     - every checkable claim in the message is consistent with state
  CONTRADICTED  - at least one checkable claim conflicts with state
  UNVERIFIABLE  - the state needed to adjudicate a material claim is absent
"""

import hashlib
import json
import pathlib

# ---------------------------------------------------------------------------
# State fixtures. Referenced by name so the same state can back several cases.
# ---------------------------------------------------------------------------

NOW = "2026-09-04T10:00:00+05:30"

STATES = {
    # --- offer / discount / deadline -------------------------------------
    "offer_15_live": {
        "now": NOW,
        "offers": [{"offer_id": "ofr_A1", "percent": 15, "valid_until": "2026-09-14T23:59:59+05:30", "active": True}],
    },
    "offer_40_live": {
        "now": NOW,
        "offers": [{"offer_id": "ofr_A2", "percent": 40, "valid_until": "2026-09-05T06:00:00+05:30", "active": True}],
    },
    "offer_15_expired": {
        "now": NOW,
        "offers": [{"offer_id": "ofr_A3", "percent": 15, "valid_until": "2026-09-01T23:59:59+05:30", "active": False}],
    },
    "offer_15_tonight": {
        "now": NOW,
        "offers": [{"offer_id": "ofr_A6", "percent": 15, "valid_until": "2026-09-04T23:59:59+05:30", "active": True}],
    },
    "offer_none": {"now": NOW, "offers": []},
    "offer_absent_field": {"now": NOW},  # offers key entirely missing
    "offer_flat_500": {
        "now": NOW,
        "offers": [{"offer_id": "ofr_A4", "flat_amount": 500, "currency": "INR",
                    "valid_until": "2026-09-20T23:59:59+05:30", "active": True}],
    },
    "offer_flat_150": {
        "now": NOW,
        "offers": [{"offer_id": "ofr_A5", "flat_amount": 150, "currency": "INR",
                    "valid_until": "2026-09-20T23:59:59+05:30", "active": True}],
    },

    # --- inventory --------------------------------------------------------
    "inv_2": {"now": NOW, "inventory": {"sku_88": 2}},
    "inv_240": {"now": NOW, "inventory": {"sku_88": 240}},
    "inv_absent": {"now": NOW},  # platform holds no inventory - genuinely unknowable

    # --- subscription -----------------------------------------------------
    "sub_attempt_4_of_4": {
        "now": NOW,
        "subscription": {"status": "active", "attempt_index": 4, "max_attempts": 4, "next_action": "cancel"},
    },
    "sub_attempt_1_of_4": {
        "now": NOW,
        "subscription": {"status": "active", "attempt_index": 1, "max_attempts": 4, "next_action": "retry"},
    },
    "sub_cancelled": {
        "now": NOW,
        "subscription": {"status": "cancelled", "attempt_index": 4, "max_attempts": 4, "next_action": "none"},
    },

    # --- payment ----------------------------------------------------------
    "pay_failed": {"now": NOW, "payment": {"payment_id": "pay_9x", "status": "failed", "amount": 249900, "currency": "INR"}},
    "pay_captured": {"now": NOW, "payment": {"payment_id": "pay_9y", "status": "captured", "amount": 249900, "currency": "INR"}},
    "pay_absent": {"now": NOW},

    # --- cart / price -----------------------------------------------------
    "cart_2items_4999": {"now": NOW, "cart": {"item_count": 2, "total": 499900, "currency": "INR"}},
    "cart_5items_4999": {"now": NOW, "cart": {"item_count": 5, "total": 499900, "currency": "INR"}},

    # --- eligibility / customer ------------------------------------------
    "cust_optedout": {"now": NOW, "customer": {"opted_out": True, "tier": "standard"}},
    "cust_active_gold": {"now": NOW, "customer": {"opted_out": False, "tier": "gold"}},
    "cust_active_std": {"now": NOW, "customer": {"opted_out": False, "tier": "standard"}},
    "cust_tier_absent": {"now": NOW, "customer": {"opted_out": False}},
}

# ---------------------------------------------------------------------------
# Cases. (message, state_key, label, claim_types, note)
# `pair` groups two cases that MUST share identical message text.
# ---------------------------------------------------------------------------

PAIRS = [
    # 1 - canonical deadline pair
    ("Your offer expires in 24 hours.", "offer_40_live", "SUPPORTED",
     "Your offer expires in 24 hours.", "offer_15_expired", "CONTRADICTED", ["deadline"]),
    # 2 - discount magnitude, same sentence
    ("Grab a flat 15% off before you check out.", "offer_15_live", "SUPPORTED",
     "Grab a flat 15% off before you check out.", "offer_40_live", "CONTRADICTED", ["discount"]),
    # 3 - scarcity, present vs absent state -> UNVERIFIABLE is correct
    ("Hurry, only 2 left in stock.", "inv_2", "SUPPORTED",
     "Hurry, only 2 left in stock.", "inv_absent", "UNVERIFIABLE", ["scarcity"]),
    # 4 - scarcity contradicted
    ("Almost gone - just a couple of units remaining.", "inv_2", "SUPPORTED",
     "Almost gone - just a couple of units remaining.", "inv_240", "CONTRADICTED", ["scarcity"]),
    # 5 - subscription consequence
    ("This is our final attempt; your plan will be cancelled after this.", "sub_attempt_4_of_4", "SUPPORTED",
     "This is our final attempt; your plan will be cancelled after this.", "sub_attempt_1_of_4", "CONTRADICTED",
     ["subscription_consequence"]),
    # 6 - payment status
    ("We couldn't process your payment.", "pay_failed", "SUPPORTED",
     "We couldn't process your payment.", "pay_captured", "CONTRADICTED", ["payment_status"]),
    # 7 - flat amount discount
    ("Here's Rs 500 off your next order.", "offer_flat_500", "SUPPORTED",
     "Here's Rs 500 off your next order.", "offer_flat_150", "CONTRADICTED", ["discount"]),
    # 8 - cart contents
    ("You left 2 items behind.", "cart_2items_4999", "SUPPORTED",
     "You left 2 items behind.", "cart_5items_4999", "CONTRADICTED", ["cart"]),
    # 9 - eligibility, missing field -> unverifiable
    ("As a Gold member you get early access.", "cust_active_gold", "SUPPORTED",
     "As a Gold member you get early access.", "cust_tier_absent", "UNVERIFIABLE", ["eligibility"]),
    # 10 - eligibility contradicted
    ("Exclusive to our Gold tier customers.", "cust_active_gold", "SUPPORTED",
     "Exclusive to our Gold tier customers.", "cust_active_std", "CONTRADICTED", ["eligibility"]),
    # 11 - offer existence, empty list vs missing key
    ("Your 15% discount is still available.", "offer_none", "CONTRADICTED",
     "Your 15% discount is still available.", "offer_absent_field", "UNVERIFIABLE", ["discount"]),
    # 12 - indirect urgency phrasing
    ("Only a few hours left to use this.", "offer_40_live", "SUPPORTED",
     "Only a few hours left to use this.", "offer_15_live", "CONTRADICTED", ["deadline"]),
    # 13 - subscription already cancelled
    ("Your subscription is still active - renew now to keep it.", "sub_attempt_1_of_4", "SUPPORTED",
     "Your subscription is still active - renew now to keep it.", "sub_cancelled", "CONTRADICTED",
     ["subscription_consequence"]),
    # 14 - payment status, absent
    ("Your last transaction went through successfully.", "pay_captured", "SUPPORTED",
     "Your last transaction went through successfully.", "pay_absent", "UNVERIFIABLE", ["payment_status"]),
    # 15 - price claim
    ("Your basket comes to Rs 4,999.", "cart_2items_4999", "SUPPORTED",
     "Your basket comes to Rs 4,999.", "pay_absent", "UNVERIFIABLE", ["price"]),
    # 16 - compound: both claims must hold. Caught by the pair-integrity audit:
    #      the original second state (offer_15_live) also yielded CONTRADICTED,
    #      which is a correct label but makes it two singles, not a pair.
    ("Take 15% off, but it ends tonight.", "offer_15_tonight", "SUPPORTED",
     "Take 15% off, but it ends tonight.", "offer_40_live", "CONTRADICTED", ["discount", "deadline"]),
    # 17 - scarcity phrased as social proof
    ("Stock is running low on this one.", "inv_2", "SUPPORTED",
     "Stock is running low on this one.", "inv_240", "CONTRADICTED", ["scarcity"]),
    # 18 - deadline expressed as date-free urgency
    ("Last chance - this deal closes today.", "offer_40_live", "SUPPORTED",
     "Last chance - this deal closes today.", "offer_flat_500", "CONTRADICTED", ["deadline"]),
    # 19 - retry framing
    ("We'll try charging your card once more tomorrow.", "sub_attempt_1_of_4", "SUPPORTED",
     "We'll try charging your card once more tomorrow.", "sub_attempt_4_of_4", "CONTRADICTED",
     ["subscription_consequence"]),
    # 20 - opted-out customer (policy, not truth - tests label discipline)
    ("Here's an update on your order.", "cust_active_std", "SUPPORTED",
     "Here's an update on your order.", "cust_optedout", "CONTRADICTED", ["eligibility"]),
    # 21 - flat vs percent confusion
    ("You've got 500 off waiting for you.", "offer_flat_500", "SUPPORTED",
     "You've got 500 off waiting for you.", "offer_15_live", "UNVERIFIABLE", ["discount"]),
    # 22 - expired but active-sounding
    ("Your discount code is live right now.", "offer_15_live", "SUPPORTED",
     "Your discount code is live right now.", "offer_15_expired", "CONTRADICTED", ["discount", "deadline"]),
]

SINGLES = [
    ("Thanks for shopping with us - your order is on its way.", "cart_2items_4999", "UNVERIFIABLE",
     ["delivery"], "no shipment state present"),
    ("You have 240 units available if you want to bulk order.", "inv_240", "SUPPORTED", ["scarcity"], ""),
    ("Reply STOP to unsubscribe at any time.", "cust_active_std", "SUPPORTED", ["eligibility"],
     "no factual claim about state"),
    ("Your plan renews automatically unless cancelled.", "sub_attempt_1_of_4", "SUPPORTED",
     ["subscription_consequence"], ""),
    ("We noticed you were looking at this item.", "cart_2items_4999", "UNVERIFIABLE", ["cart"],
     "browsing history not in state"),
    ("This price is the lowest it has ever been.", "cart_2items_4999", "UNVERIFIABLE", ["price"],
     "no price history in state"),
    ("Your card ending 4242 was declined.", "pay_failed", "UNVERIFIABLE", ["payment_status"],
     "status matches but card last4 not in state"),
    ("Everyone in your city is buying this right now.", "inv_240", "UNVERIFIABLE", ["scarcity"],
     "no geographic demand data"),
    ("Rs 500 off, valid until 20 September.", "offer_flat_500", "SUPPORTED", ["discount", "deadline"], ""),
    ("Rs 500 off, valid until 20 September.", "offer_flat_150", "CONTRADICTED", ["discount", "deadline"], ""),
    ("Your subscription payment failed four times.", "sub_attempt_4_of_4", "SUPPORTED",
     ["subscription_consequence"], ""),
    ("Your subscription payment failed four times.", "sub_attempt_1_of_4", "CONTRADICTED",
     ["subscription_consequence"], ""),
    ("You're one of only 2 people with this in their cart.", "inv_2", "UNVERIFIABLE", ["scarcity"],
     "inventory 2 != carts 2; different quantity"),
    ("Complete checkout to secure your 15% saving.", "offer_15_live", "SUPPORTED", ["discount"], ""),
    ("Complete checkout to secure your 15% saving.", "offer_none", "CONTRADICTED", ["discount"], ""),
    ("We've held your items for you.", "cart_2items_4999", "UNVERIFIABLE", ["cart"], "no hold/reservation state"),
    ("Payment of Rs 2,499 could not be collected.", "pay_failed", "SUPPORTED", ["payment_status", "price"], ""),
    ("Payment of Rs 2,499 could not be collected.", "pay_captured", "CONTRADICTED", ["payment_status", "price"], ""),
    ("Your offer has already expired.", "offer_15_expired", "SUPPORTED", ["deadline"], ""),
    ("Your offer has already expired.", "offer_15_live", "CONTRADICTED", ["deadline"], ""),
    ("You qualify for free delivery on this order.", "cart_2items_4999", "UNVERIFIABLE", ["eligibility"],
     "no shipping rules in state"),
    ("There is no discount on your cart at the moment.", "offer_none", "SUPPORTED", ["discount"], ""),
    ("There is no discount on your cart at the moment.", "offer_15_live", "CONTRADICTED", ["discount"], ""),
    ("Your gold-tier benefits are active.", "cust_active_gold", "SUPPORTED", ["eligibility"], ""),
    ("A quick reminder about the items in your basket.", "cart_5items_4999", "SUPPORTED", ["cart"],
     "vague, no falsifiable quantity"),
    ("Buy now before the price goes up next week.", "cart_2items_4999", "UNVERIFIABLE", ["price"],
     "future pricing not in state"),
]


def case_id(message, state_key):
    h = hashlib.sha1(f"{message}||{state_key}".encode()).hexdigest()
    return "c_" + h[:10]


def build():
    cases = []
    for i, (m1, s1, l1, m2, s2, l2, ctypes) in enumerate(PAIRS):
        assert m1 == m2, f"pair {i} messages differ - breaks the experiment"
        pid = "p_" + hashlib.sha1(m1.encode()).hexdigest()[:8]
        for msg, sk, lbl in ((m1, s1, l1), (m2, s2, l2)):
            cases.append({
                "case_id": case_id(msg, sk), "pair_id": pid, "message": msg,
                "state_key": sk, "state": STATES[sk], "claim_types": ctypes,
                "label": lbl, "note": "",
            })
    for msg, sk, lbl, ctypes, note in SINGLES:
        cases.append({
            "case_id": case_id(msg, sk), "pair_id": None, "message": msg,
            "state_key": sk, "state": STATES[sk], "claim_types": ctypes,
            "label": lbl, "note": note,
        })

    # Deterministic split that keeps pairs intact: bucket by pair_id (or case_id
    # for singles) so a pair always lands together.
    for c in cases:
        key = c["pair_id"] or c["case_id"]
        bucket = int(hashlib.sha1(key.encode()).hexdigest(), 16) % 2
        c["split"] = "heldout" if bucket == 0 else "dev"

    cases.sort(key=lambda c: c["case_id"])
    return cases


if __name__ == "__main__":
    cases = build()
    out = pathlib.Path(__file__).parent / "dataset.json"
    payload = json.dumps(cases, indent=2, sort_keys=True, ensure_ascii=False)
    out.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (out.parent / "dataset.sha256").write_text(digest, encoding="utf-8")
    print(f"cases={len(cases)}  sha256={digest}")
