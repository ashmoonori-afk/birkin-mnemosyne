"""Handoff command family for the mnemosyne CLI.

``mnemosyne --vault V handoff capture|latest|resume|fold|undo``:

* ``capture`` publishes one immutable scoped handoff from flags or a matching
  ``--json-stdin`` payload; nothing is written unless the request validates.
* ``latest`` prints the complete newest capture for a scope, or exits 1.
* ``resume`` prints the actual StartupReader bundle: complete INDEX plus the
  latest handoff, plus every lexical ``--task`` match.
* ``fold`` previews curation-gated retention by default; ``--apply`` requires
  the exact ``--plan-id`` of a fresh preview.
* ``undo`` restores a committed or prepared fold through the checked journal.

Success exits 0, invalid input exits 2 with a useful stderr message, and a
missing latest capture exits 1. Only required_scope resolves project/task
identity; no shared active scope is ever written into the vault.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from .consolidation import Consolidation
from .handoff_cli_payload import payload_capture
from .handoff_context import required_scope
from .handoff_records import HandoffFields
from .handoff_retention import HandoffRetention
from .handoffs import HandoffStore
from .startup import StartupReader

INVALID_EXIT = 2
ABSENT_EXIT = 1

_CAPTURE_FLAGS = (
    "--project-key", "--task-key", "--capture-id", "--work", "--next-step",
    "--decision", "--open-item", "--open-question", "--link",
)


class HandoffArguments(argparse.Namespace):
    """Typed parse result; the CLI namespace subclasses this for parity."""

    vault: str | None = None
    handoff_command: str | None = None
    project_key: str | None = None
    task_key: str | None = None
    capture_id: str | None = None
    work: str | None = None
    next_step: str | None = None
    decisions: list[str] | None = None
    open_items: list[str] | None = None
    open_questions: list[str] | None = None
    links: list[str] | None = None
    json_stdin: bool = False
    task: str | None = None
    keep: int = 3
    plan_id: str | None = None
    transaction: str | None = None
    apply: bool = False


def add_handoff_parser(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Attach the ``handoff`` subcommand tree to the top-level parser."""
    handoff = commands.add_parser(
        "handoff", help="publish, resume, fold or undo scoped handoffs",
        allow_abbrev=False,
    )
    subcommands = handoff.add_subparsers(dest="handoff_command", required=True)
    capture = subcommands.add_parser(
        "capture", help="publish an immutable handoff capture",
        allow_abbrev=False,
    )
    _add_scope_args(capture)
    _ = capture.add_argument(
        "--capture-id", help="stable identity for one capture request")
    _ = capture.add_argument(
        "--work", help="verbatim work text; required unless --json-stdin")
    _ = capture.add_argument("--next-step", help="free-text next step")
    for flag, dest in (("--decision", "decisions"), ("--open-item", "open_items"),
                       ("--open-question", "open_questions"), ("--link", "links")):
        _ = capture.add_argument(
            flag, dest=dest, action="append", default=None,
            help=f"repeated {flag[2:].replace('-', ' ')} value")
    _ = capture.add_argument(
        "--json-stdin", action="store_true",
        help="read the equivalent structured payload from stdin")
    latest = subcommands.add_parser(
        "latest", help="print the complete newest capture",
        allow_abbrev=False,
    )
    _add_scope_args(latest)
    resume = subcommands.add_parser(
        "resume",
        help="print the complete startup bundle with INDEX and latest",
        allow_abbrev=False,
    )
    _add_scope_args(resume)
    _ = resume.add_argument(
        "--task", help="free-text task; independent of --task-key")
    fold = subcommands.add_parser(
        "fold", help="preview or apply retention folds", allow_abbrev=False,
    )
    _add_scope_args(fold)
    _ = fold.add_argument(
        "--keep", type=int, default=3,
        help="newest active captures retained (default 3)")
    _ = fold.add_argument(
        "--apply", action="store_true",
        help="apply the fold; requires --plan-id from preview")
    _ = fold.add_argument("--plan-id", help="64-hex plan_id from preview")
    undo = subcommands.add_parser(
        "undo", help="undo one journaled fold transaction", allow_abbrev=False,
    )
    _ = undo.add_argument("--transaction", help="id from a committed fold")


