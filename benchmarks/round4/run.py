"""Round-4 immutable evaluation protocol: integrity guard and sealed scoring.

``--check-inputs-only`` is the integrity gate. It hashes the frozen inputs and
scorers against the committed manifest, parses every JSON payload, and reports
the modes and required author slices the locked evaluation must provide. It
measures nothing and is never product-performance evidence. The module-level
imports are standard library only, and scoring dependencies stay lazy so the
core CI lane needs neither the tokenizer nor numpy.

Problem discovery of the round-4 protocol (recorded for T4/T15):

* ``StartupReader.read(paths)`` in ``birkin_mnemosyne.startup`` has no mode
  keyword, so a compact complete read requires the future public
  ``StartupReader(root).read(paths, compact=True)`` surface (plan T6).
* ``Consolidation(root)`` in ``birkin_mnemosyne.consolidation`` accepts no
  semantic or threshold configuration, so the explicit semantic-ready
  detection mode requires the future public
  ``Consolidation(root, semantic=True, thresholds=locked_config)`` surface
  (plan T11/T12).

Unavailable delegations stay explicit PENDING; they never become a pass by
falling back to legacy implementations. Sealed scoring defaults to compact
startup and semantic detection, invokes unchanged round3 entry points, and
publishes only aggregate gates on stdout. The owner runs the locked evaluation
once; implementation tests use invented data and scorer entry points only.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import tempfile
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import (
    TYPE_CHECKING,
    Final,
    Literal,
    NoReturn,
    Protocol,
    TypeAlias,
    TypedDict,
    TypeGuard,
    TypeVar,
)

if TYPE_CHECKING:  # type-checker only; product imports stay lazy inside functions
    from typing_extensions import override

    from birkin_mnemosyne.consolidation import Consolidation as _Consolidation
    from birkin_mnemosyne.consolidation import Question as _Question
    from birkin_mnemosyne.startup import StartupBundle as _StartupBundle
    from birkin_mnemosyne.startup import StartupReader as _StartupReader
else:
    _Method = TypeVar("_Method", bound=Callable[..., object])

    def override(method: _Method) -> _Method:
        """Runtime stand-in for ``typing.override`` (Python 3.12+); marks nothing."""
        return method

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_MANIFEST = HERE / "frozen-manifest.json"
THRESHOLDS_PATH = HERE / "detection-thresholds.json"
BENCHMARKS = ROOT / "benchmarks"

# Scorer modules whose functions stay byte-unchanged; imported on demand only.
SCORER_MODULES = ("benchmarks.round3.run", "benchmarks.round3.answerer",
                  "benchmarks.round3.startup_answerer", "benchmarks.retrieval.bench_retrieval")

LEGACY_STARTUP_MODE: Final = "legacy"
COMPACT_STARTUP_MODE: Final = "compact"
LEGACY_DETECTION_MODE: Final = "lexical"
SEMANTIC_DETECTION_MODE: Final = "semantic"


class PendingSurface(TypedDict):
    surface: str
    delivered_by: str
    detection_mode: str


#: Wrapper-local delegation points for surfaces that do not exist yet. Each
#: entry names the import path, the required call shape and the delivering
#: plan task, so the gap stays visible instead of becoming a silent fallback.
PENDING_PRODUCT_SURFACES: dict[str, PendingSurface] = {
    "compact-startup": {
        "surface": "birkin_mnemosyne.StartupReader(root).read(paths, compact=True)",
        "delivered_by": "round4 T6",
        "detection_mode": COMPACT_STARTUP_MODE,
    },
    "semantic-consolidation": {
        "surface": "birkin_mnemosyne.Consolidation(root, semantic=True, thresholds=locked_config)",
        "delivered_by": "round4 T11/T12",
        "detection_mode": SEMANTIC_DETECTION_MODE,
    },
}

_UTF8_BOM = b"\xef\xbb\xbf"

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
_json: Callable[[str], JsonValue] = json.loads


class _BlobCheck(TypedDict):
    checked: Literal[True]
    object_id: str | None
    normalized_sha256: str
    checkout_form: Literal["blob", "working-eol"]


class _VerifiedFile(TypedDict):
    path: str
    matched: Literal["raw", "git-blob"]
    bytes: int
    raw_sha256: str
    git_blob_sha256: str


class _BoundVerifiedFile(_VerifiedFile):
    source_tree_sha256: str


class _ManifestFields(TypedDict):
    required_files: dict[str, dict[str, JsonValue]]
    required_authors: dict[str, dict[str, list[str]]]
    author_identity: dict[str, str]
    hash_contract: dict[str, str]
    slices_validated_at: str


class FrozenManifest(_ManifestFields, total=False):
    manifest_version: int
    bootstrap_raw_sha256: dict[str, str]
    required_recall_authors: list[str]
    required_recall_slices: list[str]
    source_tree_sha256: str
    recall_baseline: dict[str, JsonValue]


class _AuthorSlice(TypedDict):
    author: str
    slice: str
    file: str


class _PayloadRow(TypedDict):
    path: str
    top_level_keys: int


class _ProbeMeasurements(TypedDict):
    load_read_ms: float
    peak_rss_bytes: int
    context_characters: int


class _LegacyProbePayload(_ProbeMeasurements):
    tokenizer_loaded: bool


class LegacyProbeResult(_LegacyProbePayload):
    mode: str
    probe: str
    legacy: Literal[True]


class _Round4ProbePayload(_ProbeMeasurements):
    mode: str
    probe: str
    root: str
    paths: list[str]
    context_sha256: str
    product_imported: bool
    optional_imports: list[str]


class Round4ProbeResult(_Round4ProbePayload):
    legacy: Literal[False]


class _ExistingMode(TypedDict):
    available: Literal[True]
    evidence: str


class _PendingMode(TypedDict):
    available: bool
    pending: PendingSurface


class _StartupModes(TypedDict):
    legacy: _ExistingMode
    compact: _PendingMode
    authoritative_timing: str


class _DetectionModes(TypedDict):
    lexical: _ExistingMode
    semantic: _PendingMode


class DeclaredModes(TypedDict):
    startup: _StartupModes
    detection: _DetectionModes
    scope: str


class IntegrityReport(TypedDict):
    manifest: str
    manifest_version: int | None
    hashed_files: int
    hash_modes: list[Literal["raw", "git-blob"]]
    source_tree_sha256: str
    files: list[_BoundVerifiedFile]
    payloads: list[_PayloadRow]
    required_authors: list[str]
    required_recall_authors: list[str] | None
    required_recall_slices: list[str] | None
    slices_validated_at: str
    scorer_modules: list[str]
    modes: DeclaredModes
    integrity_only: Literal[True]
    product_performance_claimed: Literal[False]
    frozen_rows_read: list[str]
    frozen_row_content_interpreted: Literal[False]
    scoring_executed: Literal[False]


class FrozenInputError(RuntimeError):
    """A frozen input, scorer or required author slice failed its integrity contract."""


class PendingProductSurfaceError(FrozenInputError):
    """A selected public product surface cannot supply valid measured evidence."""


def normalize_blob(data: bytes) -> bytes:
    """Normalize checkout CRLF without discarding source bytes such as a BOM."""
    return data.replace(b"\r\n", b"\n")


def _object_digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def blob_sha256(data: bytes) -> str:
    """SHA256 of the Git content-normalized blob, so CRLF checkouts verify."""
    return _object_digest(normalize_blob(data))


def normalized_object_id(data: bytes) -> str | None:
    """Git's own content-normalized object id for the bytes.

    ``git hash-object`` applies the repository's declared ``text``/``eol``
    attributes, so this is the checkout-independent decision for the declared
    blob contract. ``None`` means no usable git executable, which the guard
    reports rather than treating the normalization rule as verified.
    """
    import subprocess

    try:
        process = subprocess.run(
            ["git", "-C", str(ROOT), "hash-object", "--stdin", "--path",
             "benchmarks/round3/_probe.py"], input=data, capture_output=True, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return process.stdout.decode("ascii").strip()


def verify_declared_blob(
    relative: str, meta: Mapping[str, JsonValue], data: bytes,
) -> _BlobCheck:
    """Compare the file's normalized object id with the declared pinned id.

    ``git_blob_sha256`` in the manifest is the SHA256 of the tracked blob, i.e.
    the value pinned by the repository history; the object id git computes for
    the supplied bytes must reproduce it under the declared EOL text rule.
    """
    declared = meta.get("git_blob_sha256")
    if not isinstance(declared, str):
        raise FrozenInputError(f"{relative}: a pinned git_blob_sha256 is required")
    pinned = _pinned_blob_bytes(relative)
    if pinned is None:
        raise FrozenInputError(f"{relative}: the tracked blob could not be verified")
    current = _object_digest(pinned)
    if current != declared:
        raise FrozenInputError(
            f"{relative}: repository object {declared} hashes to {current}, so the pinned " +
            "git_blob_sha256 declaration is wrong for this repository history")
    object_id = normalized_object_id(data)
    if pinned == data:
        return {"checked": True, "object_id": object_id, "normalized_sha256": current,
                "checkout_form": "blob"}
    if normalize_blob(data) == pinned or normalize_blob(data) == normalize_blob(pinned):
        return {"checked": True, "object_id": object_id, "normalized_sha256": current,
                "checkout_form": "working-eol"}
    raise FrozenInputError(
        f"frozen input drifted: {relative}: the Git-normalized bytes (object {object_id}) " +
        f"differ from the pinned blob content (object {declared})")


def _pinned_blob_bytes(relative: str) -> bytes | None:
    """Read tracked bytes through Git, including linked and packed worktrees."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"HEAD:{relative}"],
            check=True, capture_output=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise FrozenInputError(f"{relative}: cannot read its tracked Git blob") from exc
    return result.stdout


