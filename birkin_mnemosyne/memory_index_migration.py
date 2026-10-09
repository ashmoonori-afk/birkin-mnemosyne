"""Explicit, lossless Markdown-note splitting with an auditable line map."""

from __future__ import annotations

import json
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from pathlib import Path

from .atomic import atomic_write_bytes
from .identity_reader import parse_sections
from .memory_index import (
    IndexEntry,
    MemoryIndex,
    MemoryIndexError,
    validate_index_budget,
)
from .mnemosyne import slug
from .review_journal import Change, commit
from .startup import source_blocks
from .startup_coverage import digest
from .vault_lock import VaultLock

NOTICE_PREFIX = "<!-- mnemosyne-memory-index split:"


@dataclass(frozen=True, slots=True)
class TopicSpan:
    trigger: str
    document: str
    start_byte: int
    end_byte: int
    prefix_bytes: int


@dataclass(frozen=True, slots=True)
class RuleLocation:
    line: int
    text: str
    document: str
    document_line: int


@dataclass(frozen=True, slots=True)
class SplitReport:
    source: str
    source_sha256: str
    source_bytes: int
    topics: tuple[TopicSpan, ...]
    coverage: tuple[RuleLocation, ...]
    applied: bool
    coverage_receipt: str | None
    backup_journal: str | None


def split_note(
    root: str | Path, document: str, *, apply: bool = False,
    max_tokens: int | None = None,
) -> SplitReport:
    """Preview by default; preserve every byte before replacing the source.

    Topics and additive routes precede the source change. The existing review
    journal records the original before that change and supports checked undo.
    Failures can leave new topics/routes, but never silently erase source text.
    """
    index = MemoryIndex(root)
    with VaultLock(index.root).hold() if apply else nullcontext():
        _ = index.read()
        if max_tokens is not None:
            _ = validate_index_budget(max_tokens)
        source = index.document_path(document)
        if source.suffix != ".md":
            raise MemoryIndexError("split_note requires a .md note")
        raw = source.read_bytes()
        text = raw.decode("utf-8")
        if text.startswith(NOTICE_PREFIX):
            raise MemoryIndexError("note is already a routing notice; inspect its coverage receipt")
        relative = source.relative_to(index.root).as_posix()
        identifier = digest(relative.encode("utf-8") + b"\0" + raw)
        sections = {s.line_start: s for s in parse_sections(text, startup_labels=True)}
        topics: list[TopicSpan] = []
        contents: list[bytes] = []
        coverage: list[RuleLocation] = []
        blocks = sorted(source_blocks(relative, raw), key=lambda block: block["start_byte"])
        cursor = 0
        for number, block in enumerate(blocks):
            start, end = block["start_byte"], block["end_byte"]
            if start != cursor:
                raise MemoryIndexError("source partition has a gap or overlap")
            cursor = end
            section = sections.get(block["start_line"])
            heading = block["heading"]
            trigger = (source.stem if heading in {"Preamble", "Source preamble", "Source remainder"}
                       else heading) or source.stem
            target = f"topics/{slug(source.stem)[:24]}-{identifier[:12]}-{number:03d}.md"
            _ = IndexEntry(trigger, target)
            prefix = (
                f"<!-- Original source: {json.dumps(relative, ensure_ascii=False)}; "
                "local references remain relative to that source. -->\n"
            )
            if section is not None:
                prefix += "".join(
                    f"{'#' * level} {ancestor}\n"
                    for level, ancestor in enumerate(section.ancestry, 1)
                )
            prefix_raw = prefix.encode("utf-8")
            topics.append(TopicSpan(trigger, target, start, end, len(prefix_raw)))
            contents.append(prefix_raw + raw[start:end])
            first_line = block["start_line"]
            for offset, line in enumerate(raw[start:end].decode("utf-8").splitlines(keepends=True)):
                coverage.append(RuleLocation(
                    first_line + offset, line, target,
                    len(prefix.splitlines()) + offset + 1,
                ))
        if cursor != len(raw) or b"".join(
            content[topic.prefix_bytes:] for topic, content in zip(topics, contents)
        ) != raw:
            raise MemoryIndexError("split failed complete source-byte coverage")
        if not apply:
            return SplitReport(relative, digest(raw), len(raw), tuple(topics),
                               tuple(coverage), False, None, None)

        targets = [index.document_path(topic.document) for topic in topics]
        receipt_dir = index.directory / "splits"
        if receipt_dir.is_symlink():
            raise MemoryIndexError("split receipts must not be a symlink")
        receipt_path = receipt_dir / f"{identifier}.json"
        for path in (*targets, receipt_path):
            if path.exists() or path.is_symlink():
                raise MemoryIndexError(
                    f"split destination already exists: {path.relative_to(index.root).as_posix()}")
        for path, content in zip(targets, contents):
            atomic_write_bytes(path, content)
        for topic in topics:
            _ = index.register(topic.trigger, topic.document, max_tokens=max_tokens)
        registered = set(index.read().entries)
        if any(IndexEntry(t.trigger, t.document) not in registered for t in topics):
            raise MemoryIndexError("a split topic is missing from the INDEX")
        recovered = b"".join(
            path.read_bytes()[topic.prefix_bytes:]
            for path, topic in zip(targets, topics)
        )
        if recovered != raw:
            raise MemoryIndexError("written topics failed complete source-byte coverage")
        notice = (
            f"{NOTICE_PREFIX}{identifier} -->\n"
            "# Memory details\n"
            "Read the always-loaded Memory INDEX for the complete trigger map. "
            "Original details are preserved in its topic documents.\n"
        ).encode()
        receipt = {
            "version": 1, "source": relative, "source_sha256": digest(raw),
            "source_bytes": len(raw), "notice_sha256": digest(notice),
            "topics": [asdict(topic) for topic in topics],
        }
        atomic_write_bytes(receipt_path, (
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"))
        backup = commit(
            index.root, f"memory-index-split:{identifier}", "memory-index-split",
            "", relative, (Change(relative, relative, raw, notice),),
        )
        return SplitReport(
            relative, digest(raw), len(raw), tuple(topics), tuple(coverage), True,
            receipt_path.relative_to(index.root).as_posix(), backup.journal_path,
        )


def format_coverage(report: SplitReport) -> str:
    """Print every original line, escaped for a readable one-line table row."""
    lines = [
        "| Source line | Original text (escaped) | Topic document | Topic line |",
        "| --- | --- | --- | --- |",
    ]
    for row in report.coverage:
        text = repr(row.text)[1:-1].replace("|", "\\|")
        lines.append(f"| {row.line} | {text} | {row.document} | {row.document_line} |")
    return "\n".join(lines)
