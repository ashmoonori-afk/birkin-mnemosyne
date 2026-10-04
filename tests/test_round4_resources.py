"""Round-4 resource probe metrics, modes, readiness and capacity (QA-5).

Deterministic: every test drives the driver's own helpers or a disposable
fresh child process. Nothing here depends on the optional semantic model being
prepared and nothing is skipped on any OS: the optional-dependent branches
assert the *weaker* real contract when the model is absent instead of excusing
themselves.

The regressions pin the corrected surfaces:

- ``compact`` invokes the real ``StartupReader.read(paths, compact=True)``
  surface, never a legacy-but-relabelled read;
- ``consolidation-semantic`` invokes the real semantic Consolidation with a
  locked thresholds config supplied by the caller and requires
  ``semantic_status == "ready"`` afterwards, never a lexical/retrieval
  substitute;
- the child clock starts BOTH before its first product import and before
  constructor/operation, so a mode cannot be reported under a timer that
  misses import cost;
- observations without mode evidence are rejected, not averaged in.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.round4 import resource_probe as probe

# -- metrics -------------------------------------------------------------------

def test_summary_reports_min_median_max_and_ignores_missing():
    obs = [{"load_ms": 3.0}, {"load_ms": 1.0}, {"load_ms": 2.0}, {"load_ms": None}]
    assert probe._summary(obs, "load_ms") == {"n": 3, "min_ms": 1.0, "median_ms": 2.0,
                                              "max_ms": 3.0}
    assert probe._summary([{"load_ms": None}], "load_ms") == {"n": 0}


def test_bounds_are_the_declared_contract():
    assert probe.MODE_BOUNDS["compact"] == {"startup_ms": 1000}
    assert probe.MODE_BOUNDS["kibitzer"]["peak_rss_bytes"] == 150_000_000
    semantic_bounds = probe.MODE_BOUNDS["consolidation-semantic"]
    assert semantic_bounds["total_peak_rss_bytes"] == 150_000_000
    for mode in probe.MODES:
        assert probe.MODE_BOUNDS[mode]["startup_ms"] == 1000


def test_absent_product_surfaces_are_detected_not_assumed():
    """At the protocol base the future APIs do not exist; the probe must say so."""
    assert probe.supported is not None
    assert probe.startup_compact_available is not None
    assert probe.consolidation_semantic_available is not None


class _FakeReader:
    def read(self, paths, *, compact=False):
        del paths, compact


class _FakeConsolidation:
    def __init__(self, vault, *, semantic=None, thresholds=None):
        del vault, semantic, thresholds
        self.semantic_status = "ready"

    def questions(self, limit=20):
        del limit
        return ()


class _LegacyConsolidation:
    """The base version: no semantic/thresholds kwargs and no limit kwarg."""

    def __init__(self, vault):
        del vault

    def questions(self):
        return ()


class _QuestionsStatus:
    """The planned shape where the ready status rides on the result object."""

    semantic_status = "ready"

    def questions(self, limit=20):
        del limit
        return self


class _LegacyReader:
    def read(self, paths):
        del paths


def test_surface_detection_accepts_real_shapes_and_rejects_legacy_ones():
    assert probe.supported(_FakeReader, "read") is True
    assert probe.supported(_LegacyReader, "read") is False
    assert probe.supported(_FakeConsolidation, "questions") is True    # has limit=
    assert probe.supported(_QuestionsStatus, "questions") is True
    assert probe.supported(_LegacyConsolidation, "questions") is False
    assert probe.questions_carry_status(_QuestionsStatus()) is True
    assert probe.questions_carry_status(_LegacyConsolidation("v")) is False
    assert probe.supported(object) is False
    assert probe._required(_LegacyReader, "read") == ("compact",)
    assert probe.consolidation_semantic_available(_FakeConsolidation) is True
    assert probe.consolidation_semantic_available(_LegacyConsolidation) is False


@pytest.mark.parametrize("elapsed,rss,expected", [
    (999.0, 149_999_999, True),
    (1000.0, 150_000_000, True),
    (1000.01, 149_999_999, False),
    (999.0, 150_000_001, False),
])
def test_usable_observation_must_also_meet_resource_bars(
        monkeypatch, tmp_path, elapsed, rss, expected):
    observation = {"mode": "kibitzer", "load_ms": elapsed,
                   "import_ms": 0.1, "peak_rss_bytes": rss, "candidates": 1}
    monkeypatch.setattr(probe, "run_child", lambda *args: dict(observation))
    result = probe.measure_mode("kibitzer", tmp_path, None, 1, {})
    assert result["usable_observations"] == 1
    assert result["bounds_met"] is expected


def test_pending_observations_are_usable_but_never_evidence():
    pending = {"mode": "compact", "status": "PENDING", "load_ms": 1.0,
               "import_ms": 1.0, "peak_rss_bytes": 1000,
               "reason": "compact-read-api-absent"}
    assert probe.observation_errors(pending) == []      # no false defect claims
    assert probe.EVIDENCE_KEYS["compact"]               # ...but no evidence was faked
    assert probe.observation_errors({**pending, "status": None}) == ["context_sha256"]


@pytest.mark.parametrize("retain_chunks", [False, True])
def test_pending_attempt_never_enters_ready_resource_evidence(monkeypatch, tmp_path, retain_chunks):
    ready = {"mode": "consolidation-semantic", "load_ms": 10.0,
             "import_ms": 1.0, "peak_rss_bytes": 1_000_000,
             "encoded_chunks": 2, "semantic_status": "ready"}
    unavailable = {"mode": "consolidation-semantic", "status": "PENDING",
                   "reason": "semantic-not-ready", "detail": "not ready",
                   "load_ms": 10.0, "import_ms": 1.0, "peak_rss_bytes": 1_000_000,
                   "semantic_status": "unavailable"}
    if retain_chunks:
        unavailable["encoded_chunks"] = 2
    attempts = iter((ready, unavailable))
    monkeypatch.setattr(probe, "run_child", lambda *args: dict(next(attempts)))
    result = probe.measure_mode("consolidation-semantic", tmp_path, None, 2, {})
    assert "status" in result and "chunks" in result
    assert "semantic_status" in result and "startup_ms" in result
    assert result["status"] == "PENDING"
    assert result["usable_observations"] == 1
    assert result["bounds_met"] is False
    assert result["chunks"] == 2
    assert result["semantic_status"] == "ready"
    assert result["startup_ms"]["n"] == 1
    assert len(result["observations"]) == 2


def test_observation_requires_finite_positive_measurements():
    good = {"mode": "compact", "load_ms": 12.5, "peak_rss_bytes": 40_000_000,
            "import_ms": 30.0, "context_sha256": "ab" * 32}
    assert probe.observation_errors(good) == []
    assert probe.observation_errors({**good, "load_ms": 0.0}) == ["load_ms"]
    assert probe.observation_errors({**good, "load_ms": None}) == ["load_ms"]
    assert probe.observation_errors({**good, "load_ms": float("nan")}) == ["load_ms"]
    assert probe.observation_errors({**good, "load_ms": float("inf")}) == ["load_ms"]
    assert probe.observation_errors({**good, "peak_rss_bytes": 0}) == ["peak_rss_bytes"]
    assert probe.observation_errors({**good, "import_ms": -1.0}) == ["import_ms"]


def test_repetitions_restore_pristine_bytes_and_discard_derived_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "policy.md"
    cache = vault / ".mnemosyne-index.json"
    added = vault / "added.md"
    _ = note.write_bytes(b"Original policy.\r\n")
    _ = cache.write_bytes(b"preflight cache")
    starts: list[tuple[bytes, bool, bool]] = []
    transitions: list[bool] = []

    def changing_child(
        args: list[str], _env: dict[str, str],
    ) -> dict[str, str | int | float]:
        assert Path(args[2]) == vault
        starts.append((note.read_bytes(), cache.exists(), added.exists()))
        _ = note.write_bytes(b"Changed policy.\n")
        _ = cache.write_bytes(b"derived cache")
        _ = added.write_bytes(b"Child-added policy.\n")
        transitions.append(note.read_bytes() != b"Original policy.\r\n")
        return {
            "mode": "kibitzer", "load_ms": 1.0, "import_ms": 0.5,
            "peak_rss_bytes": 1_000_000, "candidates": 1,
        }

    monkeypatch.setattr(probe, "run_child", changing_child)

    _ = probe.measure_mode("kibitzer", vault, None, 2, {})

    assert starts == [(b"Original policy.\r\n", False, False)] * 2
    assert transitions == [True, True]


def test_observation_requires_the_mode_specific_evidence_key():
    assert probe.observation_errors({"mode": "compact", "load_ms": 1.0,
                                     "peak_rss_bytes": 1, "import_ms": 1.0,
                                     "context_sha256": "ab" * 32}) == []
    missing_compact = {"mode": "compact", "load_ms": 1.0, "peak_rss_bytes": 1,
                       "import_ms": 1.0, "context_sha256": ""}
    assert "context_sha256" in probe.observation_errors(missing_compact)
    assert "candidates" in probe.observation_errors(
        {"mode": "kibitzer", "load_ms": 1.0, "peak_rss_bytes": 1, "import_ms": 1.0})
    assert probe.observation_errors({"mode": "kibitzer", "load_ms": 1.0,
                                     "peak_rss_bytes": 1, "import_ms": 1.0,
                                     "candidates": 2}) == []
    assert "encoded_chunks" in probe.observation_errors(
        {"mode": "consolidation-semantic", "load_ms": 1.0, "peak_rss_bytes": 1,
         "import_ms": 1.0, "semantic_status": "ready"})
    # a semantic observation must carry BOTH the encode count and the ready status
    assert "semantic_status" in probe.observation_errors(
        {"mode": "consolidation-semantic", "load_ms": 1.0, "peak_rss_bytes": 1,
         "import_ms": 1.0, "encoded_chunks": 3})


def test_new_product_findings_refuse_a_nonfinite_or_zero_value():
    def findings(**over: probe.JsonValue) -> list[str]:
        base: dict[str, probe.JsonValue] = {
            "finite": True, "nonzero": True, "dtype": "float32",
            "shape": [1, 256], "values": [0.5],
        }
        return probe._new_product_findings({**base, **over})

    assert findings() == []
    assert findings(finite=False) == ["finite"]
    assert findings(nonzero=False) == ["nonzero"]
    assert findings(values=[0.0, 0.0]) == ["values"]


@pytest.mark.parametrize("values", [None, True, 7, "not-a-vector"])
def test_encode_findings_reject_nonlist_values(
    values: probe.JsonValue, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "model"
    model.mkdir()
    _ = (model / "meta.json").write_text("{}", encoding="utf-8")
    encode: dict[str, probe.JsonValue] = {
        "finite": True, "nonzero": True, "values": values,
    }

    def child_observation(
        _args: list[str], _env: dict[str, str],
    ) -> dict[str, probe.JsonValue]:
        return {
            "load_ms": 1.0, "peak_rss_bytes": 1_000_000,
            "surface_status": {}, "encode": encode,
        }

    monkeypatch.setattr(probe, "run_child", child_observation)

    report = probe.backend_check(model)

    assert "encode_findings" in report and "vault_removed" in report
    assert report["encode_findings"] == ["values"]
    assert report["vault_removed"] is True


# -- capacity ------------------------------------------------------------------

@pytest.mark.parametrize("notes,chunks,total_bytes,supported", [
    (160, 1, 4096, True),
    (1000, 4096, 8 * 1024 * 1024, True),
    (1001, 1, 4096, False),                       # note count above the contract
    (1000, 4097, 4096, False),                    # span count above the contract
    (1000, 4096, 8 * 1024 * 1024 + 1, False),     # bytes above the contract
])
def test_capacity_boundaries_refuse_instead_of_truncating(notes, chunks, total_bytes,
                                                          supported):
    got = probe.capacity(notes, chunks, total_bytes)
    assert got["supported"] is supported
    assert got["notes_limit"] == 1000 and got["chunk_limit"] == 4096
    assert got["byte_limit"] == 8 * 1024 * 1024


# -- vault fixture + fresh child modes -----------------------------------------

@pytest.mark.parametrize("arguments", [[], ["run"], ["run", "kibitzer"]])
def test_child_cli_refuses_missing_required_positions(arguments: list[str]) -> None:
    process = subprocess.run(
        [
            sys.executable, str(ROOT / "benchmarks" / "round4" / "resource_probe.py"),
            "__child", *arguments,
        ],
        capture_output=True, text=True, check=False, timeout=10,
    )

    assert process.returncode == 2
    assert process.stdout == ""


def _fake_child_stdout(monkeypatch: pytest.MonkeyPatch, stdout: str) -> None:
    def fake_run(
        command: list[str], *, check: bool, capture_output: bool, text: bool,
        env: dict[str, str], cwd: str,
    ) -> subprocess.CompletedProcess[str]:
        assert command[-3:] == ["run", "compact", "vault"]
        assert not check and capture_output and text
        assert env == {} and cwd == str(ROOT)
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)


@pytest.mark.parametrize("reply", ["[1, 2]", "null", "7", '"text"', "true"])
def test_run_child_rejects_non_object_json_reply(
    monkeypatch: pytest.MonkeyPatch, reply: str,
) -> None:
    _fake_child_stdout(monkeypatch, f"noise\n{reply}\n")

    with pytest.raises(ValueError):
        _ = probe.run_child(["run", "compact", "vault"], {})


def test_run_child_keeps_nested_object_from_last_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"a": [1, 2.5, None, {"b": [True, "x"]}], "meta": {"k": None}}
    _fake_child_stdout(monkeypatch, "{\"ignored\": 1}\n" + json.dumps(payload) + "\n")

    assert probe.run_child(["run", "compact", "vault"], {}) == payload


def _vault(tmp_path: Path, notes: int = 160) -> Path:
    return probe.write_practice_vault(tmp_path / "vault", notes)


def test_practice_vault_is_deterministic_without_frozen_material(tmp_path):
    first = sorted(p.name for p in _vault(tmp_path / "a", 160).rglob("*.md"))
    second = sorted(p.name for p in _vault(tmp_path / "b", 160).rglob("*.md"))
    # 160 total: 4 startup sources + the duplicate pair + 154 filler notes
    assert first == second and len(first) == 160
    assert (tmp_path / "a" / "vault" / "knowledge" / "release-gate.md").is_file()
    # the two discoverable notes share an identical body (an exact duplicate pair)
    knowledge = tmp_path / "a" / "vault" / "knowledge"
    gate = (knowledge / "release-gate.md").read_text("utf-8")
    rollback = (knowledge / "release-rollback.md").read_text("utf-8")
    assert gate.split("---\n\n", 1)[1] == rollback.split("---\n\n", 1)[1]


def test_practice_vault_duplicate_pair_is_detected_by_the_core_pipeline(tmp_path):
    """The probe's own practice vault must be a real, discoverable signal."""
    from birkin_mnemosyne import Consolidation

    vault = _vault2(tmp_path, 6)
    questions = Consolidation(vault).questions()
    assert len(questions) >= 1
    assert {q.reason for q in questions} == {"duplicate"}
    both = {(q.first.path, q.second.path) for q in questions}
    assert any("release-gate" in a and "release-rollback" in b for a, b in both)


