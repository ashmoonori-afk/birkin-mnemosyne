#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Round-4 resource contract, provenance and preparation driver (QA-5).

    python benchmarks/round4/resource_probe.py --prepare
    python benchmarks/round4/resource_probe.py --check [--model-dir DIR]
    python benchmarks/round4/resource_probe.py \
        --modes compact,kibitzer,consolidation-semantic --repeats 10 --offline

This module is both the driver and its own fresh-process child. ``--check`` and
``--modes`` import product code here, in the parent; the measured child
re-executes this same file as ``resource_probe.py __child ...`` and prints one
JSON line.

Measured modes (each in a fresh process, at a versioned note-count boundary -
160 and 1000 notes, 8 MiB of note bytes, 4096 spans):

``compact``
    the real ``birkin_mnemosyne.StartupReader.read(paths, compact=True)``
    surface. The clock starts before the child's *first product import* and
    covers the import, reader construction, the complete compact closure,
    verification and serialization. A legacy read is never measured under this
    label.
``kibitzer``
    note discovery and candidate selection with immediate visibility of
    changed notes (the per-vault cache is a fresh artifact and is removed).
``consolidation-semantic``
    the real semantic question surface, ``Consolidation(vault, semantic=True,
    thresholds=config)``. The mode is only measured when that surface reports
    ``semantic_status == "ready"``; otherwise it is reported as ``PENDING``.
    No lexical or retrieval substitute is ever measured under this label, and
    no scoring global is mutated.

The optional model is a *product runtime dependency*: ``--prepare`` reports
``was_prepared`` and never re-downloads or overwrites an existing cache. A
conversion is installation work and is always reported separately from
prepared startup.

``--check`` is a backend readiness check: dependency availability, prepared
model, real ``StaticModel`` load time, a finite/nonzero float encode of the
original practice text, total peak RSS and mmap release - labelled as a
backend check, never as a detector proof.

Every observation must carry finite positive measurements and the mode's own
evidence key; incomplete observations are dropped by ``_summary`` and made
fatal for bounds in the report, never silently averaged in.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

MODEL_NAME = "minishlab/potion-multilingual-128M"
MODES = ("compact", "kibitzer", "consolidation-semantic")
NOTE_BOUNDS = (160, 1000)
CHUNK_LIMIT = 4096
BYTE_LIMIT = 8 * 1024 * 1024
MODE_BOUNDS = {"compact": {"startup_ms": 1000},
               "kibitzer": {"startup_ms": 1000, "peak_rss_bytes": 150_000_000},
               "consolidation-semantic": {"startup_ms": 1000,
                                          "total_peak_rss_bytes": 150_000_000}}
CORE_OPTIONAL_MODULES = ("numpy", "safetensors", "huggingface_hub")
THRESHOLDS_PATH = HERE / "detection-thresholds.json"
SURFACES = {"compact": "StartupReader.read(compact=True)",
            "kibitzer": "KibitzerAdapter.select",
            "consolidation-semantic": "Consolidation(semantic=True)"}
EVIDENCE_KEYS: dict[str, tuple[tuple[str, str], ...]] = {
    "compact": (("context_sha256", "digest"),),
    "kibitzer": (("candidates", "count"),),
    "consolidation-semantic": (("encoded_chunks", "count"),
                              ("semantic_status", "ready"))}
PRODUCT_MARKERS = ("birkin_mnemosyne", "numpy", "safetensors", "huggingface_hub")

PRACTICE_NOTE_TITLE = "Release gate policy"
PRACTICE_NOTE = (
    "Every production release waits for a plain-language approval from the "
    "release owner, and the approval must arrive before the artifacts are "
    "published; when a defect is found after publication the rollback window "
    "stays open for one hour, during which the deployment can be reverted "
    "without a second review."
)
PRACTICE_QUERY = "release approval rollback window"
PRACTICE_TEXT = f"{PRACTICE_NOTE_TITLE}\n{PRACTICE_NOTE}"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def supported(api: Any, attribute: str = "") -> bool:
    """Whether the planned product surface exists at all.

    The compact startup read and the semantic Consolidation integration are
    product work (T6/T11) that does not exist at the protocol base. Their modes
    must report an explicit ``PENDING`` naming the missing surface - never a
    legacy or lexical substitute under the same label.
    """
    import inspect

    required = _required(api, attribute)
    if not required:                      # no such planned surface at all
        return False
    target = api if attribute == "" else getattr(api, attribute, None)
    if target is None:
        return False
    try:
        parameters = inspect.signature(target).parameters
    except (TypeError, ValueError):
        return False
    return all(name in parameters for name in required)


def _required(api: Any, attribute: str = "") -> tuple[str, ...]:
    name = getattr(api, "__name__", "") if attribute == "" else attribute
    if attribute == "read" or name == "read":
        return ("compact",)
    if attribute == "questions":
        return ("limit",)
    if name == "__init__" or name.startswith("Consolidation"):
        return ("semantic", "thresholds")
    return ()


def startup_compact_available(reader_cls: Any | None = None) -> bool:
    if reader_cls is None:
        from birkin_mnemosyne import StartupReader as reader_cls
    return supported(reader_cls, "read")


def questions_carry_status(questions: Any) -> bool:
    """True when the object owning ``questions()`` can report a ready status."""
    return hasattr(questions, "semantic_status")


