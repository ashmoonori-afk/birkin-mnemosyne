"""Checked fold receipts and exclusive summary staging in the existing journal."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Iterator
from pathlib import Path

from .atomic import atomic_create_bytes
from .handoff_files import safe_path
from .handoff_models import FoldResult, FoldSource, HandoffScope
from .handoff_records import scope_directory
from .review_journal import JsonValue, Manifest, ReviewError, _decode_manifest, _safe

REVIEWS_DIRECTORY = ".mnemosyne-reviews"
FOLD_PREFIX = "handoff:fold:"
_json: Callable[[str], JsonValue] = json.loads


def _reviews(vault: Path) -> Iterator[Manifest]:
    root = vault / REVIEWS_DIRECTORY
    safe_path(vault, root)
    if not root.exists():
        return
    for path in sorted(root.glob("*.json")):
        safe_path(vault, path)
        try:
            yield _decode_manifest(path.read_text(encoding="utf-8"))
        except (UnicodeError, OSError) as exc:
            raise ReviewError(f"cannot read fold journal: {path.name}") from exc


def fold_state(vault: Path, scope: HandoffScope) -> str:
    prefix = f"{FOLD_PREFIX}{scope_directory(scope)}:"
    rows = [
        (manifest["question_id"], manifest["state"])
        for manifest in _reviews(vault) if manifest["question_id"].startswith(prefix)
    ]
    return hashlib.sha256(json.dumps(
        rows, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def question_id(scope: HandoffScope, plan_id: str) -> str:
    return f"{FOLD_PREFIX}{scope_directory(scope)}:{plan_id}"


def fold_reviews(
    vault: Path, scope: HandoffScope, plan_id: str,
) -> tuple[Manifest | None, Manifest | None]:
    prefix, target = f"{FOLD_PREFIX}{scope_directory(scope)}:", question_id(scope, plan_id)
    pending: Manifest | None = None
    committed: Manifest | None = None
    for manifest in _reviews(vault):
        if not manifest["question_id"].startswith(prefix):
            continue
        if manifest["state"] in ("prepared", "recovery-required"):
            pending = manifest
        elif manifest["state"] == "committed" and manifest["question_id"] == target:
            committed = manifest
    return pending, committed


def _committed_images_agree(vault: Path, manifest: Manifest) -> bool:
    if not manifest["changes"]:
        return False
    for image in manifest["changes"]:
        source, target = _safe(vault, image["source"]), _safe(vault, image["target"])
        try:
            before = base64.b64decode(image["before"], validate=True)
            after = base64.b64decode(image["after"], validate=True)
        except ValueError:
            return False
        if hashlib.sha256(before).hexdigest() != image["before_sha256"] or \
                hashlib.sha256(after).hexdigest() != image["after_sha256"]:
            return False
        if source.exists() or not target.is_file() or target.read_bytes() != after:
            return False
    return True


def _source(value: JsonValue) -> FoldSource:
    match value:
        case {"path": str() as path, "sha256": str() as digest,
              "recorded_at": str() as stamp, "reason": str() as reason}:
            return FoldSource(path, digest, stamp, reason)
        case _:
            raise ReviewError("malformed saved fold source")


def replay_result(vault: Path, manifest: Manifest, plan_id: str, keep: int) -> FoldResult:
    """Return the original report, not a new preview mislabeled as the old fold."""
    if not _committed_images_agree(vault, manifest):
        raise ReviewError("committed fold images changed; refusing idempotent retry")
    try:
        saved = _json(manifest["merged_body"])
    except ValueError as exc:
        raise ReviewError("malformed saved fold report") from exc
    match saved:
        case {
            "keep": int() as saved_keep,
            "result": {
                "plan_id": str() as saved_id,
                "accepted": list() as accepted,
                "rejected": list() as rejected,
                "pinned": pinned,
                "summary": str() as summary, "summary_sha256": str() as summary_hash,
                "plan_archive_cap": int() as cap,
            },
        } if type(saved_keep) is int and type(cap) is int:
            if saved_id != plan_id or saved_keep != keep:
                raise ReviewError("fold retry does not match the committed request")
            sources = tuple(_source(source) for source in accepted)
            expected = tuple((image["source"], image["before_sha256"])
                             for image in manifest["changes"][:-1])
            raw_summary = base64.b64decode(manifest["changes"][-1]["after"], validate=True)
            if tuple((source.path, source.sha256) for source in sources) != expected or \
                    summary.encode("utf-8") != raw_summary or \
                    summary_hash != hashlib.sha256(raw_summary).hexdigest():
                raise ReviewError("saved fold report does not match its journal images")
            return FoldResult(
                saved_id, sources, tuple(_source(source) for source in rejected),
                None if pinned is None else _source(pinned),
                summary, summary_hash, cap, manifest["transaction_id"], "idempotent",
                f"{REVIEWS_DIRECTORY}/{manifest['transaction_id']}.json",
            )
        case _:
            raise ReviewError("malformed saved fold report")


def stage_summary(vault: Path, staging: Path, raw: bytes) -> None:
    safe_path(vault, vault / REVIEWS_DIRECTORY)
    safe_path(vault, staging)
    if staging.exists():
        if staging.read_bytes() != raw:
            raise ReviewError(f"staged fold summary conflict: {staging.relative_to(vault)}")
        return
    try:
        atomic_create_bytes(staging, raw)
    except FileExistsError as exc:
        raise ReviewError("staged fold summary already exists") from exc
