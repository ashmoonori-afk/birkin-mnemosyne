"""Read-only orphan, dangling-route, and lossless-migration coverage checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .memory_index import IndexEntry, MemoryIndex, MemoryIndexError, decode_index_json
from .memory_index_migration import TopicSpan
from .startup_coverage import digest


@dataclass(frozen=True, slots=True)
class IndexCheck:
    enabled: bool
    entries: int
    documents: int
    orphan_documents: tuple[str, ...]
    dangling_entries: tuple[IndexEntry, ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not (self.orphan_documents or self.dangling_entries or self.errors)


def _coverage_source(index: MemoryIndex, path: Path, entries: set[IndexEntry]) -> str:
    """Validate an untrusted receipt and reconstruct its original source bytes."""
    if path.is_symlink():
        raise MemoryIndexError("coverage receipt must not be a symlink")
    try:
        data = decode_index_json(path.read_bytes().decode("utf-8"))
    except ValueError as exc:
        raise MemoryIndexError("invalid coverage JSON") from exc
    match data:
        case {
            "version": version, "source": str() as source,
            "source_sha256": str() as original_hash, "source_bytes": int() as size,
            "notice_sha256": str() as notice_hash, "topics": list() as rows,
        }:
            if type(version) is not int or version != 1 or type(size) is not int or size < 0:
                raise MemoryIndexError("invalid coverage receipt version or size")
            assembled = bytearray()
            cursor = 0
            for row in rows:
                match row:
                    case {
                        "trigger": str() as trigger, "document": str() as document,
                        "start_byte": int() as start, "end_byte": int() as end,
                        "prefix_bytes": int() as prefix,
                    }:
                        if any(type(n) is not int for n in (start, end, prefix)) or \
                                start != cursor or end < start or end > size or prefix < 0:
                            raise MemoryIndexError("coverage ranges have a gap, overlap, or invalid bound")
                        topic = TopicSpan(trigger, document, start, end, prefix)
                        if IndexEntry(topic.trigger, topic.document) not in entries:
                            raise MemoryIndexError(f"original rules lack an INDEX entry: {document}")
                        raw = index.document_path(document).read_bytes()
                        if len(raw) < prefix + end - start:
                            raise MemoryIndexError(f"topic is truncated: {document}")
                        assembled.extend(raw[prefix:prefix + end - start])
                        cursor = end
                    case _:
                        raise MemoryIndexError("invalid coverage topic record")
            if not rows or cursor != size or digest(bytes(assembled)) != original_hash:
                raise MemoryIndexError("original source bytes no longer reconstruct")
            source_hash = digest(index.document_path(source).read_bytes())
            if source_hash not in {original_hash, notice_hash}:
                raise MemoryIndexError(f"source contains unaccounted changes: {source}")
            return source
        case _:
            raise MemoryIndexError("invalid coverage receipt")


def check_index(root: str | Path) -> IndexCheck:
    """Report every visible active Markdown document without a route and broken routes."""
    index = MemoryIndex(root)
    documents: set[str] = set()
    for node in sorted(index.root.iterdir()):
        if node.name.startswith(".") or node.name == "_archive" or node.is_symlink():
            continue
        candidates = [node] if node.is_file() else list(node.iterdir()) if node.is_dir() else []
        for path in candidates:
            if path.suffix == ".md" and not path.name.startswith(".") and \
                    not path.is_symlink() and path.is_file():
                documents.add(path.relative_to(index.root).as_posix())
    errors: list[str] = []
    try:
        view = index.read()
    except MemoryIndexError as exc:
        return IndexCheck(True, 0, len(documents), tuple(sorted(documents)), (), (str(exc),))
    linked = {entry.document for entry in view.entries}
    dangling: list[IndexEntry] = []
    for entry in view.entries:
        try:
            _ = index.document_path(entry.document).read_bytes().decode("utf-8")
        except (MemoryIndexError, OSError, UnicodeError):
            dangling.append(entry)
    managed_sources: set[str] = set()
    receipts = index.directory / "splits"
    if receipts.is_symlink():
        errors.append("split receipts must not be a symlink")
    else:
        for path in sorted(receipts.glob("*.json")):
            try:
                managed_sources.add(_coverage_source(index, path, set(view.entries)))
            except (MemoryIndexError, OSError, UnicodeError) as exc:
                detail = exc.strerror if isinstance(exc, OSError) else str(exc)
                errors.append(f"{path.relative_to(index.root).as_posix()}: {detail}")
    return IndexCheck(
        view.enabled, len(view.entries), len(documents),
        tuple(sorted(documents - linked - managed_sources)), tuple(dangling), tuple(errors),
    )
