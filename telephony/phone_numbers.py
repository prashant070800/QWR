"""Phone-number normalization helpers."""

from __future__ import annotations

import re


def to_e164(raw_number: str | None, *, default_country_code: str = "91") -> str:
    """Return a best-effort E.164 phone number.

    Exotel payloads can arrive as ``+9198...``, ``9198...``, ``098...``, or
    occasionally with punctuation/spaces. The assignment target is India, so
    local 10-digit numbers default to +91.
    """
    if not raw_number:
        return ""

    cleaned = str(raw_number).strip()
    if not cleaned:
        return ""

    if cleaned.startswith("+"):
        digits = re.sub(r"\D", "", cleaned)
        return f"+{digits}" if digits else ""

    digits = re.sub(r"\D", "", cleaned)
    if not digits:
        return ""

    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = f"{default_country_code}{digits[1:]}"
    elif len(digits) == 10:
        digits = f"{default_country_code}{digits}"

    return f"+{digits}"
