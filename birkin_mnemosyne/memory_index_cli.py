"""First-run onboarding, checker, splitter and handoff commands for the memory INDEX.

Three commands over one vault:

* ``init`` previews deterministic onboarding, or applies additive writes and
  journaled frontmatter completion only with ``--apply``.
* ``check`` reports orphan documents, dangling routes, and lost coverage as
  JSON (the ``IndexCheck`` fields plus ``ok``) and never writes.
* ``split`` previews a lossless note split by default, or applies it with
  ``--apply``, printing the source digest and the complete coverage table.

The ``handoff`` family adds immutable scoped session memory: ``capture``
publishes a record from flags or JSON stdin, ``latest`` prints the newest
capture, ``resume`` prints the complete StartupReader bundle with INDEX and
latest handoff, ``fold`` previews or applies curation-gated retention, and
``undo`` restores one fold through the checked journal.

Invalid input, reads, and migrations surface as a clear stderr message and
exit status 2; a failed ``check`` exits 1 and an absent latest handoff
exits 1. Nothing else is caught.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from io import TextIOWrapper

from .handoff_cli import HandoffArguments, add_handoff_parser, run_handoff
from .handoff_records import HandoffError
from .memory_index import MemoryIndexError
from .memory_index_integrity import check_index
from .memory_index_migration import format_coverage, split_note
from .onboarding import run_init
from .onboarding_plan import plan_init
from .review_journal import ReviewError
from .startup import StartupError

INVALID_EXIT = 2


class _Arguments(HandoffArguments):
    """Typed parse result; attribute defaults mirror the parser defaults."""

    vault: str | None = None
    init_vault: str | None = None
    import_dir: str | None = None
    command: str | None = None
    note: str | None = None
    apply: bool = False
    max_tokens: int | None = None
    enable_handoff: bool = False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mnemosyne",
        description="Initialize a vault, check its INDEX, or split one note into routed topics.",
        allow_abbrev=False,
    )
    _ = parser.add_argument("--vault", type=str, help="vault root directory")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser(
        "init", help="preview or apply deterministic first-run onboarding", allow_abbrev=False,
    )
    _ = init.add_argument("--vault", dest="init_vault", help="vault root; defaults to current directory")
    _ = init.add_argument("--import", dest="import_dir", help="external plain-Markdown directory")
    _ = init.add_argument("--apply", action="store_true", help="authorize additive and journaled writes")
    _ = init.add_argument("--max-tokens", type=int, default=None, help="INDEX estimated-token budget")
    _ = init.add_argument("--enable-handoff", action="store_true",
                          help="enable managed scoped handoff memory on explicit apply")

    _ = commands.add_parser(
        "check", help="report orphans, dangling routes, and lost coverage", allow_abbrev=False,
    )
    split = commands.add_parser(
        "split", help="preview or apply a lossless note split", allow_abbrev=False,
    )
    _ = split.add_argument("note", help="vault-relative path of the .md note to split")
    _ = split.add_argument("--apply", action="store_true", help="write the split; default is preview")
    _ = split.add_argument(
        "--max-tokens", type=int, default=None, help="INDEX budget to enforce while registering",
    )
    add_handoff_parser(commands)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if isinstance(stream, TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parser = _build_parser()
    arguments = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(arguments, namespace=_Arguments())
    assert args.command is not None
    if args.command == "init":
        if sum(argument.split("=", 1)[0] == "--vault" for argument in arguments) > 1:
            parser.error("supply --vault only once")
        args.vault = args.init_vault or args.vault or "."
    elif args.vault is None:
        parser.error("--vault is required for check, split and handoff")
    assert args.vault is not None
    try:
        if args.command == "init":
            report = run_init(plan_init(args.vault, import_dir=args.import_dir,
                                        max_tokens=args.max_tokens,
                                        enable_handoff=args.enable_handoff), apply=args.apply)
            print(json.dumps(asdict(report), ensure_ascii=False))
            return 0 if not args.apply or report.ok else 1
        if args.command == "check":
            checked = check_index(args.vault)
            payload = asdict(checked)
            payload["ok"] = checked.ok
            print(json.dumps(payload, ensure_ascii=False))
            return 0 if checked.ok else 1
        if args.command == "handoff":
            return run_handoff(args, arguments, parser)

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
    except (HandoffError, MemoryIndexError, ReviewError, StartupError,
            OSError, UnicodeError) as exc:
        print(f"{parser.prog}: {exc}", file=sys.stderr)
        return INVALID_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
