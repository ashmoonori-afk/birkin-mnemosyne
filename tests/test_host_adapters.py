"""Host-neutral adapter behavior; actual host discovery is checked separately."""

import importlib.util
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from birkin_mnemosyne import MemoryIndex, MemoryIndexError

SOURCE = Path(__file__).resolve().parents[1] / "integrations" / "hermes" / "provider.py"
spec = importlib.util.spec_from_file_location("mnemosyne_hermes_operations", SOURCE)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def provider(tmp_path):
    instance = module.VaultProvider()
    instance.initialize("test-session", hermes_home=str(tmp_path))
    yield instance
    instance.shutdown()


def call(provider, name, **arguments):
    return json.loads(provider.handle_tool_call(name, arguments))


def seed_cleanup_notes(provider):
    call(provider, "birkin_memory_remember", title="Cleanup probe", body="Synthetic zirconium probe.")
    call(provider, "birkin_memory_remember", title="Retained", body="Keep this other note.")


def test_cleanup_schemas_are_exact_and_confirm_defaults_false(provider):
    schemas = {s["name"]: s["parameters"] for s in provider.get_tool_schemas()}
    for name in ("birkin_memory_forget", "birkin_memory_restore"):
        schema = schemas[name]
        assert schema["required"] == ["note"]
        assert schema["properties"]["confirm"]["type"] == "boolean"
        assert schema["properties"]["confirm"]["default"] is False
        assert schema["additionalProperties"] is False


def test_forget_previews_without_moving_note(provider, tmp_path):
    seed_cleanup_notes(provider)
    result = call(provider, "birkin_memory_forget", note="knowledge/cleanup-probe.md")
    assert result["success"] and result["allowed"] and result["dry_run"]
    assert not result["archived"] and result["effected"] == []
    assert (vault_home(tmp_path) / "knowledge/cleanup-probe.md").is_file()


def test_forget_archives_bytes_and_hides_search_but_allows_direct_read(provider, tmp_path):
    seed_cleanup_notes(provider)
    source = vault_home(tmp_path) / "knowledge/cleanup-probe.md"
    original = source.read_bytes()
    result = call(provider, "birkin_memory_forget", note="cleanup-probe", confirm=True)
    assert result["success"] and result["archived"] and not result["dry_run"]
    assert not source.exists()
    assert (vault_home(tmp_path) / "_archive/knowledge/cleanup-probe.md").read_bytes() == original
    assert call(provider, "birkin_memory_search", query="zirconium")["results"] == []
    assert provider.prefetch("zirconium") == ""
    assert result["path"] == "_archive/knowledge/cleanup-probe.md"
    assert call(provider, "birkin_memory_get_note", title=result["path"])["body"] == "Synthetic zirconium probe."


@pytest.mark.parametrize("tool", ["birkin_memory_forget", "birkin_memory_restore"])
def test_cleanup_missing_note_is_an_error(provider, tool):
    result = call(provider, tool, note="missing", confirm=True)
    assert not result["success"] and "Note not found" in result["error"]


@pytest.mark.parametrize("note", ["Cleanup Probe", "cleanup", "zirconium", "knowledge/../knowledge/cleanup-probe.md"])
def test_forget_never_uses_query_or_normalized_title_matching(provider, tmp_path, note):
    seed_cleanup_notes(provider)
    result = call(provider, "birkin_memory_forget", note=note, confirm=True)
    assert "Note not found" in result["error"]
    assert (vault_home(tmp_path) / "knowledge/cleanup-probe.md").exists()


def test_forget_already_archived_note_errors(provider):
    seed_cleanup_notes(provider)
    archived = call(provider, "birkin_memory_forget", note="cleanup-probe", confirm=True)
    result = call(provider, "birkin_memory_forget", note=archived["slug"], confirm=True)
    assert not result["success"] and "already forgotten" in result["error"]


def test_forget_accepts_exact_stored_title(provider):
    seed_cleanup_notes(provider)
    result = call(provider, "birkin_memory_forget", note="Cleanup probe", confirm=True)
    assert result["success"] and result["archived"]


