"""Fresh-process stdlib-core startup/RAM probe; never imports the tokenizer."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmarks.retrieval._probe import peak_rss_bytes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("startup", "full"))
    parser.add_argument("root", type=Path)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    start = time.perf_counter()
    if args.mode == "startup":
        from birkin_mnemosyne import StartupReader

        context = StartupReader(args.root).read(args.paths).context
    else:
        context = json.dumps({"files": [
            {"path": path, "text": (args.root / path).read_text("utf-8")}
            for path in args.paths]}, ensure_ascii=False)
    elapsed = (time.perf_counter() - start) * 1000
    assert "tiktoken" not in sys.modules
    print(json.dumps({"load_read_ms": elapsed, "peak_rss_bytes": peak_rss_bytes(),
                      "context_characters": len(context), "tokenizer_loaded": False}))


if __name__ == "__main__":
    main()
