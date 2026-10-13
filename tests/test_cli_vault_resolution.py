"""One vault order for every command, proved through real CLI subprocesses."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import birkin_mnemosyne
from birkin_mnemosyne import HandoffStore, MemoryIndex
from birkin_mnemosyne.handoff_records import HandoffFields, HandoffScope
from birkin_mnemosyne.mcp_server import DEFAULT_VAULT

ORIGIN_CHECK = """
import pathlib
import runpy
import sys
import birkin_mnemosyne

expected = pathlib.Path(sys.argv.pop(1)).resolve()
actual = birkin_mnemosyne.__file__
if actual is None or pathlib.Path(actual).resolve() != expected:
    print(f"CLI package origin mismatch: expected {expected}, got {actual}", file=sys.stderr)
    raise SystemExit(93)
runpy.run_module("birkin_mnemosyne.memory_index_cli", run_name="__main__", alter_sys=True)
"""


def run_cli(*args: str, cwd: Path, env: dict[str, str] | None = None,
            stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    """The installed package's CLI, with an environment the test controls."""
    module_file = birkin_mnemosyne.__file__
    assert module_file is not None
    environment = dict(os.environ)
    environment.pop("MNEMOSYNE_VAULT", None)
    environment.update(env or {})
    return subprocess.run(
        [sys.executable, "-c", ORIGIN_CHECK,
         str(Path(module_file).resolve()), *args],
        cwd=cwd, capture_output=True, check=False, input=stdin,
        env=environment,
    )


def routed_vault(root: Path, name: str = "vault") -> Path:
    """A vault holding one indexed note named after its directory."""
    vault = root / name
    vault.mkdir(parents=True)
    (vault / f"{name}-note.md").write_bytes(
        f"---\ntitle: {name} note\n---\n\nRule: keep approval.\n".encode())
    _ = MemoryIndex(vault).register("main task", f"{name}-note.md")
    return vault


def test_env_vault_resolves_check_without_the_flag(tmp_path: Path) -> None:
    # Given a vault reachable only through the environment.
    vault = routed_vault(tmp_path)

    # When check runs with no --vault at all.
    result = run_cli("check", cwd=tmp_path,
                     env={"MNEMOSYNE_VAULT": str(vault)})

    # Then it reports that vault's INDEX.
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True and payload["enabled"] is True
    assert payload["entries"] == 1 and payload["orphan_documents"] == []


def test_env_vault_resolves_handoff_latest(tmp_path: Path) -> None:
    # Given a capture published into the environment's vault.
    vault = tmp_path / "vault"
    _ = HandoffStore(vault).capture(
        HandoffScope("env-project", None), HandoffFields("ENV_VAULT_SENTINEL"),
        capture_id="one")

    # When latest runs with no --vault at all.
    result = run_cli("handoff", "latest", "--project-key", "env-project",
                     cwd=tmp_path, env={"MNEMOSYNE_VAULT": str(vault)})

    # Then the capture comes back from the environment's vault.
    assert result.returncode == 0, result.stderr
    assert "ENV_VAULT_SENTINEL" in json.loads(result.stdout)["fields"]["work"]


def test_flag_vault_beats_the_environment(tmp_path: Path) -> None:
    # Given two vaults, each with its own note.
    flagged = routed_vault(tmp_path, "flagged")
    ignored = routed_vault(tmp_path, "ignored")

    # When the flag and the environment disagree.
    result = run_cli("list", "--vault", str(flagged), cwd=tmp_path,
                     env={"MNEMOSYNE_VAULT": str(ignored)})

    # Then only the flag's vault is read.
    assert result.returncode == 0, result.stderr
    assert [note["slug"] for note in json.loads(result.stdout)["notes"]] == \
        ["flagged-note"]


