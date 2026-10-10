# Frozen public task-memory delivery benchmark

Run from a checkout with the product importable:

```bash
.venv/bin/python -m benchmarks.memory_triggers.run --output /tmp/triggers-after.json
.venv/bin/python -m benchmarks.memory_triggers.run --baseline --output /tmp/triggers-before.json
```

The fixture is the byte-for-byte public input frozen before implementation.
SHA-256: `a482f7f3af566c392aa6ca2cf7890f6ce48adfcb8e133571adcfc3d52a3936de`.
The runner rejects changed bytes. Never adjust tasks or required paths to fit
results. Only task text enters routing; required paths enter scoring afterward.
The product matcher uses ANY non-stopword lexical intersection, not conjunction.
This runner does not implement another matcher.

Each run creates temporary vaults, writes complete fictional documents, and
registers every alias through `MemoryIndex.register`. The frozen grown shape is
12 topics, 20 documents per topic, and 2 aliases per document: 240 documents and
480 routes. `read().entries` must retain every original route. Optional grouped
metadata is reported only when available; no grouped representation is assumed.
Temporary vaults are removed on success and exceptions.

Default mode calls actual `StartupReader.read([], task=task)` and independently
verifies the returned context with the same task. Missing task APIs or
`matched_entries` fail loudly. Bodies are reconstructed from actual returned
source blocks, not inferred from route receipts. Every row reports required and
returned paths, misses, extras, byte-exact full-body equality, verified coverage,
and matched entries. Missing bodies, partial bodies, or failed verification fail
the default CLI with a nonzero exit after writing the report. As frozen in the
fixture, positives require every required body; positive extras are reported
separately, not hidden or treated as misses. Negatives require no returned bodies.

Baseline mode deliberately calls release-style `read([])` without a task.
It records automatic delivery failures rather than treating them as runner
failures. `MemoryIndex.open(task, limit=3)` is measured separately in both modes:
optional retrieval is not automatic delivery. Baseline success means the
measurement and verification completed, not that automatic delivery succeeded.

All costs use the existing benchmark `size` helper: characters, UTF-8 bytes,
bytes/4 estimate, and `o200k_base` tokens. The tokenizer is imported lazily and is
not a core dependency. Costs cover rendered indexes, complete startup contexts,
complete per-task contexts, optional serialized open payloads, and optional
document bodies. Both modes measure the entire grown startup context, including
instructions and certificates. These are comparison units, not billing claims.
No model calls are made; optional search is run with semantic models disabled.

For release 0.6.0, copy this benchmark directory into that release's worktree,
then run `--baseline` there using a Python environment with tiktoken installed.
The adjacent `benchmarks.memory_index.baseline.size` exists in that release.
Alternatively append the current benchmark checkout to `sys.path` after making
the release product importable; never prepend it over an installed release wheel.
Reports identify the loaded product source directory and hash its current Python
source bytes. Git revision and committed product-tree identifiers are recorded
when available. Dirty product changes are allowed and distinguished by the
current source hash; no commit or clean-tree prerequisite is imposed.

This fictional fixture measures lexical routing and full-body transport, not
semantic understanding, model obedience, or backend integration. MCP and Hermes
checks are separate lead-owned end-to-end checks.