def raw_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_shape(value: dict[str, JsonValue]) -> TypeGuard[FrozenManifest]:
    files = value.get("required_files")
    authors = value.get("required_authors")
    identities = value.get("author_identity")
    hash_contract = value.get("hash_contract")
    if not isinstance(files, dict) or not all(isinstance(meta, dict) for meta in files.values()):
        return False
    if not isinstance(authors, dict) or not isinstance(identities, dict):
        return False
    if not all(isinstance(identity, str) for identity in identities.values()):
        return False
    if not isinstance(hash_contract, dict) or not all(
        isinstance(rule, str) for rule in hash_contract.values()
    ):
        return False
    if not isinstance(value.get("slices_validated_at"), str):
        return False
    if "bootstrap_raw_sha256" in value:
        bootstrap = value["bootstrap_raw_sha256"]
        if not isinstance(bootstrap, dict) or not all(
            isinstance(checksum, str) for checksum in bootstrap.values()
        ):
            return False
    for slices in authors.values():
        if not isinstance(slices, dict):
            return False
        for paths in slices.values():
            if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
                return False
    if "manifest_version" in value and (
        not isinstance(value["manifest_version"], int)
        or isinstance(value["manifest_version"], bool)
    ):
        return False
    for name in ("required_recall_authors", "required_recall_slices"):
        if name in value:
            entries = value[name]
            if not isinstance(entries, list) or not all(isinstance(entry, str) for entry in entries):
                return False
    return True