def test_forget_requires_path_when_same_title_is_ambiguous(provider, tmp_path):
    seed_cleanup_notes(provider)
    vault = vault_home(tmp_path)
    (vault / "other").mkdir()
    shutil.copyfile(vault / "knowledge/cleanup-probe.md", vault / "other/cleanup-probe.md")
    result = call(provider, "birkin_memory_forget", note="Cleanup probe", confirm=True)
    assert not result["success"] and "ambiguous note" in result["error"]
    result = call(provider, "birkin_memory_forget", note="other/cleanup-probe.md", confirm=True)
    assert result["success"] and result["archived"]
    assert (vault / "knowledge/cleanup-probe.md").is_file()
    assert (vault / "_archive/other/cleanup-probe.md").is_file()


def test_archive_path_still_targets_original_after_a_newer_same_name_note(provider, tmp_path):
    seed_cleanup_notes(provider)
    forgotten = call(provider, "birkin_memory_forget", note="cleanup-probe", confirm=True)
    vault = vault_home(tmp_path)
    archive = vault / forgotten["path"]
    original = archive.read_bytes()
    newer = vault / "newer/cleanup-probe.md"
    newer.parent.mkdir()
    newer.write_text("Newer unrelated note.", encoding="utf-8")
    timestamp = archive.stat().st_mtime + 100
    os.utime(newer, (timestamp, timestamp))
    assert call(provider, "birkin_memory_get_note", title="cleanup-probe")["body"] == "Newer unrelated note."
    assert call(provider, "birkin_memory_get_note", title=forgotten["path"])["body"] == "Synthetic zirconium probe."
    repeated = call(provider, "birkin_memory_forget", note=forgotten["path"], confirm=True)
    assert not repeated["success"] and "already forgotten" in repeated["error"]
    restored = call(provider, "birkin_memory_restore",
                    note=forgotten["path"], zone="restored", confirm=True)
    assert restored["success"] and restored["path"] == "restored/cleanup-probe.md"
    assert (vault / restored["path"]).read_bytes() == original
    assert newer.read_text(encoding="utf-8") == "Newer unrelated note."
    assert not archive.exists()


@pytest.mark.parametrize("attributes", [
    {"polarity": "negative"}, {"note_type": "preference"},
    {"zone": "identity", "note_type": "identity"},
    {"zone": "filed", "links": ["retained"]},
])
def test_forget_refuses_core_protected_notes(provider, tmp_path, attributes):
    from birkin_mnemosyne import VaultMemory

    seed_cleanup_notes(provider)
    memory = VaultMemory({"vault_path": str(vault_home(tmp_path))})
    # Identity is a frontmatter type understood by the curation gate, not write_note.
    if attributes.get("note_type") == "identity":
        path = memory.write_note("Protected", "Keep this.", zone="identity")
        path.write_text(path.read_text().replace("type: topic", "type: identity"))
    else:
        memory.write_note("Protected", "Keep this.", **attributes)
    result = call(provider, "birkin_memory_forget", note="protected", confirm=True)
    assert not result["success"] and result["error"] == "protected note"
    assert not result["archived"] and not result["allowed"]
    assert memory.get_note("protected") is not None


def test_forget_retains_the_core_last_active_note_cap(provider):
    call(provider, "birkin_memory_remember", title="Only", body="The sole active note.")
    result = call(provider, "birkin_memory_forget", note="only", confirm=True)
    assert not result["success"] and result["archive_cap"] == 0
    assert result["error"] == "archive_capped (>0)"
    assert not result["archived"]


def test_forget_refuses_hermes_note_with_body_wikilink(provider):
    seed_cleanup_notes(provider)
    created = call(provider, "birkin_memory_remember",
                   title="Linked canary", body="See [[retained]] for the control.")
    result = call(provider, "birkin_memory_forget", note=created["path"], confirm=True)
    assert not result["success"] and result["error"] == "protected note"
    assert not result["archived"]
    assert call(provider, "birkin_memory_get_note", title=created["path"])["body"] == "See [[retained]] for the control."


