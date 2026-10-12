"""search/list/show answer like the MCP tools and never write to the vault."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from test_cli_vault_resolution import run_cli

from birkin_mnemosyne.memory import VaultMemory
from birkin_mnemosyne.mnemosyne import DYNAMICS_FILE

KOREAN_TITLE = "릴리스 준비"
KOREAN_BODY = "릴리스 체크리스트: dns cutover 승인 후 배포"


def seeded_vault(root: Path) -> Path:
    """A vault with one used Korean note, so dynamics exist on disk."""
    vault = root / "vault"
    memory = VaultMemory({"vault_path": str(vault)})
    _ = memory.write_note(KOREAN_TITLE, KOREAN_BODY, note_type="project",
                          tags=["release"], zone="inbox")
    _ = memory.get_note(KOREAN_TITLE)   # reading through the library = usage
    memory.dex.flush()
    assert (vault / DYNAMICS_FILE).is_file()
    return vault


def digests(vault: Path) -> dict[str, str]:
    return {path.relative_to(vault).as_posix():
            hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(vault.rglob("*"))
            if path.is_file() and (path.suffix == ".md"
                                   or path.name == DYNAMICS_FILE)}


def test_search_keeps_korean_under_a_cp1252_console(tmp_path: Path) -> None:
    # Given a Korean note and a console encoding that cannot hold it.
    vault = seeded_vault(tmp_path)

    # When the terminal searches for a Korean word.
    result = run_cli("search", "릴리스", "--vault", str(vault), cwd=tmp_path,
                     env={"PYTHONIOENCODING": "cp1252"})

    # Then the JSON on stdout is UTF-8 with the Korean intact.
    assert result.returncode == 0, result.stderr
    hit, = json.loads(result.stdout.decode("utf-8"))["results"]
    assert hit["title"] == KOREAN_TITLE
    assert hit["slug"] and "릴리스" in hit["snippet"]
    assert hit["zone"] == "inbox" and hit["type"] == "project"


def test_reads_change_no_note_and_no_dynamics_byte(tmp_path: Path) -> None:
    # Given a vault whose notes and usage dynamics are already on disk.
    vault = seeded_vault(tmp_path)
    before = digests(vault)
    assert f"{DYNAMICS_FILE}" in before

    # When every read command runs over it.
    for case in (("search", "릴리스"), ("list",), ("show", KOREAN_TITLE)):
        result = run_cli(*case, "--vault", str(vault), cwd=tmp_path)
        assert result.returncode == 0, (case, result.stderr)

    # Then no note and no usage ranking moved (the index cache may refresh).
    assert digests(vault) == before


def test_list_pages_the_newest_notes_first(tmp_path: Path) -> None:
    # Given three notes in one vault.
    vault = tmp_path / "vault"
    memory = VaultMemory({"vault_path": str(vault)})
    for title in ("First note", "Second note", "Third note"):
        _ = memory.write_note(title, f"body of {title}", zone="inbox")
    memory.dex.flush()

    # When the list is paged.
    first = run_cli("list", "--limit", "2", "--vault", str(vault),
                    cwd=tmp_path)
    second = run_cli("list", "--limit", "2", "--offset", "2", "--vault",
                     str(vault), cwd=tmp_path)

    # Then the totals and the page sizes match the MCP list contract.
    assert first.returncode == 0 and second.returncode == 0, first.stderr
    head, tail = json.loads(first.stdout), json.loads(second.stdout)
    assert head["total"] == tail["total"] == 3
    assert head["offset"] == 0 and tail["offset"] == 2
    assert len(head["notes"]) == 2 and len(tail["notes"]) == 1
    assert {note["slug"] for note in head["notes"] + tail["notes"]} == \
        {"first-note", "second-note", "third-note"}


def test_show_of_an_absent_note_exits_one_with_stderr(tmp_path: Path) -> None:
    # Given a vault without that note.
    vault = seeded_vault(tmp_path)

    # When show names it anyway.
    result = run_cli("show", "no-such-note", "--vault", str(vault),
                     cwd=tmp_path)

    # Then the absence is exit 1 on stderr, not an error payload.
    assert result.returncode == 1
    assert result.stdout == b""
    assert b"no note" in result.stderr


def test_invalid_zone_and_limit_exit_two(tmp_path: Path) -> None:
    # Given a vault that must not be read on invalid input.
    vault = seeded_vault(tmp_path)

    for case in (("search", "릴리스", "--zone", "Not A Zone"),
                 ("search", "릴리스", "--limit", "0"),
                 ("list", "--limit", "501"),
                 ("list", "--offset", "-1")):
        # When a bound or zone name is out of contract.
        result = run_cli(*case, "--vault", str(vault), cwd=tmp_path)

        # Then the command boundary refuses it.
        assert result.returncode == 2, (case, result.stdout)
        assert result.stderr, case


def _mcp_tool(vault: Path, name: str, arguments: dict[str, Any]) -> Any:
    from mcp import Client

    from birkin_mnemosyne._mcp_app import create_server

    async def run() -> Any:
        async with Client(create_server(vault)) as client:
            return await client.call_tool(name, arguments)

    result = asyncio.run(run())
    assert not result.is_error, result.content
    return result.structured_content


def test_cli_payload_keys_equal_the_mcp_tool_keys(tmp_path: Path) -> None:
    _ = pytest.importorskip("mcp")

    # Given one vault read by both surfaces.
    vault = seeded_vault(tmp_path)
    cases = (
        (("search", "릴리스"), "memory_search", {"query": "릴리스"}, "results"),
        (("list",), "memory_list", {}, "notes"),
        (("show", KOREAN_TITLE), "memory_get_note", {"note": KOREAN_TITLE},
         None),
    )

    for command, tool, arguments, items in cases:
        # When the CLI and the MCP tool answer the same question.
        result = run_cli(*command, "--vault", str(vault), cwd=tmp_path)
        assert result.returncode == 0, (command, result.stderr)
        cli = json.loads(result.stdout.decode("utf-8"))
        served = _mcp_tool(vault, tool, arguments)

        # Then the payload keys are identical, item keys included.
        assert set(cli) == set(served), command
        if items is not None:
            assert cli[items] and served[items], command
            assert set(cli[items][0]) == set(served[items][0]), command


def test_list_offset_past_any_page_size_is_accepted(tmp_path: Path) -> None:
    # Given a vault with one note.
    vault = tmp_path / "vault"
    memory = VaultMemory({"vault_path": str(vault)})
    _ = memory.write_note("Only note", "body", zone="inbox")
    memory.dex.flush()

    # When the offset is beyond any page size (MCP accepts any offset >= 0).
    result = run_cli("list", "--offset", "501", "--vault", str(vault),
                     cwd=tmp_path)

    # Then the page is simply empty.
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["offset"] == 501 and payload["notes"] == [] and payload["total"] == 1


@pytest.mark.parametrize("command", [("search", "deployment"), ("list", "--limit", "1")])
def test_label_filters_are_anded_before_results_and_counts(
    tmp_path: Path, command: tuple[str, ...],
) -> None:
    # Given two matching notes and a newer-sorting note carrying only one label.
    vault = tmp_path / "vault"
    memory = VaultMemory({"vault_path": str(vault)})
    for title in ("Match alpha", "Match beta"):
        memory.write_note(title, "deployment checklist", zone="inbox",
                          labels=["project:alpha", "stage:ready"])
    memory.write_note("Z nonmatching", "deployment checklist", zone="inbox",
                      labels=["project:alpha", "stage:draft"])
    memory.dex.flush()
    before = digests(vault)

    # When the terminal applies both label constraints.
    result = run_cli(*command, "--label", "project:alpha", "--label", "stage:ready",
                     "--vault", str(vault), cwd=tmp_path)

    # Then filtering precedes pagination and does not change notes or usage.
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    if command[0] == "list":
        assert payload["total"] == 2 and len(payload["notes"]) == 1
        assert payload["label_counts"] == {"project:alpha": 2, "stage:ready": 2}
        assert payload["notes"][0]["slug"] in {"match-alpha", "match-beta"}
    else:
        assert {hit["slug"] for hit in payload["results"]} == {"match-alpha", "match-beta"}
    assert digests(vault) == before
