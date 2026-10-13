"""Vault resolution shared by every ``mnemosyne`` command.

One order for every command: an explicit ``--vault`` (the global flag or a
subcommand's own), then ``$MNEMOSYNE_VAULT``, then the documented default --
the current directory for ``init``, and ``~/.birkin-mnemosyne/vault`` (the
``mnemosyne-mcp`` default, so terminal and MCP server agree) for everything
else. ``~`` is expanded, so a quoted ``--vault ~/mnemosyne`` can never create
a literal ``~`` directory.

Resolving never creates anything. Read commands that have nothing to report on
an absent vault call :func:`require_vault`, which exits 2 without writing.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .mcp_server import DEFAULT_VAULT

MISSING_EXIT = 2
VAULT_ENV = "MNEMOSYNE_VAULT"
# Commands whose repeated global ``--vault`` was accepted before (last wins).
REPEATABLE_GLOBAL_VAULT = frozenset({"check", "split"})


def add_vault_option(parser: argparse.ArgumentParser) -> None:
    """Accept ``--vault`` after a subcommand name, as well as before it."""
    _ = parser.add_argument("--vault", dest="sub_vault",
                            help="vault root directory")


def resolve_vault(explicit: str | None, *, use_cwd: bool = False) -> Path:
    """The absolute vault directory one command acts on; nothing is created."""
    raw = explicit or os.environ.get(VAULT_ENV) or ""
    if not raw.strip():
        raw = str(Path.cwd()) if use_cwd else DEFAULT_VAULT
    return Path(raw).expanduser().resolve()


def require_vault(vault: Path, parser: argparse.ArgumentParser) -> None:
    """Exit 2 instead of reading, or creating, a vault that is not there."""
    if not vault.is_dir():
        parser.exit(MISSING_EXIT, f"{parser.prog}: vault not found: {vault}\n")


def duplicate_vault(arguments: list[str], command: str,
                    sub_vault: str | None) -> bool:
    """True when ``--vault`` is supplied more than once where that is refused.

    ``check`` and ``split`` keep their earlier behavior for a repeated global
    ``--vault`` (the last one wins); every other repetition, and any mix of a
    global and a subcommand ``--vault``, is refused.
    """
    count = sum(argument.split("=", 1)[0] == "--vault"
                for argument in arguments)
    if count <= 1:
        return False
    return command not in REPEATABLE_GLOBAL_VAULT or sub_vault is not None
