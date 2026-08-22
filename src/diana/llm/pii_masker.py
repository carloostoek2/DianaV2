"""PII masking at the LLM trust boundary (pure functions, no I/O).

Every outbound LLM call crosses a trust boundary: message text leaves the
system and is processed by an external provider. This module replaces
personal identifiers (emails, phone numbers, payment cards, @handles, URLs)
with collision-safe placeholders before the payload is sent, and can restore
the originals on the provider reply when the model echoed a placeholder
verbatim (the reply goes back to the same VIP, so restoring is safe).

Design rules:
- Pure: no network, no Telegram, no persistence, no settings.
- Collision-safe: a placeholder is never a substring of the input text and
  is never reused for two different values.
- Order matters: URLs before emails (a URL may embed an email-like segment),
  phones before cards (a card-shaped digit run must not be half-consumed as
  a phone; cards are Luhn-validated), handles last (emails are already
  replaced, so their "@" never re-matches).
- Names are intentionally NOT masked: personalization depends on them and
  regexes cannot distinguish a first name from ordinary capitalized words.
  The agreement with the provider (docs/ACUERDO-PROVEEDOR-LLM.md) is the
  legal layer that covers the remaining exposure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_EMAIL_RE = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_URL_RE = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+")
# 13–19 digits (spaces/dashes allowed between groups), Luhn-validated below.
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
# Mexico-centric phone shapes; the lookbehinds and trailing guard reject a
# match that starts inside a longer digit run, so a 16-digit card is never
# half-consumed as a phone.
_PHONE_MX_RE = re.compile(
    r"(?<!\d)(?<!\d[\s-])"
    r"(?:\+?52[\s-]?)?"
    r"(?:1[\s-]?)?"
    r"\(?\d{2,4}\)?"
    r"[\s-]?\d{3,4}"
    r"[\s-]?\d{3,4}"
    r"(?![\s-]?\d)"
)
# International numbers that carry a "+" prefix.
_PHONE_INTL_RE = re.compile(
    r"(?<![\w+])\+\d{1,3}(?:[\s-]?\d{2,4}){2,5}(?![\s-]?\d)"
)
_HANDLE_RE = re.compile(r"(?<![A-Za-z0-9_])@[A-Za-z0-9_]{3,32}(?![A-Za-z0-9_])")


@dataclass(frozen=True)
class MaskResult:
    """Output of :func:`mask_pii`."""

    masked: str
    mapping: dict[str, str] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)


def _luhn_valid(digits: str) -> bool:
    """Luhn checksum guard against false positives on long digit runs."""
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = ord(ch) - 48
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _fresh_token(label: str, text: str, used: set[str]) -> str:
    """Placeholder that is neither present in ``text`` nor already used."""
    token = f"[{label}]"
    counter = 0
    while token in text or token in used:
        counter += 1
        token = f"[{label}-{counter}]"
    return token


def mask_pii(text: str) -> MaskResult:
    """Replace personal identifiers with placeholders.

    Returns the masked text plus a mapping placeholder → original value and
    per-entity counters. A text without matches is returned untouched with an
    empty mapping.
    """
    if not text:
        return MaskResult(masked=text)

    masked = text
    mapping: dict[str, str] = {}
    used: set[str] = set()
    stats: dict[str, int] = {}

    def _replace(pattern: re.Pattern[str], label: str) -> None:
        nonlocal masked
        count = 0

        def _sub(match: re.Match[str]) -> str:
            nonlocal count
            value = match.group(0)
            if label == "tarjeta" and not _luhn_valid(re.sub(r"\D", "", value)):
                return value
            token = _fresh_token(label, masked, used)
            used.add(token)
            mapping[token] = value
            count += 1
            return token

        masked = pattern.sub(_sub, masked)
        if count:
            stats[label] = count

    _replace(_URL_RE, "enlace")
    _replace(_EMAIL_RE, "correo")
    _replace(_PHONE_INTL_RE, "telefono")
    _replace(_PHONE_MX_RE, "telefono")
    _replace(_CARD_RE, "tarjeta")
    _replace(_HANDLE_RE, "usuario")
    return MaskResult(masked=masked, mapping=mapping, stats=stats)


def unmask_pii(text: str, mapping: dict[str, str]) -> str:
    """Restore placeholders introduced by :func:`mask_pii`.

    Only tokens present in ``mapping`` are replaced, so this can never inject
    data that was not masked in the first place. Longest tokens first so a
    generic placeholder never partially replaces a numbered one.
    """
    if not text or not mapping:
        return text
    for token in sorted(mapping, key=len, reverse=True):
        text = text.replace(token, mapping[token])
    return text
