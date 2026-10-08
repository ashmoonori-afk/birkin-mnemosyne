"""A small YAML-subset parser for ``SKILL.md`` frontmatter.

We intentionally avoid a PyYAML dependency. This parser handles the subset
used by skill frontmatter:

- ``key: value`` scalars (strings, ints, floats, booleans, null)
- quoted strings (``"..."`` / ``'...'``)
- inline lists ``[a, b, c]``
- nested mappings via indentation (e.g. ``metadata.hermes.tags``)
- block lists (``- item``)

It is forgiving: anything it cannot parse degrades to a raw string rather than
raising.
"""

from __future__ import annotations

import re
from typing import Any


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_text, body). No frontmatter -> ('', text)."""
    if not text.startswith("---"):
        return "", text
    lines = text.splitlines()
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:])
    return "", text


def parse(text: str) -> tuple[dict[str, Any], str]:
    """Parse a full SKILL.md string into (meta, body)."""
    fm, body = split_frontmatter(text)
    if not fm:
        return {}, body
    meta = _parse_block(fm.splitlines(), 0, 0)[0] or {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, body


# -- internals -------------------------------------------------------------

def _indent(s: str) -> int:
    return len(s) - len(s.lstrip(" "))


def _split_commas(s: str, quotes: bool = True) -> list[str]:
    out, depth, buf = [], 0, []
    in_str = esc = False
    for ch in s:
        if in_str:   # inside a double-quoted token: commas/brackets are text
            buf.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if quotes and ch == '"' and not "".join(buf).strip():
            in_str = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return [x.strip() for x in out if x.strip()]


_UNESCAPE_RE = re.compile(r'\\([\\"])')
_QUOTED_RE = re.compile(r'"(?:[^"\\]|\\.)*"')
_INT_RE = re.compile(r"-?(?:0|[1-9]\d*)")
_FLOAT_RE = re.compile(r"-?(?:0|[1-9]\d*)\.\d+")


def _parse_value(s: str) -> Any:
    s = s.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        if s[0] == '"':   # only \\ and \" are escapes; old data has neither
            return _UNESCAPE_RE.sub(r"\1", s[1:-1])
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        items = _split_commas(inner)
        if any(x.startswith('"') and not _QUOTED_RE.fullmatch(x) for x in items):
            # The writer only emits well-formed quoted tokens, so this list
            # predates quoting (e.g. ["D:\dir\", "x"]): split on commas and
            # keep the inner text raw, exactly as before.
            return [x[1:-1] if len(x) >= 2 and x[0] == x[-1] == '"'
                    else _parse_value(x)
                    for x in _split_commas(inner, quotes=False)]
        return [_parse_value(x) for x in items]
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "~", ""):
        return None
    # Strict numerics only: never nan/inf/exponent forms or leading-zero ids.
    if _INT_RE.fullmatch(s):
        return int(s)
    if _FLOAT_RE.fullmatch(s):
        return float(s)
    return s


def _parse_block(lines: list[str], i: int, base: int):
    """Parse lines[i:] at indentation >= base into a dict or list.

    Returns (obj, next_index).
    """
    result: Any = None
    while i < len(lines):
        raw = lines[i]
        if not raw.strip():
            i += 1
            continue
        ind = _indent(raw)
        if ind < base:
            break
        content = raw.strip()

        if content.startswith("- "):  # block list item
            if result is None:
                result = []
            item = content[2:].strip()
            if ":" in item and not item.startswith("["):
                key, _, val = item.partition(":")
                entry: dict[str, Any] = {}
                if val.strip():
                    entry[key.strip()] = _parse_value(val)
                sub, i = _parse_block(lines, i + 1, ind + 2)
                if isinstance(sub, dict):
                    entry.update(sub)
                result.append(entry)
            else:
                result.append(_parse_value(item))
                i += 1
            continue

        # mapping entry
        if result is None:
            result = {}
        key, _, val = content.partition(":")
        key = key.strip()
        val = val.strip()
        if val:
            result[key] = _parse_value(val)
            i += 1
        else:
            sub, i = _parse_block(lines, i + 1, ind + 1)
            result[key] = {} if sub is None else sub
    return result, i
