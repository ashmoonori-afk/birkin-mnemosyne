"""``mnemosyne-mcp`` - serve a vault over the Model Context Protocol (stdio).

This module is stdlib-only so the console script can explain a missing
optional dependency; the SDK-backed server lives in :mod:`._mcp_app` and needs
``pip install "birkin-mnemosyne[mcp]"``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from . import __version__

DEFAULT_VAULT = "~/.birkin-mnemosyne/vault"
_SDK_MODULES = {"mcp", "mcp_types", "pydantic", "anyio"}
_TRUTHY = {"1", "true", "yes", "on"}

log = logging.getLogger("birkin_mnemosyne.mcp")


def resolve_vault(arg: str | None = None) -> Path:
    raw = arg or os.environ.get("MNEMOSYNE_VAULT") or DEFAULT_VAULT
    vault = Path(raw).expanduser().resolve()
    vault.mkdir(parents=True, exist_ok=True)
    return vault


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mnemosyne-mcp",
        description="Serve a birkin-mnemosyne vault as an MCP server (stdio).")
    p.add_argument("--vault", help="vault directory (default: $MNEMOSYNE_VAULT "
                   f"or {DEFAULT_VAULT})")
    p.add_argument("--evidence-required", action="store_true",
                   default=os.environ.get("MNEMOSYNE_EVIDENCE_REQUIRED", "")
                   .strip().lower() in _TRUTHY,
                   help="refuse to create a note without a `source` "
                   "(or set MNEMOSYNE_EVIDENCE_REQUIRED=1)")
    p.add_argument("--version", action="version",
                   version=f"birkin-mnemosyne {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # stdout is the MCP protocol channel; every log line goes to stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="mnemosyne-mcp: %(message)s")
    try:
        from ._mcp_app import create_server
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] not in _SDK_MODULES:
            raise
        log.error("the MCP SDK is not installed (%s). Install the optional "
                  "extra: pip install \"birkin-mnemosyne[mcp]\"", exc.name)
        return 2
    vault = resolve_vault(args.vault)
    log.info("serving vault %s (evidence_required=%s)", vault,
             args.evidence_required)
    create_server(vault, evidence_required=args.evidence_required).run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