def load_manifest(path: Path) -> FrozenManifest:
    raw = Path(path).read_bytes()
    try:
        manifest = _json(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise FrozenInputError(f"manifest {path} is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise FrozenInputError(f"manifest {path} must be a JSON object")
    required = manifest.get("required_files")
    if not isinstance(required, dict) or not required:
        raise FrozenInputError(f"manifest {path} declares no required files")
    if not _manifest_shape(manifest):
        raise FrozenInputError(f"manifest {path} has invalid required metadata")
    return manifest


def _resolve(relative: str) -> Path:
    candidate = (ROOT / relative).resolve()
    if not candidate.is_relative_to(ROOT.resolve()):
        raise FrozenInputError(f"manifest path escapes the repository: {relative}")
    return candidate


def verify_file(
    relative: str, meta: Mapping[str, JsonValue], root: Path | None = None,
) -> _VerifiedFile:
    """Check one declared file against the two independently declared hashes.

    Two declarations are pinned up front: ``raw_sha256`` (the canonical
    LF checkout bytes) and ``git_blob_sha256`` (the tracked Git blob).
    Original Windows working-byte hashes remain separate bootstrap provenance.
    Accepting either alone would let a rewrite satisfy the contract by
    copying a recomputed value, so both must independently reproduce the file:
    the raw form matches the declared raw bytes, or the Git content-normalized
    form matches the declared tracked blob for a different-EOL checkout.
    """
    path = (root / relative).resolve() if root is not None else _resolve(relative)
    if not path.is_file():
        raise FrozenInputError(f"required frozen file is missing: {relative}")
    data = path.read_bytes()
    _ = verify_declared_blob(relative, meta, data)
    actual_raw = raw_sha256(data)
    actual_blob = blob_sha256(data)
    declared_raw = meta.get("raw_sha256")
    declared_blob = meta.get("git_blob_sha256")
    if actual_raw == declared_raw:
        matched = "raw"
    elif actual_blob == declared_blob or actual_blob == declared_raw:
        matched = "git-blob"
    else:
        raise FrozenInputError(
            f"frozen input drifted: {relative} raw={actual_raw} " +
            f"declared_raw={declared_raw} blob={actual_blob} declared_blob={declared_blob}")
    return {"path": relative, "matched": matched, "bytes": len(data),
            "raw_sha256": actual_raw, "git_blob_sha256": actual_blob}


def verify_author_identity(relative: str, expected: str, root: Path | None = None) -> str:
    """Confirm the declared author model ID; the question and answer rows stay unread."""
    path = (root / relative).resolve() if root is not None else _resolve(relative)
    try:
        payload = _json(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise FrozenInputError(f"frozen payload {relative} is not valid JSON: {exc}") from exc
    author = payload.get("author") if isinstance(payload, dict) else None
    if not isinstance(author, str) or not author.strip():
        raise FrozenInputError(f"{relative}: an actual author model ID is required")
    if author != expected:
        raise FrozenInputError(f"{relative}: author {author!r} != required {expected!r}")
    if expected.startswith("anthropic-subscription/") and "claude" not in author.casefold():
        raise FrozenInputError(f"{relative}: the required independent Claude author is absent")
    return author


def relative_key(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def check_frozen_files(manifest: FrozenManifest, root: Path | None = None) -> list[_BoundVerifiedFile]:
    """Hash every declared input with its declared EOL rule.

    ``root`` verifies a disposable copy of the frozen tree (mutation proofs);
    leaving it out verifies the repository the guard ships in. The pinned Git
    blob lookup always uses this guard's own repository.
    """
    rows = [verify_file(rel, meta, root) for rel, meta in sorted(manifest["required_files"].items())]
    models = sorted(SCORER_MODULES)
    bundle = json.dumps({"frozen_files": rows, "scorer_modules": models},
                        sort_keys=True, separators=(",", ":"))
    tree_digest = hashlib.sha256(bundle.encode("utf-8")).hexdigest()
    return [{**row, "source_tree_sha256": tree_digest} for row in rows]


def validate_required_authors(
    frozen_root: Path | None = None, manifest_path: Path = DEFAULT_MANIFEST,
) -> list[_AuthorSlice]:
    """Validate declared author identity and required feature slices.

    Called by the locked round-4 evaluation (plan T15), not by the integrity
    check: this function reads frozen question payloads to confirm that every
    required author and slice is present. It is testable against a disposable
    copy, so the protocol is proven without consuming the real frozen rows.
    """
    manifest = load_manifest(manifest_path)
    base = ROOT if frozen_root is None else frozen_root
    checked: list[_AuthorSlice] = []
    if not manifest["required_authors"]:
        raise FrozenInputError("no required authors declared")
    for author, slices in sorted(manifest["required_authors"].items()):
        if not author.strip() or not {"startup", "consolidation"} <= set(slices):
            raise FrozenInputError(f"{author!r}: missing required startup/consolidation slice")
        for slice_name, files in sorted(slices.items()):
            if not files:
                raise FrozenInputError(f"{author}: missing files for required slice {slice_name!r}")
            for relative in files:
                path = (base / relative).resolve()
                if not path.is_relative_to(base.resolve()):
                    raise FrozenInputError(f"manifest path escapes the repository: {relative}")
                if relative not in manifest["required_files"]:
                    raise FrozenInputError(f"{relative}: required slice is not hash-bound")
                declared = manifest["author_identity"].get(relative)
                if declared != author:
                    raise FrozenInputError(f"{relative} does not declare author {author!r}")
                seen = verify_author_identity(relative, author, base)
                payload = _json((base / relative).read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise FrozenInputError(f"frozen payload {relative} must be a JSON object")
                if not payload.get(slice_name):
                    raise FrozenInputError(
                        f"{relative}: missing required slice {slice_name!r} for {author}")
                checked.append({"author": seen, "slice": slice_name, "file": relative})
    return checked


def _validate_payloads(manifest: FrozenManifest, root: Path | None = None) -> list[_PayloadRow]:
    """Parse every frozen JSON payload without interpreting its rows."""
    parsed: list[_PayloadRow] = []
    for relative in sorted(manifest["required_files"]):
        if not relative.endswith(".json"):
            continue
        path = (root / relative).resolve() if root is not None else _resolve(relative)
        payload = _json(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise FrozenInputError(f"frozen payload {relative} must be a JSON object")
        parsed.append({"path": relative, "top_level_keys": len(payload)})
    return parsed


def declared_modes() -> DeclaredModes:
    """The startup and detection modes the locked evaluation must provide."""
    if TYPE_CHECKING:
        from birkin_mnemosyne.consolidation import Consolidation
        from birkin_mnemosyne.startup import StartupReader
    else:
        from birkin_mnemosyne import Consolidation, StartupReader

    compact_available = "compact" in inspect.signature(StartupReader.read).parameters
    semantic_available = {"semantic", "thresholds"} <= set(
        inspect.signature(Consolidation.__init__).parameters)
    return {
        "startup": {
            LEGACY_STARTUP_MODE: {"available": True,
                                  "evidence": "original round3 subprocess captures (legacy)"},
            COMPACT_STARTUP_MODE: {"available": compact_available,
                                   "pending": PENDING_PRODUCT_SURFACES["compact-startup"]},
            "authoritative_timing": "benchmarks/round4/_startup_probe.py",
        },
        "detection": {
            LEGACY_DETECTION_MODE: {"available": True, "evidence": "frozen scoring functions"},
            SEMANTIC_DETECTION_MODE: {"available": semantic_available,
                                      "pending": PENDING_PRODUCT_SURFACES["semantic-consolidation"]},
        },
        "scope": "T1 declares and guards these modes; compact/semantic behavior is a future " +
                 "product claim (T5-T15), never asserted here",
    }


def check_inputs(manifest_path: Path = DEFAULT_MANIFEST, root: Path | None = None) -> IntegrityReport:
    """Integrity-only check: hashes, JSON parse, declared modes and required slices.

    ``root`` pins the tree under test for disposable mutation proofs; the CLI
    passes the repository the guard ships in, so a copy of the guard can never
    silently verify the original frozen files instead of its own tree.
    """
    manifest = load_manifest(manifest_path)
    files = check_frozen_files(manifest, root)
    payloads = _validate_payloads(manifest, root)
    return {
        "manifest": str(manifest_path),
        "manifest_version": manifest.get("manifest_version"),
        "hashed_files": len(files),
        "hash_modes": sorted({row["matched"] for row in files}),
        "source_tree_sha256": files[0]["source_tree_sha256"] if files else "",
        "files": files,
        "payloads": payloads,
        "required_authors": sorted(manifest["required_authors"]),
        "required_recall_authors": manifest.get("required_recall_authors"),
        "required_recall_slices": manifest.get("required_recall_slices"),
        "slices_validated_at": manifest["slices_validated_at"],
        "scorer_modules": sorted(SCORER_MODULES),
        "modes": declared_modes(),
        "integrity_only": True,
        "product_performance_claimed": False,
        "frozen_rows_read": [row["path"] for row in files],
        "frozen_row_content_interpreted": False,
        "scoring_executed": False,
    }


class _CompactRead(Protocol):
    """A bound ``StartupReader.read`` that accepts the future ``compact`` keyword."""

    def __call__(self, paths: Sequence[str], *, compact: bool) -> _StartupBundle: ...


def _accepts_compact(read: Callable[[Sequence[str]], _StartupBundle]) -> TypeGuard[_CompactRead]:
    return "compact" in inspect.signature(read).parameters


class _CompactFormatRead(Protocol):
    """A bound ``StartupReader.read`` that also accepts ``compact_format``."""

    def __call__(self, paths: Sequence[str], *, compact: bool,
                 compact_format: str) -> _StartupBundle: ...


def _accepts_compact_format(read: _CompactRead) -> TypeGuard[_CompactFormatRead]:
    return "compact_format" in inspect.signature(read).parameters


class _SemanticFactory(Protocol):
    """A ``Consolidation`` constructor that accepts the future semantic keywords."""

    def __call__(self, vault: Path, *, semantic: bool,
                 thresholds: dict[str, JsonValue]) -> _Consolidation: ...


def _accepts_semantic(cls: type[_Consolidation]) -> TypeGuard[_SemanticFactory]:
    return {"semantic", "thresholds"} <= set(inspect.signature(cls.__init__).parameters)


class _SemanticReporting(Protocol):
    semantic_status: str


def _reports_semantic_status(value: _Consolidation) -> TypeGuard[_SemanticReporting]:
    return hasattr(value, "semantic_status")


class _ScoreBindings(TypedDict):
    StartupReader: Callable[[Path], _StartupReader]
    Consolidation: Callable[[Path], _Consolidation]


def _legacy_startup_engine() -> Callable[[Path], _StartupReader]:
    if TYPE_CHECKING:
        from birkin_mnemosyne.startup import StartupReader
    else:
        from birkin_mnemosyne import StartupReader

    def engine(root: Path) -> _StartupReader:
        return StartupReader(root)

    return engine


def _pending(surface: str, task: str) -> Callable[[Path], NoReturn]:
    def engine(root: Path) -> NoReturn:
        _ = root
        raise PendingProductSurfaceError(
            f"{surface} is not available on this base; delivered by {task}. " +
            "Refusing instead of silently falling back to the legacy implementation.")

    return engine


def configured_startup(root: Path, mode: str = LEGACY_STARTUP_MODE) -> _StartupReader:
    """Build the explicitly named startup implementation for ``mode``.

    ``compact`` delegates to the future public
    ``StartupReader(root).read(paths, compact=True)`` and is refused until the
    round-4 T6 product surface exists.
    """
    if mode == LEGACY_STARTUP_MODE:
        return _legacy_startup_engine()(root)
    if mode == COMPACT_STARTUP_MODE:
        if TYPE_CHECKING:
            from birkin_mnemosyne.startup import StartupReader
        else:
            from birkin_mnemosyne import StartupReader

        if "compact" not in inspect.signature(StartupReader.read).parameters:
            pending = PENDING_PRODUCT_SURFACES["compact-startup"]
            return _pending(pending["surface"], pending["delivered_by"])(root)

        class CompactReader(StartupReader):
            @override
            def read(self, paths: Sequence[str], *, compact: bool = True,
                     compact_format: str = "v2") -> _StartupBundle:
                base_read = super().read
                if not _accepts_compact(base_read):
                    pending = PENDING_PRODUCT_SURFACES["compact-startup"]
                    return _pending(pending["surface"], pending["delivered_by"])(self.root)
                if _accepts_compact_format(base_read):
                    return base_read(paths, compact=compact, compact_format=compact_format)
                if compact_format != "v2":
                    raise FrozenInputError(
                        f"compact format {compact_format!r} is not supported by this base " +
                        "reader. Refusing instead of silently returning the default format.")
                return base_read(paths, compact=compact)

        return CompactReader(root)
    raise FrozenInputError(f"unknown startup mode {mode!r}")


def configured_consolidation(root: Path, mode: str = LEGACY_DETECTION_MODE) -> _Consolidation:
    """Build the explicitly named detection implementation for ``mode``.

    ``semantic`` delegates to the future public
    ``Consolidation(root, semantic=True, thresholds=locked_config)`` with a
    required ready status and is refused until T11/T12 exist.
    """
    if TYPE_CHECKING:
        from birkin_mnemosyne.consolidation import Consolidation
    else:
        from birkin_mnemosyne import Consolidation

    if mode == LEGACY_DETECTION_MODE:
        return Consolidation(root)
    if mode == SEMANTIC_DETECTION_MODE:
        parameters = inspect.signature(Consolidation.__init__).parameters
        if not {"semantic", "thresholds"} <= set(parameters):
            pending = PENDING_PRODUCT_SURFACES["semantic-consolidation"]
            return _pending(pending["surface"], pending["delivered_by"])(root)
        if not THRESHOLDS_PATH.is_file():
            raise FrozenInputError("locked practice thresholds are missing")
        config = _json(THRESHOLDS_PATH.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise FrozenInputError("semantic scoring requires locked practice thresholds")
        thresholds = config.get("thresholds")
        if config.get("locked") is not True or not isinstance(thresholds, dict) or not thresholds:
            raise FrozenInputError("semantic scoring requires locked practice thresholds")

        class SemanticConsolidation(Consolidation):
            @override
            def questions(self, limit: int = 20) -> tuple[_Question, ...]:
                result = super().questions(limit)
                if not (_reports_semantic_status(self) and self.semantic_status == "ready"):
                    raise PendingProductSurfaceError("semantic question pipeline is not ready")
                return result

        if not _accepts_semantic(SemanticConsolidation):
            pending = PENDING_PRODUCT_SURFACES["semantic-consolidation"]
            return _pending(pending["surface"], pending["delivered_by"])(root)
        return SemanticConsolidation(root, semantic=True, thresholds=thresholds)
    raise FrozenInputError(f"unknown detection mode {mode!r}")


def _probe_measurements(value: Mapping[str, JsonValue]) -> bool:
    elapsed = value.get("load_read_ms")
    if not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool):
        return False
    for field in ("peak_rss_bytes", "context_characters"):
        number = value.get(field)
        if not isinstance(number, int) or isinstance(number, bool):
            return False
    return True


def _legacy_probe_shape(value: JsonValue) -> TypeGuard[_LegacyProbePayload]:
    return isinstance(value, dict) and _probe_measurements(value) and \
        isinstance(value.get("tokenizer_loaded"), bool)


def _round4_probe_shape(value: JsonValue) -> TypeGuard[_Round4ProbePayload]:
    if not isinstance(value, dict) or not _probe_measurements(value):
        return False
    if not isinstance(value.get("product_imported"), bool):
        return False
    for field in ("mode", "probe", "root", "context_sha256"):
        if not isinstance(value.get(field), str):
            return False
    for field in ("paths", "optional_imports"):
        entries = value.get(field)
        if not isinstance(entries, list) or not all(isinstance(entry, str) for entry in entries):
            return False
    return True


def legacy_probe(root: Path, paths: list[str], mode: str) -> LegacyProbeResult:
    """Run an unchanged legacy round3 fresh probe; these captures stay legacy."""
    if mode not in ("startup", "full"):
        raise FrozenInputError(f"legacy probe mode must be startup or full, got {mode!r}")
    import subprocess

    probe = BENCHMARKS / "round3" / "_probe.py"
    if not probe.is_file():
        raise FrozenInputError(f"legacy probe is missing: {relative_key(probe)}")
    process = subprocess.run([sys.executable, str(probe), mode, str(root), *paths],
                             capture_output=True, text=True, check=True)
    payload = _json(process.stdout.strip().splitlines()[-1])
    if not _legacy_probe_shape(payload):
        raise FrozenInputError("legacy probe returned invalid measurement metadata")
    return {**payload, "mode": mode, "probe": relative_key(probe), "legacy": True}


def round4_probe(root: Path, paths: list[str], mode: str) -> Round4ProbeResult:
    """Run the round4 fresh probe for one explicit mode in its own process."""
    if mode not in ("full", "compact"):
        raise FrozenInputError(f"round4 probe mode must be full or compact, got {mode!r}")
    import subprocess

    probe = HERE / "_startup_probe.py"
    if not probe.is_file():
        raise FrozenInputError(f"round4 probe is missing: {relative_key(probe)}")
    process = subprocess.run([sys.executable, str(probe), mode, str(root), *paths],
                             capture_output=True, text=True, check=True)
    payload = _json(process.stdout.strip().splitlines()[-1])
    if not _round4_probe_shape(payload):
        raise FrozenInputError("round4 probe returned invalid measurement metadata")
    if payload["mode"] != mode:
        raise FrozenInputError("round4 probe did not run the requested mode")
    return {**payload, "probe": relative_key(probe), "legacy": False}


def score_bindings(startup_mode: str, detection_mode: str) -> _ScoreBindings:
    """The engine-constructor globals the locked evaluation may bind per mode.

    The startup scorer's fresh subprocesses stay legacy; this binding is only
    for the in-process measurement path and must be restored afterwards.
    """
    return {"StartupReader": lambda root: configured_startup(root, startup_mode),
            "Consolidation": lambda root: configured_consolidation(root, detection_mode)}


def _mapping(value: JsonValue, label: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise FrozenInputError(f"{label}: expected a JSON object")
    return value


def _records(value: JsonValue, label: str) -> list[dict[str, JsonValue]]:
    if not isinstance(value, list) or not value:
        raise FrozenInputError(f"{label}: expected nonempty rows")
    return [_mapping(row, label) for row in value]


def _number(value: JsonValue, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise FrozenInputError(f"{label}: expected a finite number")
    return float(value)


def _text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise FrozenInputError(f"{label}: expected a nonempty string")
    return value


def _json_value(value: IntegrityReport | Round4ProbeResult) -> JsonValue:
    """Keep structured protocol records JSON-typed at the serialization boundary."""
    return _json(json.dumps(value, allow_nan=False))


def _gate(passed: bool, reason: str = "") -> dict[str, JsonValue]:
    return {"status": "PASS" if passed else "FAIL", "reason": reason}


def _pending_gate(reason: str) -> dict[str, JsonValue]:
    return {"status": "PENDING", "reason": reason}


def startup_gates(
    measured: Mapping[str, JsonValue], timing: Mapping[str, JsonValue] | None,
) -> dict[str, dict[str, JsonValue]]:
    """Zero misses and unchanged correct answers; strict whole-context/time gains."""
    rows = _records(measured.get("rows"), "startup.rows")
    complete = measured.get("complete") is True and measured.get("missing_required_items") == []
    unchanged = all(row.get("before_correct") is True and row.get("after_correct") is True
                    for row in rows)
    coverage = _gate(complete and unchanged, "complete closure, zero misses, unchanged answers")
    if timing is None:
        gain = _pending_gate("compact API or authoritative paired timing unavailable")
    else:
        whole = _mapping(timing.get("whole_context"), "paired whole contexts")
        full = _mapping(whole.get("full"), "paired full context")
        candidate = _mapping(whole.get("compact"), "paired compact context")
        smaller = _number(candidate.get("tokens_measured_o200k_base"), "compact BPE") < \
            _number(full.get("tokens_measured_o200k_base"), "full BPE")
        faster = _number(timing.get("compact_median_load_read_ms"), "compact median") < \
            _number(timing.get("full_median_load_read_ms"), "full median")
        gain = _gate(complete and unchanged and smaller and faster,
                     "whole-context o200k_base BPE and ten-pair median must both be strictly lower")
    return {"IS-1": coverage, "IS-2": gain}


def consolidation_gate(measured: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Abstentions stay in the complete positive denominator, never predicted positives."""
    precision, recall = measured.get("after_precision"), measured.get("after_recall")
    return _gate(precision is not None and _number(precision, "consolidation precision") == 1 and
                 recall is not None and
                 _number(recall, "consolidation recall") >= 0.9,
                 "precision must equal 1; complete recall including abstentions must be >= 0.9")


class _HistoricalQuery(Protocol):
    author: str
    split: str
    kind: str


class _HistoricalCorpus(Protocol):
    def queries(self) -> Sequence[_HistoricalQuery]: ...


class _FrozenScorer(Protocol):
    StartupReader: Callable[[Path], _StartupReader]
    Consolidation: Callable[[Path], _Consolidation]
    corpus: _HistoricalCorpus

    def startup(self, data: Mapping[str, JsonValue]) -> dict[str, JsonValue]: ...
    def identity(self, data: Mapping[str, JsonValue]) -> dict[str, JsonValue]: ...
    def consolidation(self, data: Mapping[str, JsonValue]) -> dict[str, JsonValue]: ...
    def kibitzer(self) -> list[dict[str, JsonValue]]: ...
    def context_size(self, text: str) -> dict[str, JsonValue]: ...


def _scorer_shape(module: ModuleType) -> TypeGuard[_FrozenScorer]:
    return all(callable(getattr(module, name, None)) for name in
               ("startup", "identity", "consolidation", "kibitzer", "StartupReader", "Consolidation")) \
        and callable(getattr(module, "context_size", None)) \
        and callable(getattr(getattr(module, "corpus", None), "queries", None))


def _load_scorer() -> _FrozenScorer:
    """Import unchanged public entry points only after the integrity guard has passed."""
    modules = [importlib.import_module(name) for name in SCORER_MODULES]
    for name, module in zip(SCORER_MODULES, modules, strict=True):
        expected = ROOT / (name.replace(".", "/") + ".py")
        if module.__file__ is None or Path(module.__file__).resolve() != expected.resolve():
            raise FrozenInputError(f"{name}: scorer imported from an unverified tree")
    runner = modules[0]
    if not _scorer_shape(runner):
        raise FrozenInputError("round3 scorer public entry points are missing")
    return runner


@contextmanager
def _bound_scoring(
    scorer: _FrozenScorer, startup_mode: str, detection_mode: str,
) -> Generator[None]:
    bindings = score_bindings(startup_mode, detection_mode)
    startup, consolidation = scorer.StartupReader, scorer.Consolidation
    try:
        scorer.StartupReader = bindings["StartupReader"]
        scorer.Consolidation = bindings["Consolidation"]
        yield
    finally:
        scorer.StartupReader, scorer.Consolidation = startup, consolidation


def _required_recall(manifest: FrozenManifest) -> set[tuple[str, str, str]]:
    authors, kinds = manifest.get("required_recall_authors"), manifest.get("required_recall_slices")
    if not authors or not kinds:
        raise FrozenInputError("required historical recall authors/kinds are missing")
    return {(author, split, kind) for author in authors for split in ("dev", "test") for kind in kinds}


def _recall_key(row: Mapping[str, JsonValue]) -> tuple[str, str, str]:
    return (_text(row.get("author"), "recall.author"),
            _text(row.get("split"), "recall.split"), _text(row.get("kind"), "recall.kind"))


def _recall_index(
    rows: Sequence[dict[str, JsonValue]],
) -> dict[tuple[str, str, str], dict[str, JsonValue]]:
    indexed: dict[tuple[str, str, str], dict[str, JsonValue]] = {}
    for row in rows:
        key = _recall_key(row)
        if key in indexed:
            raise FrozenInputError(f"duplicate historical recall slice: {key}")
        indexed[key] = row
    return indexed


def recall_gates(
    candidate: Sequence[dict[str, JsonValue]], baseline: Sequence[dict[str, JsonValue]],
    required: set[tuple[str, str, str]],
) -> list[dict[str, JsonValue]]:
    """Recorded before metrics, not a newly measured or averaged baseline, are authoritative."""
    measured, recorded = _recall_index(candidate), _recall_index(baseline)
    results: list[dict[str, JsonValue]] = []
    for key in sorted(required | set(measured)):
        label = "/".join(key)
        if key not in measured:
            raise FrozenInputError(f"missing required historical recall slice: {label}")
        row: dict[str, JsonValue] = {"author": key[0], "split": key[1], "kind": key[2]}
        if key not in recorded:
            row["gate"] = _pending_gate(f"missing recorded baseline slice: {label}")
        else:
            before = _mapping(recorded[key].get("before"), f"{label}.baseline.before")
            after = _mapping(measured[key].get("after"), f"{label}.candidate.after")
            missing = [name for name in ("r@1", "r@5", "mrr", "ndcg@10", "n")
                       if name not in before or name not in after]
            missing.extend(name for name in ("before_raw_precision_at_1", "before_p95_ms")
                           if name not in recorded[key])
            missing.extend(name for name in ("after_raw_precision_at_1", "after_p95_ms")
                           if name not in measured[key])
            if missing:
                row["gate"] = _pending_gate(f"{label}: missing recorded/candidate fields: {missing}")
            else:
                same_n = _number(after["n"], label) == _number(before["n"], label) > 0
                ranks = all(_number(after[name], label) >= _number(before[name], label)
                            for name in ("r@1", "r@5", "mrr", "ndcg@10"))
                raw = _number(measured[key]["after_raw_precision_at_1"], label) >= \
                    _number(recorded[key]["before_raw_precision_at_1"], label)
                latency = _number(measured[key]["after_p95_ms"], label) <= \
                    _number(recorded[key]["before_p95_ms"], label)
                row["gate"] = _gate(same_n and ranks and raw and latency,
                                    "same denominator; every metric >= recorded baseline; p95 <= baseline")
            row["baseline"] = recorded[key]
        row["candidate"] = measured[key]
        results.append(row)
    return results


def _aggregate(gates: Sequence[dict[str, JsonValue]]) -> dict[str, JsonValue]:
    statuses = [gate["status"] for gate in gates]
    if "FAIL" in statuses:
        return _gate(False)
    if not statuses or "PENDING" in statuses:
        return _pending_gate("one or more required results are unavailable")
    return _gate(True)


def _startup_files(data: Mapping[str, JsonValue], root: Path) -> list[str]:
    """Materialize the unchanged round3 fixture expansion, outside every probe timer."""
    fixture = _mapping(data.get("startup"), "startup fixture")
    files: dict[str, str] = {}
    for record in _records(fixture.get("files"), "startup files"):
        name = _text(record.get("path"), "startup path")
        text = record.get("text")
        if not isinstance(text, str) or name in files:
            raise FrozenInputError(f"{name}: invalid or duplicate startup source")
        files[name] = text
    material = fixture.get("long_material", [])
    if not isinstance(material, list):
        raise FrozenInputError("startup long_material must be a list")
    for raw in material:
        record = _mapping(raw, "startup long_material")
        name = _text(record.get("path"), "startup long path")
        count = record.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0 or name not in files:
            raise FrozenInputError("invalid startup long_material expansion")
        template = _text(record.get("line_template"), "startup line_template")
        tail = record.get("tail")
        if not isinstance(tail, str):
            raise FrozenInputError("startup long_material tail must be a string")
        files[name] += "".join(template.format(i=index) for index in range(count)) + tail
    for name, text in files.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()):
            raise FrozenInputError(f"startup source escapes temporary root: {name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_bytes(text.encode("utf-8"))
    return list(files)


def paired_startup(
    data: Mapping[str, JsonValue], scorer: _FrozenScorer, measured: Mapping[str, JsonValue],
) -> dict[str, JsonValue]:
    """Ten fresh full/compact pairs, alternating order, with every raw observation."""
    from benchmarks.round4._startup_probe import full_context

    with tempfile.TemporaryDirectory(prefix="mnemosyne-r4-startup-") as directory:
        root = Path(directory)
        paths = _startup_files(data, root)
        full = full_context(root, paths)
        reader = configured_startup(root, COMPACT_STARTUP_MODE)
        compact = reader.read(paths).context
        if not reader.verify(compact, paths).complete:
            raise FrozenInputError("paired startup context is not complete")
        expected = {mode: raw_sha256(context.encode("utf-8"))
                    for mode, context in (("full", full), ("compact", compact))}
        sizes = {"full": scorer.context_size(full), "compact": scorer.context_size(compact)}
        recorded_compact = _mapping(measured.get("complete_context"), "startup.complete_context")
        if sizes["compact"] != recorded_compact:
            raise FrozenInputError("compact: paired context differs from unchanged startup scoring")
        # round3 full_read uses read_text, which normalizes CRLF. Keep those
        # unchanged observations, but use the probe's raw-byte full context for
        # the authoritative BPE comparison over the identical source closure.
        recorded_full = _mapping(measured.get("full_context"), "startup.full_context")
        samples: dict[str, list[float]] = {"full": [], "compact": []}
        pairs: list[JsonValue] = []
        for index in range(10):
            order = ["full", "compact"] if index % 2 == 0 else ["compact", "full"]
            observations: list[JsonValue] = []
            for mode in order:
                probe = round4_probe(root, paths, mode)
                elapsed = _number(probe["load_read_ms"], "paired startup load_read_ms")
                if elapsed < 0 or probe["context_sha256"] != expected[mode] or \
                        probe["paths"] != paths or Path(probe["root"]).resolve() != root.resolve():
                    raise FrozenInputError(f"{mode}: fresh probe did not measure the identical closure")
                samples[mode].append(elapsed)
                observations.append(_json_value(probe))
            pairs.append({"pair": index + 1, "order": list(order), "observations": observations})
    size_json: dict[str, JsonValue] = {mode: size for mode, size in sizes.items()}
    hash_json: dict[str, JsonValue] = {mode: digest for mode, digest in expected.items()}
    return {
        "pairs": pairs, "observations_per_mode": 10,
        "full_median_load_read_ms": statistics.median(samples["full"]),
        "compact_median_load_read_ms": statistics.median(samples["compact"]),
        "whole_context": size_json, "context_sha256": hash_json,
        "round3_full_context_size_matches_raw_full": sizes["full"] == recorded_full,
        "clock": "round4 probe load_read_ms; fresh process; installed bytecode allowed",
        "cleanup": "temporary startup closure removed",
    }


def _score_slice(
    scorer: _FrozenScorer, feature: str, data: Mapping[str, JsonValue],
    startup_mode: str, detection_mode: str,
) -> dict[str, JsonValue]:
    with _bound_scoring(scorer, startup_mode, detection_mode):
        match feature:
            case "startup":
                result = scorer.startup(data)
                expected = _records(_mapping(data.get("startup"), "startup").get("questions"),
                                    "startup questions")
            case "identity":
                result = scorer.identity(data)
                expected = _records(_mapping(data.get("identity"), "identity").get("questions"),
                                    "identity questions")
            case "consolidation":
                expected = _records(data.get("consolidation"), "consolidation cases")
                # The immutable scorer measures one unordered pair per case. A
                # larger inventory needs a different locked scorer, not a false
                # complete-recall claim from bool(questions[:20]).
                for case in expected:
                    titles, bodies = case.get("titles"), case.get("bodies")
                    if not isinstance(titles, list) or len(titles) != 2 or \
                            not isinstance(bodies, list) or len(bodies) != 2:
                        raise FrozenInputError("unchanged consolidation scorer requires two-note pair cases")
                result = scorer.consolidation(data)
            case _:
                raise FrozenInputError(f"unsupported required feature slice: {feature}")
    rows = _records(result.get("rows"), f"{feature} results")
    expected_ids = [_text(row.get("id"), f"{feature} case id") for row in expected]
    actual_ids = [_text(row.get("id"), f"{feature} result id") for row in rows]
    if result.get("author") != data.get("author") or sorted(actual_ids) != sorted(expected_ids) \
            or len(set(expected_ids)) != len(expected_ids):
        raise FrozenInputError(f"{feature}: scorer omitted, duplicated or misattributed cases")
    if feature == "consolidation":
        if any(not isinstance(row.get("gold_related"), bool)
               or not isinstance(row.get("after_detected"), bool) for row in rows):
            raise FrozenInputError("consolidation scorer returned invalid pair decisions")
        tp = sum(row["gold_related"] is True and row["after_detected"] is True for row in rows)
        fp = sum(row["gold_related"] is False and row["after_detected"] is True for row in rows)
        fn = sum(row["gold_related"] is True and row["after_detected"] is False for row in rows)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        if result.get("after_precision") != precision or result.get("after_recall") != recall:
            raise FrozenInputError("consolidation scorer denominator does not include every abstention")
        result["complete_counts"] = {
            "tp": tp, "fp": fp, "fn": fn, "cases": len(rows),
            "abstentions": sum(row["after_detected"] is False for row in rows),
            "scope": "complete two-note pair-case inventory; not capped mixed-vault recall",
        }
    return result


def _baseline(
    manifest: FrozenManifest,
) -> tuple[list[dict[str, JsonValue]], dict[str, JsonValue]]:
    config = manifest.get("recall_baseline", {})
    name = _text(config.get("path", "benchmarks/round3/results.json"), "recall baseline path")
    path = _resolve(name)
    if not path.is_file():
        return [], {"path": name, "status": "PENDING", "reason": "recorded recall baseline file missing"}
    raw = path.read_bytes()
    digest = raw_sha256(raw)
    declared = config.get("raw_sha256")
    if declared is not None:
        if digest != declared:
            raise FrozenInputError(f"{name}: recorded recall baseline hash mismatch")
    else:
        pinned = _pinned_blob_bytes(name)
        if pinned is None or normalize_blob(raw) != normalize_blob(pinned):
            raise FrozenInputError(f"{name}: recorded recall baseline must match the tracked blob")
    payload = _mapping(_json(raw.decode("utf-8")), "recorded recall baseline")
    rows = _records(payload.get("kibitzer"), "recorded baseline kibitzer")
    return rows, {"path": name, "raw_sha256": digest,
                  "source": "recorded round3 kibitzer.before, before_raw_precision_at_1, before_p95_ms"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bytecode_state() -> dict[str, JsonValue]:
    """Disclose existing cache bytes; do not remove allowed installed .pyc files."""
    paths = set(ROOT.rglob("*.pyc"))
    for name, module in tuple(sys.modules.items()):
        if name.startswith(("benchmarks.", "birkin_mnemosyne", "tiktoken")):
            cached: str | None = getattr(module, "__cached__", None)
            if cached is not None and Path(cached).is_file():
                paths.add(Path(cached))
    files: list[JsonValue] = [{"path": str(path), "sha256": raw_sha256(path.read_bytes())}
                             for path in sorted(paths)]
    return {"policy": "installed .pyc allowed; no cache purging or prewarming",
            "dont_write_bytecode": sys.dont_write_bytecode, "cache_tag": sys.implementation.cache_tag,
            "pycache_prefix": sys.pycache_prefix, "files": files}


def _tree_state() -> dict[str, JsonValue]:
    def git(*arguments: str) -> str:
        return subprocess.run(["git", "-C", str(ROOT), *arguments], check=True,
                              capture_output=True, text=True).stdout.strip()

    paths = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], check=True,
                           capture_output=True).stdout.decode("utf-8").split("\0")
    hashes: dict[str, JsonValue] = {}
    for name in sorted(path for path in paths if path):
        path = ROOT / name
        hashes[name] = raw_sha256(path.read_bytes()) if path.is_file() else None
    return {"head": git("rev-parse", "HEAD"), "git_tree": git("rev-parse", "HEAD^{tree}"),
            "status": git("status", "--porcelain"),
            "working_tree_sha256": raw_sha256(json.dumps(
                hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")),
            "tracked_working_files": hashes}


def sealed_evaluation(
    manifest_path: Path = DEFAULT_MANIFEST, *, root: Path = ROOT,
    startup_mode: str = COMPACT_STARTUP_MODE, detection_mode: str = SEMANTIC_DETECTION_MODE,
) -> dict[str, JsonValue]:
    """Score once on verified inputs; only the owner invokes this on real frozen data."""
    started = _utc_now()
    # Unchanged scorer modules use their own checkout globals. Reject verifying
    # one tree while scoring another; synthetic tests rebind ROOT explicitly.
    if root.resolve() != ROOT.resolve():
        raise FrozenInputError("scoring --root must be the scorer checkout; use a disposable checkout")
    bytecode_before = _bytecode_state()
    integrity = check_inputs(manifest_path, root=root)
    manifest = load_manifest(manifest_path)
    for module in SCORER_MODULES:
        relative = module.replace(".", "/") + ".py"
        if relative not in manifest["required_files"]:
            raise FrozenInputError(f"{relative}: immutable scorer is not hash-bound by the manifest")
    _ = validate_required_authors(root, manifest_path)
    required_recall = _required_recall(manifest)
    baseline, baseline_source = _baseline(manifest)
    if startup_mode not in (LEGACY_STARTUP_MODE, COMPACT_STARTUP_MODE) or \
            detection_mode not in (LEGACY_DETECTION_MODE, SEMANTIC_DETECTION_MODE):
        raise FrozenInputError("unknown explicit startup/detection mode")
    modes = integrity["modes"]
    compact = modes["startup"]["compact"]["available"]
    semantic = modes["detection"]["semantic"]["available"]
    threshold_hash = raw_sha256(THRESHOLDS_PATH.read_bytes()) if THRESHOLDS_PATH.is_file() else None
    semantic_pending = not semantic or threshold_hash is None
    if detection_mode == SEMANTIC_DETECTION_MODE and not semantic_pending:
        config = _mapping(_json(THRESHOLDS_PATH.read_text("utf-8")), "threshold config")
        if config.get("locked") is not True or not _mapping(config.get("thresholds"), "thresholds"):
            raise FrozenInputError("semantic scoring requires locked practice thresholds")
    manifest_hash = raw_sha256(manifest_path.read_bytes())
    tree_before = _tree_state()
    scorer = _load_scorer()
    observed = {(query.author, query.split, query.kind) for query in scorer.corpus.queries()}
    missing_recall = sorted(required_recall - observed)
    if missing_recall:
        raise FrozenInputError(f"missing required historical recall author/split/kind: {missing_recall}")
    authors: dict[str, JsonValue] = {}
    per_row: dict[str, list[dict[str, JsonValue]]] = {key: [] for key in ("IS-1", "IS-2", "IS-6")}
    try:
        for author, slices in sorted(manifest["required_authors"].items()):
            features: dict[str, JsonValue] = {}
            for feature, files in sorted(slices.items()):
                results: list[JsonValue] = []
                for name in files:
                    data = _mapping(_json(_resolve(name).read_text("utf-8")), name)
                    legacy = _score_slice(scorer, feature, data, LEGACY_STARTUP_MODE, LEGACY_DETECTION_MODE)
                    pending = (feature == "startup" and startup_mode == COMPACT_STARTUP_MODE and not compact) \
                        or (feature == "consolidation" and detection_mode == SEMANTIC_DETECTION_MODE
                            and semantic_pending)
                    result: dict[str, JsonValue] = {"file": name, "legacy": legacy}
                    if pending:
                        gate = _pending_gate(
                            "compact startup API unavailable" if feature == "startup" else
                            "semantic consolidation API or locked thresholds unavailable")
                        result["configured"] = gate
                        for key in (("IS-1", "IS-2") if feature == "startup" else ("IS-6",)):
                            per_row[key].append(gate)
                    else:
                        try:
                            candidate = _score_slice(scorer, feature, data, startup_mode, detection_mode)
                        except PendingProductSurfaceError as exc:
                            gate = _pending_gate(str(exc))
                            result["configured"] = gate
                            for key in (("IS-1", "IS-2") if feature == "startup" else ("IS-6",)):
                                per_row[key].append(gate)
                            results.append(result)
                            continue
                        result["configured"] = candidate
                        if feature == "startup":
                            timing = paired_startup(data, scorer, candidate) \
                                if startup_mode == COMPACT_STARTUP_MODE else None
                            result["paired_startup"] = timing
                            gates = startup_gates(candidate, timing)
                            result["gates"] = {key: gate for key, gate in gates.items()}
                            for key, gate in gates.items():
                                per_row[key].append(gate)
                        if feature == "consolidation":
                            gate = consolidation_gate(candidate)
                            result["gate"] = gate
                            per_row["IS-6"].append(gate)
                    results.append(result)
                features[feature] = results
            authors[author] = features
        recall = recall_gates(scorer.kibitzer(), baseline, required_recall)
    finally:
        # Detect drift even when a scorer raises, without replacing or editing it.
        after = check_frozen_files(manifest, root=root)
        if after != integrity["files"]:
            raise FrozenInputError("immutable input/scorer bytes changed during evaluation")
    tree_after = _tree_state()
    if tree_before != tree_after or raw_sha256(manifest_path.read_bytes()) != manifest_hash or \
            (raw_sha256(THRESHOLDS_PATH.read_bytes()) if THRESHOLDS_PATH.is_file() else None) != threshold_hash:
        raise FrozenInputError("tree, manifest or locked config changed during evaluation")
    if "raw_sha256" in baseline_source and \
            raw_sha256(_resolve(_text(baseline_source["path"], "baseline path")).read_bytes()) != \
            baseline_source["raw_sha256"]:
        raise FrozenInputError("recorded baseline changed during evaluation")
    gates = {f"IS-{index}": _pending_gate("outside the frozen scoring surface; separate QA required")
             for index in range(1, 11)}
    gates.update({key: _aggregate(values) for key, values in per_row.items()})
    gates["IS-4"] = _aggregate([_mapping(row["gate"], "recall gate") for row in recall])
    gates["IS-9"] = _gate(True, "inputs/scorers/tree/config unchanged; author-separated sealed evidence")
    measured_status = _aggregate([gates[key] for key in ("IS-1", "IS-2", "IS-4", "IS-6", "IS-9")])
    gate_json: dict[str, JsonValue] = {key: gate for key, gate in gates.items()}
    return {
        "sealed": True, "status": measured_status["status"], "gates": gate_json,
        "status_scope": "IS-1/IS-2/IS-4/IS-6/IS-9 frozen scoring only",
        "all_IS_status": _aggregate(list(gates.values()))["status"],
        "authors": authors, "historical_recall": list(recall),
        "integrity": _json_value(integrity), "baseline_source": baseline_source,
        "configuration": {"startup_mode": startup_mode, "detection_mode": detection_mode,
                          "thresholds_path": str(THRESHOLDS_PATH), "thresholds_sha256": threshold_hash},
        "provenance": {"tree_before": tree_before, "tree_after": tree_after,
                       "manifest_sha256": manifest_hash,
                       "manifest_source_tree_sha256": manifest.get("source_tree_sha256"),
                       "manifest_source_tree_sha256_missing": "source_tree_sha256" not in manifest,
                       "input_source_tree_sha256": integrity["source_tree_sha256"],
                       "interpreter": {"executable": sys.executable, "version": sys.version,
                                       "platform": platform.platform()},
                       "bytecode_before": bytecode_before, "bytecode_after": _bytecode_state()},
        "started_at": started, "finished_at": _utc_now(),
        "pending_product_surfaces": {
            key: {"status": "AVAILABLE" if available else "PENDING", "surface": value["surface"]}
            for key, value, available in (
                ("compact-startup", PENDING_PRODUCT_SURFACES["compact-startup"], compact),
                ("semantic-consolidation", PENDING_PRODUCT_SURFACES["semantic-consolidation"],
                 not semantic_pending))},
        "scope": "fixed context-only extraction and complete pair-case discovery; " +
                 "historical raw P@1 and sibling-filtered metrics remain distinct; no author averaging",
    }


def _gates_path(output: Path) -> Path:
    return output.with_name(output.stem.removesuffix("-results") + "-gates.json")


def _write_sealed(path: Path, result: Mapping[str, JsonValue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        _ = stream.write(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False) + "\n")


class _Arguments(argparse.Namespace):
    """Mutable argument carrier populated by argparse, with concrete field types."""

    check_inputs_only: bool = False
    manifest: Path = DEFAULT_MANIFEST
    root: Path = ROOT
    output: Path | None = None
    startup_mode: str = COMPACT_STARTUP_MODE
    detection_mode: str = SEMANTIC_DETECTION_MODE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument("--check-inputs-only", action="store_true",
                        help="verify the frozen manifest; never runs scoring")
    _ = parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    _ = parser.add_argument("--root", type=Path, default=ROOT,
                        help="tree to verify (default: the repository this guard ships in)")
    _ = parser.add_argument("--output", type=Path, default=None)
    _ = parser.add_argument("--startup-mode", default=COMPACT_STARTUP_MODE)
    _ = parser.add_argument("--detection-mode", default=SEMANTIC_DETECTION_MODE)
    args = _Arguments()
    _ = parser.parse_args(argv, namespace=args)

    if not args.check_inputs_only:
        if args.output is None:
            parser.error("--output is required for sealed scoring")
        try:
            gates_path = _gates_path(args.output)
            if args.output.exists() or gates_path.exists():
                raise FrozenInputError("sealed output already exists; refusing to overwrite evidence")
            sealed = sealed_evaluation(args.manifest, root=args.root,
                                       startup_mode=args.startup_mode,
                                       detection_mode=args.detection_mode)
            _write_sealed(args.output, sealed)
            summary: dict[str, JsonValue] = {
                "status": sealed["status"], "gates": sealed["gates"],
                "status_scope": sealed["status_scope"], "all_IS_status": sealed["all_IS_status"],
                "output": str(args.output), "gates_output": str(gates_path),
            }
            _write_sealed(gates_path, summary)
        except (FrozenInputError, OSError, ValueError, ImportError, subprocess.SubprocessError) as exc:
            print(json.dumps({"status": "FAIL", "reason": str(exc)}), file=sys.stderr)
            return 1
        print(json.dumps(summary, ensure_ascii=True))
        return 0 if sealed["status"] == "PASS" else 2
    try:
        report = check_inputs(args.manifest, root=args.root)
    except FrozenInputError as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}), file=sys.stderr)
        return 1
    text = json.dumps(report, indent=2, ensure_ascii=True)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        _ = args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