def consolidation_semantic_available(consolidation_cls: Any | None = None) -> bool:
    if consolidation_cls is None:
        from birkin_mnemosyne import Consolidation as consolidation_cls
    return (supported(consolidation_cls, "__init__")
            and supported(consolidation_cls, "questions"))


# -- shared contracts ----------------------------------------------------------

def capacity(notes: int, chunks: int, total_bytes: int) -> dict[str, Any]:
    """Declared supported input contract; exceeding it refuses, never truncates."""
    return {"notes": notes, "chunks": chunks, "total_bytes": total_bytes,
            "notes_limit": 1000, "chunk_limit": CHUNK_LIMIT, "byte_limit": BYTE_LIMIT,
            "supported": notes <= 1000 and chunks <= CHUNK_LIMIT
            and total_bytes <= BYTE_LIMIT}


def finite_positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and \
        math.isfinite(float(value)) and float(value) > 0


def observation_errors(observation: dict[str, Any]) -> list[str]:
    """Why an observation may not enter a bound claim; empty means usable."""
    missing: list[str] = []
    for key in ("load_ms", "peak_rss_bytes", "import_ms"):
        if not finite_positive(observation.get(key)):
            missing.append(key)
    mode = observation.get("mode")
    evidence = EVIDENCE_KEYS.get(mode) if isinstance(mode, str) else None
    if evidence is None:
        return [*missing, "mode"]
    if observation.get("status") == "PENDING":
        return missing
    for key, kind in evidence:
        present = observation.get(key)
        if kind == "ready":
            if present != "ready":
                missing.append(key)
        elif kind == "digest":
            if not isinstance(present, str) or len(present) < 8:
                missing.append(key)
        elif not finite_positive(present):
            missing.append(key)
    return missing


def _new_product_findings(encode: dict[str, Any]) -> list[str]:
    """Refuse an encode that is not finite, not nonzero, or all zeros."""
    findings: list[str] = []
    if encode.get("finite") is not True:
        findings.append("finite")
    if encode.get("nonzero") is not True:
        findings.append("nonzero")
    if not any(finite_positive(v) for v in encode.get("values", [])):
        findings.append("values")
    return findings


# -- practice vault ------------------------------------------------------------

def _frontmatter(title: str, body: str, source: str) -> str:
    return (f"---\ntitle: {title}\ntype: topic\ncreated: 2026-10-02\n"
            f"source: {source}\n---\n\n{body}\n")


def write_practice_vault(vault: Path, notes: int) -> Path:
    """Deterministic, original practice vault (no frozen material).

    Always contains the startup sources and the discoverable duplicate pair,
    plus filler notes so runs are reproducible byte-for-byte at a given count.
    """
    vault.mkdir(parents=True, exist_ok=True)
    _ = (vault / "MODE.md").write_text(
        "# Boot\nMUST READ: handoff.md\nMUST READ: profile/soul.md\n"
        "MUST READ: registry.json\npending: capture the release receipt\n",
        encoding="utf-8")
    _ = (vault / "handoff.md").write_text(
        "TOP NOTE 2026-09-01\nPort: 4100\n"
        "TOP NOTE 2026-10-01\nSupersedes: TOP NOTE 2026-09-01\nPort: 4200\n",
        encoding="utf-8")
    (vault / "profile").mkdir(exist_ok=True)
    _ = (vault / "profile" / "soul.md").write_text(
        "# Soul\nMUST READ: human.md\nVoice: direct\n", encoding="utf-8")
    _ = (vault / "profile" / "human.md").write_text(
        "# Human\nApproval: publication requires consent\n", encoding="utf-8")
    _ = (vault / "registry.json").write_text(
        '{"jobs":[{"state":"active","pending":"capture CI receipt"}]}\n',
        encoding="utf-8")
    (vault / "knowledge").mkdir(exist_ok=True)
    _ = (vault / "knowledge" / "release-gate.md").write_text(
        _frontmatter(PRACTICE_NOTE_TITLE, PRACTICE_NOTE, "user:practice"),
        encoding="utf-8")
    _ = (vault / "knowledge" / "release-rollback.md").write_text(
        _frontmatter("Rollback window", PRACTICE_NOTE, "user:practice"),
        encoding="utf-8")
    for i in range(max(0, notes - 6)):   # 4 startup sources + the duplicate pair
        filler = (f"Topic {i} records fictional background detail {i} about "
                  "routine operations and unrelated reference material. ")
        _ = (vault / "knowledge" / f"filler-{i:04d}.md").write_text(
            _frontmatter(f"Filler topic {i}", filler * 3, f"user:practice-{i}"),
            encoding="utf-8")
    return vault


def scratch_paths(vault: Path) -> list[Path]:
    """Per-vault cache artifacts created by a probe run and removed after it."""
    return [vault / ".mnemosyne-index.json", vault / ".mnemosyne-index.json.z",
            vault / ".mnemosyne-vectors.npz", vault / ".mnemosyne-mcp.lock"]


def child_env(offline: bool, model_dir: Path | None = None) -> dict[str, str]:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(
        filter(None, [str(ROOT), os.environ.get("PYTHONPATH")]))}
    if offline:
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                     "HF_HUB_OFFLINE", "HF_ENDPOINT"):
            _ = env.pop(name, None)
        env["HF_HUB_OFFLINE"] = "1"
        env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    if model_dir is not None:
        # scope a copy of the model cache so a conversion can never be touched
        env["MNEMOSYNE_MODEL_CACHE"] = str(Path(model_dir).parent)
    return env


