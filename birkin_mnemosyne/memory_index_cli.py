"""Command-line checker and splitter for the always-loaded memory INDEX.

Two commands over one vault:

* ``check`` reports orphan documents, dangling routes, and lost coverage as
  JSON (the ``IndexCheck`` fields plus ``ok``) and never writes.
* ``split`` previews a lossless note split by default, or applies it with
  ``--apply``, printing the source digest and the complete coverage table.

Invalid input, reads, and migrations surface as a clear stderr message and
exit status 2; a failed ``check`` exits 1. Nothing else is caught.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from io import TextIOWrapper

from .memory_index import MemoryIndexError
from .memory_index_integrity import check_index
from .memory_index_migration import format_coverage, split_note
from .review_journal import ReviewError

INVALID_EXIT = 2


class _Arguments(argparse.Namespace):
    """Typed parse result; attribute defaults mirror the parser defaults."""

    vault: str | None = None
    command: str | None = None
    note: str | None = None
    apply: bool = False
    max_tokens: int | None = None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mnemosyne-index",
        description="Check the memory INDEX or split one note into routed topics.",
    )
    _ = parser.add_argument("--vault", type=str, required=True, help="vault root directory")
    commands = parser.add_subparsers(dest="command", required=True)
    _ = commands.add_parser("check", help="report orphans, dangling routes, and lost coverage")
    split = commands.add_parser("split", help="preview or apply a lossless note split")
    _ = split.add_argument("note", help="vault-relative path of the .md note to split")
    _ = split.add_argument("--apply", action="store_true", help="write the split; default is preview")
    _ = split.add_argument(
        "--max-tokens", type=int, default=None, help="INDEX budget to enforce while registering",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    args = _build_parser().parse_args(argv, namespace=_Arguments())
    assert args.vault is not None and args.command is not None
    try:
        if args.command == "check":
            checked = check_index(args.vault)
            payload = asdict(checked)
            payload["ok"] = checked.ok
            print(json.dumps(payload, ensure_ascii=False))
            return 0 if checked.ok else 1

        assert args.note is not None
        report = split_note(args.vault, args.note, apply=args.apply,
                            max_tokens=args.max_tokens)
        print(f"source: {report.source}")
        print(f"sha256: {report.source_sha256}")
        print(f"bytes: {report.source_bytes}")
        print(f"mode: {'applied' if report.applied else 'preview'}")
        print(format_coverage(report))
        if report.applied:
            print(f"receipt: {report.coverage_receipt}")
            print(f"journal: {report.backup_journal}")
        return 0
    except (MemoryIndexError, ReviewError, OSError, UnicodeError) as exc:
        print(f"mnemosyne-index: {exc}", file=sys.stderr)
        return INVALID_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
