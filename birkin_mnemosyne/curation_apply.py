from __future__ import annotations

from pathlib import Path

from . import mnemosyne
from .identity_reader import parse_sections
from .mnemosyne import Mnemosyne


def _append_related(path: Path, dex: Mnemosyne, target_title: str) -> bool:
    if dex.key_for_path(path) is None:
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if f"[[{target_title}]]" in text:
        return False
    related = next((section for section in parse_sections(text)
                    if section.level == 2 and section.heading == "Related"), None)
    if related is not None:
        lines = text.splitlines(keepends=True)
        before = "".join(lines[:related.line_end])
        after = "".join(lines[related.line_end:])
        separator = "" if before.endswith("\n") else "\n"
        new = before + separator + f"- [[{target_title}]]\n\n" + after
    else:
        new = text.rstrip() + f"\n\n## Related\n- [[{target_title}]]\n"
    mnemosyne.atomic_write(path, new)
    dex.note_written(path)
    return True


def _append_line(path: Path, dex: Mnemosyne, line: str) -> bool:
    if dex.key_for_path(path) is None:
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if line in text:
        return False
    mnemosyne.atomic_write(path, text.rstrip() + f"\n\n{line}\n")
    dex.note_written(path)
    return True


def apply_plan(accepted: list[dict], vault: Path,
               dex: Mnemosyne) -> list[dict]:
    bound = dex.entries()
    effected: list[dict] = []
    for op in accepted:
        kind = op["op"]
        try:
            if kind == "rezone":
                target = op["slug"]
                key = dex.key_for_path(vault / bound[target]["rel"])
                if key is None:
                    raise ValueError(f"note moved or removed: {bound[target]['rel']}")
                path = dex.rezone(key, op["zone"])
                bound[target] = {**bound[target], "rel": path.relative_to(vault).as_posix()}
                effected.append({"op": "rezone", "slug": op["slug"],
                                 "zone": op["zone"]})
            elif kind == "archive":
                target = op["slug"]
                key = dex.key_for_path(vault / bound[target]["rel"])
                if key is None:
                    raise ValueError(f"note moved or removed: {bound[target]['rel']}")
                path = dex.rezone(key, mnemosyne.ARCHIVE_ZONE)
                bound[target] = {**bound[target], "rel": path.relative_to(vault).as_posix()}
                effected.append({"op": "archive", "slug": op["slug"]})
            elif kind == "link":
                a, b = op["a"], op["b"]
                ok1 = _append_related(vault / bound[a]["rel"], dex, bound[b]["title"])
                ok2 = _append_related(vault / bound[b]["rel"], dex, bound[a]["title"])
                if ok1 or ok2:
                    effected.append({"op": "link", "a": a, "b": b})
            elif kind == "supersede":
                st, by = op["stale"], op["by"]
                ok = _append_line(vault / bound[st]["rel"], dex,
                                  f"> Superseded by [[{bound[by]['title']}]]")
                _append_related(vault / bound[by]["rel"], dex, bound[st]["title"])
                if ok:
                    effected.append({"op": "supersede", "stale": st, "by": by})
        except (ValueError, OSError) as exc:
            effected.append({"op": kind, "error": str(exc)})
    return effected
