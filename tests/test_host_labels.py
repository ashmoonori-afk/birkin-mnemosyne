"""Hermes label filters: schema exposure and real registered-provider behavior.

``birkin_memory_search`` accepts an optional ``labels`` array (or null); the
provider validates every entry with the same core normalization stored labels
use, forwards the AND filter to ``VaultMemory.search`` and keeps
missing/null/empty filters unfiltered.  Malformed filters error without ever
broadening recall, and the scoped handoff + INDEX prefetch bundle stays
complete and unchanged.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from birkin_mnemosyne import HandoffStore, MemoryIndex, StartupReader
from birkin_mnemosyne.memory import VaultMemory

SOURCE = Path(__file__).resolve().parents[1] / "integrations" / "hermes" / "provider.py"
spec = importlib.util.spec_from_file_location("mnemosyne_hermes_labels", SOURCE)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

PROJECT = "mn-070-hermes"
TASK = "handoff"
USER_TEXT = "HERMES_USER_SENTINEL: finish the release."
ASSISTANT_TEXT = (
    "HERMES_ASSISTANT_SENTINEL: preserve this complete response.\n"
    "## Decisions\n- Retain original notes.\n"
    "## Open items\n- Run Windows CI.\n"
    "## Open questions\n- Which gate is open?\n"
    "## Next step\nOpen the PR.\n"
    "## Links\nhttps://example.invalid/42\n"
)
MESSAGES = [
    {"role": "user", "content": USER_TEXT},
    {"role": "assistant", "content": ASSISTANT_TEXT},
]


def vault_path(home):
    return Path(home) / "birkin-mnemosyne" / "vault"


def seed(home, title, body, labels=None):
    VaultMemory({"vault_path": str(vault_path(home))}).write_note(
        title, body, source="test", labels=labels)


@pytest.fixture
def provider(tmp_path):
    instance = module.VaultProvider()
    instance.initialize("test-session", hermes_home=str(tmp_path))
    yield instance
    instance.shutdown()


def call(provider, **arguments):
    return json.loads(provider.handle_tool_call("birkin_memory_search", arguments))


def titles(result):
    assert result["success"]
    return {entry["title"] for entry in result["results"]}


def test_search_schema_exposes_labels_array_of_strings_or_null(provider):
    schemas = {s["name"]: s["parameters"] for s in provider.get_tool_schemas()}
    search = schemas["birkin_memory_search"]
    labels = search["properties"]["labels"]
    assert labels["type"] == ["array", "null"]
    assert labels["items"] == {"type": "string", "minLength": 1}
    assert "labels" not in search["required"]
    assert search["additionalProperties"] is False
    assert {"query", "limit"} <= set(search["properties"])


def test_search_requires_every_requested_label(provider, tmp_path):
    seed(tmp_path, "Alpha recall", "Config guidance: use recall filters.",
         labels=["project:alpha", "person:kim"])
    seed(tmp_path, "Bravo recall", "Config guidance: use recall filters.",
         labels=["project:alpha"])
    seed(tmp_path, "Charm recall", "Config guidance: use recall filters.",
         labels=["person:kim"])
    seed(tmp_path, "Delta recall", "Config guidance: use recall filters.")

    assert titles(call(provider, query="recall filters", labels=["project:alpha"])) == {
        "alpha-recall", "bravo-recall"}
    assert titles(call(provider, query="recall filters",
                       labels=["project:alpha", "person:kim"])) == {"alpha-recall"}


def test_missing_null_and_empty_labels_leave_search_unfiltered(provider, tmp_path):
    seed(tmp_path, "Alpha recall", "Shared recall marker text.",
         labels=["project:alpha"])
    seed(tmp_path, "Bravo recall", "Shared recall marker text.")

    unfiltered = titles(call(provider, query="Shared recall marker"))
    assert unfiltered == {"alpha-recall", "bravo-recall"}
    assert titles(call(provider, query="Shared recall marker", labels=None)) == unfiltered
    assert titles(call(provider, query="Shared recall marker", labels=[])) == unfiltered


def test_label_value_case_stays_distinct_while_namespace_normalizes(provider, tmp_path):
    seed(tmp_path, "Alpha recall", "Case sensitivity recall guidance.",
         labels=["project:Alpha", "zone:Notes"])

    assert titles(call(provider, query="recall guidance", labels=["Project:Alpha"])) == {
        "alpha-recall"}
    assert titles(call(provider, query="recall guidance", labels=["project:alpha"])) == set()


@pytest.mark.parametrize("labels", [
    "project:alpha",
    3,
    [3],
    [{"project": "alpha"}],
    ["nolabel"],
    ["project:"],
    [""],
    [None],
    [True],
])
def test_malformed_label_filters_error_without_broadening(provider, tmp_path, labels):
    seed(tmp_path, "Alpha recall", "Config guidance for malformed filters.",
         labels=["project:alpha"])

    result = call(provider, query="recall", labels=labels)
    assert not result["success"]
    assert str(result["error"]).startswith("labels:")


def test_scoped_handoff_and_index_prefetch_stay_complete_with_label_filter(tmp_path):
    vault = vault_path(tmp_path)
    HandoffStore(vault).enable()
    (vault / "notes").mkdir(parents=True, exist_ok=True)
    (vault / "notes" / "hermes-route.md").write_text(
        "Hermes recall route stays complete.\n", encoding="utf-8")
    MemoryIndex(vault).register("Hermes handoff route", "notes/hermes-route.md")
    instance = module.VaultProvider()
    instance.initialize("session-1", hermes_home=str(tmp_path),
                        agent_workspace=PROJECT, task_key=TASK)
    try:
        _ = instance.on_pre_compress(MESSAGES)
        instance.on_session_end(MESSAGES)
        reader = StartupReader(vault, require_index=True)
        bundle = instance.prefetch("")
        coverage = reader.verify(bundle, [], project_key=PROJECT, task_key=TASK)
        assert coverage.complete
        assert USER_TEXT in bundle
        assert ASSISTANT_TEXT.splitlines()[0] in bundle
        assert "Hermes handoff route -> notes/hermes-route.md" in bundle
        prompt_before = instance.system_prompt_block()
        labeled = call(instance, query="Hermes", labels=["project:alpha"])
        assert labeled["success"] and labeled["results"] == []
        assert instance.prefetch("") == bundle
        assert instance.system_prompt_block() == prompt_before
    finally:
        instance.shutdown()