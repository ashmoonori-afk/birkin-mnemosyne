"""Pure label value rules: shape validation, normalization and bounded evidence.

This module owns the value-level contract of a label: a ``namespace:value``
pair whose namespace is ASCII ``[a-z][a-z0-9_-]*`` after lowercasing, with a
nonempty value that contains no control characters.  Normalization is
deterministic: NFC, outer whitespace trimmed, namespace lowercased, value
spelling/case preserved, then sorted and deduplicated.

It also implements the bounded evidence helpers used by inference (real ISO
calendar dates, typed wikilink extraction and script-based language evidence).
These never consult the clock and never call a provider.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from datetime import date, datetime
from typing import Final


class LabelError(ValueError):
    """Malformed explicit label input rejected at a boundary."""


_NAMESPACE: Final = re.compile(r"[a-z][a-z0-9_-]*\Z")
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
_WIKILINK: Final = re.compile(
    r"\[\[\s*(project|person|entity)\s*:\s*([^\[\]\r\n|#]+?)"
    + r"(?:[|#][^\[\]\r\n]*)?\s*\]\]"
)
_ISO_DATE: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[T ][0-9:.,+Z-]+)?\Z")
_DATE_IN_TEXT: Final = re.compile(r"(?<!\d)[0-9]{4}-[0-9]{2}-[0-9]{2}(?!\d)")

# Script categories inferred conservatively to a single language.  Latin maps
# to nothing on purpose: Latin text alone is never proof of a specific
# language, so unknown Latin text stays unknown.
_SCRIPT_LANGUAGE: Final = {
    "hangul": "ko",
    "kana": "ja",
    "cyrillic": "ru",
    "arabic": "ar",
    "devanagari": "hi",
    "hebrew": "he",
    "greek": "el",
    "thai": "th",
    "georgian": "ka",
}
_SCRIPT_RANGES: Final = (
    (0xAC00, 0xD7A3, "hangul"),
    (0x1100, 0x11FF, "hangul"),
    (0x3130, 0x318F, "hangul"),
    (0x3040, 0x30FF, "kana"),
    (0x0400, 0x04FF, "cyrillic"),
    (0x0500, 0x052F, "cyrillic"),
    (0x0600, 0x06FF, "arabic"),
    (0x0750, 0x077F, "arabic"),
    (0x0900, 0x097F, "devanagari"),
    (0x05D0, 0x05EA, "hebrew"),
    (0x0370, 0x03FF, "greek"),
    (0x0E00, 0x0E7F, "thai"),
    (0x10A0, 0x10FF, "georgian"),
)


def _label_parts(label: object) -> tuple[str, str] | None:
    """Return (namespace, value) normalized, or None when the label is invalid."""
    if not isinstance(label, str) or _CONTROL.search(label):
        return None
    nfc = unicodedata.normalize("NFC", label).strip()
    raw_namespace, sep, raw_value = nfc.partition(":")
    if not sep:
        return None
    namespace = raw_namespace.strip().lower()
    value = raw_value.strip()
    if not _NAMESPACE.fullmatch(namespace) or not value:
        return None
    return namespace, value


def is_valid_label(label: str) -> bool:
    """True when the label can be normalized into a valid ``ns:value`` pair."""
    return _label_parts(label) is not None


def normalize_labels(values: Iterable[str]) -> tuple[str, ...]:
    """Normalize, sort and deduplicate an iterable of label strings.

    A bare string or bytes (instead of an iterable of strings) is rejected:
    an empty string must never silently mean "clear".  Malformed entries
    raise :class:`LabelError`; the namespace is lowercased while the value
    keeps its spelling and case.
    """
    if isinstance(values, (str, bytes)):
        raise LabelError("labels must be an iterable of 'namespace:value' strings")
    pairs: set[tuple[str, str]] = set()
    for value in values:
        parts = _label_parts(value)
        if parts is None:
            raise LabelError(f"invalid label: {value!r}")
        pairs.add(parts)
    return tuple(f"{namespace}:{value}" for namespace, value in sorted(pairs))


def yaml_label_list(labels: tuple[str, ...]) -> str:
    """Render labels as an inline YAML list with ``\\`` and ``"`` escaped."""
    return "[" + ", ".join('"' + label.replace("\\", "\\\\").replace('"', '\\"') + '"'
                           for label in labels) + "]"


def typed_wikilinks(text: str) -> tuple[tuple[str, str], ...]:
    """Extract ``[[project:...]]`` / ``[[person:...]]`` / ``[[entity:...]]``.

    Returned as ``(namespace, target)`` pairs in document order; targets are
    trimmed and display suffixes (``|``) are not part of a typed label link.
    """
    return tuple((m[1], m[2].strip()) for m in _WIKILINK.finditer(text))


def parse_iso_date(value: str) -> str | None:
    """Return the canonical ``YYYY-MM-DD`` of a real calendar date, or None.

    Accepts full ISO datetimes (``2026-10-11T12:00:00+09:00``) and zero-padded
    calendar dates.  Impossible dates (``2026-02-30``) and non-padded forms
    are not real ISO calendar dates and return None.
    """
    candidate = value.strip()
    if not _ISO_DATE.fullmatch(candidate):
        return None
    try:
        if len(candidate) == 10:
            return date.fromisoformat(candidate).isoformat()
        return datetime.fromisoformat(candidate.removesuffix("Z") + (
            "+00:00" if candidate.endswith("Z") else ""
        )).date().isoformat()
    except ValueError:
        return None


def iso_dates_in_text(text: str) -> tuple[str, ...]:
    """Real ISO calendar dates mentioned in free text, sorted, deduplicated."""
    found: set[str] = set()
    for match in _DATE_IN_TEXT.finditer(text):
        try:
            parsed = date.fromisoformat(match[0])
        except ValueError:
            continue
        found.add(parsed.isoformat())
    return tuple(sorted(found))


def detect_language(text: str) -> str | None:
    """Conservative script evidence for the note language, or None.

    Only unmistakable non-Latin scripts map to a language, and only when one
    script is dominant with at least four characters; mixed scripts and
    Latin-only text stay unknown (None).
    """
    counts: dict[str, int] = {}
    for char in text:
        script = _script_of(char)
        if script is not None:
            counts[script] = counts.get(script, 0) + 1
    strong = [script for script, count in counts.items() if count >= 4]
    if len(strong) != 1:
        return None
    return _SCRIPT_LANGUAGE.get(strong[0])


def _script_of(char: str) -> str | None:
    codepoint = ord(char)
    for start, end, script in _SCRIPT_RANGES:
        if start <= codepoint <= end:
            return script
    return None
