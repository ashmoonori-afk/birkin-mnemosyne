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
