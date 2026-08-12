from __future__ import annotations

import json
from pathlib import Path
from threading import Event

import pytest

from birkin_mnemosyne import ProfileMemory, ProfileReviewError

EXPECTED_FILES = {
    "user": "User characteristics and stable personal context.",
    "preferences": "User preferences and favored choices.",
    "soul": "Conversation style and interaction guidance.",
    "workflow": "User work process and execution guidance.",
    "automation": "User workflow automation guidance.",
}


def _review(**profiles: str):
    payload = {"profiles": profiles}
    return lambda _exchange: json.dumps(payload)


def test_profile_store_bootstraps_five_role_files(tmp_path: Path):
    memory = ProfileMemory(tmp_path, _review())
    memory.close()

    system = tmp_path / "system"
    assert {path.name for path in system.glob("*.md")} == {
        f"{name}.md" for name in EXPECTED_FILES
    }
    for name, description in EXPECTED_FILES.items():
        text = (system / f"{name}.md").read_text(encoding="utf-8")
        assert f"description: {description}" in text
        assert "## Guidance" in text


def test_record_exchange_reviews_and_saves_profiles_automatically(
    tmp_path: Path,
):
    review = _review(
        user="Builds local-first AI tools.",
        preferences="Prefers concise evidence.",
        soul="Use direct Korean.",
        workflow="Test behavior before implementation.",
        automation="Automate repetitive verification.",
    )

    with ProfileMemory(tmp_path, review) as memory:
        memory.record_exchange("깊이 들어가자", "증거 중심으로 구현하겠습니다.")
        memory.flush()

    with ProfileMemory(tmp_path, _review()) as reloaded:
        profiles = reloaded.read_profiles()

    assert profiles == {
        "user": ["Builds local-first AI tools."],
        "preferences": ["Prefers concise evidence."],
        "soul": ["Use direct Korean."],
        "workflow": ["Test behavior before implementation."],
        "automation": ["Automate repetitive verification."],
    }


def test_record_exchange_returns_before_background_review_finishes(
    tmp_path: Path,
):
    started = Event()
    release = Event()

    def review(_exchange):
        started.set()
        assert release.wait(timeout=2)
        return json.dumps({"profiles": {"user": "Values bounded waits."}})

    memory = ProfileMemory(tmp_path, review)
    future = memory.record_exchange("remember this", "working")

    assert started.wait(timeout=2)
    assert not future.done()

    release.set()
    memory.flush()
    assert future.done()
    assert memory.read_profiles()["user"] == ["Values bounded waits."]

    memory.close()
    with pytest.raises(RuntimeError, match="closed"):
        memory.record_exchange("too late", "ignored")


def test_malformed_review_cannot_escape_profile_files(tmp_path: Path):
    def review(_exchange):
        return json.dumps(
            {
                "profiles": {
                    "../escape": "must not be written",
                    "user": ["not", "a", "string"],
                }
            }
        )

    memory = ProfileMemory(tmp_path, review)
    memory.record_exchange("malformed", "review")

    with pytest.raises(ProfileReviewError):
        memory.flush()
    memory.close()

    assert not (tmp_path / "escape.md").exists()
    assert {path.name for path in (tmp_path / "system").glob("*.md")} == {
        f"{name}.md" for name in EXPECTED_FILES
    }