def _add_scope_args(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument(
        "--project-key",
        help="opaque project key; required unless MNEMOSYNE_PROJECT_KEY is set")
    _ = parser.add_argument(
        "--task-key", help="optional opaque task key within the project")


def run_handoff(args: HandoffArguments, arguments: list[str],
                parser: argparse.ArgumentParser) -> int:
    """Dispatch one validated handoff command; returns the process status."""
    _duplicate(parser, arguments, "--vault")
    vault = args.vault
    assert vault is not None
    match args.handoff_command:
        case "capture":
            return _capture(vault, args, arguments, parser)
        case "latest":
            return _latest(vault, args, arguments, parser)
        case "resume":
            return _resume(vault, args, arguments, parser)
        case "fold":
            return _fold(vault, args, arguments, parser)
        case "undo":
            return _undo(vault, args, arguments, parser)
        case _:
            raise AssertionError(
                f"unknown handoff command: {args.handoff_command}")


def _duplicate(parser: argparse.ArgumentParser, arguments: list[str],
               *flags: str) -> None:
    for flag in flags:
        if sum(argument.split("=", 1)[0] == flag for argument in arguments) > 1:
            parser.error(f"supply {flag} only once")


def _capture(vault: str, args: HandoffArguments, arguments: list[str],
             parser: argparse.ArgumentParser) -> int:
    _duplicate(parser, arguments, "--project-key", "--task-key",
               "--capture-id", "--work", "--next-step")
    if args.json_stdin:
        for flag in _CAPTURE_FLAGS:
            if any(argument.split("=", 1)[0] == flag for argument in arguments):
                parser.error(f"--json-stdin cannot be combined with {flag}")
        scope, fields, capture_id, event, session_id, source = payload_capture()
    else:
        if args.capture_id is None:
            parser.error("--capture-id is required (or supply --json-stdin)")
        if args.work is None:
            parser.error("--work is required (or supply --json-stdin)")
        scope = required_scope(args.project_key, args.task_key)
        fields = HandoffFields(
            work=args.work, next_step=args.next_step or "",
            decisions=tuple(args.decisions or ()),
            open_items=tuple(args.open_items or ()),
            open_questions=tuple(args.open_questions or ()),
            links=tuple(args.links or ()),
        )
        capture_id, event, session_id, source = args.capture_id, "explicit", "", "api"
    receipt = HandoffStore(vault).capture(
        scope, fields, capture_id=capture_id, event=event,
        session_id=session_id, source=source,
    )
    print(json.dumps(asdict(receipt), ensure_ascii=False))
    return 0


def _latest(vault: str, args: HandoffArguments, arguments: list[str],
            parser: argparse.ArgumentParser) -> int:
    _duplicate(parser, arguments, "--project-key", "--task-key")
    scope = required_scope(args.project_key, args.task_key)
    note = HandoffStore(vault).latest(scope)
    if note is None:
        print(f"{parser.prog}: no active handoff capture for this scope",
              file=sys.stderr)
        return ABSENT_EXIT
    payload = asdict(note.record)
    payload["path"] = note.path
    payload["sha256"] = note.sha256
    payload["raw"] = note.raw.decode("utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _resume(vault: str, args: HandoffArguments, arguments: list[str],
            parser: argparse.ArgumentParser) -> int:
    _duplicate(parser, arguments, "--project-key", "--task-key", "--task")
    scope = required_scope(args.project_key, args.task_key)
    result = StartupReader(vault).read(
        [], task=args.task, project_key=scope.project_key,
        task_key=scope.task_key,
    )
    print(json.dumps({
        "complete": result.coverage.complete,
        "context": result.context,
        "coverage": asdict(result.coverage),
        "cache_hit": result.cache_hit,
        "estimated_tokens": result.estimated_tokens,
        "matched_entries": [asdict(entry) for entry in result.matched_entries],
    }, ensure_ascii=False))
    return 0


def _fold(vault: str, args: HandoffArguments, arguments: list[str],
          parser: argparse.ArgumentParser) -> int:
    _duplicate(parser, arguments, "--project-key", "--task-key",
               "--keep", "--plan-id")
    if args.apply and args.plan_id is None:
        parser.error("--apply requires --plan-id (run preview first)")
    scope = required_scope(args.project_key, args.task_key)
    retention = HandoffRetention(vault)
    if args.apply:
        plan_id = args.plan_id
        assert plan_id is not None
        result = retention.apply(scope, plan_id, keep=args.keep)
    else:
        result = retention.preview(scope, keep=args.keep)
    print(json.dumps(asdict(result), ensure_ascii=False))
    return 0


def _undo(vault: str, args: HandoffArguments, arguments: list[str],
          parser: argparse.ArgumentParser) -> int:
    _duplicate(parser, arguments, "--transaction")
    if args.transaction is None:
        parser.error("--transaction is required")
    receipt = Consolidation(vault).undo(args.transaction)
    print(json.dumps(asdict(receipt), ensure_ascii=False))
    return 0
