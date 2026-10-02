"""Host-neutral adapter behavior; actual host discovery is checked separately."""

import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

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
