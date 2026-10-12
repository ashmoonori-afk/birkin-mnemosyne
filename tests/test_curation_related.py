"""Related links belong to the Markdown section, not an unrelated tail."""

from pathlib import Path

import pytest

from birkin_mnemosyne import VaultMemory, evaluate_plan
from birkin_mnemosyne.identity_reader import parse_sections


@pytest.mark.parametrize(
    "body",
    [
        "## Related\n- [[Existing]]\n\n## Notes\nKeep these notes.\n",
        "```markdown\n## Related\n```\n\n## Notes\nKeep these notes.\n",
        "Related\n-------\n- [[Existing]]\n\n## Notes\nKeep these notes.\n",
    ],
)
def test_links_enter_the_related_section_without_moving_other_content(
    tmp_path: Path, body: str,
) -> None:
    # Given a note with a real or fenced Related heading and a following section.
    memory = VaultMemory({"vault_path": str(tmp_path)})
    source = memory.write_note("Source", body, zone="inbox")
    memory.write_note("Target", "Target detail.", zone="inbox")

    # When the public curation entry point links them.
    result = evaluate_plan(tmp_path, {
        "plan_version": 1,
        "ops": [{"op": "link", "a": "source", "b": "target"}],
    }, apply=True)

    # Then the new link is in the real Related section and the Notes remain intact.
    assert {"op": "link", "a": "source", "b": "target"} in result.effected
    sections = parse_sections(Path(source).read_text(encoding="utf-8"))
    related = [section for section in sections
               if section.level == 2 and section.heading == "Related"]
    assert len(related) == 1
    assert "- [[Target]]" in related[0].text
    notes = next(section for section in sections if section.heading == "Notes")
    assert "Keep these notes." in notes.text
    assert "[[Target]]" not in notes.text