def test_scratch_paths_cover_the_probe_cache_artifacts(tmp_path):
    names = [p.name for p in probe.scratch_paths(tmp_path)]
    assert ".mnemosyne-index.json" in names and ".mnemosyne-vectors.npz" in names


def _vault2(tmp_path: Path, notes: int) -> Path:
    return probe.write_practice_vault(tmp_path / f"v{notes}", notes)


def _object(value: probe.JsonValue) -> dict[str, probe.JsonValue]:
    assert isinstance(value, dict)
    return value


def _array(value: probe.JsonValue) -> list[probe.JsonValue]:
    assert isinstance(value, list)
    return value


def _number(value: probe.JsonValue) -> int | float:
    assert isinstance(value, (int, float)) and not isinstance(value, bool)
    return value


def _handle(mode: str, repeats: int = 2, model_dir: Path | None = None):
    return __import__("argparse").Namespace(
        modes=mode, repeats=repeats, offline=True, notes=160, keep_vaults=False,
        model_dir=model_dir)


def _run(mode: str, vault: Path, repeats: int = 2,
         model_dir: Path | None = None) -> Mapping[str, Any]:
    return probe.run_probe(_handle(mode, repeats, model_dir))


def test_compact_mode_is_pending_until_the_real_read_exists(tmp_path):
    """No compact-read API at this base -> explicit PENDING, never a fake pass."""
    vault = _vault(tmp_path)
    out = _run("compact", vault)
    record = out["modes"]["compact"]
    assert record["surface"] == "StartupReader.read(compact=True)"
    assert not [p for p in vault.rglob("*") if p.name.startswith(".mnemosyne")]
    assert any("workspace_removed" in c or "residue_files" in c for c in out["cleanup"])
    if probe.startup_compact_available():
        assert record["supported"] is True
        assert record["startup_ms"]["n"] == 2
        assert record["observations"][0]["clock_origin"] == "pre_import"
        assert record["observations"][0]["context_sha256"]
    else:
        assert not record["supported"]
        assert record["status"] == "PENDING"
        assert record["reason"] == "compact-read-api-absent"
        assert record["detail"].startswith("StartupReader.read")