def run_child(args: list[str], env: dict[str, str]) -> dict[str, Any]:
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                           "__child", *args],
                          check=False, capture_output=True, text=True,
                          env=env, cwd=str(ROOT))
    if proc.returncode != 0:
        tail = proc.stderr.strip()[-800:]
        raise RuntimeError(f"probe child failed ({proc.returncode}): {tail}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


# -- readiness -----------------------------------------------------------------

def _check_prepared(model_dir: Path | None) -> bool:
    if model_dir is not None:
        return (Path(model_dir) / "meta.json").is_file()
    from birkin_mnemosyne import semantic

    return semantic.prepared()


def dependency_state(model_dir: Path | None = None) -> dict[str, Any]:
    from birkin_mnemosyne import semantic

    scoped = Path(model_dir) if model_dir is not None else semantic.model_dir()
    return {"available": semantic.available(),
            "prepared": (scoped / "meta.json").is_file(),
            "model_dir": str(scoped)}


def check_model(prepared: bool) -> dict[str, Any]:
    """Ready means: dependencies importable and the compact model converted."""
    from birkin_mnemosyne import semantic

    if not semantic.available():
        name = "ml-dependencies-missing"
    elif prepared:
        name = "ready"
    else:
        name = "model_not_prepared"
    return {"status": name, "available": semantic.available(), "prepared": prepared,
            "model_dir": str(semantic.model_dir())}


def _fresh_download_guard(prepared: bool, model_dir: Path | None) -> dict[str, Any]:
    """Semantic status when the model was absent: never a silent ready claim."""
    if prepared:
        return {"status": "ready", "cleared": True}
    return {"status": "model_not_prepared", "cleared": False,
            "detail": "no compact model present; run --prepare (or an explicit "
                      "`python -m birkin_mnemosyne.semantic`) before measuring; "
                      "an absent model is not a pass"}


def _summary(observations: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [float(o[key]) for o in observations
              if check_key(o.get(key)) and not o.get("defects")]
    if not values:
        return {"n": 0}
    return {"n": len(values), "min_ms": round(min(values), 3),
            "median_ms": round(statistics.median(values), 3),
            "max_ms": round(max(values), 3)}


def check_key(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and \
        math.isfinite(float(value))


PHASES = ("first_unencoded_vault", "warm_vault", "changed_note")


def _phase_summary(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-vault-state timing summary, kept separate from the gate number.

    An attempt only contributes to a phase when that phase was actually
    observed with a finite positive elapsed time; a PENDING or partial attempt
    yields ``n: 0`` for the phase rather than a fabricated value.
    """
    summary: dict[str, Any] = {}
    for phase in PHASES:
        values = [float(a["phases"][phase]["elapsed_ms"]) for a in attempts
                  if isinstance(a.get("phases"), dict)
                  and isinstance(a["phases"].get(phase), dict)
                  and finite_positive(a["phases"][phase].get("elapsed_ms"))]
        summary[phase] = ({"n": len(values), "min_ms": round(min(values), 3),
                           "median_ms": round(statistics.median(values), 3),
                           "max_ms": round(max(values), 3)}
                          if values else {"n": 0})
    return summary


# -- measurement ---------------------------------------------------------------

def measure_mode(mode: str, vault: Path, model_dir: Path | None, repeats: int,
                 env: dict[str, str]) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for _ in range(repeats):
        extra = [str(model_dir)] if model_dir else []
        attempt = run_child(["run", mode, str(vault), *extra], env)
        defects = observation_errors(attempt)
        attempt["defects"] = defects
        attempts.append(attempt)
    usable = [a for a in attempts
              if a.get("status") != "PENDING" and not a["defects"]
              and (mode != "consolidation-semantic"
                   or a.get("semantic_status") == "ready")]
    if attempts and all(a.get("status") == "PENDING" for a in attempts):
        first = attempts[0]
        return {"mode": mode, "status": "PENDING", "reason": first["reason"],
                "reason_status": first.get("semantic_status"),
                "detail": first["detail"], "surface": SURFACES[mode],
                "planned": first.get("planned"),
                "scopes": {"fresh_process": True, "prepared_startup": mode != "compact",
                           "includes_first_unencoded_vault": True,
                           "separate_vault_states": list(PHASES)},
                "observations": attempts, "startup_ms": _summary(attempts, "load_ms"),
                "import_ms": _summary(attempts, "import_ms"),
                "phase_summary": _phase_summary(attempts),
                "usable_observations": 0, "bounds_met": False}
    result: dict[str, Any] = {
        "mode": mode, "repeats": repeats, "usable_observations": len(usable),
        "observations": attempts,
        "phase_summary": _phase_summary(usable),
        "startup_ms": _summary(usable, "load_ms"),
        "import_ms": _summary(usable, "import_ms"),
        "max_peak_rss_bytes": max((a["peak_rss_bytes"] for a in usable), default=None),
        "total_peak_rss_bytes": max((a["peak_rss_bytes"] for a in usable),
                                    default=None),
        "bounds_met": len(usable) == repeats and bool(usable) and all(
            not a["defects"] and a["load_ms"] <= MODE_BOUNDS[mode]["startup_ms"]
            and a["peak_rss_bytes"] <= 150_000_000 for a in attempts),
        "surface": SURFACES[mode],
        "scopes": {"fresh_process": True,
                   "prepared_startup": mode != "compact",
                   "includes_first_unencoded_vault": mode == "consolidation-semantic",
                   "separate_vault_states": ["first_unencoded_vault", "warm_vault",
                                             "changed_note"]}}
    if mode == "consolidation-semantic":
        result["chunks"] = max((a["encoded_chunks"] for a in usable), default=None)
        result["semantic_status"] = max((a["semantic_status"] for a in usable),
                                         default=None)
    if len(usable) != repeats:
        result.update({"status": "PENDING", "reason": "incomplete-observations",
                       "detail": "Not every requested attempt produced ready usable evidence"})
    return result


def run_probe(args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    unknown = [m for m in modes if m not in MODES]
    if unknown:
        raise SystemExit(f"unknown modes: {unknown}; expected {MODES}")
    dependency = dependency_state(args.model_dir)
    results: dict[str, Any] = {"dependencies": dependency,
                     "prepared": dependency["prepared"],
                     "repeats": args.repeats, "offline": args.offline,
                     "bounds": {"startup_ms": 1000,
                                "total_peak_rss_bytes": 150_000_000},
                     "model_name": MODEL_NAME, "modes": {}, "cleanup": []}
    with tempfile.TemporaryDirectory(prefix="mnemosyne-r4-resource-") as directory:
        workspace = Path(directory)
        for mode in modes:
            if mode == "consolidation-semantic" and not dependency["prepared"]:
                results["modes"][mode] = {
                    "mode": mode, "status": "PENDING", "reason": "model_not_prepared",
                    "detail": "run --prepare first; an absent model is not a pass",
                    "surface": SURFACES[mode],
                    "scopes": {"fresh_process": True, "prepared_startup": True,
                               "includes_first_unencoded_vault": True,
                               "separate_vault_states": list(PHASES)},
                    "phase_summary": {phase: {"n": 0} for phase in PHASES},
                    "observations": [], "usable_observations": 0,
                    "bounds_met": False}
                continue
            vault = workspace / mode
            _ = write_practice_vault(vault, args.notes)
            bytes_total = sum(p.stat().st_size for p in vault.rglob("*.md"))
            semantic_mode = mode == "consolidation-semantic"
            model_dir = Path(str(dependency["model_dir"])) if semantic_mode else None
            child = child_env(args.offline, model_dir)
            checked = run_child(["check", mode, str(vault)]
                                + ([str(model_dir)] if model_dir else [])
                                + ["--notes", str(args.notes)], child)
            record = measure_mode(mode, vault, model_dir, args.repeats, child)
            record["capacity"] = checked["capacity"]
            record["bytes"] = bytes_total
            record["supported"] = checked["capacity"]["supported"]
            if record.get("status") == "PENDING":
                record["supported"] = False
                record["capacity"]["supported"] = False
            results["modes"][mode] = record
        residue = [str(p) for p in workspace.rglob("*") if p.is_file()
                   and p.name.startswith(".mnemosyne")]
        results["cleanup"].append({"residue_files": residue,
                                   "vault_cache_removed": not residue})
        if args.keep_vaults:
            results["cleanup"].append({"workspace_retained": directory})
    results["cleanup"].append({"scoped_env": ["MNEMOSYNE_MODEL_CACHE"],
                               "note": "the user model cache is never "
                                       "overwritten or re-deleted"})
    return results


# -- backend check (parent) ----------------------------------------------------

def backend_check(model_dir: Path | None) -> dict[str, Any]:
    """Real prepared-model load and finite encode, labelled as a backend check.

    The child process guarantees the mmap is released at exit; the encode is
    performed on the original practice text only and requires no network.
    The compact reader and the semantic Consolidation are *product* surfaces
    (planned T6/T11) that do not exist at the protocol base: their readiness
    is reported explicitly as PENDING, never as a substituted pass.
    """
    prepared = _check_prepared(model_dir)
    status = check_model(prepared)
    from birkin_mnemosyne import Consolidation, StartupReader

    surface_status = {
        "startup_compact": {
            "status": "ready" if startup_compact_available(StartupReader)
            else "PENDING",
            "required": "StartupReader.read(paths, compact=True)",
            "planned": "T6 (startup.py)",
            "reason": None if startup_compact_available(StartupReader)
            else "compact-read-api-absent"},
        "consolidation_semantic": {
            "status": "ready" if consolidation_semantic_available(Consolidation)
            else "PENDING",
            "required": "Consolidation(vault, semantic=True, thresholds=config)",
            "planned": "T11 (consolidation.py)",
            "reason": None if consolidation_semantic_available(Consolidation)
            else "semantic-consolidation-api-absent"}}
    report: dict[str, Any] = {
        "action": "check", "backend": "StaticModel",
        "surface": "StaticModel.encode", "surface_status": surface_status,
        "detector_status": "PENDING",
        "detector_note": "backend readiness only; the semantic question detector "
                         "and its frozen evaluation are future product work",
        **status, "readiness": {**status, "model_dir": str(
            Path(model_dir) if model_dir is not None else status["model_dir"])},
        **_fresh_download_guard(prepared, model_dir)}
    report["model_dir"] = report["readiness"]["model_dir"]
    vault = Path(tempfile.mkdtemp(prefix="mnemosyne-r4-check-"))
    try:
        _ = write_practice_vault(vault, 2)
        env = child_env(True, model_dir)
        out = run_child(["check", "consolidation-semantic", str(vault),
                         str(report["model_dir"]), "--notes", "2"], env)
        report["load_ms"] = out["load_ms"]
        report["total_peak_rss_bytes"] = out["peak_rss_bytes"]
        report["surface_status"] = out["surface_status"]
        report["encode"] = out["encode"] if prepared else None
        report["encode_findings"] = (_new_product_findings(out["encode"])
                                     if prepared else [])
    finally:
        for artifact in scratch_paths(vault):
            artifact.unlink(missing_ok=True)
        import shutil

        shutil.rmtree(vault, ignore_errors=True)
        report["vault_removed"] = not vault.exists()
    return report


# -- child ---------------------------------------------------------------------

def _surface_name(module: str) -> str:
    return SURFACES.get(module, module)


def child_check(mode: str, vault: Path, model_dir: Path | None, notes: int) -> None:
    from birkin_mnemosyne import Consolidation, StartupReader

    out: dict[str, Any] = {"mode": mode, "backend": mode, "vault": str(vault),
                 "notes": notes, "surface": _surface_name(mode),
                 "detector_status": "PENDING",
                 "surface_status": {
                     "startup_compact": {
                         "status": "ready" if startup_compact_available(StartupReader)
                         else "PENDING",
                         "required": "StartupReader.read(paths, compact=True)",
                         "planned": "T6 (startup.py)"},
                     "consolidation_semantic": {
                         "status": "ready" if consolidation_semantic_available(
                             Consolidation) else "PENDING",
                         "required": "Consolidation(vault, semantic=True, "
                                     "thresholds=config)",
                         "planned": "T11 (consolidation.py)"}},
                 "capacity": capacity(notes, 1, vault_bytes(vault))}
    out["numpy_importable"] = importable("numpy")
    out["readiness"] = check_model(
        model_dir is None or (model_dir / "meta.json").is_file())
    if mode == "consolidation-semantic":
        model = model_dir or Path(out["readiness"]["model_dir"])
        out["model"] = {"path": str(model), "prepared": (model / "meta.json").is_file(),
                        "files_present": sorted(p.name for p in model.glob("*"))
                        if model.is_dir() else []}
        if out["model"]["prepared"]:
            start = time.perf_counter()
            encode = encode_probe(model)
            out["load_ms"] = (time.perf_counter() - start) * 1000.0
            out["encode"] = encode
            out["encode_findings"] = _new_product_findings(encode)
        else:
            out["load_ms"] = None
            out["encode"] = {"ok": False, "reason": "model_not_prepared"}
            out["encode_findings"] = ["model_not_prepared"]
    else:
        out["load_ms"] = None
        out["encode"] = None
    out["peak_rss_bytes"] = peak_rss_bytes()
    print(json.dumps(out, ensure_ascii=True))


def importable(name: str) -> bool:
    """True when ``name`` imports; a broken install is reported, not hidden."""
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def vault_bytes(vault: Path) -> int:
    return sum(p.stat().st_size for p in vault.rglob("*.md"))


def encode_probe(model_dir: Path) -> dict[str, Any]:
    """Encode the original practice text once with the real prepared model."""
    import numpy as np

    from birkin_mnemosyne.static_model import StaticModel

    model = StaticModel(model_dir)
    start = time.perf_counter()
    vec = model.encode([PRACTICE_TEXT])
    elapsed = (time.perf_counter() - start) * 1000.0
    finite = bool(np.isfinite(vec).all())
    nonzero = bool(np.any(vec))
    values = [float(v) for v in vec[0][:8].tolist()] if finite else []
    model.release()
    return {"ok": finite and nonzero,
            "finite": finite, "nonzero": nonzero,
            "dtype": str(vec.dtype), "shape": list(vec.shape),
            "values": values,
            "released": model._table is None,
            "encode_ms": elapsed,
            "text_bytes": len(PRACTICE_TEXT.encode("utf-8"))}


def run_compact(root: Path) -> None:
    start, imported = clock_at_first_import()
    from birkin_mnemosyne import StartupReader  # the import a real caller pays

    mark = time.perf_counter()
    if not startup_compact_available(StartupReader):
        pending(mode="compact", surface=SURFACES["compact"],
                reason="compact-read-api-absent", planned="T6 (startup.py)",
                detail="StartupReader.read must accept compact=True (planned T6 in "
                       "startup.py); a legacy read is never measured under this label",
                load_ms=(time.perf_counter() - start) * 1000.0,
                import_ms=(mark - start) * 1000.0,
                first_product_import_ms=(imported - start) * 1000.0)
        return
    reader = StartupReader(root)
    cold_digest = vault_digest(root)
    phase_start = time.perf_counter()
    bundle = reader.read(["MODE.md"], compact=True)
    cold_ms = (time.perf_counter() - phase_start) * 1000.0
    text = bundle.context
    phase_start = time.perf_counter()
    warm_bundle = reader.read(["MODE.md"], compact=True)
    warm_ms = (time.perf_counter() - phase_start) * 1000.0
    changed_path = root / "handoff.md"
    _ = changed_path.write_text(changed_path.read_text("utf-8") + "\nPort: 4300\n",
                            encoding="utf-8")
    changed_digest = vault_digest(root)
    phase_start = time.perf_counter()
    changed_bundle = reader.read(["MODE.md"], compact=True)
    changed_ms = (time.perf_counter() - phase_start) * 1000.0
    elapsed = (time.perf_counter() - start) * 1000.0
    phases = {
        "first_unencoded_vault": {"elapsed_ms": cold_ms,
                                  "context_sha256": digest(text),
                                  "vault_digest": cold_digest},
        "warm_vault": {"elapsed_ms": warm_ms,
                       "context_sha256": digest(warm_bundle.context),
                       "vault_digest": cold_digest},
        "changed_note": {"elapsed_ms": changed_ms,
                         "context_sha256": digest(changed_bundle.context),
                         "vault_digest": changed_digest}}
    print(json.dumps({"mode": "compact", "surface": SURFACES["compact"],
                      "compact": True, "load_ms": elapsed,
                      "import_ms": (mark - start) * 1000.0,
                      "first_product_import_ms": (imported - start) * 1000.0,
                      "clock_origin": "pre_import",
                      "peak_rss_bytes": peak_rss_bytes(),
                      "context_characters": len(text),
                      "context_bytes": len(text.encode("utf-8")),
                      "context_sha256": digest(text),
                      "phases": phases,
                      "changed_note_visible": changed_bundle.context != text,
                      "cache_hit": bundle.cache_hit,
                      "coverage_complete": bundle.coverage.complete,
                      "tokenizer_loaded": "tiktoken" in sys.modules},
                     ensure_ascii=True))


# clock state: both values precede every product import in the child
_clock: dict[str, float] = {"origin": time.perf_counter(), "first_import": math.inf}


def clock_at_first_import() -> tuple[float, float]:
    """(timer origin, first product import). Both precede any product import."""
    return _clock["origin"], _clock["first_import"]


def run_kibitzer(vault: Path) -> None:
    """Three separately timed phases on one fresh process.

    ``first_unencoded_vault`` runs before any index artifact exists;
    ``warm_vault`` repeats the identical selection against the warm in-process
    cache; ``changed_note`` mutates one note on disk and selects again, proving
    the new bytes are discovered in the same process. Each phase carries its
    own elapsed time and vault digest so a reader can never average them into
    one ambiguity. ``load_ms`` stays BOTH the gate number (first unencoded
    discovery) and the sum of the three phase observations, so no phase is
    silently excluded from the reported startup cost.
    """
    start, imported = clock_at_first_import()
    from birkin_mnemosyne import kibitzer as kib

    mark = time.perf_counter()
    adapter = kib.KibitzerAdapter(vault)
    import_ms = (mark - start) * 1000.0

    cold_digest = vault_digest(vault)
    phase_start = time.perf_counter()
    cold = adapter.select(PRACTICE_QUERY, limit=3)
    cold_ms = (time.perf_counter() - phase_start) * 1000.0

    phase_start = time.perf_counter()
    warm = adapter.select(PRACTICE_QUERY, limit=3)
    warm_ms = (time.perf_counter() - phase_start) * 1000.0

    changed_path = vault / "knowledge" / "release-gate.md"
    _ = changed_path.write_text(
        changed_path.read_text("utf-8") + "\nThe freeze window is two hours.\n",
        encoding="utf-8")
    changed_digest = vault_digest(vault)
    phase_start = time.perf_counter()
    changed = adapter.select(PRACTICE_QUERY, limit=3)
    changed_ms = (time.perf_counter() - phase_start) * 1000.0

    elapsed = (time.perf_counter() - start) * 1000.0
    phases = {
        "first_unencoded_vault": {"elapsed_ms": cold_ms, "candidates": len(cold),
                                  "vault_digest": cold_digest},
        "warm_vault": {"elapsed_ms": warm_ms, "candidates": len(warm),
                       "vault_digest": cold_digest},
        "changed_note": {"elapsed_ms": changed_ms, "candidates": len(changed),
                         "vault_digest": changed_digest}}
    print(json.dumps({"mode": "kibitzer", "surface": SURFACES["kibitzer"],
                      "load_ms": elapsed,
                      "import_ms": import_ms,
                      "first_product_import_ms": (imported - start) * 1000.0,
                      "clock_origin": "pre_import",
                      "peak_rss_bytes": peak_rss_bytes(),
                      "candidates": len(cold),
                      "vault_digest": cold_digest,
                      "phases": phases,
                      "changed_note_visible": changed_digest != cold_digest,
                      "bm25_imported": "birkin_mnemosyne.mnemosyne" in sys.modules},
                     ensure_ascii=True))


def vault_digest(vault: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(vault.rglob("*.md")):
        hasher.update(path.relative_to(vault).as_posix().encode("utf-8"))
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def run_consolidation(vault: Path, model_dir: Path) -> None:
    start, imported = clock_at_first_import()
    from birkin_mnemosyne import Consolidation

    mark = time.perf_counter()
    if not consolidation_semantic_available(Consolidation):
        pending(mode="consolidation-semantic",
                surface=SURFACES["consolidation-semantic"],
                reason="semantic-consolidation-api-absent",
                planned="T11 (consolidation.py)",
                detail="Consolidation must accept semantic=True and thresholds=<locked "
                       "config> and expose a ready status (planned T11 in "
                       "consolidation.py); a lexical or retrieval substitute is never "
                       "measured under this label",
                load_ms=(time.perf_counter() - start) * 1000.0,
                import_ms=(mark - start) * 1000.0,
                first_product_import_ms=(imported - start) * 1000.0)
        return
    if not THRESHOLDS_PATH.is_file():
        pending(mode="consolidation-semantic",
                surface=SURFACES["consolidation-semantic"],
                reason="locked-thresholds-absent", planned="T12 (calibrate.py)",
                detail="Practice-calibrated locked thresholds are required; "
                       "placeholder values are never passed to the detector",
                load_ms=(time.perf_counter() - start) * 1000.0,
                import_ms=(mark - start) * 1000.0,
                first_product_import_ms=(imported - start) * 1000.0)
        return
    config = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
    thresholds = config.get("thresholds")
    if config.get("locked") is not True or not isinstance(thresholds, dict) or not thresholds:
        raise ValueError("semantic resource proof requires a locked thresholds config")
    cold_digest = vault_digest(vault)
    cons = Consolidation(vault, semantic=True, thresholds=thresholds)
    phase_start = time.perf_counter()
    result = cons.questions()          # first unencoded vault: encodes every note
    cold_ms = (time.perf_counter() - phase_start) * 1000.0
    phases: dict[str, Any] = {"first_unencoded_vault":
                             {"elapsed_ms": cold_ms, "vault_digest": cold_digest}}
    if not questions_carry_status(cons):
        pending(mode="consolidation-semantic",
                surface=SURFACES["consolidation-semantic"],
                reason="semantic-status-absent", planned="T11 (consolidation.py)",
                semantic_status="missing",
                detail="Consolidation exposes no ready detection status; the semantic "
                       "resource leg is not proven",
                load_ms=(time.perf_counter() - start) * 1000.0,
                import_ms=(mark - start) * 1000.0,
                first_product_import_ms=(imported - start) * 1000.0)
        return
    status = str(cons.semantic_status)
    phases["first_unencoded_vault"]["semantic_status"] = status
    if status != "ready":
        pending(mode="consolidation-semantic",
                surface=SURFACES["consolidation-semantic"],
                reason="semantic-not-ready", semantic_status=status or "missing",
                detail="the real semantic Consolidation did not report a ready "
                       "detection status; the resource leg is not proven",
                load_ms=(time.perf_counter() - start) * 1000.0,
                import_ms=(mark - start) * 1000.0,
                first_product_import_ms=(imported - start) * 1000.0)
        return
    raw_questions = getattr(result, "questions", result)
    questions = raw_questions if isinstance(raw_questions, (list, tuple)) else result
    encoded_chunks = int(getattr(result, "encoded_chunks", 0) or
                         getattr(cons, "encoded_chunks", 0))

    phase_start = time.perf_counter()
    warm = cons.questions()
    warm_ms = (time.perf_counter() - phase_start) * 1000.0
    status = str(getattr(cons, "semantic_status", "missing"))
    phases["warm_vault"] = {"elapsed_ms": warm_ms, "vault_digest": cold_digest,
                           "semantic_status": status}
    if status != "ready":
        pending(mode="consolidation-semantic", surface=SURFACES["consolidation-semantic"],
                reason="semantic-not-ready", semantic_status=status, phases=phases,
                detail="Warm discovery did not retain a ready semantic service",
                load_ms=(time.perf_counter() - start) * 1000.0,
                import_ms=(mark - start) * 1000.0,
                first_product_import_ms=(imported - start) * 1000.0)
        return

    changed_path = vault / "knowledge" / "release-gate.md"
    _ = changed_path.write_text(
        changed_path.read_text("utf-8") + "\nThe freeze window is two hours.\n",
        encoding="utf-8")
    changed_digest = vault_digest(vault)
    phase_start = time.perf_counter()
    changed = cons.questions()
    changed_ms = (time.perf_counter() - phase_start) * 1000.0
    status = str(getattr(cons, "semantic_status", "missing"))
    phases["changed_note"] = {"elapsed_ms": changed_ms,
                              "vault_digest": changed_digest,
                              "semantic_status": status,
                              "questions": len(changed)
                              if hasattr(changed, "__len__") else None}
    if status != "ready":
        pending(mode="consolidation-semantic", surface=SURFACES["consolidation-semantic"],
                reason="semantic-not-ready", semantic_status=status, phases=phases,
                detail="Changed-note discovery did not retain a ready semantic service",
                load_ms=(time.perf_counter() - start) * 1000.0,
                import_ms=(mark - start) * 1000.0,
                first_product_import_ms=(imported - start) * 1000.0)
        return

    elapsed = (time.perf_counter() - start) * 1000.0
    print(json.dumps({"mode": "consolidation-semantic",
                      "surface": SURFACES["consolidation-semantic"],
                      "semantic_status": status,
                      "load_ms": elapsed,
                      "import_ms": (mark - start) * 1000.0,
                      "first_product_import_ms": (imported - start) * 1000.0,
                      "clock_origin": "pre_import",
                      "peak_rss_bytes": peak_rss_bytes(),
                      "notes": sum(path.is_file() for path in vault.rglob("*.md")),
                      "encoded_chunks": encoded_chunks,
                      "questions": len(questions),
                      "phases": phases,
                      "changed_note_visible": changed_digest != cold_digest,
                      "warm_questions": len(warm) if hasattr(warm, "__len__") else None,
                      "thresholds": thresholds,
                      "optional_imports": [m for m in sys.modules if m in
                                           CORE_OPTIONAL_MODULES]},
                     ensure_ascii=True))


def pending(*, mode: str, surface: str, reason: str, detail: str,
            load_ms: float, import_ms: float, first_product_import_ms: float,
            **extra: Any) -> None:
    """A mode whose real product surface does not exist yet: explicit PENDING.

    The three vault states are declared but remain ``n: 0`` in the phase
    summary: an absent surface yields no phase observation, never a fabricated
    one.
    """
    print(json.dumps({"mode": mode, "status": "PENDING", "surface": surface,
                      "reason": reason, "detail": detail,
                      "load_ms": load_ms, "import_ms": import_ms,
                      "first_product_import_ms": first_product_import_ms,
                      "clock_origin": "pre_import",
                      "phases": {phase: {"n": 0} for phase in PHASES},
                      "peak_rss_bytes": peak_rss_bytes(), **extra},
                     ensure_ascii=True))


def run_child_command(args: argparse.Namespace) -> None:
    """Entry point of the fresh child: parse args, load the RSS helper, then
    start the product clock."""
    start_child_clock()
    from benchmarks.retrieval._probe import peak_rss_bytes as helper

    globals()["peak_rss_bytes"] = helper
    _record_first_import("birkin_mnemosyne")   # the product work is about to start
    if args.command == "check":
        child_check(args.mode, args.target, args.model_dir, args.notes)
        return
    if args.mode == "compact":
        run_compact(args.target)
    elif args.mode == "kibitzer":
        run_kibitzer(args.target)
        for path in scratch_paths(args.target):
            path.unlink(missing_ok=True)
    elif args.mode == "consolidation-semantic":
        if args.model_dir is None:
            raise SystemExit("consolidation-semantic requires a model directory")
        run_consolidation(args.target, args.model_dir)
        for path in scratch_paths(args.target):
            path.unlink(missing_ok=True)
    else:
        raise SystemExit(f"unknown run mode {args.mode!r}")


def peak_rss_bytes() -> int | None:   # replaced by the helper in the child
    raise RuntimeError("peak_rss_bytes is only available inside a probe child")


def start_child_clock() -> None:
    """Reset the clock so the caller covers the product work, not the parse."""
    _clock["origin"] = time.perf_counter()
    _clock["first_import"] = math.inf


def _record_first_import(name: str | None) -> None:
    if not name or math.isfinite(_clock["first_import"]):
        return
    root = name.partition(".")[0]
    if root == "birkin_mnemosyne" or root in CORE_OPTIONAL_MODULES:
        _clock["first_import"] = time.perf_counter()


def install_import_clock() -> None:
    """Wrap the product loader so the first product import is timestamped.

    Python 3.12 removed the legacy ``find_module`` fallback, so the wrapper sits
    directly on ``PathFinder.find_spec`` (the actual product loader); stdlib
    imports never reach the product branches.
    """
    import importlib.machinery

    finder: Any = importlib.machinery.PathFinder
    if getattr(finder, "probe_clock", False):
        return
    original = finder.find_spec

    def find_spec(fullname: str, path: Any = None, target: Any = None) -> Any:
        _record_first_import(fullname)
        return original(fullname, path, target)

    finder.find_spec = staticmethod(find_spec)
    finder.probe_clock = True
    for name in ("birkin_mnemosyne", "numpy", "safetensors", "huggingface_hub"):
        if name in sys.modules:
            _record_first_import(name)
            break


# -- CLI -----------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "__child":
        parser = argparse.ArgumentParser(prog="resource_probe.py __child")
        _ = parser.add_argument("command", choices=("check", "run"))
        _ = parser.add_argument("mode")
        _ = parser.add_argument("target", type=Path)
        _ = parser.add_argument("model_dir", nargs="?", type=Path)
        _ = parser.add_argument("--notes", type=int, default=1)
        run_child_command(parser.parse_args(sys.argv[2:]))
        return

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=(
                                         argparse.RawDescriptionHelpFormatter))
    _ = parser.add_argument("--modes", default=",".join(MODES))
    _ = parser.add_argument("--repeats", type=int, default=10)
    _ = parser.add_argument("--offline", action="store_true")
    _ = parser.add_argument("--prepare", action="store_true")
    _ = parser.add_argument("--check", action="store_true")
    _ = parser.add_argument("--model-dir", type=Path, default=None)
    _ = parser.add_argument("--notes", type=int, default=NOTE_BOUNDS[0])
    _ = parser.add_argument("--keep-vaults", action="store_true")
    _ = parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.repeats < 1:
        raise SystemExit("--repeats must be >= 1")

    if args.prepare:
        from birkin_mnemosyne import semantic

        before = semantic.prepared()
        start = time.perf_counter()
        prepared_path = semantic.prepare()
        report: dict[str, Any] = {
            "action": "prepare", "was_prepared": before, "path": str(prepared_path),
            "prepared": semantic.prepared(), "model_dir": str(semantic.model_dir()),
            "possibly_converted": not before,
            "elapsed_ms": (time.perf_counter() - start) * 1000.0}
    elif args.check:
        report = backend_check(args.model_dir)
    else:
        report = run_probe(args, child_env(args.offline, args.model_dir))
    text = json.dumps(report, indent=2, ensure_ascii=True)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")


install_import_clock()

if __name__ == "__main__":
    main()
