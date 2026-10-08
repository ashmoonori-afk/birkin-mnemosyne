"""README.md is the PyPI long description, so every link must be absolute.

PyPI does not resolve repository-relative paths: a relative image or file
link renders broken on pypi.org. In-page anchors (``#section``) are fine.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_FENCED_CODE = re.compile(r"^```.*?^```", re.M | re.S)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_LINK_TARGETS = re.compile(
    r"\]\(\s*<?(?P<md>[^)\s>]+)"
    r"|\b(?:src|href)\s*=\s*[\"'](?P<html>[^\"']+)"
    r"|^\s*\[[^\]]+\]:\s*<?(?P<ref>\S+?)>?\s*$",
    re.M,
)
_ALLOWED_PREFIXES = ("https://", "http://", "mailto:", "#")


def _link_targets(markdown: str) -> list[str]:
    text = _INLINE_CODE.sub("", _FENCED_CODE.sub("", markdown))
    return [
        m.group("md") or m.group("html") or m.group("ref")
        for m in _LINK_TARGETS.finditer(text)
    ]


def test_readme_has_no_relative_links() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    targets = _link_targets(readme)
    assert targets, "expected README.md to contain links"
    relative = [t for t in targets if not t.startswith(_ALLOWED_PREFIXES)]
    assert relative == [], f"relative links break on PyPI: {relative}"


def test_link_scanner_flags_relative_and_allows_anchors() -> None:
    sample = (
        "![hero](docs/a.png) [ok](#intro) [web](https://x.y/z)\n"
        '<img src="img/b.png"> `[code](not/a/link)`\n'
        "[ref]: LICENSE\n"
    )
    targets = _link_targets(sample)
    relative = [t for t in targets if not t.startswith(_ALLOWED_PREFIXES)]
    assert relative == ["docs/a.png", "img/b.png", "LICENSE"]