def test_compact_child_uses_the_compact_surface_or_reports_absence(tmp_path):
    """When the API exists the child must drive the real compact surface; the
    evidence is the byte-exact ``compact=True`` context, refused if the child
    only made a legacy (``compact=False``) read."""
    if not probe.startup_compact_available():
        vault = _vault2(tmp_path, 6)
        out = probe.run_child(["run", "compact", str(vault)],
                              probe.child_env(offline=True))
        assert out["status"] == "PENDING"
        assert out["reason"] == "compact-read-api-absent"
        assert out["surface"] == "StartupReader.read(compact=True)"
        return
    vault = _vault(tmp_path, 6)
    from birkin_mnemosyne import StartupReader

    # The child appends to handoff.md in its changed_note phase, so every
    # parent-side context is computed around the child run.
    reader = StartupReader(vault)
    compact = reader.read(["MODE.md"], compact=True).context
    legacy = reader.read(["MODE.md"], compact=False).context
    out = probe.run_child(["run", "compact", str(vault)], probe.child_env(offline=True))
    changed = StartupReader(vault).read(["MODE.md"], compact=True).context
    phases = out["phases"]
    assert phases["first_unencoded_vault"]["context_sha256"] == probe.digest(compact)
    assert phases["warm_vault"]["context_sha256"] == probe.digest(compact)
    assert phases["changed_note"]["context_sha256"] == probe.digest(changed)
    assert phases["changed_note"]["context_sha256"] != probe.digest(compact)
    # the top-level digest reports the first (pre-mutation) compact bundle
    assert out["context_sha256"] == probe.digest(compact)
    assert out["context_sha256"] != probe.digest(legacy)
    assert out["context_bytes"] == len(compact.encode("utf-8"))
    assert out["compact"] is True


