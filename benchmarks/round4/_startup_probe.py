#!/usr/bin/env python
"""Fresh-process startup probe for round 4: explicit ``full`` or ``compact``.

Run one mode per brand-new interpreter:

    python benchmarks/round4/_startup_probe.py full ROOT PATHS...
    python benchmarks/round4/_startup_probe.py compact ROOT PATHS...

The clock starts after argument parsing and after the shared stdlib/RSS helper
is in place, and it covers exactly the declared mode.

``full``
    fresh raw-byte acquisition, UTF-8 decoding and the existing spaced
    ``{"files": [{"path", "text"}]}`` JSON serialization for the explicit
    closure. No product module is imported in this mode.

``compact``
    the first product import, reader construction, fresh complete closure,
    verification and serialization all happen inside the timer. The file never
    prewarms the product, so the measured cold import is the real one.

``compact`` requires the future public ``StartupReader.read(paths, compact=True)``
surface (round4 T6). While that surface is absent this mode exits nonzero with
an explicit pending message rather than silently measuring the legacy v1
payload and calling it compact.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypeGuard

if TYPE_CHECKING:
    from birkin_mnemosyne.startup import StartupBundle

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmarks.retrieval._probe import peak_rss_bytes

MODES = ("full", "compact")
PENDING_COMPACT = ("compact mode requires the future public "
                   "StartupReader(root).read(paths, compact=True) surface (round4 T6); "
                   "refusing to relabel the legacy payload as compact")


@dataclass
class _CliOptions:
    """The concrete shape of the three parsed CLI tokens.

    ``argparse.Namespace`` resolves every attribute as ``Any``, so the CLI hands
    the parsed values to this typed carrier instead of leaking that ``Any`` into
    the measured boundaries.
    """

    mode: str = ""
    root: Path = Path()
    paths: list[str] = field(default_factory=list)


def context_sha256(context: str) -> str:
    return hashlib.sha256(context.encode("utf-8")).hexdigest()


def full_context(root: Path, paths: list[str]) -> str:
    """The legacy plain full read: raw bytes, decoding, spaced JSON."""
    return json.dumps({"files": [{"path": path, "text": (root / path).read_bytes().decode("utf-8")}
                                 for path in paths]}, ensure_ascii=False)


class _CompactRead(Protocol):
    def __call__(self, paths: Sequence[str], *, compact: bool) -> StartupBundle: ...


def _supports_compact(
    read: Callable[[Sequence[str]], StartupBundle],
) -> TypeGuard[_CompactRead]:
    return "compact" in inspect.signature(read).parameters


def compact_context(root: Path, paths: list[str]) -> str:
    # The first product import stays inside the measured call.
    from birkin_mnemosyne.startup import StartupReader

    reader = StartupReader(root)
    read = reader.read
    if not _supports_compact(read):
        raise TypeError("compact startup reading is not supported")
    bundle = read(paths, compact=True)
    if not bundle.coverage.complete:
        raise SystemExit("compact startup read did not report complete coverage")
    if not reader.verify(bundle.context, paths).complete:
        raise SystemExit("compact startup context failed verification against fresh sources")
    return bundle.context


def main() -> None:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("mode", choices=MODES)
    _ = parser.add_argument("root", type=Path)
    _ = parser.add_argument("paths", nargs="+")
    cli = _CliOptions()
    _ = parser.parse_args(namespace=cli)
    mode, root, paths = cli.mode, cli.root, cli.paths

    start = time.perf_counter()
    try:
        context = full_context(root, paths) if mode == "full" \
            else compact_context(root, paths)
    except TypeError as exc:
        if mode == "compact" and "compact" in str(exc):
            print(f"{PENDING_COMPACT} ({exc})", file=sys.stderr)
            raise SystemExit(2) from exc
        raise
    elapsed = (time.perf_counter() - start) * 1000.0

    optional = sorted(name for name in ("numpy", "safetensors", "huggingface_hub", "tiktoken")
                      if name in sys.modules)
    print(json.dumps({
        "probe": "benchmarks/round4/_startup_probe.py",
        "mode": mode,
        "root": str(root),
        "paths": paths,
        "load_read_ms": elapsed,
        "peak_rss_bytes": peak_rss_bytes(),
        "context_characters": len(context),
        "context_sha256": context_sha256(context),
        "product_imported": "birkin_mnemosyne" in sys.modules,
        "optional_imports": optional,
    }, ensure_ascii=True))


if __name__ == "__main__":
    main()
