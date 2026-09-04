"""One canonical coordinate system.

NFC changes string length, which shifts every later offset. If the model
computes spans on one form and the lexer runs on another, coverage misaligns
silently. Verified before the fix: PERCENT at offset 12 in NFD, 11 in NFC.
"""

import pytest

from pramaan.core.verify.coverage import find_spans
from pramaan.core.verify.normalise import (NotNormalised, is_normalised,
                                           normalise, require_normalised)

NFD = "Café - get 40% off within 24 hours"      # e + combining acute
NFC = "Café - get 40% off within 24 hours"       # precomposed


def test_nfd_and_nfc_inputs_yield_identical_spans():
    """THE first test named in the build spec."""
    a = [(s.kind, s.start, s.end) for s in find_spans(normalise(NFD))]
    b = [(s.kind, s.start, s.end) for s in find_spans(normalise(NFC))]
    assert a == b
    assert a, "expected at least one span"


def test_raw_nfd_and_nfc_offsets_actually_differ():
    """Proves the test above is testing something real."""
    assert len(NFD) != len(NFC)
    assert NFD.index("40%") != NFC.index("40%")


def test_find_spans_rejects_unnormalised_input():
    with pytest.raises(NotNormalised):
        find_spans(NFD)


def test_normalise_is_idempotent():
    once = normalise(NFD)
    assert normalise(once) == once
    assert is_normalised(once)


def test_require_normalised_accepts_canonical_form():
    require_normalised(normalise(NFD))       # must not raise