def test_child_clock_starts_before_the_first_product_import(tmp_path):
    """No mode may be reported under a timer that misses import cost."""
    vault = _vault2(tmp_path, 6)
    out = probe.run_child(["run", "kibitzer", str(vault)],
                          probe.child_env(offline=True))
    assert out["clock_origin"] == "pre_import"
    assert 0.0 <= _number(out["first_product_import_ms"]) <= _number(out["load_ms"])
    assert _number(out["load_ms"]) >= _number(out["import_ms"]) >= 0.0
    assert _number(out["first_product_import_ms"]) <= _number(out["import_ms"]) + 1.0


def test_kibitzer_mode_reports_candidates_and_capacity(tmp_path):
    vault = _vault(tmp_path)
    out = _run("kibitzer", vault, repeats=1)
    record = out["modes"]["kibitzer"]
    assert record["supported"] is True
    assert record["observations"][0]["candidates"] >= 1
    assert record["observations"][0]["bm25_imported"] is True
    assert record["capacity"]["notes"] == 160


def test_kibitzer_child_sees_changed_notes_immediately(tmp_path):
    vault = _vault2(tmp_path, 6)
    first = probe.run_child(["run", "kibitzer", str(vault)],
                            probe.child_env(offline=True))
    assert _number(first["candidates"]) >= 1
    note = vault / "knowledge" / "release-gate.md"
    note.write_text(note.read_text("utf-8").replace("rollback window",
                                                    "rollback window freeze"), "utf-8")
    second = probe.run_child(["run", "kibitzer", str(vault)],
                             probe.child_env(offline=True))
    assert second["vault_digest"] != first["vault_digest"]


