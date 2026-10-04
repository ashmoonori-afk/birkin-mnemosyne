from __future__ import annotations

from pathlib import Path

import pytest

from birkin_mnemosyne.consolidation import Consolidation
from birkin_mnemosyne.memory import VaultMemory


@pytest.mark.parametrize(("first", "second"), [
    (
        "The Zephyr cache closes at sunset. "
        + "An independent backup worker rotates its certificates every seventh week.",
        "The Zephyr cache closes at sunset. "
        + "A separate metrics logger emits numbered status reports during migration.",
    ),
    ("Cache limit: 1ms.", "Cache limit: 2ms."),
    ("Relay 12 has a cache limit of 1ms.", "Relay 12 has a cache limit of 2ms."),
    ("The Orion relay may broadcast.", "The Orion relay may not broadcast."),
    ("The harbor gate opens on 2026-10-01.", "The harbor gate opens on 2026-10-02."),
    ("The north cistern holds 120 liters.", "The north cistern holds 180 liters."),
    ("The north cistern material is steel.", "The north cistern material is copper."),
])
def test_supported_changed_assertions_are_offered(
    tmp_path: Path, first: str, second: str,
) -> None:
    memory = VaultMemory({"vault_path": str(tmp_path)})
    first_path = memory.write_note("First observation", first)
    second_path = memory.write_note("Second observation", second)

    questions = Consolidation(tmp_path).questions()

    assert len(questions) == 1
    question, = questions
    assert {question.first.path, question.second.path} == {
        first_path.relative_to(tmp_path).as_posix(),
        second_path.relative_to(tmp_path).as_posix(),
    }
    assert question.reason == "overlap-or-conflict"


@pytest.mark.parametrize(("first", "second"), [
    (
        "Queue latency is monitored daily by the north branch.",
        "Queue retention is monitored daily by the north branch.",
    ),
    (
        "The north cache closes after 12 hours.",
        "The south cache closes after 12 hours.",
    ),
    (
        "For the west region the cache limit is 12 hours.",
        "For the east region the cache limit is 18 hours.",
    ),
    (
        "The queue limit is less than 12 hours.",
        "The queue delay is more than 18 hours.",
    ),
    ("Relay 12 broadcasts status every evening.", "Relay 18 broadcasts status every evening."),
    ("Relay 12 cache limit: 1ms.", "Relay 18 cache limit: 2ms."),
    ("The north cistern holds 120 liters.", "The south cistern holds 180 liters."),
    ("The north cistern holds 120 liters.", "The north cistern holds 180 gallons."),
    ("The north cistern material is steel.", "The north cistern color is copper."),
    ("The north cistern material is steel.", "The south cistern material is copper."),
    ("The north cistern is red.", "The north cistern is heavy."),
    (
        "The sample collector logs water levels each Monday. "
        + "We improve steadily, we improve together.",
        "The access ledger tracks key renewals each Friday. "
        + "We improve steadily, we improve together.",
    ),
    (
        "The ferry roster changed at dawn. "
        + "Send feedback to the team - we respond to every request.",
        "The hillside checkpoint closes at dusk. "
        + "Send feedback to the team - we respond to every request.",
    ),
])
def test_topic_similarity_without_assertion_witness_is_not_offered(
    tmp_path: Path, first: str, second: str,
) -> None:
    memory = VaultMemory({"vault_path": str(tmp_path)})
    _ = memory.write_note("First observation", first)
    _ = memory.write_note("Second observation", second)

    questions = Consolidation(tmp_path).questions()

    assert questions == ()