def test_two_consecutive_canaries_succeed_with_unique_titles(provider, tmp_path):
    call(provider, "birkin_memory_remember", title="Retained", body="A retained control.")
    for run_id in ("run-0001", "run-0002"):
        title = f"Cleanup probe {run_id}"
        created = call(provider, "birkin_memory_remember", title=title, body="Synthetic canary.")
        assert created["success"]
        assert call(provider, "birkin_memory_get_note", title=created["title"])["body"] == "Synthetic canary."
        forgotten = call(provider, "birkin_memory_forget", note=created["path"], confirm=True)
        assert forgotten["success"] and forgotten["archived"]
        assert call(provider, "birkin_memory_search", query=run_id)["results"] == []
        reused = call(provider, "birkin_memory_remember", title=title, body="Do not overwrite.")
        assert not reused["success"] and reused["error"] == "A note with this title already exists"
    archived = list((vault_home(tmp_path) / "_archive/knowledge").glob("cleanup-probe-*.md"))
    assert len(archived) == 2


@pytest.mark.parametrize("zone", ["inbox", "projects/cleanup"])
def test_restore_previews_then_roundtrips_bytes_and_recall(provider, tmp_path, zone):
    seed_cleanup_notes(provider)
    original = (vault_home(tmp_path) / "knowledge/cleanup-probe.md").read_bytes()
    archived = call(provider, "birkin_memory_forget", note="cleanup-probe", confirm=True)
    arguments = {} if zone == "inbox" else {"zone": zone}
    dry = call(provider, "birkin_memory_restore", note=archived["slug"], **arguments)
    assert dry["success"] and dry["dry_run"]
    assert (vault_home(tmp_path) / "_archive/knowledge/cleanup-probe.md").is_file()
    result = call(provider, "birkin_memory_restore", note=archived["slug"], confirm=True, **arguments)
    expected = "cleanup-probe.md" if zone == "inbox" else f"{zone}/cleanup-probe.md"
    assert result["success"] and not result["dry_run"] and result["path"] == expected
    assert (vault_home(tmp_path) / expected).read_bytes() == original
    assert call(provider, "birkin_memory_search", query="zirconium")["results"][0]["title"] == "cleanup-probe"


def test_restore_active_note_errors(provider):
    seed_cleanup_notes(provider)
    result = call(provider, "birkin_memory_restore", note="cleanup-probe", confirm=True)
    assert not result["success"] and "not archived" in result["error"]


@pytest.mark.parametrize("zone, error", [
    ("_archive", "restore target cannot be _archive"),
    ("_archive/nested", "cannot write a new note into the archive zone"),
    ("../outside", "invalid zone name"),
    ("/absolute", "invalid zone name"),
])
def test_restore_rejects_unsafe_or_archive_target(provider, tmp_path, zone, error):
    seed_cleanup_notes(provider)
    archived = call(provider, "birkin_memory_forget", note="cleanup-probe", confirm=True)
    assert archived["success"] and archived["archived"]
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*.md")}
    target = str(tmp_path / "absolute-outside") if zone == "/absolute" else zone
    result = call(provider, "birkin_memory_restore",
                  note=archived["path"], zone=target, confirm=True)
    assert not result["success"] and result["error"].startswith(error)
    assert (vault_home(tmp_path) / archived["path"]).is_file()
    assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*.md")} == before
    assert not (vault_home(tmp_path).parent / "outside").exists()
    assert not (tmp_path / "absolute-outside").exists()


