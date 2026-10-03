"""Private Markdown boundaries shared by identity and startup readers."""

from __future__ import annotations

import re
from typing import TypeAlias

Span: TypeAlias = tuple[int, int, str, int]


def parse_spans(text: str, *, startup_labels: bool = False) -> tuple[Span, ...]:
    """Return nonblank raw line spans with headings and levels, excluding frontmatter."""
    lines = text.splitlines(keepends=True)
    syntax_lines = list(lines)
    if syntax_lines:
        syntax_lines[0] = syntax_lines[0].removeprefix("\ufeff")
    start = 0
    if syntax_lines and syntax_lines[0].strip() == "---":
        close = next((i for i in range(1, len(lines))
                      if lines[i].strip() == "---"), None)
        if close is not None:
            start = close + 1
    headings: list[tuple[int, int, str]] = []
    fence = ""
    width = 0
    i = start
    while i < len(lines):
        line = syntax_lines[i].rstrip("\r\n")
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            run, rest = marker.groups()
            if not fence:
                fence, width = run[0], len(run)
            elif run[0] == fence and len(run) >= width and not rest.strip():
                fence = ""
            i += 1
            continue
        if fence:
            i += 1
            continue
        atx = re.match(r"^ {0,3}(#{1,6})(?:[ \t]+(.+?)|[ \t]*)$", line)
        if atx:
            title = re.sub(r"[ \t]+#+[ \t]*$", "", atx.group(2) or "")
            headings.append((i, len(atx.group(1)), title))
        elif startup_labels and re.match(r"^ {0,3}TOP NOTE\b", line, re.IGNORECASE):
            headings.append((i, 2, line.strip()))
        elif i + 1 < len(lines) and line.strip():
            underline = re.fullmatch(r" {0,3}(=+|-+)[ \t]*", lines[i + 1].rstrip("\r\n"))
            if underline:
                headings.append((i, 1 if underline.group(1)[0] == "=" else 2,
                                 line.strip()))
                i += 1
        i += 1
    if not headings or headings[0][0] > start:
        headings.insert(0, (start, 0, "Preamble"))
    result: list[Span] = []
    for position, (begin, level, heading) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        if "".join(lines[begin:end]).strip():
            result.append((begin, end, heading, level))
    return tuple(result)
