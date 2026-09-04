"""Project the frozen benchmark dataset into the production snapshot shape.

dataset.json is hash-frozen (f3b65c56...) and pre-registered, so it must NOT be
edited. The field-name and unit differences are reconciled HERE instead.

Two kinds of difference, established by reading the dataset's own gold labels:

  RENAME ONLY - the dataset already stores minor units
      payment.amount   249900  <- "Payment of Rs 2,499 could not be collected"
      cart.total       499900  <- "Your basket comes to Rs 4,999"

  RENAME + UNIT CONVERSION - the dataset stores rupees here
      offers[].flat_amount  500  <- "Here's Rs 500 off your next order"

That inconsistency is inside the frozen dataset. It is not corrected there; it
is documented and converted at this boundary so the benchmark and the
production adjudicator agree on units.

  PASSED THROUGH, DELIBERATELY - no EvidenceRef can address it
      inventory.*

      Razorpay holds no inventory, so the production schema has no way to cite
      it and quantity claims are always UNVERIFIABLE. But 9 dataset cases have
      gold labels that DEPEND on inventory, so dropping it would make the
      competing arm (B2, an LLM reasoning over the state) answer UNVERIFIABLE
      where gold says SUPPORTED - penalising B2 for our schema's limitation.
      That would be a rigged benchmark.

      So inventory stays in the snapshot. Every arm sees identical state. B3
      then loses those cases honestly, because its architecture genuinely
      cannot express the claim. That is a real limitation being measured, not
      an artefact of unfair state.

  DROPPED - carry no adjudicable meaning
      *.currency    (schema is INR-only)
      payment_id
"""

RUPEES_TO_PAISE = 100


def dataset_state_to_snapshot(state: dict) -> dict:
    """Pure projection. No I/O, no mutation of the input."""
    snap: dict = {}
    if "now" in state:
        snap["now"] = state["now"]

    if "offers" in state:
        offers = []
        for o in state["offers"]:
            out = {"offer_id": o["offer_id"], "active": o.get("active", True)}
            if "percent" in o:
                out["percent"] = o["percent"]
            if "flat_amount" in o:
                # rupees in the dataset, minor units in the schema
                out["flat_amount_minor"] = int(o["flat_amount"]) * RUPEES_TO_PAISE
            if "valid_until" in o:
                out["valid_until"] = o["valid_until"]
            offers.append(out)
        snap["offers"] = sorted(offers, key=lambda o: o["offer_id"])

    if "subscription" in state:
        s = state["subscription"]
        snap["subscription"] = {k: s[k] for k in
                                ("status", "attempt_index", "max_attempts",
                                 "next_action") if k in s}

    if "payment" in state:
        p = state["payment"]
        out = {}
        if "status" in p:
            out["status"] = p["status"]
        if "amount" in p:
            out["amount_minor"] = int(p["amount"])      # already minor units
        snap["payment"] = out

    if "cart" in state:
        c = state["cart"]
        out = {}
        if "item_count" in c:
            out["item_count"] = c["item_count"]
        if "total" in c:
            out["total_minor"] = int(c["total"])        # already minor units
        snap["cart"] = out

    if "inventory" in state:
        # not citable by any EvidenceRef - see module docstring
        snap["inventory"] = dict(state["inventory"])

    if "customer" in state:
        c = state["customer"]
        snap["customer"] = {k: c[k] for k in ("tier", "opted_out") if k in c}

    return snap