@pytest.mark.parametrize("confirm", [False, True])
def test_restore_never_overwrites_existing_destination(provider, tmp_path, confirm):
    seed_cleanup_notes(provider)
    archived = call(provider, "birkin_memory_forget", note="cleanup-probe", confirm=True)
    destination = vault_home(tmp_path) / "cleanup-probe.md"
    destination.write_text("Unrelated existing note.", encoding="utf-8")
    archive = vault_home(tmp_path) / "_archive/knowledge/cleanup-probe.md"
    before = archive.read_bytes()
    result = call(provider, "birkin_memory_restore",
                  note="_archive/knowledge/cleanup-probe.md", confirm=confirm)
    assert archived["archived"] and not result["success"] and "already exists" in result["error"]
    assert destination.read_text() == "Unrelated existing note."
    assert archive.read_bytes() == before


@pytest.mark.parametrize("confirm", [False, True])
def test_restore_preview_and_apply_enforce_zone_cap(provider, tmp_path, confirm):
    from birkin_mnemosyne.mnemosyne import MAX_ZONES

    seed_cleanup_notes(provider)
    call(provider, "birkin_memory_forget", note="cleanup-probe", confirm=True)
    vault = vault_home(tmp_path)
    for number in range(MAX_ZONES - 1):
        zone = vault / f"zone-{number}"
        zone.mkdir()
        (zone / f"control-{number}.md").write_text("Retained control.", encoding="utf-8")
    archive = vault / "_archive/knowledge/cleanup-probe.md"
    before = archive.read_bytes()
    result = call(provider, "birkin_memory_restore",
                  note="_archive/knowledge/cleanup-probe.md", zone="new-zone", confirm=confirm)
    assert not result["success"] and result["error"].startswith(f"zone cap reached ({MAX_ZONES})")
    assert archive.read_bytes() == before
    assert not (vault / "new-zone").exists()


@pytest.mark.parametrize("tool", ["birkin_memory_forget", "birkin_memory_restore"])
@pytest.mark.parametrize("arguments", [
    {"confirm": "true"}, {"confirm": 1}, {"confirm": None}, {"extra": True},
])
def test_cleanup_rejects_invalid_arguments(provider, tool, arguments):
    result = call(provider, tool, note="missing", **arguments)
    assert not result["success"]
    assert result["error"].startswith(("confirm:", "arguments:"))


def test_unrelated_search_value_error_is_not_hidden_by_cleanup_error_handler(provider, monkeypatch):
    def broken_search(*_args, **_kwargs):
        raise ValueError("invalid index record")

    monkeypatch.setattr(module.VaultMemory, "search", broken_search)
    with pytest.raises(ValueError, match="invalid index record"):
        call(provider, "birkin_memory_search", query="query")


@pytest.mark.parametrize("tool", ["birkin_memory_forget", "birkin_memory_restore"])
@pytest.mark.parametrize("context", ["subagent", "cron", "flush"])
def test_cleanup_cannot_mutate_outside_primary_context(provider, tmp_path, tool, context):
    seed_cleanup_notes(provider)
    result = json.loads(provider.handle_tool_call(
        tool, {"note": "cleanup-probe", "confirm": True}, agent_context=context))
    assert result["error"] == "Memory writes require a primary agent context"
    provider.initialize("readonly", hermes_home=str(tmp_path), agent_context=context)
    result = call(provider, tool, note="cleanup-probe", confirm=True)
    assert result["error"] == "Memory writes require a primary agent context"


def test_recall_finds_note_written_through_provider(provider):
    # Given an explicit durable memory.
    call(provider, "birkin_memory_remember", title="Tea order", body="The usual drink is jasmine tea.")
    # When the model asks a lexical question.
    result = call(provider, "birkin_memory_search", query="jasmine")
    # Then it receives the stored snippet and a readable note identifier.
    assert result["success"]
    assert result["results"][0]["title"] == "tea-order"
    assert "jasmine tea" in result["results"][0]["snippet"]


def test_get_note_preserves_full_body_after_restart(tmp_path):
    first = module.VaultProvider()
    first.initialize("one", hermes_home=str(tmp_path))
    body = "First paragraph.\n\nSecond paragraph with 한국어."
    call(first, "birkin_memory_remember", title="Persistent note", body=body)
    first.shutdown()
    second = module.VaultProvider()
    second.initialize("two", hermes_home=str(tmp_path))
    try:
        result = call(second, "birkin_memory_get_note", title="Persistent note")
        assert result["success"] and result["body"] == body
    finally:
        second.shutdown()


