"""Explicit, recoverable application of a captured first-run plan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .atomic import atomic_create_bytes
from .handoffs import HandoffStore
from .import_candidates import scan_import
from .memory_index import MemoryIndex, MemoryIndexError
from .memory_index_integrity import check_index
from .memory_triggers import IndexEntry
from .onboarding_notes import inventory
from .onboarding_plan import InitPlan
from .onboarding_state import existing_state
from .review_journal import Change, ReviewError, commit
from .startup import StartupReader
from .startup_coverage import digest
from .vault_lock import VaultLock


@dataclass(frozen=True, slots=True)
class SourceAction:
    path: str
    before_sha256: str
    after_sha256: str
    frontmatter_additions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewItem:
    id: str
    first: str
    second: str
    reason: str
    similarity: float


@dataclass(frozen=True, slots=True)
class InitReport:
    mode: Literal["preview", "applied"]
    ok: bool
    notes: int
    imports: int
    topics: int
    index_tokens: int
    index_mode: str
    warning_count: int
    warnings: tuple[str, ...]
    mutations: int
    sources: tuple[SourceAction, ...]
    import_documents: tuple[str, ...]
    topic_documents: tuple[str, ...]
    routes: tuple[IndexEntry, ...]
    review_questions: tuple[ReviewItem, ...]
    review_limit: int
    review_truncated: bool
    journal: str | None
    undo_transaction: str | None
    verification: Literal["planned", "passed", "failed"]
    verification_scope: Literal["resident-index"]
    enable_handoff: bool
    handoff_enabled: bool
    label_counts: tuple[tuple[str, int], ...]


def run_init(plan: InitPlan, *, apply: bool = False) -> InitReport:
    """Preview by default; retain additive artifacts and journal source changes."""
    index = MemoryIndex(plan.root)
    view = plan.projected
    warnings = list(plan.warnings)
    journal = None
    undo_transaction = None
    verification: Literal["planned", "passed", "failed"] = "planned"
    ok = not plan.state.recovery
    changes = tuple(Change(note.path, note.path, note.raw, note.normalized)
                    for note in plan.notes if note.raw != note.normalized)
    previous_routes = set(plan.state.view.entries)
    missing_catalogues = tuple(document for document in plan.catalogues
                               if document.path not in {source.path for source in plan.originals})
    mutations = (
        sum(copy.existing is None for copy in plan.imports) + len(missing_catalogues)
        + sum(route not in previous_routes for route in plan.routes) + len(changes)
        + int(not plan.state.view.enabled or plan.state.view.max_tokens != view.max_tokens)
        + int(plan.enable_handoff and not plan.handoff_config.enabled)
    )
    if apply:
        with VaultLock(plan.root).hold():
            if inventory(plan.root) != plan.originals or existing_state(index) != plan.state:
                raise ReviewError("onboarding inputs changed; preview a fresh plan")
            if plan.state.recovery:
                raise ReviewError("checked recovery required: " + ", ".join(plan.state.recovery))
            if plan.enable_handoff and \
                    HandoffStore(plan.root).settings() != plan.handoff_config:
                raise ReviewError("handoff settings changed; preview a fresh plan")
            if plan.import_root is not None:
                try:
                    live = scan_import(plan.import_root)
                except MemoryIndexError as exc:
                    raise ReviewError("import source selection changed; preview a fresh plan") from exc
                expected = sorted((copy.source_label, copy.preimage) for copy in plan.imports)
                actual = sorted((item.relative, item.preimage) for item in live)
                if expected != actual:
                    raise ReviewError("import source selection changed; preview a fresh plan")
            for copy in plan.imports:
                target = index.document_path(copy.destination.path)
                current = target.read_bytes() if target.exists() else None
                if current != copy.existing:
                    raise ReviewError(f"import destination changed: {copy.destination.path}")
            _ = index.enable(max_tokens=view.max_tokens)
            if plan.enable_handoff:
                _ = HandoffStore(plan.root).enable()
            for copy in plan.imports:
                if copy.existing is None:
                    atomic_create_bytes(index.document_path(copy.destination.path),
                                        copy.destination.raw)
            for document in missing_catalogues:
                atomic_create_bytes(index.document_path(document.path), document.raw)
            for route in plan.routes:
                _ = index.register(route.trigger, route.document)
            if changes:
                identity = digest(b"".join(
                    change.source.encode("utf-8") + b"\0" + change.before + b"\0" + change.after
                    for change in changes
                ))
                receipt = commit(plan.root, f"init-normalize:{identity}",
                                 "mnemosyne-init-normalize", "", "", changes)
                journal, undo_transaction = receipt.journal_path, receipt.transaction_id
            reader = StartupReader(plan.root, require_index=True)
            bundle = reader.read([])
            coverage = reader.verify(bundle.context, [])
            checked = check_index(plan.root)
            ok = coverage.complete and checked.ok
            verification = "passed" if ok else "failed"
            view = index.read()
            warnings.extend((*view.warnings, *coverage.warnings, *checked.warnings))
    unique_warnings = tuple(dict.fromkeys(warnings))
    enabled_state = plan.handoff_config.enabled
    if apply and plan.enable_handoff:
        enabled_state = HandoffStore(plan.root).settings().enabled
    return InitReport(
        "applied" if apply else "preview", ok, len(plan.notes), len(plan.imports),
        len(plan.catalogues), view.estimated_tokens, view.mode, len(unique_warnings),
        unique_warnings, mutations,
        tuple(SourceAction(note.path, digest(note.raw), digest(note.normalized), note.additions)
              for note in plan.notes),
        tuple(copy.destination.path for copy in plan.imports),
        tuple(document.path for document in plan.catalogues), plan.routes,
        tuple(ReviewItem(question.id, question.first.path, question.second.path,
                         question.reason, question.similarity) for question in plan.questions),
        20, plan.questions_truncated, journal, undo_transaction, verification, "resident-index",
        plan.enable_handoff, enabled_state, plan.label_counts,
    )
