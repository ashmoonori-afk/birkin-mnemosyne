"""Frozen context-only answerer for constrained section/field questions.

Question section and field are inputs, not labels recovered from gold answers.
No production reader code is imported: parser bugs cannot cancel each other.
This is not a generative-model accuracy benchmark.
"""

from __future__ import annotations

import re


def answer(context: str, section: str, field: str) -> str | None:
    """Extract the requested field only from the requested Markdown section."""
    active = False
    fence = ""
    width = 0
    for line in context.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            run = marker.group(1)
            if not fence:
                fence, width = run[0], len(run)
            elif run[0] == fence and len(run) >= width:
                fence = ""
            continue
        if fence:
            continue
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            active = heading.group(1).casefold() == section.casefold()
            continue
        key, separator, value = line.strip().partition(":")
        if active and separator and key.casefold() == field.casefold():
            return value.strip()
    return None