def test_create_refuses_overwrite_and_preserves_original(provider):
    call(provider, "birkin_memory_remember", title="Existing", body="Keep the original.")
    result = call(provider, "birkin_memory_remember", title="Existing", body="Replace it.")
    assert not result["success"]
    assert call(provider, "birkin_memory_get_note", title="Existing")["body"] == "Keep the original."


@pytest.mark.parametrize("arguments", [
    {"title": "Injected\nversion: 999", "body": "bad"},
    {"title": "!!!", "body": "bad"},
    {"title": "Valid", "body": "   "},
    {"title": "Valid", "body": "body", "unknown": True},
    {"title": None, "body": "body"},
])
def test_invalid_write_does_not_create_note(provider, tmp_path, arguments):
    result = json.loads(provider.handle_tool_call("birkin_memory_remember", arguments))
    assert not result["success"]
    assert list((tmp_path / "birkin-mnemosyne" / "vault").rglob("*.md")) == []


@pytest.mark.parametrize("limit", [0, 21, True, 1.5, "2"])
def test_search_rejects_invalid_limits(provider, limit):
    assert not call(provider, "birkin_memory_search", query="query", limit=limit)["success"]


def test_empty_recall_returns_no_memory(provider):
    result = call(provider, "birkin_memory_search", query="nothing is stored yet")
    assert result["success"] and result["results"] == []
    assert provider.prefetch("nothing is stored yet") == ""


def test_unmatched_search_does_not_return_notes_from_nonempty_vault(provider):
    call(provider, "birkin_memory_remember", title="Tea order", body="The drink is jasmine tea.")
    result = call(provider, "birkin_memory_search", query="qxjzunrecorded93851")
    assert result["success"] and result["results"] == []


def test_prefetch_returns_matching_data_and_clears_empty_result(provider):
    call(provider, "birkin_memory_remember", title="Colour", body="Favourite colour: violet.")
    assert "violet" in provider.prefetch("favourite colour")
    assert provider.prefetch("zxqnotfound") == ""


def test_profiles_are_isolated_when_alternating(tmp_path):
    profiles = []
    try:
        for name in ("a", "b"):
            instance = module.VaultProvider()
            instance.initialize(name, hermes_home=str(tmp_path / name))
            profiles.append(instance)
        call(profiles[0], "birkin_memory_remember", title="Private", body="Only profile A knows amethyst.")
        assert call(profiles[1], "birkin_memory_search", query="amethyst")["results"] == []
        assert "amethyst" in profiles[0].prefetch("amethyst")
    finally:
        for instance in profiles:
            instance.shutdown()


@pytest.mark.parametrize("context", ["subagent", "cron", "flush"])
def test_non_primary_context_cannot_write(tmp_path, context):
    instance = module.VaultProvider()
    instance.initialize("readonly", hermes_home=str(tmp_path), agent_context=context)
    try:
        assert not call(instance, "birkin_memory_remember", title="Blocked", body="Do not persist.")["success"]
        assert list((tmp_path / "birkin-mnemosyne" / "vault").rglob("*.md")) == []
    finally:
        instance.shutdown()


@pytest.mark.parametrize("context", ["subagent", "cron", "flush"])
def test_call_context_blocks_writes_even_for_primary_instance(provider, tmp_path, context):
    result = json.loads(provider.handle_tool_call(
        "birkin_memory_remember",
        {"title": "Shared instance", "body": "Do not persist this background write."},
        agent_context=context,
    ))
    assert not result["success"]
    assert list((tmp_path / "birkin-mnemosyne" / "vault").rglob("*.md")) == []


def test_concurrent_same_title_has_one_winner(provider):
    # A barrier is unnecessary: every attempt must observe create-only semantics.
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(
            lambda index: call(provider, "birkin_memory_remember", title="Contended", body=f"Writer {index}"),
            range(8),
        ))
    assert sum(result["success"] for result in results) == 1
    assert call(provider, "birkin_memory_get_note", title="Contended")["body"] in {
        f"Writer {index}" for index in range(8)
    }


