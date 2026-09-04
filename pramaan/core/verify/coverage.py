"""
Span-coverage invariant.

THE HOLE THIS CLOSES
--------------------
Validator (H1/H2/H3) checks the findings the model DID emit. It cannot see the
claim the model silently failed to report - and that omission is the failure
mode, because a model asked "did you cover everything?" is auditing its own
blind spot.

So coverage is computed from the DRAFT TEXT by code that never consults the
model: every checkable span in the draft must overlap an accepted finding's
span, or the message is blocked.

    invariant:  no un-adjudicated numeric or temporal span may ship

HONEST LIMITS (state these out loud in the demo)
------------------------------------------------
  - Catches numeric and temporal claims only. A silently-omitted QUALITATIVE
    claim ("you qualify", "exclusive to you") is NOT caught. That hole is open.
  - Deliberately over-flags. A false block costs one conversion; a false send
    costs a regulatory finding. Precision is traded for recall on purpose.
"""

import re
from dataclasses import dataclass, field

from .normalise import NotNormalised, normalise, require_normalised  # noqa: F401

# Findings may not be wildly larger than the token they claim to cover.
# Without this, one span over the whole draft covers every token (verified
# bypass, 2026-09-04: 4 spans found, 0 uncovered, passed=True).
MAX_SPAN_RATIO = 3

PATTERNS = [
    ("PERCENT",   r"\d+(?:\.\d+)?\s*(?:%|percent|per cent)"),
    ("AMOUNT",    r"(?:Rs\.?|INR|₹)\s*\d[\d,]*(?:\.\d+)?"
                  r"|\d[\d,]*(?:\.\d+)?\s*(?:rupees|rs\.?)\b"),
    ("DURATION",  r"\d+\s*(?:hour|hr|day|week|month|year|minute|min)s?\b"
                  r"|\b(?:a|an|one)\s+(?:hour|day|week|month)\b"),
    ("DATE",      r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b"
                  r"|\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b"
                  r"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\b"),
    ("RELTIME",   r"\b(?:today|tonight|tomorrow|yesterday|this\s+week|next\s+week"
                  r"|last\s+chance|final\s+attempt|right\s+now|expires?\s+soon)\b"),
    ("COUNTWORD", r"\b(?:only|just|last|final)\s+(?:a\s+)?(?:few|couple|one|two|three)\b"),
    ("BARE_NUM",  r"\b\d[\d,]*(?:\.\d+)?\b"),
]

# Spans that look checkable but are not claims about merchant state.
IGNORE = re.compile(
    r"\b(?:24\s*/\s*7|\+?91[\-\s]?\d{10}|\d{4}\s*\d{4}\s*\d{4})\b"
    r"|\bending\s+\d{4}\b",                       # card last4
    re.IGNORECASE,
)


@dataclass
class Span:
    kind: str
    start: int
    end: int
    text: str
    covered_by: str | None = None


@dataclass
class CoverageReport:
    spans: list[Span] = field(default_factory=list)
    passed: bool = True

    @property
    def uncovered(self) -> list[Span]:
        return [s for s in self.spans if s.covered_by is None]

    def reason(self) -> str:
        if self.passed:
            return f"ok - all {len(self.spans)} checkable spans adjudicated"
        bits = ", ".join(f"{s.kind} {s.text!r} at offset {s.start}" for s in self.uncovered)
        return f"uncovered span(s): {bits}"


def find_spans(draft: str) -> list[Span]:
    """Extract checkable spans, highest-priority pattern winning each region."""
    require_normalised(draft)
    consumed = [False] * len(draft)
    for m in IGNORE.finditer(draft):
        for i in range(m.start(), m.end()):
            consumed[i] = True

    spans: list[Span] = []
    for kind, pattern in PATTERNS:
        for m in re.finditer(pattern, draft, re.IGNORECASE):
            if any(consumed[m.start():m.end()]):
                continue
            for i in range(m.start(), m.end()):
                consumed[i] = True
            spans.append(Span(kind, m.start(), m.end(), m.group(0)))
    spans.sort(key=lambda s: s.start)
    return spans


def check(draft: str, accepted_findings: list[dict]) -> CoverageReport:
    """
    accepted_findings: findings that PASSED the validator, each with
    span_start / span_end into `draft`. Rejected findings are not passed in -
    a hallucinated finding must never satisfy coverage.
    """
    report = CoverageReport(spans=find_spans(draft))
    for span in report.spans:
        token_len = span.end - span.start
        for f in accepted_findings:
            fs, fe = f.get("span_start"), f.get("span_end")
            if fs is None or fe is None:
                continue
            # CONTAINMENT, not overlap. Overlap alone let a single finding
            # spanning the whole draft satisfy every token.
            if not (fs <= span.start and fe >= span.end):
                continue
            # ...and the finding may not be disproportionately wide.
            if (fe - fs) > MAX_SPAN_RATIO * token_len:
                continue
            span.covered_by = f.get("claim_kind", "unknown")
            break
    report.passed = not report.uncovered
    return report


if __name__ == "__main__":
    draft = ("Hi Rhea - only 2 left in stock. Get 40% off, expires in 24 hours. "
             "Your basket comes to Rs 4,999. Card ending 4242. Support is 24/7.")

    print("DRAFT:", draft, "\n")
    print("SPANS FOUND")
    for s in find_spans(draft):
        print(f"  {s.kind:<10} {s.text!r:<18} [{s.start}:{s.end}]")

    # what a complete, honest model output covers
    full = [
        {"claim_kind": "quantity",         "span_start": draft.index("2 left"),  "span_end": draft.index("2 left") + 1},
        {"claim_kind": "discount_percent", "span_start": draft.index("40%"),     "span_end": draft.index("40%") + 3},
        {"claim_kind": "deadline",         "span_start": draft.index("24 hours"), "span_end": draft.index("24 hours") + 8},
        {"claim_kind": "amount",           "span_start": draft.index("Rs 4,999"), "span_end": draft.index("Rs 4,999") + 8},
    ]
    # the failure mode: model silently drops the deadline claim
    omitted = [f for f in full if f["claim_kind"] != "deadline"]

    for name, findings in (("COMPLETE", full), ("DEADLINE OMITTED", omitted), ("EMPTY", [])):
        r = check(draft, findings)
        print(f"\n{name:<18} passed={r.passed}\n  {r.reason()}")
