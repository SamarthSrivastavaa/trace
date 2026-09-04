"""One canonical text coordinate system.

NFC can change string length, which shifts every later offset. Verified:
'Cafe' + U+0301 puts PERCENT at offset 12, while the precomposed form puts it
at 11. If the model computes spans on one form and the lexer runs on another,
coverage misaligns silently.

So the whole system uses exactly ONE form. normalise() is called once at
intake; every later stage asserts it.
"""

import unicodedata


class NotNormalised(ValueError):
    """Text reached a stage that requires the canonical NFC form."""


def normalise(raw: str) -> str:
    """Canonical message form. Call ONCE at intake, before anything computes
    an offset, sends text to a model, or hashes it."""
    return unicodedata.normalize("NFC", raw)


def is_normalised(text: str) -> bool:
    return unicodedata.normalize("NFC", text) == text


def require_normalised(text: str) -> None:
    """Fail loudly rather than misalign silently."""
    if not is_normalised(text):
        raise NotNormalised(
            "text is not NFC-normalised; call normalise() at intake so model "
            "spans and lexer spans share one coordinate system")
