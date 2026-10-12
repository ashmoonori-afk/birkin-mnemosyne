"""Real MCP, CLI and Python journeys against the selected interpreter's package."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import sysconfig
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import birkin_mnemosyne
from birkin_mnemosyne import MemoryIndex, Mnemosyne, ProfileMemory, VaultMemory
from birkin_mnemosyne.identity_reader import parse_sections


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--temp-root", type=Path)
    parser.add_argument("--allow-checkout", action="store_true")
    args = parser.parse_args()
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    transcript = args.evidence_dir / "journeys.jsonl"
    package = Path(birkin_mnemosyne.__file__).resolve()
    installed_roots = [
        Path(sysconfig.get_path(kind)).resolve() for kind in ("purelib", "platlib")
    ]
    if not args.allow_checkout and not any(package.is_relative_to(root) for root in installed_roots):
        raise RuntimeError("QA requires an installed wheel, not checkout imports")

    with transcript.open("w", encoding="utf-8") as evidence:
        def record(scenario, data):
            evidence.write(json.dumps({"scenario": scenario, **data}, ensure_ascii=False) + "\n")
            evidence.flush()

        record("package", {"path": str(package), "version": birkin_mnemosyne.__version__})
        temporary_root = None
        try:
            with TemporaryDirectory(prefix="mn-", dir=args.temp_root) as temporary:
                temporary_root = temporary
                root = Path(temporary)
                env = dict(os.environ)
                for key in list(env):
                    if key.startswith("MNEMOSYNE_"):
                        del env[key]
                env.update(HOME=str(root), USERPROFILE=str(root), PYTHONUTF8="1")
                vault = root / "vault"
                memory = VaultMemory({"vault_path": str(vault)})
                source = Path(memory.write_note(
                    "Source", "## Related\n- [[Existing]]\n\n## Notes\nKeep this section.",
                    zone="inbox",
                ))
                memory.write_note("Target", "Release target.", zone="inbox")
                memory.write_note("Disposable", "Archive candidate.", zone="inbox")
                assert memory.dex.search("Release target")
                (vault / "external.MD").write_text(
                    "# External\n\nCasefold recall sentinel.\n", encoding="utf-8",
                )
                (vault / "knowledge").mkdir()
                (vault / "knowledge" / ".private.md").write_text(
                    "# Private\n\nprivatenotefixturezxq\n", encoding="utf-8",
                )
                memory.dex.refresh()
                memory.dex.flush()
                assert memory.dex.search("Casefold recall")[0]["rel"] == "external.MD"
                assert not memory.dex.search("privatenotefixturezxq")
                record("python-write-search", {"passed": True})
                original_cache = os.environ.get("MNEMOSYNE_MODEL_CACHE")
                os.environ["MNEMOSYNE_MODEL_CACHE"] = str(root / "unprepared-model")
                try:
                    fallback = Mnemosyne(vault, semantic=True)
                    assert [hit["slug"] for hit in fallback.search("Release target")] == ["target"]
                    fallback.flush()
                finally:
                    if original_cache is None:
                        os.environ.pop("MNEMOSYNE_MODEL_CACHE", None)
                    else:
                        os.environ["MNEMOSYNE_MODEL_CACHE"] = original_cache
                assert not (root / "unprepared-model").exists()
                record("semantic-offline-fallback", {"passed": True})
                MemoryIndex(vault).enable(max_tokens=1)

                async def protocol():
                    params = StdioServerParameters(
                        command=sys.executable,
                        args=["-m", "birkin_mnemosyne.mcp_server", "--vault", str(vault)],
                        env=env,
                    )
                    async with (
                        stdio_client(params) as (reader, writer),
                        ClientSession(reader, writer) as client,
                    ):
                        await client.initialize()

                        async def call(name, arguments, *, error=False) -> dict[str, Any]:
                            result = await client.call_tool(name, arguments)
                            text = "".join(
                                item.text for item in result.content if item.type == "text"
                            )
                            record(name, {
                                "arguments": arguments, "is_error": result.is_error,
                                "output": text,
                            })
                            assert bool(result.is_error) == error, (name, text)
                            return {"error": text} if error else json.loads(text)

                        note = await call("memory_remember", {
                            "title": "배포 기록", "body": "릴리스 승인 기록",
                            "zone": "inbox", "labels": ["manual:release"],
                        })
                        hits = await call("memory_search", {
                            "query": "릴리스", "labels": ["manual:release"],
                        })
                        assert hits["results"][0]["slug"] == note["slug"]
                        await call("memory_remember", {
                            "title": "배포 기록", "body": "Do not overwrite.",
                        }, error=True)
                        await call("memory_remember", {
                            "title": "배포 기록", "body": "Stale edit",
                            "mode": "replace", "expected_version": 999,
                        }, error=True)
                        changed = await call("memory_remember", {
                            "title": "배포 기록", "body": "릴리스 승인 완료",
                            "mode": "replace", "expected_version": note["version"],
                        })
                        assert changed["version"] > note["version"]
                        await call("memory_remember", {"title": "", "body": ""}, error=True)
                        review = await call("memory_review_questions", {})
                        assert review["capacity"]["warnings"]
                        assert not any(review["capacity"]["over_budget"].values())
                        assert "retire_choices" not in review
                        await call("memory_curate", {
                            "plan": {"plan_version": 1, "ops": [
                                {"op": "link", "a": "source", "b": "target"},
                            ]}, "apply": True,
                        })
                        sections = parse_sections(source.read_text(encoding="utf-8"))
                        related = next(s for s in sections if s.heading == "Related")
                        notes = next(s for s in sections if s.heading == "Notes")
                        assert "[[Target]]" in related.text and "[[Target]]" not in notes.text
                        archived = await call("memory_forget", {
                            "note": "Disposable", "confirm": True,
                        })
                        assert archived["archived"]
                        await call("memory_restore", {"note": "Disposable"})
                        assert (vault / "disposable.md").exists()
                        await call("memory_index_register", {
                            "trigger": "release approval", "document": note["path"],
                        })
                        scope = {"project_key": "qa/project", "task_key": "release"}
                        for number in range(5):
                            receipt = await call("memory_handoff_capture", {
                                **scope, "capture_id": f"checkpoint-{number}",
                                "work": f"Complete checkpoint {number}",
                            })
                            assert receipt["created"]
                        startup = await call("memory_startup_read", {
                            **scope, "task": "release approval",
                        })
                        assert startup["complete"] and "Complete checkpoint 4" in startup["context"]
                        checked = await call("memory_startup_verify", {
                            **scope, "task": "release approval", "context": startup["context"],
                        })
                        assert checked["complete"]
                        fold = await call("memory_handoff_fold", {**scope, "keep": 1})
                        assert fold["accepted"]
                        applied = await call("memory_handoff_fold", {
                            **scope, "keep": 1, "plan_id": fold["plan_id"], "apply": True,
                        })
                        await call("memory_review_undo", {
                            "transaction_id": applied["transaction_id"], "confirm": True,
                        })
                        restored = await call("memory_handoff_read", scope)
                        assert restored["count"] == 5
                    record("mcp-lifecycle", {"passed": True})
                    empty_params = StdioServerParameters(
                        command=sys.executable,
                        args=["-m", "birkin_mnemosyne.mcp_server",
                              "--vault", str(root / "empty")],
                        env=env,
                    )
                    async with (
                        stdio_client(empty_params) as (reader, writer),
                        ClientSession(reader, writer) as client,
                    ):
                        await client.initialize()
                        result = await client.call_tool("memory_startup_read", {})
                        record("empty-startup", {
                            "arguments": {}, "is_error": result.is_error,
                            "output": [item.text for item in result.content if item.type == "text"],
                        })
                        assert result.is_error

                anyio.run(protocol)

                def cli(*arguments, expected=0) -> dict[str, Any]:
                    result = subprocess.run(
                        [sys.executable, "-m", "birkin_mnemosyne.memory_index_cli", *arguments],
                        cwd=root, env=env, capture_output=True, text=True, encoding="utf-8",
                        timeout=60, check=False,
                    )
                    record("cli", {
                        "arguments": arguments, "exit": result.returncode,
                        "stdout": result.stdout, "stderr": result.stderr,
                    })
                    assert result.returncode == expected, result.stderr
                    return (json.loads(result.stdout) if result.stdout.lstrip().startswith("{") else
                            {"exit": result.returncode, "stderr": result.stderr})

                dynamics = (vault / ".mnemosyne-dynamics.json").read_bytes()
                assert cli("search", "릴리스", "--vault", str(vault))["results"]
                assert cli("list", "--vault", str(vault))["total"] >= 4
                filtered = cli("list", "--label", "manual:release", "--vault", str(vault))
                assert filtered["total"] == 1
                assert cli("search", "릴리스", "--label", "manual:release",
                           "--vault", str(vault))["results"][0]["title"] == "배포 기록"
                assert cli("show", "배포 기록", "--vault", str(vault))["body"] == "릴리스 승인 완료"
                assert (vault / ".mnemosyne-dynamics.json").read_bytes() == dynamics
                cli("show", "missing-note", "--vault", str(vault), expected=1)
                absent = root / "absent"
                cli("list", "--vault", str(absent), expected=2)
                assert not absent.exists()
                empty_preview = cli("init", "--vault", str(absent))
                assert empty_preview["mode"] == "preview" and not absent.exists()
                assert cli("search", "Casefold", "--vault", str(vault))["results"]
                assert not cli("search", "privatenotefixturezxq",
                               "--vault", str(vault))["results"]
                raw_import = root / "export.TXT"
                raw_import.write_bytes(b"Retain every imported byte.\r\n")
                imported = cli("init", "--vault", str(root / "imported"),
                               "--import", str(raw_import), "--apply")
                assert imported["imports"] == 1
                assert raw_import.read_bytes() == b"Retain every imported byte.\r\n"
                plain = root / "plain"
                plain.mkdir()
                original = b"# Plain\n\nPreserve all source bytes.\n"
                (plain / "plain.md").write_bytes(original)
                preview = cli("init", "--vault", str(plain))
                assert preview["mode"] == "preview"
                assert (plain / "plain.md").read_bytes() == original
                initialized = cli("init", "--vault", str(plain), "--apply")
                cli("undo", "--vault", str(plain), "--transaction", initialized["undo_transaction"])
                assert (plain / "plain.md").read_bytes() == original
                (plain / ".mnemosyne-memory-index" / "index.json").write_bytes(b"{invalid")
                corrupted = cli("check", "--vault", str(plain), expected=1)
                assert corrupted["errors"] and not corrupted["ok"]
                assert corrupted["orphan_documents"] == []
                assert (plain / "plain.md").read_bytes() == original

                padding = 78 - len(str(root.resolve())) - 1
                assert padding > 0, "Use a short --temp-root for the long-path scenario"
                long_vault = root / ("q" * padding)
                long_scope = ("--project-key", "project", "--task-key", "release")
                checkpoint = "Preserve the complete release checkpoint."
                receipt = cli("--vault", str(long_vault), "handoff", "capture",
                              *long_scope, "--capture-id", "qa-long-1", "--work", checkpoint)
                destination = long_vault / receipt["path"]
                assert receipt["created"] and destination.is_file()
                if os.name == "nt":
                    assert 250 <= len(str(destination)) < 260
                latest = cli("--vault", str(long_vault), "handoff", "latest", *long_scope)
                assert latest["fields"]["work"] == checkpoint
                resumed = cli("--vault", str(long_vault), "handoff", "resume", *long_scope)
                assert checkpoint in resumed["context"]
                record("long-path", {"passed": True, "destination_length": len(str(destination))})

                command = [
                    sys.executable, "-m", "birkin_mnemosyne.memory_index_cli",
                    "--vault", str(vault), "handoff", "capture",
                    "--project-key", "concurrent", "--capture-id", "same-id", "--work", "Same bytes.",
                ]
                processes = []
                try:
                    for _ in range(2):
                        processes.append(subprocess.Popen(
                            command, cwd=root, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        ))
                    outputs = [process.communicate(timeout=60) for process in processes]
                    assert all(process.returncode == 0 for process in processes), outputs
                    receipts = [json.loads(stdout) for stdout, _ in outputs]
                    assert sorted(r["created"] for r in receipts) == [False, True]
                    assert receipts[0]["path"] == receipts[1]["path"]
                    record("concurrent-idempotency", {"passed": True, "receipts": receipts})
                finally:
                    for process in processes:
                        if process.poll() is None:
                            process.kill()
                            process.wait()

                profile_root = root / "profiles"
                with ProfileMemory(profile_root, lambda _: json.dumps({
                    "profiles": {"preferences": "Prefer exact evidence."},
                })) as profiles:
                    profiles.record_exchange("Remember evidence.", "Understood.")
                assert "Prefer exact evidence." in (
                    profile_root / "system" / "preferences.md"
                ).read_text(encoding="utf-8")
                record("profile-close-drains-worker", {"passed": True})
            record("cleanup", {"temporary_root": temporary, "status": "removed"})
            record("summary", {"passed": True})
        except BaseException as exc:
            if temporary_root is not None:
                record("cleanup", {"temporary_root": temporary_root, "status": "removed"})
            record("summary", {"passed": False, "error": repr(exc)})
            raise


if __name__ == "__main__":
    main()
