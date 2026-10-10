"""Measure the fictional full-startup baseline; tokenizer is benchmark-only.

Run: python -m benchmarks.memory_index.baseline --output baseline.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from benchmarks.memory_index.sample import make_sample
from birkin_mnemosyne.startup import StartupReader


def size(text: str) -> dict[str, int]:
    import tiktoken

    return {
        "characters": len(text),
        "utf8_bytes": len(text.encode("utf-8")),
        "estimated_tokens": (len(text.encode("utf-8")) + 3) // 4,
        "o200k_base_tokens": len(tiktoken.get_encoding("o200k_base").encode(
            text, disallowed_special=())),
    }


def measure() -> dict[str, object]:
    sample = make_sample()
    with tempfile.TemporaryDirectory(prefix="mn-index-baseline-") as directory:
        root = Path(directory)
        for name, text in sample.items():
            _ = (root / name).write_bytes(text.encode("utf-8"))
        bundle = StartupReader(root).read(list(sample))
        result = {
            "source_sha256": {
                name: hashlib.sha256(text.encode("utf-8")).hexdigest()
                for name, text in sample.items()
            },
            "documents": {name: size(text) for name, text in sample.items()},
            "whole_startup_payload": size(bundle.context),
            "complete": bundle.coverage.complete,
            "covered_bytes": bundle.coverage.bytes,
            "scope": "Pattern-generated fictional corpus; no private data.",
        }
    assert not root.exists()
    return {**result, "temporary_vault_removed": True}


class _Arguments(argparse.Namespace):
    output: Path | None = None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(namespace=_Arguments())
    assert args.output is not None
    result = measure()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _ = args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
