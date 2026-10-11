"""Deterministic fallback extraction from plain transcript messages.

Hermes callback transcript parsing is intentionally conservative: work keeps
the last user and assistant textual content verbatim, sections come only from
explicitly marked headings, fenced examples are never read as declarations,
and unknown families stay empty.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict
from typing import Final, TypeAlias

from .handoff_models import HandoffFields
from .startup_sources import active_lines

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]

__all__ = ["checkpoint_capture_id", "extract_sections", "message_text", "transcript_fields"]

_SECTION_NAMES: Final = {
    "decisions": "decisions",
    "open items": "open_items",
    "open questions": "open_questions",
    "next step": "next_step",
    "links": "links",
}

_HEADING: Final = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.IGNORECASE)
_LIST: Final = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s*(.+?)\s*$")
def _message_payload(message: JsonValue) -> dict[str, JsonValue] | None:
    if not isinstance(message, dict):
        return None
    return message


def message_text(message: JsonValue) -> str | None:
    """Full textual content of one OpenAI-style message, or None when absent.

    Accepts both plain string content and the standard parts list; only text
    parts contribute and a blank message carries no text.
    """
    payload = _message_payload(message)
    if payload is None:
        return None
    content = payload.get("content")
    if isinstance(content, str):
        return content if content.strip() else None
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") != "text":
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text)
        if not parts:
            return None
        return "\n".join(parts)
    return None


def _last_role_text(messages: Sequence[JsonValue], role: str) -> str | None:
    for message in reversed(messages):
        payload = _message_payload(message)
        if payload is None or payload.get("role") != role:
            continue
        text = message_text(message)
        if text is not None:
            return text
    return None


def transcript_fields(messages: Sequence[JsonValue]) -> HandoffFields | None:
    """Fallback fields from a plain transcript; None when it has no text.

    ``work`` joins the last user and assistant textual content verbatim
    (both, in order, with no cuts); sections come from explicitly marked
    headings only.
    """
    parts = [
        text for text in (
            _last_role_text(messages, "user"),
            _last_role_text(messages, "assistant"),
        ) if text is not None
    ]
    if not parts:
        return None
    sections = extract_sections(messages)
    return HandoffFields(
        work="\n\n".join(parts),
        next_step="\n".join(sections["next_step"]),
        decisions=sections["decisions"],
        open_items=sections["open_items"],
        open_questions=sections["open_questions"],
        links=sections["links"],
    )


def extract_sections(
    messages: Sequence[JsonValue],
) -> dict[str, tuple[str, ...]]:
    """Explicitly marked sections in transcript order, fences excluded.

    A heading opens its named family and any heading closes the previous one;
    section bodies keep every nonblank line as an item, stripping list
    markers from bullet/numbered lines.
    """
    result: dict[str, list[str]] = {
        family: [] for family in _SECTION_NAMES.values()
    }
    for message in messages:
        payload = _message_payload(message)
        if payload is None or payload.get("role") not in ("user", "assistant"):
            continue
        text = message_text(message)
        if text is None:
            continue
        current: str | None = None
        for line in active_lines(text):
            stripped = line.strip()
            if not stripped:
                continue
            heading = _HEADING.fullmatch(stripped)
            if heading is not None:
                name = heading.group(1).strip()
                current = _SECTION_NAMES.get(name.casefold())
                continue
            if current is not None:
                item = _LIST.match(stripped)
                result[current].append(
                    item.group(1).strip() if item is not None else stripped)
    return {name: tuple(values) for name, values in result.items()}


def checkpoint_capture_id(session_id: str, event: str,
                          fields: HandoffFields) -> str:
    """Stable identity from session, event and canonical captured evidence.

    Identical callbacks derive the same id (an idempotent store retry), while
    changed evidence produces a fresh id and therefore another record.
    """
    canonical = json.dumps(
        asdict(fields), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(
        f"{event}\n{session_id}\n{canonical}".encode("utf-8")).hexdigest()
    return ":".join(part for part in (session_id, event, digest) if part)
