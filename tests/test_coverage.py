"""Coverage: the only defence against the model silently omitting a claim.

Regression-locks a FATAL bypass found on 2026-09-04: with overlap-only
matching, ONE finding spanning the whole draft satisfied every token
(4 spans found, 0 uncovered, passed=True).
"""

from attest.core.verify.coverage import MAX_SPAN_RATIO, check, find_spans, normalise

DRAFT = normalise("Get 40% off, expires in 24 hours. Only 2 left. Total Rs 4,999.")


def _finding(needle, kind="x", anchor=None):
    """anchor disambiguates repeated text - DRAFT.index("2") finds the '2' in
    '24 hours', not the one in 'Only 2 left'."""
    base = DRAFT.index(anchor) if anchor else 0
    i = DRAFT.index(needle, base)
    return {"claim_kind": kind, "span_start": i, "span_end": i + len(needle)}


def _all_findings():
    return [_finding("40%"), _finding("24 hours"),
            _finding("2", anchor="Only"), _finding("Rs 4,999")]


def test_exact_findings_cover_everything():
    r = check(DRAFT, _all_findings())
    assert r.passed, r.reason()


def test_whole_draft_span_cannot_cover_everything():
    """The FATAL bypass. Must stay closed."""
    r = check(DRAFT, [{"claim_kind": "x", "span_start": 0, "span_end": len(DRAFT)}])
    assert not r.passed
    assert len(r.uncovered) == len(r.spans)


def test_slightly_wide_span_still_counts():
    """Containment must not be so strict that honest findings fail."""
    i = DRAFT.index("40%")
    others = [f for f in _all_findings() if f["span_start"] != i]
    r = check(DRAFT, others + [
        {"claim_kind": "discount", "span_start": i - 1, "span_end": i + 4}])
    assert r.passed, r.reason()


def test_span_wider_than_ratio_is_rejected():
    i = DRAFT.index("40%")
    wide = 3 * MAX_SPAN_RATIO
    r = check(DRAFT, [{"claim_kind": "x", "span_start": max(0, i - wide),
                       "span_end": i + 3 + wide}])
    assert not r.passed


def test_omitting_one_finding_is_detected():
    r = check(DRAFT, [f for f in _all_findings()
                      if DRAFT[f["span_start"]:f["span_end"]] != "24 hours"])
    assert not r.passed
    assert [s.text for s in r.uncovered] == ["24 hours"]


def test_benign_values_are_not_claims():
    """Card last4 and 24/7 must not become false positives."""
    d = normalise("Card ending 4242. Support is 24/7. Call +919876543210.")
    assert find_spans(d) == []


def test_composite_tokens_are_single_spans():
    spans = {s.text: s.kind for s in find_spans(DRAFT)}
    assert spans["40%"] == "PERCENT"
    assert spans["Rs 4,999"] == "AMOUNT"
    assert spans["24 hours"] == "DURATION"
    assert "4" not in spans and "999" not in spans


def test_repeated_values_need_separate_findings():
    """Matching is by position, never by value."""
    d = normalise("2 items in your cart, only 2 left in stock.")
    first = d.index("2")
    r = check(d, [{"claim_kind": "item_count", "span_start": first,
                   "span_end": first + 1}])
    assert not r.passed, "one finding covered both occurrences of '2'"
    assert len(r.uncovered) == 1


def test_compound_text_requires_one_claim_per_token():
    """A claim carries exactly one asserted value, so it covers exactly one
    token. Compound text is two claims, not one wide span - discovered when a
    span covering '15% off, ends tonight' failed the ratio bound."""
    d = normalise("Take 15% off, ends tonight.")
    a, b = d.index("15%"), d.index("tonight")

    wide = check(d, [{"claim_kind": "compound", "span_start": a,
                      "span_end": b + len("tonight")}])
    assert not wide.passed, "one wide span must not stand in for two claims"

    split = check(d, [
        {"claim_kind": "discount_percent", "span_start": a, "span_end": a + 3},
        {"claim_kind": "deadline_within", "span_start": b, "span_end": b + 7}])
    assert split.passed, split.reason()
