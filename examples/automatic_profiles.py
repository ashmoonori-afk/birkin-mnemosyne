"""Exercise automatic role-profile memory through its public API."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from birkin_mnemosyne import PROFILE_DESCRIPTIONS, ProfileMemory


def review_exchange(_exchange) -> str:
    return json.dumps(
        {
            "profiles": {
                "user": "Builds local-first AI tools.",
                "preferences": "Prefers concise evidence.",
                "soul": "Use direct Korean.",
                "workflow": "Test behavior before implementation.",
                "automation": "Automate repetitive verification.",
            }
        }
    )


with TemporaryDirectory(prefix="mnemosyne-profiles-") as directory:
    vault = Path(directory)
    with ProfileMemory(vault, review_exchange) as memory:
        memory.record_exchange(
            "메모리를 자동으로 관리해 줘.",
            "대화를 백그라운드에서 검토해 역할별로 저장하겠습니다.",
        )
        memory.flush()

    with ProfileMemory(vault, review_exchange) as reloaded:
        profiles = reloaded.read_profiles()

    for name, description in PROFILE_DESCRIPTIONS.items():
        relative = f"system/{name}.md"
        print(f"{relative} | {description} | {profiles[name][0]}")