def test_default_vault_is_the_mcp_default_under_home(tmp_path: Path) -> None:
    # Given the mnemosyne-mcp default vault inside a controlled home.
    home = tmp_path / "home"
    vault = routed_vault(home / ".birkin-mnemosyne", "vault")
    assert DEFAULT_VAULT == "~/.birkin-mnemosyne/vault"

    # When a read command runs with neither flag nor environment.
    result = run_cli("list", cwd=tmp_path,
                     env={"HOME": str(home), "USERPROFILE": str(home)})

    # Then the server's default vault is what the terminal read.
    assert result.returncode == 0, result.stderr
    assert [note["slug"] for note in json.loads(result.stdout)["notes"]] == \
        ["vault-note"]
    assert vault.is_dir() and not (tmp_path / "~").exists()


def test_tilde_vault_expands_instead_of_creating_a_literal_directory(
    tmp_path: Path,
) -> None:
    # Given a quoted ~ path and a controlled home directory.
    home = tmp_path / "home"
    home.mkdir()

    # When init applies onboarding to it.
    result = run_cli("init", "--vault", "~/tilde-vault", "--apply",
                     cwd=tmp_path,
                     env={"HOME": str(home), "USERPROFILE": str(home)})

    # Then the home-relative vault is used and no ./~ directory appears.
    assert result.returncode == 0, result.stderr
    expanded = (home / "tilde-vault").resolve()
    assert json.loads(result.stdout)["vault"] == str(expanded)
    assert (expanded / ".mnemosyne-memory-index" / "index.json").is_file()
    assert not (tmp_path / "~").exists() and not (home / "~").exists()


def test_init_reports_the_resolved_vault_it_acted_on(tmp_path: Path) -> None:
    # Given a vault supplied through the environment.
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "policy.md").write_bytes(b"Approval is required.\n")

    # When init previews it from a different working directory.
    result = run_cli("init", cwd=tmp_path, env={"MNEMOSYNE_VAULT": str(vault)})

    # Then the additive vault key names the absolute path it planned against.
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["vault"] == str(vault.resolve())
    assert payload["mode"] == "preview" and payload["notes"] == 1


def test_missing_vault_exits_two_without_creating_it(tmp_path: Path) -> None:
    # Given a vault path that does not exist.
    missing = tmp_path / "absent"

    for case in (("search", "release"), ("list",), ("show", "policy")):
        # When a read command is pointed at it.
        result = run_cli(*case, "--vault", str(missing), cwd=tmp_path)

        # Then it refuses with exit 2 and leaves the filesystem alone.
        assert result.returncode == 2, (case, result.stdout)
        assert b"vault not found" in result.stderr, case
        assert str(missing) in result.stderr.decode("utf-8", "replace"), case
        assert not missing.exists(), case


def test_init_apply_is_undone_by_the_shared_undo_command(tmp_path: Path) -> None:
    # Given a frontmatter-less note that onboarding will complete.
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "policy.md"
    original = b"Approval is required.\n"
    note.write_bytes(original)

    applied = run_cli("init", "--apply", cwd=tmp_path,
                      env={"MNEMOSYNE_VAULT": str(vault)})
    assert applied.returncode == 0, applied.stderr
    transaction = json.loads(applied.stdout)["undo_transaction"]
    assert transaction and note.read_bytes() != original

    # When the top-level undo command runs that transaction.
    undone = run_cli("undo", "--transaction", transaction, "--vault",
                     str(vault), cwd=tmp_path)

    # Then the original bytes are back, byte for byte.
    assert undone.returncode == 0, undone.stderr
    receipt = json.loads(undone.stdout)
    assert receipt["transaction_id"] == transaction
    assert receipt["state"] == "undone"
    assert note.read_bytes() == original