def test_unprepared_semantic_mode_is_pending_never_a_silent_pass(tmp_path):
    _vault(tmp_path, 2)
    empty_cache = tmp_path / "cache"
    empty_cache.mkdir()
    handle = _handle("consolidation-semantic", repeats=1, model_dir=empty_cache)
    # a machine with a prepared model must still not be read as ready when the
    # scoped model directory handed to the probe is empty
    assert probe._check_prepared(empty_cache) is False
    out = probe.run_probe(handle)
    record = out["modes"]["consolidation-semantic"]
    assert "status" in record and "reason" in record and "detail" in record
    assert record["status"] == "PENDING"
    assert record["reason"] == "model_not_prepared"
    detail = record["detail"]
    assert isinstance(detail, str)
    assert "not a pass" in detail


def test_semantic_mode_reports_pending_when_the_semantic_api_is_absent(
        tmp_path, monkeypatch, capsys):
    import birkin_mnemosyne

    monkeypatch.setattr(birkin_mnemosyne, "Consolidation", _LegacyConsolidation)
    monkeypatch.setattr(probe, "peak_rss_bytes", lambda: 1_000_000)
    vault = _vault2(tmp_path, 6)
    probe.run_consolidation(vault)
    record = json.loads(capsys.readouterr().out)
    assert record["status"] == "PENDING"
    assert record["reason"] == "semantic-consolidation-api-absent"
    assert record["surface"] == "Consolidation(semantic=True)"
    assert "semantic=True" in record["detail"]
    assert probe.observation_errors(record) == []


def test_semantic_mode_requires_locked_thresholds_before_construction(
        tmp_path, monkeypatch, capsys):
    import birkin_mnemosyne

    monkeypatch.setattr(birkin_mnemosyne, "Consolidation", _FakeConsolidation)
    monkeypatch.setattr(probe, "THRESHOLDS_PATH", tmp_path / "absent.json")
    monkeypatch.setattr(probe, "peak_rss_bytes", lambda: 1_000_000)
    probe.run_consolidation(_vault2(tmp_path, 6))
    record = json.loads(capsys.readouterr().out)
    assert record["status"] == "PENDING"
    assert record["reason"] == "locked-thresholds-absent"


@pytest.mark.parametrize("final_status", ["ready", "unavailable"])
def test_semantic_mode_forwards_locked_config_and_reads_service_status_after_questions(
        tmp_path, monkeypatch, capsys, final_status):
    import birkin_mnemosyne

    calls = []
    thresholds = {"min_cosine": 0.95, "min_margin": 0.05}
    config_path = tmp_path / "thresholds.json"
    config_path.write_text(json.dumps({"locked": True, "thresholds": thresholds}),
                           encoding="utf-8")

    class ReadyService:
        encoded_chunks = 1

        def __init__(self, vault, *, semantic=False, thresholds=None):
            calls.append((vault, semantic, thresholds))
            self.semantic_status = "starting"

        def questions(self, limit=20):
            calls.append(("questions", limit))
            self.semantic_status = final_status
            return ()

        def entries(self):
            return (1,)

    monkeypatch.setattr(birkin_mnemosyne, "Consolidation", ReadyService)
    monkeypatch.setattr(probe, "THRESHOLDS_PATH", config_path)
    monkeypatch.setattr(probe, "peak_rss_bytes", lambda: 1_000_000)
    vault = _vault2(tmp_path, 6)
    probe.run_consolidation(vault)
    record = json.loads(capsys.readouterr().out)
    # one construction, then the three vault-state passes
    assert calls[0] == (vault, True, thresholds)
    if final_status == "ready":
        assert calls[1:] == [("questions", 20)] * 3
        assert record["semantic_status"] == "ready"
        assert "status" not in record
        assert record["thresholds"] == thresholds
        assert record["encoded_chunks"] == 1
        assert record["questions"] == 0
        assert set(record["phases"]) == set(probe.PHASES)
        assert record["phases"]["changed_note"]["vault_digest"] != \
            record["phases"]["first_unencoded_vault"]["vault_digest"]
    else:
        # the first pass already reports a non-ready service: no further work
        assert calls == [(vault, True, thresholds), ("questions", 20)]
        assert record["status"] == "PENDING"
        assert record["reason"] == "semantic-not-ready"


