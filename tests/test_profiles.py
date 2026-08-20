from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from threading import Event

import pytest

from birkin_mnemosyne import ProfileMemory, ProfileProposal, ProfileReviewError

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


def test_legacy_mode_adds_guidance_once(tmp_path: Path):
    review = _review(preferences="  Prefers concise   evidence.  ")

    with ProfileMemory(tmp_path, review) as memory:
        memory.record_exchange("remember", "ok").result()
        memory.record_exchange("remember again", "ok").result()

    path = tmp_path / "system" / "preferences.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines.count("- Prefers concise evidence.") == 1


def test_sink_mode_delivers_proposals_without_writing_files(tmp_path: Path):
    calls = []

    def save(proposals):
        calls.append(proposals)

    def review(_exchange):
        return json.dumps(
            {
                "profiles": {
                    "preferences": "  Keep   this normalized. ",
                    "workflow": [
                        {"action": "add", "content": "Add this."},
                        {
                            "action": "replace",
                            "old_text": "Old workflow.",
                            "content": "New workflow.",
                        },
                    ],
                    "automation": [
                        {"action": "remove", "old_text": "Outdated automation."}
                    ],
                }
            }
        )

    with ProfileMemory(tmp_path, review, save=save) as memory:
        memory.record_exchange("review", "queued").result()
        with pytest.raises(RuntimeError, match="sink mode.*owns no files"):
            memory.read_profiles()

    assert not (tmp_path / "system").exists()
    assert list(tmp_path.iterdir()) == []
    assert calls == [
        (
            ProfileProposal(
                profile="preferences",
                action="add",
                content="Keep this normalized.",
            ),
            ProfileProposal(
                profile="workflow",
                action="add",
                content="Add this.",
            ),
            ProfileProposal(
                profile="workflow",
                action="replace",
                content="New workflow.",
                old_text="Old workflow.",
            ),
            ProfileProposal(
                profile="automation",
                action="remove",
                old_text="Outdated automation.",
            ),
        )
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"profiles": {"unknown": "bad"}},
        {"profiles": {"preferences": "ok"}, "extra": True},
        {"profiles": {"preferences": ""}},
        {"profiles": {"preferences": [{"action": "archive"}]}},
        {"profiles": {"preferences": [{"action": "add", "content": ""}]}},
        {
            "profiles": {
                "preferences": [
                    {"action": "add", "content": "ok", "old_text": "old"}
                ]
            }
        },
        {"profiles": {"preferences": [{"action": "replace", "content": "ok"}]}},
        {
            "profiles": {
                "preferences": [
                    {"action": "remove", "content": "bad", "old_text": "old"}
                ]
            }
        },
        {"profiles": {"preferences": [{"action": "remove", "old_text": ""}]}},
        {"profiles": {"preferences": [{"action": "add", "content": 3}]}},
    ],
)
def test_malformed_sink_reviews_raise_without_saving(tmp_path: Path, payload):
    calls = []

    memory = ProfileMemory(
        tmp_path,
        lambda _exchange: json.dumps(payload),
        save=lambda proposals: calls.append(proposals),
    )
    memory.record_exchange("bad", "review")

    with pytest.raises(ProfileReviewError):
        memory.flush()
    memory.close()

    assert calls == []
    assert not (tmp_path / "system").exists()


def test_importing_profiles_does_not_load_mnemosyne_module():
    code = (
        "import sys; "
        "import birkin_mnemosyne.profiles; "
        "assert 'birkin_mnemosyne.mnemosyne' not in sys.modules; "
        "print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "ok"
