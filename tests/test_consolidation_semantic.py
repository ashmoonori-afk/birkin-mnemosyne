"""Synthetic contract checks; inference tests require existing prepared assets."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from birkin_mnemosyne import _semantic_questions as provider
from birkin_mnemosyne import semantic as runtime
from birkin_mnemosyne._semantic_questions import Configuration
from birkin_mnemosyne.consolidation import Answer, Consolidation
from birkin_mnemosyne.memory import VaultMemory
from birkin_mnemosyne.review_journal import ReviewError


@pytest.fixture
def prepared_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    """Prepare tiny authored tensors through the real offline model pipeline."""
    import numpy as np
    from safetensors.numpy import save

    from birkin_mnemosyne.static_model import prepare

    monkeypatch.setenv("MNEMOSYNE_MODEL_CACHE", str(tmp_path / "model-cache"))
    snapshot = tmp_path / "model-snapshot"
    snapshot.mkdir()
    verbs = (
        "accepts allows closes consumes decrypts deletes demands encrypts erases "
        + "expires forbids keeps maintains opens permits preserves prohibits "
        + "rejects removes requires retains saves shuts unlocks"
    ).split()
    pieces = ["[PAD]", "[UNK]", "\u2581"] + list("abcdefghijklmnopqrstuvwxyz")
    pieces += [piece for verb in verbs for piece in ("\u2581" + verb, verb)]
    vocabulary = [(piece, -1.0 if piece.lstrip("\u2581") in verbs else -10.0)
                  for piece in pieces]
    _ = (snapshot / "tokenizer.json").write_text(json.dumps({
        "model": {"type": "Unigram", "unk_id": 1, "vocab": vocabulary},
    }), encoding="utf-8")
    embeddings = np.zeros((len(pieces), 2), dtype=np.float32)
    for index, piece in enumerate(pieces[3:], start=3):
        word = piece.lstrip("\u2581")
        if word in verbs:
            embeddings[index] = (0.2 + 0.01 * verbs.index(word), 1.0)
        else:
            embeddings[index] = (1.0, 0.0)
    _ = (snapshot / "model.safetensors").write_bytes(save({"embeddings": embeddings}))
    path = runtime.model_dir()
    prepare(snapshot, path)
    assert runtime.prepared()
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns)
              for p in path.iterdir() if p.is_file()}
    yield path
    after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns)
             for p in path.iterdir() if p.is_file()}
    assert after == before


def seed(vault: Path, bodies: tuple[str, ...]) -> None:
    memory = VaultMemory({"vault_path": str(vault)})
    for index, body in enumerate(bodies):
        _ = memory.write_note(f"Observation {index}", body)


def images(vault: Path) -> dict[str, bytes]:
    return {p.relative_to(vault).as_posix(): p.read_bytes()
            for p in vault.rglob("*.md")}


def test_real_inference_warm_changed_and_reversible(
    tmp_path: Path, prepared_assets: Path,
) -> None:
    assert prepared_assets.is_dir()
    seed(tmp_path, (
        "The amber relay keeps audit records.",
        "The amber relay retains audit records.",
    ))
    before = images(tmp_path)
    assert Consolidation(tmp_path).questions() == ()
    service = Consolidation(tmp_path, semantic=True,
                            thresholds={"cosine": 0.5, "margin": 0.0})
    assert service.semantic_status == "ready", service.semantic_error
    questions = service.questions()
    assert len(questions) == 1
    question, = questions
    assert question.reason == "overlap-or-conflict"
    assert 0.5 <= question.similarity <= 1.0
    assert question.configuration_id == service.configuration_id
    assert service.encoded_chunks > 0
    assert images(tmp_path) == before
    assert service.questions() == questions
    assert service.encoded_chunks == 0

    receipt = service.apply(question, Answer(question.id, "keep-first"))
    _ = service.undo(receipt.transaction_id)
    assert images(tmp_path) == before
    memory = VaultMemory({"vault_path": str(tmp_path)})
    _ = memory.write_note("Observation 1", "The violet relay retains audit records.")
    assert service.questions() == ()
    assert service.encoded_chunks > 0
    assert service.semantic_status == "ready"
    with pytest.raises(ReviewError, match="stale"):
        _ = service.apply(question, Answer(question.id, "keep-first"))
    print(f"READINESS status={service.semantic_status} "
          + f"cold_pair_similarity={question.similarity} "
          + f"configuration_id={service.configuration_id} "
          + f"changed_encoded_chunks={service.encoded_chunks}")


def test_thresholds_snapshot_and_answer_configuration_binding(
    tmp_path: Path, prepared_assets: Path,
) -> None:
    assert prepared_assets.is_dir()
    seed(tmp_path, (
        "The harbor gate closes at sunset.",
        "The harbor gate shuts at sunset.",
    ))
    thresholds = {"cosine": 0.5, "margin": 0.0}
    service = Consolidation(tmp_path, semantic=True, thresholds=thresholds)
    question, = service.questions()
    thresholds["cosine"] = 1.0
    assert service.questions() == (question,)
    for config in (thresholds, {"cosine": 0.5, "margin": 1.0}):
        changed = Consolidation(tmp_path, semantic=True, thresholds=config)
        assert changed.semantic_status == "ready", changed.semantic_error
        assert changed.configuration_id != service.configuration_id
        # No competing supported frame means an unavailable margin, not zero.
        expected_count = 0 if config["cosine"] == 1.0 else 1
        assert len(changed.questions()) == expected_count
        with pytest.raises(ReviewError, match="bind"):
            _ = changed.apply(question, Answer(question.id, "keep-first"))
    with pytest.raises(ReviewError, match="bind"):
        _ = Consolidation(tmp_path).apply(question, Answer(question.id, "keep-first"))


def test_topic_scope_values_and_examples_are_not_semantic_evidence(
    tmp_path: Path, prepared_assets: Path,
) -> None:
    assert prepared_assets.is_dir()
    pairs = (
        ("The north gate closes at sunset.", "The south gate shuts at sunset."),
        ("The harbor gate closes at sunset.", "The harbor gate shuts at sunrise."),
        ("Relay 12 keeps audit records.", "Relay 18 retains audit records."),
        ("The relay keeps records for 12 hours.", "The relay retains records for 18 hours."),
        ("Audit records remain confidential.", "Audit logs remain confidential."),
        ("# The harbor gate closes at sunset.", "# The harbor gate shuts at sunset."),
        ("```\nThe harbor gate closes at sunset.\n```",
         "```\nThe harbor gate shuts at sunset.\n```"),
    )
    for index, pair in enumerate(pairs):
        root = tmp_path / str(index)
        seed(root, pair)
        service = Consolidation(root, semantic=True,
                                thresholds={"cosine": 0.5, "margin": 0.0})
        assert service.questions() == (), pair
        assert service.semantic_status == "ready", service.semantic_error


def test_semantic_frames_do_not_require_lexical_clause_support(
    tmp_path: Path, prepared_assets: Path,
) -> None:
    # Given a supported literal subject longer than the lexical grammar allows.
    assert prepared_assets.is_dir()
    seed(tmp_path, (
        "The amber signal repeater relay keeps audit records.",
        "The amber signal repeater relay retains audit records.",
    ))
    assert Consolidation(tmp_path).questions() == ()
    service = Consolidation(tmp_path, semantic=True,
                            thresholds={"cosine": 0.5, "margin": 0.0})

    # When the complete semantic proposal pipeline discovers the pair.
    questions = service.questions()

    # Then independently parsed semantic frames can produce an actual offer.
    assert len(questions) == 1
    assert questions[0].configuration_id == service.configuration_id


def test_supported_neighbor_margin_rejects_competing_subject(
    tmp_path: Path, prepared_assets: Path,
) -> None:
    # Given supported competing subjects rather than a predicate/topic proxy.
    assert prepared_assets.is_dir()
    seed(tmp_path, (
        "The amber relay keeps audit records.",
        "The amber relay retains audit records.",
        "The violet relay retains audit records.",
    ))
    service = Consolidation(tmp_path, semantic=True,
                            thresholds={"cosine": 0.5, "margin": 0.2})

    # When a competing supported frame is closer than the allowed gap.
    questions = service.questions()

    # Then no pair is offered on the strength of predicate/topic affinity.
    assert questions == ()


def test_unavailable_margin_uses_structured_witness_without_suppressing_matches(
    tmp_path: Path, prepared_assets: Path,
) -> None:
    # Given only genuine matches with identical subject and argument anchors.
    assert prepared_assets.is_dir()
    seed(tmp_path, (
        "The amber relay keeps audit records.",
        "The amber relay retains audit records.",
        "The amber relay preserves audit records.",
    ))
    service = Consolidation(tmp_path, semantic=True,
                            thresholds={"cosine": 0.5, "margin": 0.2})

    # When all supported frames belong to the same subject/attribute.
    questions = service.questions(limit=10000)

    # Then genuine neighbors do not enter the margin denominator or hide pairs.
    assert len(questions) == 3


def test_complete_semantic_discovery_exceeds_shortlists_and_public_caps(
    tmp_path: Path, prepared_assets: Path,
) -> None:
    # Given a crowded neighborhood with every unordered pair genuinely related.
    assert prepared_assets.is_dir()
    seed(tmp_path, tuple(
        f"The amber relay {verb} audit records."
        for verb in ("keeps", "retains") * 17
    ))
    service = Consolidation(tmp_path, semantic=True,
                            thresholds={"cosine": 0.5, "margin": 0.2})

    # When discovery requests complete rather than capped offers.
    questions = service.questions(limit=10000)

    # Then no neighborhood cap suppresses a genuine match.
    assert len(questions) == 34 * 33 // 2
    assert len({(q.first.path, q.second.path) for q in questions}) == 561


@pytest.mark.parametrize("thresholds", [
    None, {}, {"cosine": 0.5}, {"cosine": 0.5, "margin": 0.0, "unused": 1.0},
    {"cosine": float("nan"), "margin": 0.0},
    {"cosine": 0.5, "margin": float("inf")},
    {"cosine": -0.1, "margin": 0.0}, {"cosine": 0.5, "margin": 1.1},
    {"cosine": True, "margin": 0.0},
])
def test_invalid_configuration_is_refused(
    thresholds: dict[str, float] | None,
) -> None:
    with pytest.raises(ValueError, match="thresholds"):
        _ = Configuration.parse(thresholds)


def test_preserved_stat_asset_change_is_refused(
    tmp_path: Path, prepared_assets: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given real prepared assets copied into an owned, mutable test root.
    local_assets = tmp_path / "assets"
    _ = shutil.copytree(prepared_assets, local_assets)
    monkeypatch.setattr(provider, "model_dir", lambda: local_assets)
    vault = tmp_path / "vault"
    seed(vault, ("The amber relay keeps audit records.",
                 "The amber relay retains audit records."))
    service = Consolidation(vault, semantic=True, thresholds={"cosine": 0.72, "margin": 0.02})
    assert service.semantic_status == "ready"
    assert service.questions()
    asset = local_assets / "emb_int8.npy"
    old = asset.stat()
    with asset.open("r+b") as stream:
        _ = stream.seek(-1, os.SEEK_END)
        value = stream.read(1)
        _ = stream.seek(-1, os.SEEK_END)
        _ = stream.write(bytes((value[0] ^ 1,)))
    os.utime(asset, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert (asset.stat().st_size, asset.stat().st_mtime_ns) == (old.st_size, old.st_mtime_ns)

    # When discovery verifies the prepared runtime after a same-stat edit.
    questions = service.questions()

    # Then stale model content cannot retain readiness or produce offers.
    assert questions == ()
    assert service.semantic_status == "unavailable"


def test_missing_assets_refuse_instead_of_offering_lexical_pairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MNEMOSYNE_MODEL_CACHE", str(tmp_path / "absent-cache"))
    seed(tmp_path, ("The amber relay keeps records.",) * 2)
    assert len(Consolidation(tmp_path).questions()) == 1
    service = Consolidation(tmp_path, semantic=True,
                            thresholds={"cosine": 0.5, "margin": 0.0})
    assert service.semantic_status == "unavailable"
    assert service.semantic_error
    assert service.questions() == ()
    assert service.encoded_chunks == 0
    assert not (tmp_path / "absent-cache").exists()
    with pytest.raises(ValueError, match="semantic=True"):
        _ = Consolidation(tmp_path, thresholds={"cosine": 0.5, "margin": 0.0})


def test_changed_local_asset_refuses_discovery_and_apply(
    tmp_path: Path, prepared_assets: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tmp_path / "owned-cache"
    model = cache / prepared_assets.name
    model.mkdir(parents=True)
    for asset in prepared_assets.iterdir():
        if asset.is_file():
            if asset.name == "meta.json":
                _ = (model / asset.name).write_bytes(asset.read_bytes())
            else:
                (model / asset.name).symlink_to(asset)
    monkeypatch.setenv("MNEMOSYNE_MODEL_CACHE", str(cache))
    vault = tmp_path / "vault"
    seed(vault, ("The amber relay keeps audit records.",
                 "The amber relay retains audit records."))
    service = Consolidation(vault, semantic=True,
                            thresholds={"cosine": 0.5, "margin": 0.0})
    question, = service.questions()
    _ = (model / "meta.json").write_bytes(b"{}")
    with pytest.raises(ReviewError, match="unavailable"):
        _ = service.apply(question, Answer(question.id, "keep-first"))
    assert service.questions() == ()
    assert service.semantic_status == "unavailable"
    assert "assets changed" in service.semantic_error
    broken = Consolidation(vault, semantic=True,
                           thresholds={"cosine": 0.5, "margin": 0.0})
    assert broken.semantic_status == "unavailable"
    assert broken.questions() == ()


def test_lexical_zero_dependency_and_missing_optional_runtime(tmp_path: Path) -> None:
    """Use a fresh import boundary; no encoder or ready flag is mocked."""
    script = """
import importlib.abc
import sys
from pathlib import Path
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"numpy", "safetensors", "huggingface_hub"}:
            raise ModuleNotFoundError("optional dependency intentionally absent")
sys.meta_path.insert(0, BlockOptional())
from birkin_mnemosyne import Consolidation, VaultMemory
root = Path(sys.argv[1])
memory = VaultMemory({"vault_path": str(root)})
memory.write_note("First", "The amber relay keeps audit records.")
memory.write_note("Second", "The amber relay keeps audit records.")
lexical = Consolidation(root)
assert len(lexical.questions()) == 1
assert lexical.semantic_status == "lexical"
assert not {"numpy", "safetensors", "huggingface_hub"} & sys.modules.keys()
optional = Consolidation(root, semantic=True, thresholds={"cosine": 0.5, "margin": 0})
assert optional.semantic_status == "unavailable"
assert optional.questions() == ()
assert optional.semantic_error
print("ZERO_DEPENDENCY lexical=1 optional=unavailable")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], check=True,
        capture_output=True, text=True,
        env={**os.environ, "MNEMOSYNE_SEMANTIC": "1"},
    )
    assert result.stdout.strip() == "ZERO_DEPENDENCY lexical=1 optional=unavailable"