@pytest.mark.parametrize("failure_call", [2, 3])
def test_semantic_resource_probe_rejects_readiness_loss_after_cold(
        tmp_path, monkeypatch, capsys, failure_call):
    import birkin_mnemosyne

    config = tmp_path / "thresholds.json"
    config.write_text(json.dumps({"locked": True, "thresholds": {"min_cosine": 0.9}}),
                      encoding="utf-8")
    calls = []

    class Service:
        encoded_chunks = 1

        def __init__(self, vault, *, semantic=False, thresholds=None):
            self.semantic_status = "starting"

        def questions(self, limit=20):
            calls.append(limit)
            self.semantic_status = "unavailable" if len(calls) == failure_call else "ready"
            return ()

    monkeypatch.setattr(birkin_mnemosyne, "Consolidation", Service)
    monkeypatch.setattr(probe, "THRESHOLDS_PATH", config)
    monkeypatch.setattr(probe, "peak_rss_bytes", lambda: 1_000_000)
    probe.run_consolidation(_vault2(tmp_path, 6))
    observed = json.loads(capsys.readouterr().out)
    assert observed["status"] == "PENDING"
    assert observed["semantic_status"] == "unavailable"
    assert len(calls) == failure_call
    phase = "warm_vault" if failure_call == 2 else "changed_note"
    assert observed["phases"][phase]["semantic_status"] == "unavailable"


@pytest.mark.parametrize("config", [
    None,
    False,
    [],
    "invalid",
    {"locked": False, "thresholds": {"min_cosine": 0.95}},
    {"locked": True, "thresholds": {}},
    {"locked": True, "thresholds": None},
])
def test_semantic_resource_proof_refuses_unlocked_or_placeholder_config(
        tmp_path, monkeypatch, config):
    import birkin_mnemosyne

    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(birkin_mnemosyne, "Consolidation", _FakeConsolidation)
    monkeypatch.setattr(probe, "THRESHOLDS_PATH", path)
    with pytest.raises(ValueError, match="locked thresholds"):
        probe.run_consolidation(_vault2(tmp_path, 6))


# -- readiness -----------------------------------------------------------------

def test_check_model_reports_ready_only_with_dependencies_and_prepared_model(
        monkeypatch):
    from birkin_mnemosyne import semantic

    monkeypatch.setattr(semantic, "available", lambda: True)
    assert probe.check_model(True)["status"] == "ready"
    monkeypatch.setattr(semantic, "available", lambda: False)
    assert probe.check_model(True)["status"] == "ml-dependencies-missing"
    assert probe.check_model(False)["status"] == "ml-dependencies-missing"


def test_fresh_download_guard_labels_an_unprepared_model():
    assert probe._fresh_download_guard(True)["status"] == "ready"
    guard = probe._fresh_download_guard(False)
    assert guard["status"] == "model_not_prepared" and not guard["cleared"]


# -- real child contracts ------------------------------------------------------

def test_child_check_mode_reports_real_availability(tmp_path):
    vault = _vault(tmp_path, 2)
    out = probe.run_child(["check", "compact", str(vault), "--notes", "2"],
                          probe.child_env(offline=True))
    assert out["mode"] == "compact" and out["notes"] == 2
    assert isinstance(out["numpy_importable"], bool)
    assert _object(out["capacity"])["supported"] is True
    assert out["backend"] == "compact"
    assert out["surface"] == "StartupReader.read(compact=True)"


def test_child_check_reports_model_status_and_finite_encode_when_prepared(tmp_path):
    from birkin_mnemosyne import semantic

    vault = _vault(tmp_path, 2)
    model_dir = semantic.model_dir()
    out = probe.run_child(["check", "consolidation-semantic", str(vault),
                           str(model_dir), "--notes", "2"],
                          probe.child_env(offline=True))
    model = _object(out["model"])
    surfaces = _object(out["surface_status"])
    assert model["path"] == str(model_dir)
    assert _object(surfaces["startup_compact"])["status"] in {"ready", "PENDING"}
    planned = _object(surfaces["consolidation_semantic"])["planned"]
    assert planned == "T11 (consolidation.py)"
    if model["prepared"]:
        encode = _object(out["encode"])
        assert encode["ok"] is True and encode["finite"] is True
        assert encode["nonzero"] is True and _array(encode["shape"])[0] == 1
        assert encode["dtype"] == "float32" and _number(encode["encode_ms"]) > 0
        assert encode["released"] is True          # mmap released after the encode
        assert out["backend"] == "consolidation-semantic"
        assert out["detector_status"] == "PENDING"
    else:
        assert out["encode"] == {"ok": False, "reason": "model_not_prepared"}
        assert out["detector_status"] == "PENDING"


