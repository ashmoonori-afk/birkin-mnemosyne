"""Disk-backed inverted index so the large corpus fits a memory-capped run.

    python benchmarks/unanswerable/large_index.py <repo> <corpus.jsonl> <out-dir>

Tokens come from the package's own ``tokenize``, over ``description + " " + body``
as in ``KibitzerAdapter._snapshot``. Passages are public text, so the snapshot's
secret redaction is skipped. Postings are hash-partitioned into SQLite shards and
loaded per term, which is all ``bm25_scores`` needs.
"""

from __future__ import annotations

import json
import multiprocessing
import sqlite3
import sys
import zlib
from array import array
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SHARDS = 64
WORKERS = 8
CHUNK = 64 * 1024 * 1024


def _shard(term: str) -> int:
    return zlib.crc32(term.encode("utf-8", "surrogatepass")) % SHARDS


def _spans(path: Path) -> list[tuple[int, int, int]]:
    """Byte ranges on line ends, each with the line number of its first document."""
    spans, start, line = [], 0, 0
    with path.open("rb") as handle:
        while True:
            block = handle.readlines(CHUNK)
            if not block:
                return spans
            end = handle.tell()
            spans.append((start, end, line))
            start, line = end, line + len(block)


def _tokenize_span(job: tuple[str, str, str, int, int, int, int]) -> list[tuple[int, int]]:
    repo, corpus, scratch, part, start, end, first = job
    sys.path.insert(0, repo)
    from birkin_mnemosyne.mnemosyne import tokenize
    lengths = []
    rows: list[list[str]] = [[] for _ in range(SHARDS)]
    with open(corpus, "rb") as handle:
        handle.seek(start)
        for doc, raw in enumerate(handle.read(end - start).splitlines(True), first):
            row = json.loads(raw)
            terms = tokenize(row["description"] + " " + row["body"])
            lengths.append((doc, len(terms)))
            for term, count in Counter(terms).items():
                rows[_shard(term)].append(f"{term}\t{doc}\t{count}\n")
    for shard, lines in enumerate(rows):
        path = Path(f"{scratch}/{part}.{shard}")
        with path.open("w", encoding="utf-8", errors="surrogatepass") as file:
            file.writelines(lines)
    return lengths


def _merge_shard(job: tuple[str, str, int, int]) -> int:
    scratch, out, shard, parts = job
    postings: dict[str, tuple[array[int], array[int]]] = defaultdict(
        lambda: (array("I"), array("I")))
    for part in range(parts):
        path = Path(f"{scratch}/{part}.{shard}")
        with path.open(encoding="utf-8", errors="surrogatepass") as handle:
            for line in handle:
                term, doc, count = line.rstrip("\n").split("\t")
                docs, counts = postings[term]
                docs.append(int(doc))
                counts.append(int(count))
        path.unlink()
    db = sqlite3.connect(f"{out}/shard-{shard}.sqlite")
    db.execute("create table postings(term text primary key, docs blob, counts blob)")
    db.executemany("insert into postings values(?,?,?)",
                   ((term, docs.tobytes(), counts.tobytes())
                    for term, (docs, counts) in postings.items()))
    db.commit()
    db.close()
    return len(postings)


def build(repo: str, corpus: str, out: str) -> None:
    Path(out).mkdir(parents=True, exist_ok=False)
    scratch = f"{out}/parts"
    Path(scratch).mkdir()
    spans = _spans(Path(corpus))
    jobs = [(repo, corpus, scratch, i, *span) for i, span in enumerate(spans)]
    with multiprocessing.Pool(WORKERS) as pool:
        lengths = dict(pair for part in pool.imap_unordered(_tokenize_span, jobs) for pair in part)
        terms = pool.map(_merge_shard,
                         [(scratch, out, shard, len(spans)) for shard in range(SHARDS)])
    Path(scratch).rmdir()
    Path(f"{out}/lengths.bin").write_bytes(
        array("I", (lengths[i] for i in range(len(lengths)))).tobytes())
    Path(f"{out}/meta.json").write_text(json.dumps({
        "documents": len(lengths), "terms": sum(terms), "corpus": corpus}), encoding="utf-8")


class LazyPostings:
    """``postings.get(term)`` over the shards; one connection per process."""

    def __init__(self, root: str, paths: list[str]) -> None:
        self.root, self.paths = root, paths
        self._open: dict[tuple[int, int], sqlite3.Connection] = {}

    def get(self, term: str, default: Any = None) -> dict[str, int] | None:
        import os
        key = (os.getpid(), _shard(term))
        if key not in self._open:
            self._open[key] = sqlite3.connect(f"{self.root}/shard-{key[1]}.sqlite")
        row = self._open[key].execute("select docs, counts from postings where term=?",
                                      (term,)).fetchone()
        if row is None:
            return default
        docs, counts = array("I"), array("I")
        docs.frombytes(row[0])
        counts.frombytes(row[1])
        paths = self.paths
        return {paths[doc]: count for doc, count in zip(docs, counts)}


def load_snapshot(root: str) -> Any:
    from datetime import date

    from birkin_mnemosyne.kibitzer import RecallDocument, _Snapshot
    meta = json.loads(Path(f"{root}/meta.json").read_text(encoding="utf-8"))
    lengths_raw = array("I")
    lengths_raw.frombytes(Path(f"{root}/lengths.bin").read_bytes())
    documents = []
    with open(meta["corpus"], encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            documents.append(RecallDocument(row["path"], row["description"], row["body"]))
    paths = [doc.path for doc in documents]
    postings: Any = LazyPostings(root, paths)
    return _Snapshot((), date.today(), tuple(documents), postings, dict(zip(paths, lengths_raw)))


if __name__ == "__main__":
    build(*sys.argv[1:4])
