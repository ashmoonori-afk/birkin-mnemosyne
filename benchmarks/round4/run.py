"""Round-4 immutable evaluation protocol: integrity guard and explicit modes.

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

Both delegations therefore stay parked in
:data:`PENDING_PRODUCT_SURFACES`: the wrapper refuses the configured modes and
says exactly what is pending instead of silently falling back to the legacy
implementation. A delegating adapter is added only once the product API is
available on the review base.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
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


def validate_required_authors(frozen_root: Path | None = None) -> list[_AuthorSlice]:
    """Validate declared author identity and required feature slices.

    Called by the locked round-4 evaluation (plan T15), not by the integrity
    check: this function reads frozen question payloads to confirm that every
    required author and slice is present. It is testable against a disposable
    copy, so the protocol is proven without consuming the real frozen rows.
    """
    manifest = load_manifest(DEFAULT_MANIFEST)
    base = ROOT if frozen_root is None else frozen_root
    checked: list[_AuthorSlice] = []
    for author, slices in sorted(manifest["required_authors"].items()):
        for slice_name, files in sorted(slices.items()):
            for relative in files:
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
        raise FrozenInputError(
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
                    raise FrozenInputError("semantic question pipeline is not ready")
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


class _Arguments(argparse.Namespace):
    """Mutable argument carrier populated by argparse, with concrete field types."""

    check_inputs_only: bool = False
    manifest: Path = DEFAULT_MANIFEST
    root: Path = ROOT
    output: Path | None = None
    startup_mode: str = LEGACY_STARTUP_MODE
    detection_mode: str = LEGACY_DETECTION_MODE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument("--check-inputs-only", action="store_true",
                        help="verify the frozen manifest; never runs scoring")
    _ = parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    _ = parser.add_argument("--root", type=Path, default=ROOT,
                        help="tree to verify (default: the repository this guard ships in)")
    _ = parser.add_argument("--output", type=Path, default=None)
    _ = parser.add_argument("--startup-mode", default=LEGACY_STARTUP_MODE)
    _ = parser.add_argument("--detection-mode", default=LEGACY_DETECTION_MODE)
    args = _Arguments()
    _ = parser.parse_args(argv, namespace=args)

    if not args.check_inputs_only:
        parser.error("exactly one action is required; round4 --check-inputs-only is the " +
                     "T1 integrity action and scoring belongs to the locked evaluation")
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
