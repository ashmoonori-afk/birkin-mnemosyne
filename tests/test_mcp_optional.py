"""The MCP layer is optional: the core must import and the console script
must fail helpfully when the SDK is absent (stdlib-only suite)."""

from __future__ import annotations

import subprocess
import sys

from birkin_mnemosyne import mcp_server

BLOCK_SDK = "import sys; sys.modules['mcp'] = None; "


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-c", BLOCK_SDK + code],
                          capture_output=True, text=True, timeout=60,
                          check=False)


def test_core_imports_without_mcp_sdk():
    r = _run("import birkin_mnemosyne as b; b.Mnemosyne; b.VaultMemory; "
             "b.evaluate_plan; b.run_curation_pass; "
             "import birkin_mnemosyne.mcp_server; "
             "assert sys.modules['mcp'] is None; print('ok')")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ok"


def test_console_script_explains_missing_extra(tmp_path):
    r = _run("from birkin_mnemosyne.mcp_server import main; "
             f"raise SystemExit(main(['--vault', {str(tmp_path)!r}]))")
    assert r.returncode == 2
    assert 'pip install "birkin-mnemosyne[mcp]"' in r.stderr
    assert r.stdout == ""


def test_resolve_vault_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMOSYNE_VAULT", str(tmp_path / "env"))
    assert mcp_server.resolve_vault(str(tmp_path / "arg")) == \
        (tmp_path / "arg").resolve()
    assert mcp_server.resolve_vault() == (tmp_path / "env").resolve()
    monkeypatch.delenv("MNEMOSYNE_VAULT")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    default = mcp_server.resolve_vault()
    assert default == (tmp_path / ".birkin-mnemosyne" / "vault").resolve()
    assert default.is_dir()
