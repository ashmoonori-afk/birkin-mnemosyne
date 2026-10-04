"""Lexical address and decision-commentary restrictions for recall admission."""

from __future__ import annotations

import re


def addresses_agent(hint: str) -> bool:
    """Independently implement the documented address/imperative restrictions."""
    words = re.findall(r"\b[a-z]+(?:['’][a-z]+)?\b", hint.casefold())
    if set(words) & {"you", "your", "yours", "yourself"}:
        return True
    openings = {
        "never", "always", "ensure", "verify", "check", "run", "use", "read",
        "stop", "avoid", "remember", "keep", "prefer", "skip", "consider",
        "don't", "don’t",
    }
    if words and (words[0] in openings or words[:2] in (
        ["do", "not"], ["make", "sure"],
    )):
        return True
    ending = hint.rstrip(" \t.!?")
    return ending.endswith((
        "세요", "십시오", "십시요", "하라", "해라", "합니다", "지 마", "지 마라",
    )) or re.search("하지\\s*마", hint) is not None


def decision_commentary(hint: str) -> bool:
    """Reject decisions about whether to nudge, rather than stored observations."""
    text = " ".join(hint.casefold().split())
    if any(phrase in text for phrase in (
        "no stored memory", "clears the bar", "not relevant", "no relevant",
    )):
        return True
    if not ({"memory", "memories"} & set(re.findall(r"\w+", text))):
        return False
    return any(phrase in text for phrase in (
        "is unrelated to", "are unrelated to", "is not about", "are not about",
        "does not cover", "do not cover", "does not address", "do not address",
        "does not pertain", "do not pertain",
    )) or ("not the" in text and any(p in text for p in ("covers ", "cover ")))