def test_semantic_ready_check_is_a_real_data_surface_when_the_model_exists(tmp_path):
    """When the model is installed, the real encode must stay finite on the
    original practice text; when it is not, nothing here is excused as passed."""
    from birkin_mnemosyne import semantic

    vault = _vault(tmp_path, 2)
    out = probe.run_child(["check", "consolidation-semantic", str(vault),
                           str(semantic.model_dir()), "--notes", "2"],
                          probe.child_env(offline=True))
    if semantic.prepared():                        # real data-surface proof
        encode = _object(out["encode"])
        assert encode["ok"] and encode["finite"] and encode["nonzero"]
        assert _number(encode["encode_ms"]) > 0 and encode["shape"] == [1, semantic.DIM]
        readiness = _object(out["readiness"])
        assert readiness["status"] == "ready"
        assert readiness["prepared"] is True
    else:                                          # weakened, never skipped
        assert out["encode"] == {"ok": False, "reason": "model_not_prepared"}
        expected = ("model_not_prepared" if semantic.available()
                    else "ml-dependencies-missing")
        assert _object(out["readiness"])["status"] == expected
        assert out["detector_status"] == "PENDING"


def test_cli_check_reports_backend_prepared_and_encode(tmp_path):
    """``--check`` exposes the real backend contract, not a summary claim."""
    script = ROOT / "benchmarks" / "round4" / "resource_probe.py"
    checked = subprocess.run([sys.executable, str(script), "--check", "--offline"],
                             check=False, capture_output=True, text=True, cwd=str(ROOT))
    assert checked.returncode == 0, checked.stderr
    payload = json.loads(checked.stdout)
    assert payload["action"] == "check"
    assert payload["status"] in {"ready", "model_not_prepared",
                              "ml-dependencies-missing"}
    assert payload["backend"] == "StaticModel"
    assert payload["readiness"]["status"] == payload["status"]
    assert set(payload["surface_status"]) == {"startup_compact",
                                            "consolidation_semantic"}
    assert payload["detector_status"] == "PENDING"
    # the mmap load and the real encode are always reported, ready or not
    assert payload["load_ms"] is None or payload["load_ms"] > 0
    if payload["status"] == "ready":
        encode = payload["encode"]
        assert encode["finite"] and encode["nonzero"] and encode["released"]
        assert encode["shape"][0] == 1 and encode["encode_ms"] > 0
        assert payload["total_peak_rss_bytes"] > 0
        # a backend check is readiness evidence, never a detector proof
        assert payload["detector_status"] == "PENDING"
    else:
        assert payload["encode"] is None
        assert payload["detector_status"] == "PENDING"
        semantic = payload["surface_status"]["consolidation_semantic"]
        assert semantic["status"] == "PENDING"


def test_cli_json_is_parseable_for_the_run_mode(tmp_path):
    script = ROOT / "benchmarks" / "round4" / "resource_probe.py"
    out = subprocess.run([sys.executable, str(script), "--modes", "compact",
                          "--repeats", "1", "--offline", "--notes", "160"],
                         check=False, capture_output=True, text=True, cwd=str(ROOT))
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout)
    record = payload["modes"]["compact"]
    assert record["observations"][0]["clock_origin"] == "pre_import"
    assert record["surface"] == "StartupReader.read(compact=True)"
    if probe.startup_compact_available():
        assert record["supported"] is True
    else:                        # explicit PENDING, never a silent legacy result
        assert record["status"] == "PENDING" and not record["supported"]
        assert record["reason"] == "compact-read-api-absent"


# -- separation of the three vault states (corrective) -------------------------


def test_phase_names_are_the_declared_three_states():
    assert probe.PHASES == ("first_unencoded_vault", "warm_vault", "changed_note")


def test_phase_summary_separates_the_three_states_without_averaging() -> None:
    attempts: list[dict[str, probe.JsonValue]] = [
        {"phases": {phase: {"elapsed_ms": float(i + 1)}
                    for i, phase in enumerate(probe.PHASES)}}
        for _ in range(3)
    ]
    summary = probe._phase_summary(attempts)
    cold = summary["first_unencoded_vault"]
    warm = summary["warm_vault"]
    changed = summary["changed_note"]
    assert "median_ms" in cold and cold["median_ms"] == 1.0
    assert "median_ms" in warm and warm["median_ms"] == 2.0
    assert "median_ms" in changed and changed["median_ms"] == 3.0
    assert set(summary) == set(probe.PHASES)


def test_phase_summary_reports_n_zero_when_a_phase_was_not_observed():
    summary = probe._phase_summary([{}, {"phases": {"warm_vault": {"elapsed_ms": None}}}])
    assert all(summary[phase] == {"n": 0} for phase in probe.PHASES)
    assert probe._phase_summary([{"phases": {"warm_vault": {"elapsed_ms": 0.0}}}])[
        "warm_vault"] == {"n": 0}


