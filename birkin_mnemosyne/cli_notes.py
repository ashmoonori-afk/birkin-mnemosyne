"""Read-only note commands for the mnemosyne CLI: ``search``, ``list``, ``show``.

Each prints one JSON object with the same shape as the matching MCP tool
(``memory_search``, ``memory_list``, ``memory_get_note``), so a terminal check
sees exactly what the agent sees, in UTF-8 whatever the console encoding is.

All three only read: no access is recorded, so note files and
``.mnemosyne-dynamics.json`` are never touched (the rebuildable index cache
may be refreshed). ``show`` exits 1 when no note carries that slug or title.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import frontmatter
from .memory import _is_expired, _snippet
from .mnemosyne import ARCHIVE_ZONE, ZONE_RE, Mnemosyne, slug, tokenize

NOTE_COMMANDS = ("search", "list", "show")
ABSENT_EXIT = 1
SEARCH_LIMIT = 10
SEARCH_LIMIT_MAX = 50
LIST_LIMIT = 50
LIST_LIMIT_MAX = 500


def add_notes_parsers(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Attach the read-only ``search``, ``list`` and ``show`` subcommands."""
    search = commands.add_parser(
        "search", help="search notes and print ranked hits as JSON",
        allow_abbrev=False,
    )
    _ = search.add_argument("query", help="keywords, in any language")
    _ = search.add_argument(
        "--limit", type=int, default=SEARCH_LIMIT,
        help=f"maximum hits, 1-{SEARCH_LIMIT_MAX} (default {SEARCH_LIMIT})")
    _ = search.add_argument(
        "--zone", help="restrict to one zone ('inbox' = vault root)")
    listed = commands.add_parser(
        "list", help="list notes newest first as JSON", allow_abbrev=False,
    )
    _ = listed.add_argument(
        "--zone", help="only this zone ('inbox' = vault root, "
        f"'{ARCHIVE_ZONE}' = forgotten notes)")
    _ = listed.add_argument(
        "--limit", type=int, default=LIST_LIMIT,
        help=f"maximum notes, 1-{LIST_LIMIT_MAX} (default {LIST_LIMIT})")
    _ = listed.add_argument(
        "--offset", type=int, default=0, help="skip this many notes")
    show = commands.add_parser(
        "show", help="print one note in full as JSON", allow_abbrev=False,
    )
    _ = show.add_argument("note", help="note slug or title")
    for parser in (search, listed, show):
        _ = parser.add_argument(
            "--vault", dest="sub_vault", help="vault root directory")


def run_notes(command: str, vault: Path, args: argparse.Namespace,
              parser: argparse.ArgumentParser) -> int:
    """Dispatch one read-only note command; returns the process status."""
    dex = Mnemosyne(vault)
    match command:
        case "search":
            return _search(dex, args, parser)
        case "list":
            return _list(dex, args, parser)
        case "show":
            return _show(dex, args, parser)
        case _:
            raise AssertionError(f"unknown note command: {command}")


def _zone(zone: str | None, parser: argparse.ArgumentParser) -> str | None:
    if zone is None:
        return None
    name = zone.strip().lower()
    if name in ("", "inbox"):
        return ""
    if name == ARCHIVE_ZONE:
        return ARCHIVE_ZONE
    if not ZONE_RE.fullmatch(name):
        parser.error(f"invalid --zone {zone!r} (want lowercase letters, "
                     "digits and hyphens, max 32, or 'inbox')")
    return name


def _bounded(value: int, high: int, flag: str,
             parser: argparse.ArgumentParser, low: int = 1) -> int:
    if not low <= value <= high:
        parser.error(f"{flag} must be between {low} and {high}")
    return value


def _read(dex: Mnemosyne, meta: dict[str, Any]) -> tuple[dict[str, Any], str]:
    text = (dex.vault / meta["rel"]).read_text(encoding="utf-8",
                                               errors="replace")
    return frontmatter.parse(text)


def _print(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _search(dex: Mnemosyne, args: argparse.Namespace,
            parser: argparse.ArgumentParser) -> int:
    limit = _bounded(args.limit, SEARCH_LIMIT_MAX, "--limit", parser)
    zone = _zone(args.zone, parser)
    terms = tokenize(args.query)
    results: list[dict[str, Any]] = []
    for hit in dex.search(args.query, limit=limit, zone=zone):
        try:
            _, body = _read(dex, hit)
        except OSError:
            body = hit["summary"]
        results.append({
            "slug": hit["slug"], "title": hit["title"],
            "zone": hit["zone"] or "inbox", "type": hit["type"],
            "polarity": hit["polarity"], "updated": hit["updated"],
            "snippet": _snippet(body, terms),
            "related": [slug(title) for title in hit["links"][:3]],
        })
    return _print({"results": results})


def _list(dex: Mnemosyne, args: argparse.Namespace,
          parser: argparse.ArgumentParser) -> int:
    limit = _bounded(args.limit, LIST_LIMIT_MAX, "--limit", parser)
    offset = args.offset
    if offset < 0:
        parser.error("--offset must be 0 or more")
    zone = _zone(args.zone, parser)
    notes: list[dict[str, Any]] = []
    for key, entry in dex.entries().items():
        if _is_expired(entry):
            continue
        if zone is None and entry["zone"] == ARCHIVE_ZONE:
            continue
        if zone is not None and entry["zone"] != zone:
            continue
        notes.append({"slug": key, "title": entry["title"],
                      "type": entry["type"], "zone": entry["zone"] or "inbox",
                      "polarity": entry["polarity"],
                      "updated": entry["updated"]})
    notes.sort(key=lambda note: (note["updated"], note["slug"]), reverse=True)
    return _print({"total": len(notes), "offset": offset,
                   "notes": notes[offset:offset + limit]})


def _show(dex: Mnemosyne, args: argparse.Namespace,
          parser: argparse.ArgumentParser) -> int:
    key = dex.key_for(args.note)
    meta = dex.note_meta(key) if key is not None else None
    if key is None or meta is None:
        print(f"{parser.prog}: no note {args.note!r} "
              f"(slug {slug(args.note)!r}); use search or list",
              file=sys.stderr)
        return ABSENT_EXIT
    fields, body = _read(dex, meta)
    try:
        version = int(fields.get("version") or 0)
    except (TypeError, ValueError):
        version = 0
    return _print({"slug": key, "title": meta["title"],
                   "zone": meta["zone"] or "inbox", "type": meta["type"],
                   "polarity": meta["polarity"], "version": version,
                   "tags": meta["tags"], "links": meta["links"],
                   "sources": fields.get("sources") or [],
                   "updated": meta["updated"],
                   "expires_at": meta.get("expires_at"),
                   "body": body.strip()})