def test_shutdown_does_not_delete_notes_and_rejects_calls(provider, tmp_path):
    call(provider, "birkin_memory_remember", title="Retained", body="Durable after shutdown.")
    provider.shutdown()
    assert not call(provider, "birkin_memory_search", query="Durable")["success"]
    assert len(list((tmp_path / "birkin-mnemosyne" / "vault").rglob("*.md"))) == 1


def vault_home(home):
    return Path(home) / "birkin-mnemosyne" / "vault"


def seed_index(home, count, **register):
    vault = vault_home(home)
    vault.mkdir(parents=True, exist_ok=True)
    index = MemoryIndex(vault)
    for number in range(count):
        (vault / f"topic-{number}.md").write_text(f"Rule for task {number}.\n", encoding="utf-8")
        index.register(f"When handling task {number}", f"topic-{number}.md", **register)
    return index


def assert_all_entries(block, count):
    for number in range(count):
        assert f"When handling task {number} -> topic-{number}.md" in block


def test_index_survives_empty_prefetch_and_block_rebuild(tmp_path):
    seed_index(tmp_path, 12, max_tokens=1)
    instance = module.VaultProvider()
    instance.initialize("session", hermes_home=str(tmp_path))
    try:
        assert instance.prefetch("") == ""
        assert instance.prefetch("nothing matches this") == ""
        first = instance.system_prompt_block()
        rebuilt = instance.system_prompt_block()
        assert_all_entries(first, 12)
        assert_all_entries(rebuilt, 12)
        assert first == rebuilt
    finally:
        instance.shutdown()


def test_index_survives_new_provider_initialization(tmp_path):
    seed_index(tmp_path, 12)
    for _ in range(2):
        instance = module.VaultProvider()
        instance.initialize("restart", hermes_home=str(tmp_path))
        try:
            assert_all_entries(instance.system_prompt_block(), 12)
        finally:
            instance.shutdown()


def test_index_entries_stay_complete_under_one_token_budget(tmp_path):
    index = seed_index(tmp_path, 12, max_tokens=1)
    instance = module.VaultProvider()
    instance.initialize("session", hermes_home=str(tmp_path))
    try:
        block = instance.system_prompt_block()
        assert_all_entries(block, 12)
        assert index.read().over_budget
        assert index.read().warnings
    finally:
        instance.shutdown()


def test_required_index_missing_state_raises(tmp_path):
    index = seed_index(tmp_path, 3)
    instance = module.VaultProvider()
    instance.initialize("session", hermes_home=str(tmp_path), require_memory_index=True)
    assert_all_entries(instance.system_prompt_block(), 3)
    instance.shutdown()
    shutil.rmtree(index.directory)
    restarted = module.VaultProvider()
    restarted.initialize("session", hermes_home=str(tmp_path), require_memory_index=True)
    try:
        with pytest.raises(MemoryIndexError):
            restarted.system_prompt_block()
    finally:
        restarted.shutdown()


@pytest.mark.parametrize("value", [1, 0, "true", "false", None, 1.0, []])
def test_invalid_require_memory_index_is_rejected(tmp_path, value):
    instance = module.VaultProvider()
    with pytest.raises(module.InvalidArgument):
        instance.initialize("session", hermes_home=str(tmp_path), require_memory_index=value)


def test_disabled_index_keeps_legacy_prompt_block(tmp_path):
    instance = module.VaultProvider()
    instance.initialize("session", hermes_home=str(tmp_path))
    try:
        assert instance.system_prompt_block() == module._PROMPT
        assert instance.system_prompt_block() == module._PROMPT
        assert not (vault_home(tmp_path) / ".mnemosyne-memory-index").exists()
    finally:
        instance.shutdown()