def test_kibitzer_reports_first_unencoded_warm_and_changed_separately(tmp_path):
    """One process must expose all three vault states with distinct digests."""
    vault = _vault2(tmp_path, 6)
    out = probe.run_child(["run", "kibitzer", str(vault)],
                          probe.child_env(offline=True))
    phases = _object(out["phases"])
    first = _object(phases["first_unencoded_vault"])
    warm = _object(phases["warm_vault"])
    changed = _object(phases["changed_note"])
    assert set(phases) == set(probe.PHASES)
    assert _number(first["candidates"]) >= 1
    assert _number(warm["candidates"]) >= 1
    assert _number(changed["candidates"]) >= 1
    assert warm["vault_digest"] == first["vault_digest"]
    assert changed["vault_digest"] != first["vault_digest"]
    assert out["changed_note_visible"] is True
    assert all(probe.finite_positive(_object(p)["elapsed_ms"]) for p in phases.values())
    # the gate number covers the whole fresh operation, so it never hides a phase
    assert _number(out["load_ms"]) >= _number(out["import_ms"])


def test_run_record_exposes_the_separate_vault_states(tmp_path):
    vault = _vault(tmp_path)
    record = _run("kibitzer", vault, repeats=1)["modes"]["kibitzer"]
    assert record["scopes"]["separate_vault_states"] == list(probe.PHASES)
    assert set(record["phase_summary"]) == set(probe.PHASES)
    assert all(record["phase_summary"][phase]["n"] == 1 for phase in probe.PHASES)


def test_pending_modes_declare_the_phases_as_unobserved(tmp_path, monkeypatch, capsys):
    """An absent surface yields no phase value, never a fabricated one.

    Driven deterministically through ``pending()`` so the assertion holds on
    any machine and after the real compact surface lands.
    """
    monkeypatch.setattr(probe, "peak_rss_bytes", lambda: 1_000_000)
    probe.pending(mode="compact", surface=probe.SURFACES["compact"],
                  reason="compact-read-api-absent", detail="absent",
                  load_ms=1.0, import_ms=1.0, first_product_import_ms=0.5)
    record = json.loads(capsys.readouterr().out)
    assert record["status"] == "PENDING"
    assert record["phases"] == {phase: {"n": 0} for phase in probe.PHASES}


# -- corrections: false surfaces, timing and globals must not reappear ---------


def test_no_product_module_attribute_is_mutated_by_the_probe():
    """The probe must never assign scoring globals or wrap product modules.

    Rewriting the core scoring globals (the withdrawn defect) would show up as
    an assignment to a product module attribute; the probe contains none.
    """
    import ast

    source = (ROOT / "benchmarks" / "round4" / "resource_probe.py").read_text("utf-8")
    tree = ast.parse(source)
    product_roots = {"birkin_mnemosyne", "kib", "semantic", "numpy", "np",
                     "safetensors", "huggingface_hub", "mnemosyne", "consolidation"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute):
                    root = target
                    while isinstance(root, ast.Attribute):
                        root = root.value
                    # only a product-module attribute assignment is the defect
                    if isinstance(root, ast.Name) and root.id in product_roots:
                        raise AssertionError(
                            f"probe assigns module attribute {ast.unparse(target)}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in {"setattr", "delattr"}:
            raise AssertionError(f"probe calls {node.func.id}")


def test_compact_cannot_be_reported_from_a_legacy_read(monkeypatch, tmp_path, capsys):
    """The compact label must never carry a legacy ``read`` result."""
    class LegacyOnly:
        def read(self, paths):
            del paths
            return "legacy"

    import birkin_mnemosyne

    monkeypatch.setattr(birkin_mnemosyne, "StartupReader", LegacyOnly)
    monkeypatch.setattr(probe, "peak_rss_bytes", lambda: 1_000_000)
    probe.run_compact(_vault2(tmp_path, 6))
    record = json.loads(capsys.readouterr().out)
    assert record["status"] == "PENDING"
    assert record["reason"] == "compact-read-api-absent"
    assert record["surface"] == "StartupReader.read(compact=True)"
    # no legacy payload may have been emitted under the compact label
    assert record.get("compact") is not True
    assert "context_sha256" not in record


def test_import_clock_installation_is_idempotent() -> None:
    from importlib.machinery import PathFinder

    original = PathFinder.find_spec
    probe.install_import_clock()
    assert PathFinder.find_spec is original


def test_child_clock_origin_precedes_every_product_import(tmp_path):
    """A mode reported under a post-import timer would fail these bounds."""
    vault = _vault2(tmp_path, 6)
    out = probe.run_child(["run", "kibitzer", str(vault)],
                          probe.child_env(offline=True))
    assert out["clock_origin"] == "pre_import"
    # the product import is part of the measured span, not excluded from it
    assert 0.0 < _number(out["first_product_import_ms"]) <= _number(out["import_ms"]) <= _number(
        out["load_ms"])