def test_undo_rejects_an_invalid_transaction_without_writing(
    tmp_path: Path,
) -> None:
    # Given an existing vault and no journal.
    vault = routed_vault(tmp_path)
    before = {path.name: path.read_bytes() for path in vault.rglob("*")
              if path.is_file()}

    # When undo is called without, then with, a malformed transaction.
    missing = run_cli("undo", "--vault", str(vault), cwd=tmp_path)
    malformed = run_cli("undo", "--transaction", "deadbeef", "--vault",
                        str(vault), cwd=tmp_path)

    # Then both refuse with exit 2 and change nothing.
    assert missing.returncode == 2 and missing.stderr
    assert malformed.returncode == 2 and malformed.stderr
    assert {path.name: path.read_bytes() for path in vault.rglob("*")
            if path.is_file()} == before


def test_duplicate_vault_is_still_refused_once(tmp_path: Path) -> None:
    # Given two conflicting --vault values for a read command.
    result = run_cli("--vault", str(tmp_path), "list", "--vault",
                     str(tmp_path), cwd=tmp_path)

    # Then the original single-vault rule still applies.
    assert result.returncode == 2
    assert b"supply --vault only once" in result.stderr


def test_version_prints_the_package_version_and_exits_zero(
    tmp_path: Path,
) -> None:
    # When the version flag is used like any other CLI's.
    result = run_cli("--version", cwd=tmp_path)

    # Then it answers on stdout and exits 0.
    assert result.returncode == 0, result.stderr
    assert result.stdout.decode("utf-8").strip() == \
        f"birkin-mnemosyne {birkin_mnemosyne.__version__}"


def test_trailing_vault_works_for_check_split_and_handoff(tmp_path: Path) -> None:
    # Given a routed vault and a capture in it.
    vault = routed_vault(tmp_path)
    _ = HandoffStore(vault).capture(
        HandoffScope("tail-project", None), HandoffFields("TRAILING_SENTINEL"),
        capture_id="one")

    # When --vault follows the command name, as the README documents.
    checked = run_cli("check", "--vault", str(vault), cwd=tmp_path)
    split = run_cli("split", "vault-note.md", "--vault", str(vault), cwd=tmp_path)
    latest = run_cli("handoff", "latest", "--project-key", "tail-project",
                     "--vault", str(vault), cwd=tmp_path)

    # Then each command acts on that vault.
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["entries"] == 1
    assert split.returncode == 0, split.stderr
    assert b"mode: preview" in split.stdout
    assert latest.returncode == 0, latest.stderr
    assert "TRAILING_SENTINEL" in json.loads(latest.stdout)["fields"]["work"]


def test_repeated_global_vault_for_check_keeps_last_wins(tmp_path: Path) -> None:
    # Given a vault and an empty decoy directory.
    vault = routed_vault(tmp_path)
    decoy = tmp_path / "decoy"
    decoy.mkdir()

    # When check repeats the global flag, as main accepted.
    result = run_cli("--vault", str(decoy), "--vault", str(vault), "check",
                     cwd=tmp_path)
    mixed = run_cli("--vault", str(vault), "check", "--vault", str(vault),
                    cwd=tmp_path)

    # Then the last one wins, while mixing global and subcommand flags is refused.
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["entries"] == 1
    assert mixed.returncode == 2 and b"supply --vault only once" in mixed.stderr


def test_vault_after_handoff_before_its_subcommand(tmp_path: Path) -> None:
    # Given a capture in one vault.
    vault = tmp_path / "vault"
    _ = HandoffStore(vault).capture(
        HandoffScope("family-project", None), HandoffFields("FAMILY_SENTINEL"),
        capture_id="one")

    # When --vault sits between "handoff" and its subcommand, or is repeated there.
    latest = run_cli("handoff", "--vault", str(vault), "latest",
                     "--project-key", "family-project", cwd=tmp_path)
    twice = run_cli("handoff", "--vault", str(vault), "latest",
                    "--project-key", "family-project", "--vault", str(vault),
                    cwd=tmp_path)

    # Then the family flag selects the vault and a second flag is refused.
    assert latest.returncode == 0, latest.stderr
    assert "FAMILY_SENTINEL" in json.loads(latest.stdout)["fields"]["work"]
    assert twice.returncode == 2 and b"supply --vault only once" in twice.stderr