def test_trigger_routing_reaches_document_through_existing_tool(tmp_path):
    instance = module.VaultProvider()
    instance.initialize("session", hermes_home=str(tmp_path))
    try:
        call(instance, "birkin_memory_remember", title="Tea order", body="Jasmine tea is the usual drink.")
        MemoryIndex(vault_home(tmp_path)).register("ordering tea", "tea-order")
        block = instance.system_prompt_block()
        assert "ordering tea -> knowledge/tea-order.md" in block
        assert "birkin_memory_get_note" in block
        assert "birkin_memory_search" in block
        result = call(instance, "birkin_memory_get_note", title="knowledge/tea-order.md")
        assert result["success"]
        assert "Jasmine tea" in result["body"]
    finally:
        instance.shutdown()


def test_indexed_prefetch_reads_all_complete_documents_after_character_500(provider, tmp_path):
    index = MemoryIndex(vault_home(tmp_path))
    expected = {}
    for number in range(5):
        relative = f"deploy-{number}.md"
        raw = f"\ufeff# Rule {number}\r\n" + "Preserve this paragraph.\r\n" * 30 + "Last byte"
        (vault_home(tmp_path) / relative).write_bytes(raw.encode())
        index.register("When reviewing deployment", relative)
        expected[relative] = raw

    context = json.loads(provider.prefetch("Planning " * 80 + "deployment"))
    actual = {
        path: "".join(block["text"] for block in context["blocks"] if block["path"] == path)
        for path in expected
    }
    assert actual == expected


def test_indexed_prefetch_never_substitutes_search_and_keeps_the_prompt(provider, tmp_path):
    call(provider, "birkin_memory_remember", title="Tea order", body="Use a silver collimator.")
    index = MemoryIndex(vault_home(tmp_path))
    index.register("ordering tea", "tea-order")
    before = provider.system_prompt_block()

    assert provider.prefetch("collimator") == ""
    assert provider.system_prompt_block() == before

    (vault_home(tmp_path) / "knowledge" / "tea-order.md").unlink()
    with pytest.raises(FileNotFoundError):
        provider.prefetch("ordering tea")


def test_grouped_index_can_be_expanded_through_provider_tool(provider, tmp_path):
    vault = vault_home(tmp_path)
    (vault / "guides").mkdir()
    index = MemoryIndex(vault)
    for number in range(20):
        document = f"guides/procedure-{number:02d}.md"
        (vault / document).write_bytes(b"Complete rule.\n")
        index.register(f"When deploying service {number:02d} with production verification", document)
    top = index.read()
    assert top.mode == "grouped"
    assert top.context in provider.system_prompt_block()
    assert call(provider, "birkin_memory_index")["body"] == top.context
    expanded = call(provider, "birkin_memory_index", topic="dir:guides")
    assert expanded["success"]
    assert expanded["body"] == index.read(topic="dir:guides").context
    assert not call(provider, "birkin_memory_index", topic="../outside")["success"]
    assert not call(provider, "birkin_memory_index", topic=3)["success"]


def test_registered_long_document_path_is_readable_and_advertised(tmp_path):
    home = Path("\\\\?\\" + str(tmp_path)) if os.name == "nt" else tmp_path
    vault = vault_home(home)
    vault.mkdir(parents=True)
    document = "d" * 210 + ".md"
    (vault / document).write_bytes(b"Complete long-path rule.")
    MemoryIndex(vault).register("long path task", document)
    instance = module.VaultProvider()
    instance.initialize("long-path", hermes_home=str(home))
    try:
        assert document in instance.system_prompt_block()
        schemas = {s["name"]: s["parameters"] for s in instance.get_tool_schemas()}
        boundary = schemas["birkin_memory_get_note"]["properties"]["title"]
        assert boundary.get("maxLength", len(document)) >= len(document)
        result = call(instance, "birkin_memory_get_note", title=document)
        assert result["success"] and result["body"] == "Complete long-path rule."
        assert not call(instance, "birkin_memory_remember",
                        title="n" * 201, body="Not a registered path.")["success"]
    finally:
        instance.shutdown()
