"""Round-4 T1 protocol: immutable input guard, explicit modes, fresh probes.

Core-lane safe: standard library only. Scoring dependencies (tiktoken, numpy)
are never imported, and no frozen question, gold, fixture, query or inline
corpus row is read or interpreted. Only opaque byte hashing and JSON parsing
of the guard's own outputs happen here.

Every mutation test works on a disposable copy of the frozen tree under
``tmp_path``; the repository files are never written.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.machinery
import inspect
import json
import os
import shutil
import statistics
import subprocess
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.round4 import run as protocol

FROZEN_DIRS = ("benchmarks/round3", "benchmarks/retrieval")


def disposable_tree(tmp_path: Path) -> Path:
    """A byte-identical copy of the frozen tree; the originals are only read.

    ``.git`` comes along because the guard pins the declared Git blob hashes
    through ``git hash-object``; without it a checkout's EOL attributes would
    be unknown and the contract could not be checked at all. Only the copy is
    ever written.
    """
    for relative in FROZEN_DIRS:
        shutil.copytree(ROOT / relative, tmp_path / relative)
    # Copy the gitdir *contents*: in a linked worktree ``.git`` is a pointer
    # file, so page the guard's ``git -C <root>`` calls at the resolved dir.
    gitdir = ROOT / ".git"
    if gitdir.is_file():
        gitdir = Path(gitdir.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip())
    shutil.copytree(gitdir, tmp_path / "repo-git")
    for name in (".gitattributes", ".gitignore"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    return tmp_path


def manifest_dict() -> protocol.FrozenManifest:
    return protocol.load_manifest(protocol.DEFAULT_MANIFEST)


@pytest.mark.parametrize("authors", [None, False, ["invalid"], {"model": {"startup": 3}}])
def test_manifest_rejects_invalid_author_metadata(
    tmp_path: Path, authors: protocol.JsonValue,
) -> None:
    document: dict[str, protocol.JsonValue] = {
        "required_files": {"opaque.bin": {}},
        "required_authors": authors,
        "author_identity": {},
        "hash_contract": {"normalization": "text=b.replace(CRLF, LF)"},
        "slices_validated_at": "locked-evaluation",
    }
    path = tmp_path / "manifest.json"
    _ = path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(protocol.FrozenInputError):
        protocol.load_manifest(path)


def test_manifest_accepts_author_metadata_without_dropping_fields(tmp_path: Path) -> None:
    document: dict[str, protocol.JsonValue] = {
        "required_files": {"opaque.bin": {"role": "opaque"}},
        "required_authors": {"model": {"startup": ["opaque.bin"]}},
        "author_identity": {"opaque.bin": "model"},
        "hash_contract": {"normalization": "text=b.replace(CRLF, LF)"},
        "slices_validated_at": "locked-evaluation",
        "provenance": {"opaque": True},
        "bootstrap_raw_sha256": {"opaque.bin": "0" * 64},
    }
    path = tmp_path / "manifest.json"
    _ = path.write_text(json.dumps(document), encoding="utf-8")
    assert protocol.load_manifest(path) == document


@pytest.mark.parametrize("bootstrap", [None, False, [], {"opaque.bin": 3}])
def test_manifest_rejects_invalid_bootstrap_metadata(
    tmp_path: Path, bootstrap: protocol.JsonValue,
) -> None:
    document: dict[str, protocol.JsonValue] = {
        "required_files": {"opaque.bin": {"role": "opaque"}},
        "required_authors": {"model": {"startup": ["opaque.bin"]}},
        "author_identity": {"opaque.bin": "model"},
        "hash_contract": {"normalization": "text=b.replace(CRLF, LF)"},
        "slices_validated_at": "locked-evaluation",
        "bootstrap_raw_sha256": bootstrap,
    }
    path = tmp_path / "manifest.json"
    _ = path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(protocol.FrozenInputError):
        protocol.load_manifest(path)


def same_length_mutation(data: bytes) -> bytes:
    """Flip one byte of opaque JSON bytes without changing the file length."""
    mutated = data[:-2] + (b"0" if data[-2:-1] != b"0" else b"1") + data[-1:]
    assert len(mutated) == len(data) and mutated != data
    return mutated


def cli(*arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(ROOT / "benchmarks" / "round4" / "run.py"),
                           *arguments], cwd=str(cwd or ROOT), capture_output=True, text=True,
                          check=False)


@pytest.fixture
def blocked_optional_deps(monkeypatch):
    """Make an accidental tiktoken/numpy import fail loudly instead of passing.

    The assertions below compare ``sys.modules`` with the snapshot taken here,
    not with the empty set: another test module may already have imported an
    unrelated module, and this test is about what *the guard* imports.
    """
    snapshot = {name for name in sys.modules
                if name.split(".", 1)[0] not in {"tiktoken", "numpy"}}
    loader = importlib.machinery.ModuleSpec
    for name in ("tiktoken", "numpy"):
        for existing in [n for n in sys.modules if n == name or n.startswith(name + ".")]:
            monkeypatch.delitem(sys.modules, existing, raising=False)
        def _raise(*_args: object, _name: str = name, **_kwargs: object) -> None:
            raise AssertionError(f"{_name} must not be imported by the round4 protocol guard")

        blocker = types.ModuleType(name, doc="blocked optional dependency")
        blocker.__spec__ = loader(name, loader=None)
        blocker.__dict__["get_encoding"] = _raise  # a real import would call this
        monkeypatch.setitem(sys.modules, name, blocker)
    return {"snapshot": snapshot, "numpy": sys.modules["numpy"], "tiktoken": sys.modules["tiktoken"]}


def test_check_inputs_verifies_every_frozen_file_without_scoring(blocked_optional_deps):
    report = protocol.check_inputs()
    manifest = manifest_dict()
    assert report["integrity_only"] is True
    assert report["scoring_executed"] is False
    assert report["product_performance_claimed"] is False
    assert report["frozen_row_content_interpreted"] is False
    assert report["hashed_files"] == len(manifest["required_files"])
    assert {row["path"] for row in report["files"]} == set(manifest["required_files"])
    for row in report["files"]:
        assert row["matched"] in {"raw", "git-blob"}
    assert "benchmarks.round3.run" in report["scorer_modules"]
    # The stand-ins stay injected: nothing may have replaced or imported them.
    assert sys.modules["numpy"] is blocked_optional_deps["numpy"]
    assert sys.modules["tiktoken"] is blocked_optional_deps["tiktoken"]
    imported_scorers = {name for name in set(sys.modules) - blocked_optional_deps["snapshot"]
                        if name.startswith("benchmarks.")}
    assert not imported_scorers, \
        f"the guard must not import the immutable scorers: {sorted(imported_scorers)}"


def test_missing_required_frozen_file_is_rejected(tmp_path):
    root = disposable_tree(tmp_path)
    (root / "benchmarks/round3/frozen_sol.json").unlink()
    manifest = manifest_dict()
    with pytest.raises(protocol.FrozenInputError, match="is missing"):
        protocol.check_frozen_files(manifest, root=root)


def test_same_length_mutated_frozen_bytes_are_rejected(tmp_path):
    root = disposable_tree(tmp_path)
    target = root / "benchmarks/round3/frozen_sol.json"
    original = target.read_bytes()
    mutated = same_length_mutation(original)
    assert mutated[-2:-1] != original[-2:-1]
    target.write_bytes(mutated)
    with pytest.raises(protocol.FrozenInputError, match="drifted"):
        protocol.check_frozen_files(manifest_dict(), root=root)


def test_same_length_mutation_with_preserved_mtime_is_rejected(tmp_path):
    root = disposable_tree(tmp_path)
    target = root / "benchmarks/round3/frozen_sol_startup.json"
    original = target.read_bytes()
    stat = target.stat()
    target.write_bytes(same_length_mutation(original))
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert target.stat().st_mtime_ns == stat.st_mtime_ns
    with pytest.raises(protocol.FrozenInputError, match="drifted"):
        protocol.check_frozen_files(manifest_dict(), root=root)


def test_missing_required_scorer_file_is_rejected(tmp_path):
    root = disposable_tree(tmp_path)
    (root / "benchmarks/round3/answerer.py").unlink()
    with pytest.raises(protocol.FrozenInputError, match="is missing"):
        protocol.check_frozen_files(manifest_dict(), root=root)


def test_eol_normalization_accepts_crlf_and_lf_but_not_changed_bytes():
    lf = b"alpha\nbeta\n"
    crlf = b"alpha\r\nbeta\r\n"
    bom_lf = "\ufeffalpha\n".encode("utf-8")
    assert protocol.blob_sha256(lf) == protocol.blob_sha256(crlf)
    assert protocol.blob_sha256(bom_lf) != protocol.blob_sha256(b"alpha\n")
    assert protocol.blob_sha256(b"alpha\rbeta\r") != protocol.blob_sha256(lf)
    assert protocol.blob_sha256(lf) != protocol.blob_sha256(b"alpha\nbeta!\n")
    assert protocol.raw_sha256(lf) != protocol.raw_sha256(crlf)


def test_declared_git_blob_hash_rejects_arbitrary_normalized_drift(tmp_path):
    root = disposable_tree(tmp_path)
    manifest = manifest_dict()
    relative = "benchmarks/round3/frozen_sol.json"
    target = root / relative
    data = target.read_bytes()
    # The untouched copy matches its declared raw bytes.
    assert protocol.verify_file(
        relative, manifest["required_files"][relative], root=root)["matched"] == "raw"
    # An EOL-only rewrite is a different working copy of the same tracked file,
    # so it verifies through the declared raw hash it reproduces.
    crlf = data.replace(b"\n", b"\r\n")
    target.write_bytes(crlf)
    row = protocol.verify_file(relative, manifest["required_files"][relative], root=root)
    assert row["matched"] == "git-blob"
    assert row["git_blob_sha256"] == manifest["required_files"][relative]["raw_sha256"]
    # Same-length content drift is refused even though the normalization is stable.
    target.write_bytes(same_length_mutation(data))
    with pytest.raises(protocol.FrozenInputError, match="drifted"):
        protocol.verify_file(relative, manifest["required_files"][relative], root=root)


def test_matching_raw_bytes_do_not_accept_a_false_git_declaration():
    manifest = manifest_dict()
    relative = "benchmarks/round3/run.py"
    meta = dict(manifest["required_files"][relative])
    meta["git_blob_sha256"] = "0" * 64
    with pytest.raises(protocol.FrozenInputError, match="declaration is wrong"):
        protocol.verify_file(relative, meta)


def test_missing_tracked_blob_is_an_integrity_failure(monkeypatch):
    relative = "benchmarks/round3/run.py"
    meta = manifest_dict()["required_files"][relative]
    monkeypatch.setattr(protocol, "_pinned_blob_bytes", lambda _relative: None)
    with pytest.raises(protocol.FrozenInputError, match="could not be verified"):
        protocol.verify_file(relative, meta)


def test_git_unavailable_is_an_integrity_failure(monkeypatch):
    relative = "benchmarks/round3/run.py"
    meta = manifest_dict()["required_files"][relative]

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", unavailable)
    with pytest.raises(protocol.FrozenInputError, match="cannot read"):
        protocol.verify_file(relative, meta)


def test_required_author_slices_are_validated_on_a_disposable_copy(tmp_path):
    root = disposable_tree(tmp_path)
    checked = protocol.validate_required_authors(root)
    manifest = manifest_dict()
    expected = {(author, slice_name)
                for author, slices in manifest["required_authors"].items()
                for slice_name in slices}
    assert {(row["author"], row["slice"]) for row in checked} == expected

    path = root / "benchmarks/round3/frozen_sol.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["consolidation"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(protocol.FrozenInputError, match="missing required slice"):
        protocol.validate_required_authors(root)


def test_missing_required_author_slice_is_rejected_when_file_is_absent(tmp_path):
    root = disposable_tree(tmp_path)
    (root / "benchmarks/round3/frozen_claude_startup.json").unlink()
    with pytest.raises((protocol.FrozenInputError, FileNotFoundError)):
        protocol.validate_required_authors(root)


def test_misattributed_author_identity_is_rejected(tmp_path):
    root = disposable_tree(tmp_path)
    path = root / "benchmarks/round3/frozen_claude_consolidation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["author"] = "some-other-model"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(protocol.FrozenInputError, match="author"):
        protocol.validate_required_authors(root)


def compact_available() -> bool:
    """The same predicate the protocol uses to decide the compact surface exists."""
    from birkin_mnemosyne import StartupReader

    return "compact" in inspect.signature(StartupReader.read).parameters


def semantic_available() -> bool:
    """The same predicate run.py uses to decide the semantic surface exists."""
    from birkin_mnemosyne import Consolidation

    return {"semantic", "thresholds"} <= set(inspect.signature(Consolidation.__init__).parameters)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_configured_modes_refuse_pending_product_surfaces_without_fallback(tmp_path, monkeypatch):
    import birkin_mnemosyne
    from birkin_mnemosyne import Consolidation, StartupReader

    legacy = protocol.configured_consolidation(tmp_path, protocol.LEGACY_DETECTION_MODE)
    assert isinstance(legacy, Consolidation)
    if not semantic_available():
        with pytest.raises(protocol.FrozenInputError, match="not available on this base"):
            protocol.configured_consolidation(tmp_path, protocol.SEMANTIC_DETECTION_MODE)
    else:
        class LegacyConsolidation(Consolidation):
            def __init__(self, root):
                super().__init__(root)

        with monkeypatch.context() as patch:
            patch.setattr(birkin_mnemosyne, "Consolidation", LegacyConsolidation)
            with pytest.raises(protocol.FrozenInputError, match="not available on this base"):
                protocol.configured_consolidation(tmp_path, protocol.SEMANTIC_DETECTION_MODE)
        monkeypatch.setattr(protocol, "THRESHOLDS_PATH", tmp_path / "missing-thresholds.json")
        with pytest.raises(protocol.FrozenInputError, match="thresholds are missing"):
            protocol.configured_consolidation(tmp_path, protocol.SEMANTIC_DETECTION_MODE)

        from birkin_mnemosyne import VaultMemory, semantic

        thresholds = {"cosine": 0.9, "margin": 0.05}
        locked = tmp_path / "locked-thresholds.json"
        locked.write_text(json.dumps({"locked": True, "thresholds": thresholds}),
                          encoding="utf-8")
        monkeypatch.setattr(protocol, "THRESHOLDS_PATH", locked)
        vault = tmp_path / "semantic-vault"
        memory = VaultMemory({"vault_path": str(vault)})
        memory.write_note("First policy", "Review every release before publishing.",
                          source="chat:first")
        memory.write_note("Second policy", "Review every release before publishing.",
                          source="chat:second")
        built = protocol.configured_consolidation(vault, protocol.SEMANTIC_DETECTION_MODE)
        assert isinstance(built, Consolidation)
        direct = Consolidation(vault, semantic=True, thresholds=thresholds)
        assert built.configuration_id != ""
        assert built.configuration_id == direct.configuration_id
        assert built.semantic_status != "lexical"
        if semantic.prepared():
            questions = built.questions()
            assert built.semantic_status == "ready"
            assert len(questions) >= 1
        else:
            with pytest.raises(protocol.FrozenInputError,
                               match="semantic question pipeline is not ready"):
                built.questions()
    if not compact_available():
        with pytest.raises(protocol.FrozenInputError, match="not available on this base"):
            protocol.configured_startup(tmp_path, protocol.COMPACT_STARTUP_MODE)
    else:
        root = startup_fixture(tmp_path / "startup")
        paths = ["MODE.md", "profile/soul.md", "registry.json"]
        reader = protocol.configured_startup(root, protocol.COMPACT_STARTUP_MODE)
        real = StartupReader(root)
        context = reader.read(paths).context
        assert context == real.read(paths, compact=True).context
        assert context != real.read(paths).context
    with pytest.raises(protocol.FrozenInputError, match="unknown startup mode"):
        protocol.configured_startup(tmp_path, "invented-mode")

    pending = protocol.PENDING_PRODUCT_SURFACES
    assert pending["compact-startup"]["delivered_by"] == "round4 T6"
    assert pending["compact-startup"]["surface"].endswith("read(paths, compact=True)")
    assert pending["semantic-consolidation"]["surface"].endswith(
        "Consolidation(root, semantic=True, thresholds=locked_config)")


def test_declared_modes_report_pending_surfaces_and_legacy_evidence():
    modes = protocol.declared_modes()
    if not compact_available():
        assert modes["startup"][protocol.COMPACT_STARTUP_MODE]["available"] is False
        assert modes["startup"][protocol.COMPACT_STARTUP_MODE]["pending"]["delivered_by"] == "round4 T6"
    else:
        assert modes["startup"][protocol.COMPACT_STARTUP_MODE]["available"] is True
    semantic = modes["detection"][protocol.SEMANTIC_DETECTION_MODE]
    assert semantic["available"] is semantic_available()
    if not semantic_available():
        assert modes["detection"][protocol.SEMANTIC_DETECTION_MODE]["available"] is False
    else:
        assert modes["detection"][protocol.SEMANTIC_DETECTION_MODE]["available"] is True
    assert modes["detection"][protocol.LEGACY_DETECTION_MODE]["available"] is True
    assert "future" in modes["scope"]


def test_score_bindings_name_only_engine_constructors():
    bindings = protocol.score_bindings(protocol.LEGACY_STARTUP_MODE, protocol.LEGACY_DETECTION_MODE)
    assert set(bindings) == {"StartupReader", "Consolidation"}
    for forbidden in ("answer", "startup_answer", "documents", "kibitzer",
                      "rank_metrics", "gold_rank", "percentile"):
        assert forbidden not in bindings


def test_legacy_startup_factory_returns_a_reader_not_a_callback(tmp_path):
    reader = protocol.configured_startup(tmp_path, protocol.LEGACY_STARTUP_MODE)
    assert callable(reader.read)


def test_selected_compact_mode_reaches_the_public_reader(monkeypatch, tmp_path):
    import birkin_mnemosyne

    calls = []

    class Reader:
        def __init__(self, root):
            calls.append(("init", root))

        def read(self, paths, *, compact=False):
            calls.append(("read", paths, compact))
            return "actual-public-result"

    monkeypatch.setattr(birkin_mnemosyne, "StartupReader", Reader)
    bindings = protocol.score_bindings(protocol.COMPACT_STARTUP_MODE,
                                       protocol.LEGACY_DETECTION_MODE)
    assert bindings["StartupReader"](tmp_path).read(["MODE.md"]) == "actual-public-result"
    assert calls == [("init", tmp_path), ("read", ["MODE.md"], True)]
    assert protocol.declared_modes()["startup"][protocol.COMPACT_STARTUP_MODE]["available"]


def test_compact_reader_refuses_format_the_base_cannot_honor(monkeypatch, tmp_path):
    import birkin_mnemosyne

    calls = []

    class Reader:
        def __init__(self, root):
            self.root = root

        def read(self, paths, *, compact=False):
            calls.append((paths, compact))
            return "actual-public-result"

    monkeypatch.setattr(birkin_mnemosyne, "StartupReader", Reader)
    reader = protocol.configured_startup(tmp_path, protocol.COMPACT_STARTUP_MODE)
    with pytest.raises(protocol.FrozenInputError, match="'v3'"):
        reader.read(["MODE.md"], compact_format="v3")
    assert calls == []
    assert reader.read(["MODE.md"], compact_format="v2") == "actual-public-result"
    assert calls == [(["MODE.md"], True)]


@pytest.mark.parametrize("status", ["ready", "unavailable"])
def test_selected_semantic_mode_forwards_config_and_requires_pipeline_readiness(
        monkeypatch, tmp_path, status):
    import birkin_mnemosyne

    calls = []
    thresholds = {"min_cosine": 0.95, "min_margin": 0.05}
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps({"locked": True, "thresholds": thresholds}),
                    encoding="utf-8")

    class Service:
        def __init__(self, root, *, semantic=False, thresholds=None):
            calls.append((root, semantic, thresholds))
            self.semantic_status = "starting"

        def questions(self, limit=20):
            calls.append(("questions", limit))
            self.semantic_status = status
            return ("public-question",)

    monkeypatch.setattr(birkin_mnemosyne, "Consolidation", Service)
    monkeypatch.setattr(protocol, "THRESHOLDS_PATH", path)
    factory = protocol.score_bindings(protocol.LEGACY_STARTUP_MODE,
                                      protocol.SEMANTIC_DETECTION_MODE)["Consolidation"]
    service = factory(tmp_path)
    if status == "ready":
        assert service.questions(limit=100) == ("public-question",)
    else:
        with pytest.raises(protocol.FrozenInputError, match="not ready"):
            service.questions(limit=100)
    assert calls == [(tmp_path, True, thresholds), ("questions", 100)]
    assert protocol.declared_modes()["detection"][protocol.SEMANTIC_DETECTION_MODE]["available"]


@pytest.mark.parametrize("config", [None, False, [], "invalid"])
def test_semantic_factory_rejects_non_object_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: protocol.JsonValue,
) -> None:
    import birkin_mnemosyne

    class Service:
        def __init__(
            self, root: Path, *, semantic: bool = False,
            thresholds: dict[str, protocol.JsonValue] | None = None,
        ) -> None:
            _ = root, semantic, thresholds
            raise AssertionError("invalid config reached service construction")

    path = tmp_path / "thresholds.json"
    _ = path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(birkin_mnemosyne, "Consolidation", Service)
    monkeypatch.setattr(protocol, "THRESHOLDS_PATH", path)
    assert protocol.declared_modes()["detection"]["semantic"]["available"] is True
    with pytest.raises(protocol.FrozenInputError):
        protocol.configured_consolidation(tmp_path, protocol.SEMANTIC_DETECTION_MODE)


def test_cli_check_inputs_only_succeeds():
    result = cli("--check-inputs-only", "--manifest", "benchmarks/round4/frozen-manifest.json")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["integrity_only"] is True
    assert report["hashed_files"] == len(manifest_dict()["required_files"])


def test_cli_rejects_mutated_disposable_manifest_input(tmp_path):
    root = disposable_tree(tmp_path)
    manifest_path = tmp_path / "frozen-manifest.json"
    manifest_path.write_bytes(protocol.DEFAULT_MANIFEST.read_bytes())
    target = root / "benchmarks/round3/frozen_claude_identity.json"
    target.write_bytes(same_length_mutation(target.read_bytes()))
    result = cli("--check-inputs-only", "--manifest", str(manifest_path),
                 "--root", str(root))
    assert result.returncode != 0, result.stdout
    assert "drifted" in result.stderr


def test_cli_rejects_missing_disposable_manifest_input(tmp_path):
    root = disposable_tree(tmp_path)
    manifest_path = tmp_path / "frozen-manifest.json"
    manifest_path.write_bytes(protocol.DEFAULT_MANIFEST.read_bytes())
    (root / "benchmarks/retrieval/bench_retrieval.py").unlink()
    result = cli("--check-inputs-only", "--manifest", str(manifest_path),
                 "--root", str(root))
    assert result.returncode != 0, result.stdout
    assert "is missing" in result.stderr


def test_manifest_declares_eol_guard_and_all_required_inputs():
    manifest = manifest_dict()
    assert manifest["hash_contract"]["normalization"] == \
        "text=b.replace(CRLF, LF)"
    bootstrap = manifest.get("bootstrap_raw_sha256")
    assert bootstrap is not None
    assert bootstrap["benchmarks/retrieval/_probe.py"] == \
        "c446898b8f15c5d69216d6affbafe3609d1ce1e06838dcefa800e442f7c9da72"
    assert manifest["required_files"]["benchmarks/retrieval/_probe.py"]["raw_sha256"] == \
        "cd209e67fc107397edbaa4e492d51cdd64ee4ef99e3db06626b1475e4cb46304"
    for relative in ("benchmarks/round3/run.py", "benchmarks/round3/_probe.py",
                     "benchmarks/round3/answerer.py", "benchmarks/round3/startup_answerer.py",
                     "benchmarks/retrieval/bench_retrieval.py"):
        assert relative in manifest["required_files"]
    assert manifest["slices_validated_at"].startswith("locked-evaluation")


def test_frozen_input_error_reaches_the_cli_as_nonzero(tmp_path):
    manifest_path = tmp_path / "broken-manifest.json"
    manifest_path.write_text("{not json}", encoding="utf-8")
    result = cli("--check-inputs-only", "--manifest", str(manifest_path))
    assert result.returncode == 1
    assert json.loads(result.stderr)["status"] == "FAIL"


def test_manifest_path_escape_is_rejected(tmp_path):
    manifest_path = tmp_path / "escaping-manifest.json"
    payload = manifest_dict()
    payload["required_files"] = {"../outside.txt": {"raw_sha256": "0" * 64}}
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(protocol.FrozenInputError, match="escapes the repository"):
        protocol.check_inputs(manifest_path)


# --------------------------------------------------------------------------
# Fresh probes. These run real subprocesses on a synthetic local tree; they
# never touch frozen questions, gold answers or the retrieval corpus.
# --------------------------------------------------------------------------

def probe_script() -> Path:
    return ROOT / "benchmarks" / "round4" / "_startup_probe.py"


def startup_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "startup-root"
    (root / "profile").mkdir(parents=True)
    (root / "MODE.md").write_text(
        "# Mode\nMUST READ: profile/soul.md\nMUST READ: registry.json\nRule: guard\n",
        encoding="utf-8")
    (root / "profile" / "soul.md").write_text("# Soul\nVoice: direct\n", encoding="utf-8")
    (root / "registry.json").write_text('{"pending": ["capture receipt"]}\n', encoding="utf-8")
    return root


def run_probe(mode: str, root: Path, paths: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(probe_script()), mode, str(root), *paths],
                          capture_output=True, text=True, cwd=str(cwd or ROOT), check=False)


@pytest.mark.parametrize("probe", [protocol.legacy_probe, protocol.round4_probe])
def test_probe_wrapper_preserves_real_measurements(
    tmp_path: Path,
    probe: Callable[[Path, list[str], str], protocol.LegacyProbeResult | protocol.Round4ProbeResult],
) -> None:
    root = startup_fixture(tmp_path)
    result = probe(root, ["MODE.md", "profile/soul.md", "registry.json"], "full")
    assert result["mode"] == "full"
    assert result["legacy"] is (probe is protocol.legacy_probe)
    assert result["load_read_ms"] > 0
    assert result["peak_rss_bytes"] > 0
    assert result["context_characters"] > 0


@pytest.mark.parametrize(("probe", "field", "value"), [
    *[(probe, field, value)
      for probe in (protocol.legacy_probe, protocol.round4_probe)
      for field, value in (
          ("load_read_ms", True), ("load_read_ms", None),
          ("peak_rss_bytes", False), ("context_characters", "1"),
      )],
    (protocol.round4_probe, "mode", "compact"),
])
def test_probe_wrapper_rejects_invalid_measurement_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: protocol.JsonValue,
    probe: Callable[[Path, list[str], str], protocol.LegacyProbeResult | protocol.Round4ProbeResult],
) -> None:
    payload: dict[str, protocol.JsonValue] = {
        "load_read_ms": 1.0, "peak_rss_bytes": 1, "context_characters": 1,
        "tokenizer_loaded": False, "mode": "full", "probe": "synthetic",
        "root": str(tmp_path), "paths": ["MODE.md"], "context_sha256": "0" * 64,
        "product_imported": False, "optional_imports": [],
    }
    payload[field] = value

    def returned_metadata(
        command: list[str], *, capture_output: bool, text: bool, check: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert capture_output and text and check
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", returned_metadata)
    with pytest.raises(protocol.FrozenInputError):
        probe(tmp_path, ["MODE.md"], "full")


def test_probe_file_does_not_import_the_product_before_its_mode(tmp_path):
    source = probe_script().read_text(encoding="utf-8")
    module = ast.parse(source)
    compact = next(node for node in module.body
                   if isinstance(node, ast.FunctionDef) and node.name == "compact_context")
    imports = [node for node in ast.walk(compact)
               if isinstance(node, ast.ImportFrom)
               and (node.module or "").startswith("birkin_mnemosyne")]
    assert [(node.module, [alias.name for alias in node.names]) for node in imports] == [
        ("birkin_mnemosyne.startup", ["StartupReader"])]
    assert not any(isinstance(node, ast.ImportFrom)
                   and (node.module or "").startswith("birkin_mnemosyne")
                   for node in module.body)

    root = startup_fixture(tmp_path)
    paths = ["MODE.md", "profile/soul.md", "registry.json"]
    full = run_probe("full", root, paths)
    assert full.returncode == 0, full.stderr
    payload = json.loads(full.stdout.splitlines()[-1])
    assert payload["mode"] == "full"
    assert payload["product_imported"] is False
    assert payload["optional_imports"] == []
    assert payload["load_read_ms"] > 0
    assert payload["context_sha256"] == hashlib.sha256(
        payload_context(payload, root, paths).encode("utf-8")).hexdigest()


def payload_context(payload: dict[str, Any], root: Path, paths: list[str]) -> str:
    """Rebuild the legacy full context the probe declares it measured."""
    return json.dumps({"files": [{"path": path, "text": (root / path).read_bytes().decode("utf-8")}
                                 for path in paths]}, ensure_ascii=False)


def test_probe_compact_refuses_absent_product_surface_without_relabelling(tmp_path):
    root = startup_fixture(tmp_path)
    paths = ["MODE.md", "profile/soul.md", "registry.json"]
    result = run_probe("compact", root, paths)
    if not compact_available():
        assert result.returncode != 0
        assert "read(paths, compact=True)" in result.stderr
        assert "refusing to relabel" in result.stderr
        return
    from birkin_mnemosyne import StartupReader

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.splitlines()[-1])
    assert payload["mode"] == "compact"
    assert payload["product_imported"] is True
    real = StartupReader(root)
    assert payload["context_sha256"] == sha256_text(real.read(paths, compact=True).context)
    assert payload["context_sha256"] != sha256_text(real.read(paths).context)


def test_probe_reports_alternating_paired_observations_with_a_median(tmp_path):
    root = startup_fixture(tmp_path)
    paths = ["MODE.md", "profile/soul.md", "registry.json"]
    orders: list[list[str]] = []
    compact_failures: list[int] = []
    full_values: list[float] = []
    compact_values: list[float] = []
    for index in range(4):
        order = ("full", "compact") if index % 2 == 0 else ("compact", "full")
        orders.append(list(order))
        for mode in order:
            result = run_probe(mode, root, paths)
            if mode == "compact":
                compact_failures.append(result.returncode)
                if result.returncode == 0:
                    compact_values.append(
                        json.loads(result.stdout.splitlines()[-1])["load_read_ms"])
            elif result.returncode == 0:
                full_values.append(json.loads(result.stdout.splitlines()[-1])["load_read_ms"])

    assert orders == [["full", "compact"], ["compact", "full"],
                      ["full", "compact"], ["compact", "full"]]
    if not compact_available():
        assert set(compact_failures) == {2}, "compact must fail explicitly, never silently succeed"
    else:
        assert set(compact_failures) == {0}
        assert len(compact_values) == 4 and statistics.median(compact_values) > 0
    assert len(full_values) == 4 and statistics.median(full_values) > 0


def test_synthetic_complete_read_fixture_reconstructs_from_probe_full(tmp_path):
    """The exact source closure the compact gate must re-materialize, proven on synthetic bytes."""
    root = startup_fixture(tmp_path)
    paths = ["MODE.md", "profile/soul.md", "registry.json"]
    result = run_probe("full", root, paths)
    payload = json.loads(result.stdout.splitlines()[-1])
    decoded = json.loads(payload_context(payload, root, paths))
    assert [record["path"] for record in decoded["files"]] == paths
    assert decoded["files"][0]["text"].encode("utf-8") == (root / "MODE.md").read_bytes()


@pytest.mark.parametrize("raw", [
    b"\xef\xbb\xbf# Mode\r\nApproval: before release\r\n",
    b"# Mode\nFinal line without newline",
    b"",
])
def test_full_probe_preserves_raw_source_bytes(tmp_path, raw):
    (tmp_path / "MODE.md").write_bytes(raw)
    result = run_probe("full", tmp_path, ["MODE.md"])
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    expected = json.dumps({"files": [{"path": "MODE.md", "text": raw.decode("utf-8")}]},
                          ensure_ascii=False)
    assert observed["context_sha256"] == hashlib.sha256(expected.encode("utf-8")).hexdigest()
    assert observed["context_characters"] == len(expected)
    assert observed["product_imported"] is False
    assert observed["optional_imports"] == []


def test_probe_rejects_an_unknown_mode(tmp_path):
    root = startup_fixture(tmp_path)
    result = run_probe("turbo", root, ["MODE.md"])
    assert result.returncode != 0


def test_repo_frozen_files_are_never_written_by_the_suite():
    """The mutation tests above only ever wrote into tmp_path copies."""
    manifest = manifest_dict()
    for relative, meta in manifest["required_files"].items():
        data = (ROOT / relative).read_bytes()
        assert hashlib.sha256(data).hexdigest() == meta["raw_sha256"], relative


@pytest.mark.parametrize(("precision", "recall", "expected"), [
    (1.0, 0.9, "PASS"), (0.999, 1.0, "FAIL"), (1.0, 0.899, "FAIL"),
    (None, 0.0, "FAIL"),
])
def test_sealed_consolidation_gate_boundaries(precision, recall, expected):
    result = {"after_precision": precision, "after_recall": recall}
    assert protocol.consolidation_gate(result)["status"] == expected


@pytest.mark.parametrize(("tokens", "latency", "expected"), [
    (9, 0.9, "PASS"), (10, 0.9, "FAIL"), (9, 1.0, "FAIL"),
])
def test_sealed_startup_gate_requires_strict_improvements(tokens, latency, expected):
    result = {
        "complete": True, "missing_required_items": [],
        "rows": [{"before_correct": True, "after_correct": True}],
        "full_context": {"tokens_measured_o200k_base": 10},
        "complete_context": {"tokens_measured_o200k_base": tokens},
    }
    timing = {"full_median_load_read_ms": 1.0, "compact_median_load_read_ms": latency,
              "whole_context": {"full": result["full_context"], "compact": result["complete_context"]}}
    assert protocol.startup_gates(result, timing)["IS-2"]["status"] == expected


def synthetic_recall_rows():
    metrics = {"r@1": 0.8, "r@5": 0.8, "mrr": 0.8, "ndcg@10": 0.8, "n": 10.0}
    return [{"author": author, "split": split, "kind": "exact",
             "before": dict(metrics), "after": dict(metrics),
             "before_raw_precision_at_1": 0.7, "after_raw_precision_at_1": 0.7,
             "before_p95_ms": 2.0, "after_p95_ms": 2.0}
            for author in ("history-a", "history-b", "history-extra") for split in ("dev", "test")]


@pytest.fixture
def sealed_synthetic(tmp_path, monkeypatch):
    """Only invented authors, pair cases, contexts and scorer decisions enter this fixture."""
    import birkin_mnemosyne

    root = tmp_path / "sealed-tree"
    root.mkdir()
    calls = []
    probe_calls = []
    source = "# Mode\nGuard: synthetic\n"

    class Reader:
        def __init__(self, root):
            self.root = root

        def read(self, paths, *, compact=False):
            context = json.dumps({"files": [{"path": "MODE.md", "text": source}]},
                                 ensure_ascii=False, separators=(",", ":") if compact else None)
            return types.SimpleNamespace(context=context)

        def verify(self, context, paths):
            return types.SimpleNamespace(complete=True)

    class Service:
        def __init__(self, root, *, semantic=False, thresholds=None):
            self.semantic_status = "ready"
            calls.append(("service", semantic, thresholds))

        def questions(self, limit=20):
            return ()

    monkeypatch.setattr(birkin_mnemosyne, "StartupReader", Reader)
    monkeypatch.setattr(birkin_mnemosyne, "Consolidation", Service)
    monkeypatch.setattr(protocol, "ROOT", root)
    threshold_path = root / "thresholds.json"
    threshold_path.write_text(json.dumps({"locked": True, "thresholds": {"synthetic": 1}}), "utf-8")
    monkeypatch.setattr(protocol, "THRESHOLDS_PATH", threshold_path)

    def context_size(text):
        return {"characters": len(text), "utf8_bytes": len(text.encode()),
                "tokens_measured_o200k_base": 9 if '":[{' in text else 10}

    runner = types.ModuleType(protocol.SCORER_MODULES[0])
    runner.__dict__.update(StartupReader=Reader, Consolidation=Service, context_size=context_size)

    def startup(data):
        calls.append(("startup", data["author"]))
        full = Reader(root).read([]).context
        candidate = runner.StartupReader(root).read([]).context
        return {"author": data["author"], "complete": True, "missing_required_items": [],
                "rows": [{"id": "q", "before_correct": True, "after_correct": True}],
                "full_context": context_size(full), "complete_context": context_size(candidate),
                "fresh_process": {"startup": {"legacy": True}}}

    def consolidation(data):
        runner.Consolidation(root).questions()
        calls.append(("consolidation", data["author"]))
        detected = 10 if data["author"] == "invented-a" else 9
        rows = [{"id": case["id"], "gold_related": True, "after_detected": index < detected}
                for index, case in enumerate(data["consolidation"])]
        return {"author": data["author"], "rows": rows, "after_precision": 1.0,
                "after_recall": detected / 10}

    def identity(data):
        calls.append(("identity", data["author"]))
        return {"author": data["author"], "rows": [{"id": "i", "after_correct": True}]}

    rows = synthetic_recall_rows()
    runner.__dict__.update(
        startup=startup, consolidation=consolidation, identity=identity, kibitzer=lambda: rows,
        corpus=types.SimpleNamespace(queries=lambda: [
            types.SimpleNamespace(author=row["author"], split=row["split"], kind=row["kind"])
            for row in rows]),
    )
    pinned = {}
    required_files = {}
    for name in protocol.SCORER_MODULES:
        relative = name.replace(".", "/") + ".py"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Synthetic immutable scorer sentinel\n", "utf-8")
        module = runner if name == protocol.SCORER_MODULES[0] else types.ModuleType(name)
        module.__file__ = str(path)
        monkeypatch.setitem(sys.modules, name, module)
        pinned[relative] = path.read_bytes()
        digest = protocol.raw_sha256(pinned[relative])
        required_files[relative] = {"raw_sha256": digest, "git_blob_sha256": digest}
    required_authors = {}
    identities = {}
    for author in ("invented-a", "invented-b"):
        relative = author + ".json"
        data = {"author": author,
                "startup": {"files": [{"path": "MODE.md", "text": source}],
                            "questions": [{"id": "q"}]},
                "identity": {"questions": [{"id": "i"}]},
                "consolidation": [{"id": str(index), "titles": ["A", "B"], "bodies": ["A", "B"]}
                                  for index in range(10)]}
        path = root / relative
        path.write_text(json.dumps(data), "utf-8")
        pinned[relative] = path.read_bytes()
        digest = protocol.raw_sha256(pinned[relative])
        required_files[relative] = {"raw_sha256": digest, "git_blob_sha256": digest}
        required_authors[author] = {feature: [relative] for feature in
                                   ("startup", "identity", "consolidation")}
        identities[relative] = author
    baseline = root / "baseline.json"
    baseline.write_text(json.dumps({"kibitzer": rows}), "utf-8")
    manifest = {"required_files": required_files, "required_authors": required_authors,
                "author_identity": identities, "hash_contract": {"normalization": "CRLF"},
                "slices_validated_at": "synthetic", "source_tree_sha256": "synthetic-source-tree",
                "required_recall_authors": ["history-a", "history-b", "history-extra"],
                "required_recall_slices": ["exact"],
                "recall_baseline": {"path": "baseline.json",
                                    "raw_sha256": protocol.raw_sha256(baseline.read_bytes())}}
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), "utf-8")
    monkeypatch.setattr(protocol, "_pinned_blob_bytes", lambda name: pinned.get(name))
    monkeypatch.setattr(protocol, "normalized_object_id", lambda data: "synthetic-object")
    monkeypatch.setattr(protocol, "_tree_state",
                        lambda: {"head": "synthetic-head", "git_tree": "synthetic-tree",
                                 "working_tree_sha256": "synthetic-working", "status": ""})

    def probe(probe_root, paths, mode):
        context = Reader(probe_root).read(paths, compact=mode == "compact").context
        probe_calls.append((mode, probe_root, list(paths)))
        return {"mode": mode, "probe": "synthetic-probe", "root": str(probe_root), "paths": paths,
                "context_sha256": protocol.raw_sha256(context.encode()),
                "load_read_ms": 1.0 if mode == "full" else 0.5, "peak_rss_bytes": 10,
                "context_characters": len(context), "product_imported": mode == "compact",
                "optional_imports": [], "legacy": False}

    real_probe = protocol.round4_probe
    monkeypatch.setattr(protocol, "round4_probe", probe)
    return types.SimpleNamespace(root=root, manifest=manifest, path=manifest_path, pinned=pinned,
                                 runner=runner, reader=Reader, service=Service, rows=rows,
                                 calls=calls, probes=probe_calls, baseline=baseline, real_probe=real_probe)


def test_sealed_cli_preserves_authors_pairs_provenance_and_private_artifacts(sealed_synthetic, capsys):
    fixture = sealed_synthetic
    output = fixture.root / "synthetic-results.json"
    status = protocol.main(["--manifest", str(fixture.path), "--root", str(fixture.root),
                            "--output", str(output)])
    assert status == 0
    summary = json.loads(capsys.readouterr().out)
    assert set(summary) == {"status", "status_scope", "all_IS_status", "gates", "output", "gates_output"}
    assert summary["all_IS_status"] == "PENDING"
    report = json.loads(output.read_text("utf-8"))
    assert set(report["authors"]) == {"invented-a", "invented-b"}
    assert report["authors"]["invented-a"]["consolidation"][0]["configured"]["after_recall"] == 1.0
    candidate = report["authors"]["invented-b"]["consolidation"][0]["configured"]
    assert candidate["after_recall"] == 0.9
    assert candidate["complete_counts"]["fn"] == candidate["complete_counts"]["abstentions"] == 1
    assert len(report["historical_recall"]) == 6
    for author in report["authors"].values():
        timing = author["startup"][0]["paired_startup"]
        assert len(timing["pairs"]) == 10
        assert [pair["order"] for pair in timing["pairs"]] == \
            [["full", "compact"], ["compact", "full"]] * 5
        assert all(len(pair["observations"]) == 2 for pair in timing["pairs"])
        assert timing["full_median_load_read_ms"] == 1.0
        assert timing["compact_median_load_read_ms"] == 0.5
    assert len(fixture.probes) == 40
    assert all(not root.exists() for _, root, _ in fixture.probes)
    assert fixture.runner.StartupReader is fixture.reader
    assert fixture.runner.Consolidation is fixture.service
    assert report["provenance"]["manifest_source_tree_sha256"] == "synthetic-source-tree"
    assert report["configuration"]["thresholds_sha256"] == protocol.raw_sha256(
        (fixture.root / "thresholds.json").read_bytes())
    assert report["provenance"]["bytecode_before"]["policy"]
    assert report["started_at"] <= report["finished_at"]
    assert all(report["gates"][key]["status"] == "PASS" for key in
               ("IS-1", "IS-2", "IS-4", "IS-6", "IS-9"))
    assert report["gates"]["IS-8"]["status"] == "PENDING"
    assert json.loads(Path(summary["gates_output"]).read_text())["gates"] == report["gates"]


@pytest.mark.parametrize("failure", [
    "hash", "scorer-hash", "missing-file", "missing-scorer", "unhashed-scorer", "author", "wrong-author",
    "missing-slice", "empty-slice", "unhashed-slice",
    "historical-author", "historical-slice", "baseline-hash", "bad-config",
])
def test_sealed_cli_fails_closed_before_any_scoring(sealed_synthetic, capsys, failure):
    fixture = sealed_synthetic
    path = fixture.root / ("benchmarks/round3/answerer.py" if "scorer" in failure else "invented-a.json")
    if failure in ("hash", "scorer-hash"):
        path.write_bytes(path.read_bytes() + b" ")
    elif failure in ("missing-file", "missing-scorer"):
        path.unlink()
    elif failure == "unhashed-scorer":
        fixture.manifest["required_files"].pop("benchmarks/round3/answerer.py")
    elif failure in ("author", "wrong-author", "missing-slice"):
        payload = json.loads(path.read_text())
        if failure == "author":
            payload.pop("author")
        elif failure == "wrong-author":
            payload["author"] = "not-the-required-author"
        else:
            payload.pop("startup")
        path.write_text(json.dumps(payload))
        fixture.pinned["invented-a.json"] = path.read_bytes()
        digest = protocol.raw_sha256(path.read_bytes())
        fixture.manifest["required_files"]["invented-a.json"] = {
            "raw_sha256": digest, "git_blob_sha256": digest}
    elif failure == "empty-slice":
        fixture.manifest["required_authors"]["invented-a"]["startup"] = []
    elif failure == "unhashed-slice":
        fixture.manifest["required_files"].pop("invented-a.json")
    elif failure == "historical-author":
        fixture.rows[:] = [row for row in fixture.rows if row["author"] != "history-b"]
    elif failure == "historical-slice":
        fixture.rows.pop()
    elif failure == "baseline-hash":
        fixture.baseline.write_text("{}")
    elif failure == "bad-config":
        (fixture.root / "thresholds.json").write_text('{"locked": false}')
    fixture.path.write_text(json.dumps(fixture.manifest))
    output = fixture.root / "failed-results.json"
    assert protocol.main(["--manifest", str(fixture.path), "--root", str(fixture.root),
                          "--output", str(output)]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "FAIL"
    assert fixture.calls == fixture.probes == []
    assert not output.exists()


def test_sealed_restores_constructor_globals_after_scorer_failure(sealed_synthetic, monkeypatch):
    def fail(data):
        raise protocol.FrozenInputError("synthetic scorer failure")

    monkeypatch.setattr(sealed_synthetic.runner, "consolidation", fail)
    with pytest.raises(protocol.FrozenInputError, match="synthetic scorer failure"):
        protocol.sealed_evaluation(sealed_synthetic.path, root=sealed_synthetic.root)
    assert sealed_synthetic.runner.StartupReader is sealed_synthetic.reader
    assert sealed_synthetic.runner.Consolidation is sealed_synthetic.service


@pytest.mark.parametrize("surface", ["compact", "semantic", "thresholds"])
def test_sealed_missing_product_surface_is_pending(sealed_synthetic, monkeypatch, surface):
    import birkin_mnemosyne

    if surface == "compact":
        class LegacyReader(sealed_synthetic.reader):
            def read(self, paths):
                return super().read(paths)
        monkeypatch.setattr(birkin_mnemosyne, "StartupReader", LegacyReader)
    elif surface == "semantic":
        class LegacyService(sealed_synthetic.service):
            def __init__(self, root):
                super().__init__(root)
        monkeypatch.setattr(birkin_mnemosyne, "Consolidation", LegacyService)
    else:
        (sealed_synthetic.root / "thresholds.json").unlink()
    report = protocol.sealed_evaluation(sealed_synthetic.path, root=sealed_synthetic.root)
    assert report["status"] == "PENDING"
    key = "IS-2" if surface == "compact" else "IS-6"
    assert report["gates"][key]["status"] == "PENDING"


@pytest.mark.parametrize(("field", "value", "expected"), [
    ("after_p95_ms", 2.0, "PASS"), ("after_p95_ms", 2.001, "FAIL"),
    ("after_raw_precision_at_1", 0.7, "PASS"), ("after_raw_precision_at_1", 0.699, "FAIL"),
    ("mrr", 0.8, "PASS"), ("mrr", 0.799, "FAIL"), ("n", 9.0, "FAIL"),
    ("r@1", 0.8, "PASS"), ("r@1", 0.799, "FAIL"),
    ("r@5", 0.8, "PASS"), ("r@5", 0.799, "FAIL"),
    ("ndcg@10", 0.8, "PASS"), ("ndcg@10", 0.799, "FAIL"),
])
def test_sealed_recall_baseline_boundaries(field, value, expected):
    before = synthetic_recall_rows()[0]
    after = json.loads(json.dumps(before))
    if field in after["after"]:
        after["after"][field] = value
    else:
        after[field] = value
    key = (before["author"], before["split"], before["kind"])
    assert protocol.recall_gates([after], [before], {key})[0]["gate"]["status"] == expected


@pytest.mark.parametrize("missing", ["slice", "before_p95_ms", "mrr"])
def test_sealed_missing_recorded_baseline_names_exact_gap(missing):
    candidate = synthetic_recall_rows()[0]
    baseline = json.loads(json.dumps(candidate))
    if missing == "before_p95_ms":
        baseline.pop(missing)
    elif missing == "mrr":
        baseline["before"].pop(missing)
    key = (candidate["author"], candidate["split"], candidate["kind"])
    result = protocol.recall_gates([candidate], [] if missing == "slice" else [baseline], {key})[0]
    assert result["gate"]["status"] == "PENDING"
    assert missing in result["gate"]["reason"]


def test_sealed_refuses_existing_evidence_without_scoring(sealed_synthetic, capsys):
    output = sealed_synthetic.root / "existing.json"
    output.write_text("existing sealed evidence")
    assert protocol.main(["--manifest", str(sealed_synthetic.path), "--root", str(sealed_synthetic.root),
                          "--output", str(output)]) == 1
    assert "already exists" in json.loads(capsys.readouterr().err)["reason"]
    assert output.read_text() == "existing sealed evidence"
    assert sealed_synthetic.calls == []


def test_sealed_pairing_uses_twenty_real_fresh_subprocesses(sealed_synthetic, monkeypatch):
    fixture = sealed_synthetic
    probe_dir = fixture.root / "benchmarks/round4"
    probe_dir.mkdir(parents=True)
    (probe_dir / "_startup_probe.py").write_text(
        "import hashlib, json, os, pathlib, sys\n"
        "mode, root, *paths = sys.argv[1:]\n"
        "context = json.dumps({'files': [{'path': p, 'text': "
        "(pathlib.Path(root) / p).read_text()} for p in paths]}, ensure_ascii=False, "
        "separators=(',', ':') if mode == 'compact' else None)\n"
        "print(json.dumps({'mode': mode, 'probe': 'synthetic', 'root': root, 'paths': paths, "
        "'context_sha256': hashlib.sha256(context.encode()).hexdigest(), "
        "'load_read_ms': 1.0 if mode == 'full' else 0.5, 'peak_rss_bytes': 10, "
        "'context_characters': len(context), 'product_imported': mode == 'compact', "
        "'optional_imports': [], 'pid': os.getpid()}))\n",
        encoding="utf-8")
    monkeypatch.setattr(protocol, "HERE", probe_dir)
    data = json.loads((fixture.root / "invented-a.json").read_text())
    measured = protocol._score_slice(fixture.runner, "startup", data, "compact", "semantic")
    launched = []
    run = subprocess.run

    def capture(command, **kwargs):
        launched.append(list(command))
        return run(command, **kwargs)

    monkeypatch.setattr(protocol, "round4_probe", fixture.real_probe)
    monkeypatch.setattr(subprocess, "run", capture)
    timing = protocol.paired_startup(data, fixture.runner, measured)
    assert len(launched) == 20
    assert [command[2] for command in launched] == ["full", "compact", "compact", "full"] * 5
    assert all(command[0] == sys.executable and command[1] == str(probe_dir / "_startup_probe.py")
               for command in launched)
    assert all(len(pair["observations"]) == 2 for pair in timing["pairs"])
    assert len({row["pid"] for pair in timing["pairs"] for row in pair["observations"]}) == 20


def test_sealed_semantic_unready_pipeline_stays_pending(sealed_synthetic, monkeypatch):
    def unavailable(self, limit=20):
        self.semantic_status = "unavailable"
        return ()

    monkeypatch.setattr(sealed_synthetic.service, "questions", unavailable)
    report = protocol.sealed_evaluation(sealed_synthetic.path, root=sealed_synthetic.root)
    assert report["gates"]["IS-6"]["status"] == "PENDING"
    assert report["status"] == "PENDING"
    assert sealed_synthetic.runner.Consolidation is sealed_synthetic.service


def test_sealed_missing_baseline_is_pending_not_an_invented_number(sealed_synthetic):
    sealed_synthetic.baseline.unlink()
    report = protocol.sealed_evaluation(sealed_synthetic.path, root=sealed_synthetic.root)
    assert report["gates"]["IS-4"]["status"] == "PENDING"
    assert report["baseline_source"]["path"] == "baseline.json"
    assert all("baseline" not in row for row in report["historical_recall"])


def test_sealed_scorer_mutation_is_rejected_and_bindings_restored(sealed_synthetic, monkeypatch):
    original = sealed_synthetic.runner.consolidation

    def drift(data):
        result = original(data)
        (sealed_synthetic.root / "benchmarks/round3/answerer.py").write_text("changed scorer")
        return result

    monkeypatch.setattr(sealed_synthetic.runner, "consolidation", drift)
    with pytest.raises(protocol.FrozenInputError, match="drifted"):
        protocol.sealed_evaluation(sealed_synthetic.path, root=sealed_synthetic.root)
    assert sealed_synthetic.runner.StartupReader is sealed_synthetic.reader
    assert sealed_synthetic.runner.Consolidation is sealed_synthetic.service


@pytest.mark.parametrize(("field", "value"), [
    ("context_sha256", "different"), ("paths", ["other.md"]),
    ("load_read_ms", float("nan")), ("load_read_ms", -1.0),
])
def test_sealed_paired_probe_rejects_invalid_or_different_closure(
    sealed_synthetic, monkeypatch, field, value,
):
    probe = protocol.round4_probe

    def changed(*args):
        result = probe(*args)
        result[field] = value
        return result

    monkeypatch.setattr(protocol, "round4_probe", changed)
    with pytest.raises(protocol.FrozenInputError):
        protocol.sealed_evaluation(sealed_synthetic.path, root=sealed_synthetic.root)


@pytest.mark.parametrize("failure", ["omitted-case", "bad-abstention-denominator"])
def test_sealed_rejects_incomplete_scorer_evidence(sealed_synthetic, monkeypatch, failure):
    original = sealed_synthetic.runner.consolidation

    def incomplete(data):
        result = original(data)
        if failure == "omitted-case":
            result["rows"].pop()
        else:
            result["after_recall"] = 0.123
        return result

    monkeypatch.setattr(sealed_synthetic.runner, "consolidation", incomplete)
    with pytest.raises(protocol.FrozenInputError):
        protocol.sealed_evaluation(sealed_synthetic.path, root=sealed_synthetic.root)


@pytest.mark.parametrize("failure", ["incomplete", "miss", "changed-answer"])
def test_sealed_startup_zero_miss_and_unchanged_answer_boundaries(failure):
    measured = {
        "complete": failure != "incomplete",
        "missing_required_items": ["synthetic miss"] if failure == "miss" else [],
        "rows": [{"before_correct": True, "after_correct": failure != "changed-answer"}],
        "full_context": {"tokens_measured_o200k_base": 10},
        "complete_context": {"tokens_measured_o200k_base": 9},
    }
    timing = {"full_median_load_read_ms": 1.0, "compact_median_load_read_ms": 0.5,
              "whole_context": {"full": measured["full_context"], "compact": measured["complete_context"]}}
    gates = protocol.startup_gates(measured, timing)
    assert gates["IS-1"]["status"] == gates["IS-2"]["status"] == "FAIL"


def test_sealed_pair_median_keeps_raw_outlier_without_averaging(sealed_synthetic, monkeypatch):
    probe = protocol.round4_probe
    full_count = 0

    def outlier(*args):
        nonlocal full_count
        result = probe(*args)
        if result["mode"] == "full":
            full_count += 1
            result["load_read_ms"] = 100.0 if full_count == 1 else 1.0
        return result

    monkeypatch.setattr(protocol, "round4_probe", outlier)
    report = protocol.sealed_evaluation(sealed_synthetic.path, root=sealed_synthetic.root)
    timing = report["authors"]["invented-a"]["startup"][0]["paired_startup"]
    assert timing["pairs"][0]["observations"][0]["load_read_ms"] == 100.0
    assert timing["full_median_load_read_ms"] == 1.0


def test_sealed_cli_writes_pending_artifact_and_returns_nonzero(sealed_synthetic, capsys):
    sealed_synthetic.baseline.unlink()
    output = sealed_synthetic.root / "pending-results.json"
    code = protocol.main(["--manifest", str(sealed_synthetic.path), "--root", str(sealed_synthetic.root),
                          "--output", str(output)])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "PENDING"
    assert json.loads(output.read_text())["gates"]["IS-4"]["status"] == "PENDING"


def test_sealed_pair_bpe_uses_raw_crlf_context_not_normalized_round3_full(
    sealed_synthetic, monkeypatch,
):
    from benchmarks.round4._startup_probe import full_context

    source = "# Mode\r\nGuard: synthetic\r\n"
    data = {"startup": {"files": [{"path": "MODE.md", "text": source}]}}

    class RawReader:
        def __init__(self, root):
            self.root = root

        def read(self, paths):
            text = (self.root / paths[0]).read_bytes().decode("utf-8")
            return types.SimpleNamespace(context=json.dumps(
                {"files": [{"path": paths[0], "text": text}]},
                ensure_ascii=False, separators=(",", ":")))

        def verify(self, context, paths):
            return types.SimpleNamespace(complete=True)

    def size(text):
        return {"characters": len(text), "tokens_measured_o200k_base": len(text)}

    def probe(root, paths, mode):
        context = full_context(root, paths) if mode == "full" else RawReader(root).read(paths).context
        return {"mode": mode, "probe": "synthetic", "root": str(root), "paths": paths,
                "context_sha256": protocol.raw_sha256(context.encode()),
                "load_read_ms": 1.0 if mode == "full" else 0.5, "peak_rss_bytes": 10,
                "context_characters": len(context), "product_imported": mode == "compact",
                "optional_imports": [], "legacy": False}

    monkeypatch.setattr(protocol, "configured_startup", lambda root, mode: RawReader(root))
    monkeypatch.setattr(protocol, "round4_probe", probe)
    monkeypatch.setattr(sealed_synthetic.runner, "context_size", size)
    normalized = json.dumps({"files": [{"path": "MODE.md", "text": source.replace("\r\n", "\n")}]})
    compact = json.dumps({"files": [{"path": "MODE.md", "text": source}]}, separators=(",", ":"))
    measured = {"full_context": size(normalized), "complete_context": size(compact),
                "complete": True, "missing_required_items": [],
                "rows": [{"before_correct": True, "after_correct": True}]}
    timing = protocol.paired_startup(data, sealed_synthetic.runner, measured)
    assert timing["round3_full_context_size_matches_raw_full"] is False
    assert timing["whole_context"]["full"]["characters"] > measured["full_context"]["characters"]
    assert protocol.startup_gates(measured, timing)["IS-2"]["status"] == "PASS"
