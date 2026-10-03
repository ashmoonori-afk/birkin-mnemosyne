# Round-4 optional runtime provenance (T3)

The round-4 resource contract measures the **existing** optional semantic
runtime. No new transformer, tokenizer or remote provider is added: the core
package stays stdlib-only, and every semantic measurement uses
`birkin_mnemosyne.static_model.StaticModel`, the int8 memory-mapped model that
round 3 already shipped (`[semantic]` extra, PR #12).

## Model

| Field | Value |
| --- | --- |
| Model | `minishlab/potion-multilingual-128M` (static embeddings; no transformer at query time) |
| Model license | MIT |
| Source | https://huggingface.co/minishlab/potion-multilingual-128M |
| Revision | `73908c3438cf03b6a01bcb9611d62b23d0726f08` (resolved from `main` by `snapshot_download` on 2026-10-03) |
| Files fetched | `model.safetensors`, `tokenizer.json` (`semantic.MODEL_FILES`) - the 512 MB ONNX export is deliberately never downloaded |
| Compact form | `minishlab--potion-multilingual-128M-v2` under the model cache: sorted 64-bit piece hashes, piece scores, int8 table + per-row float scale, `meta.json` (`static_model.FORMAT_VERSION` = 2 in `meta`), written by `static_model.prepare_isolated` in a child process |
| Cache root | `%MNEMOSYNE_MODEL_CACHE%`, else `$XDG_CACHE_HOME/birkin-mnemosyne`, else `~/.cache/birkin-mnemosyne` |

The model is a **product runtime dependency**, not a QA temporary artifact:
it is intentionally retained so that prepared runs are reproducible. It is
classified separately from the probe's temporary vaults, per-vault caches and
environment variables, which are removed after every run. No pre-existing user
model data is overwritten or deleted: `semantic.prepare()` returns immediately
when `meta.json` already exists, and the probe's `--prepare` reports
`was_prepared: true` in that case.

## Installation vs prepared startup

Three distinct costs are reported separately and never conflated:

1. **Installation** (one-time, per machine): the `[semantic]` extra
   (`numpy`, `safetensors`, `huggingface_hub`), installed by the repository's
   own Python tooling - `python -m pip install -e '.[semantic]'`.
2. **Download + conversion** (one-time, per machine): the ~530 MB snapshot is
   downloaded once and converted once in an isolated child process by
   `python -m birkin_mnemosyne.semantic`. This is **not** prepared startup and
   is not counted against the 1000 ms gate.
3. **Prepared startup** (every process): loading the compact model from the
   cache. `StaticModel` memory-maps the int8 table, so only the pages actually
   touched are resident.

A search never downloads or converts: without a prepared model the semantic
leg is unavailable and every semantic mode reports `PENDING`
(`model_not_prepared`), never a silent pass. `--offline` clears proxy and
Hugging Face endpoint variables for the children, and the fresh-download guard
(`prepare()` still absent afterwards) proves no download happened during a
measured run.

## Mean surface = planned product surface (PENDING, not PASS)

The probe is written against the **real** future product surfaces and refuses
to measure a substitute under the same label. At the protocol base
(`4244768c9afcc14001a59af6e39151e96a43bc2a`) neither surface exists, so both
modes report an explicit `PENDING` after a real availability check:

| Mode | Required real surface | Planned | Base status |
| --- | --- | --- | --- |
| `compact` | `StartupReader.read(paths, compact=True)` (`startup.py`) | T6 | PENDING - `compact-read-api-absent` |
| `consolidation-semantic` | `Consolidation(vault, semantic=True, thresholds=<locked config>)` whose owning service reports `semantic_status == "ready"` after `questions()` (`consolidation.py`) | T11 | PENDING - `semantic-consolidation-api-absent` |

The semantic probe loads `detection-thresholds.json` and requires a locked,
nonempty `thresholds` object. If the file is absent it reports
`locked-thresholds-absent`; it never supplies the former placeholder values.
Readiness belongs to the owning service after discovery, not to its returned
question tuple. Every measured attempt must meet both the 1000 ms limit and the
150000000-byte total-RSS limit; finite, well-formed measurements alone are not a
resource pass.

When the surfaces land, the same code path runs unchanged: the compact child
calls the real `compact=True` read and evidence is the byte-exact context, and
the semantic child calls the real semantic Consolidation with the locked
thresholds config and requires `semantic_status == "ready"` afterwards. A
legacy read, a `SemanticIndex` search, a lexical `Consolidation(vault)`, or a
global scoring mutation is never measured under either label. `--check`
reports both surfaces' readiness explicitly instead of claiming a substituted
result.

## Resource contract (IS-8)

Supported input: **1000 active notes, 4096 encoded spans, 8 MiB of raw note
bytes** per vault. Exceeding any bound reports explicit capacity refusal, never
partial success. Every supported mode is measured in a **fresh process**; the
gate is **total peak RSS <= 150000000 bytes** and **prepared startup <= 1000 ms**,
with all repetitions and their median reported.

The child clock starts **before its first product import** (`clock_origin:
pre_import`), covers the import, the reader/service construction and the actual
operation, and is never computed from a cached span; `first_product_import_ms`
is measured, not assumed. Product imports are never excluded to flatter a mode.

`consolidation-semantic` performs a real encode. On the **first** run against
an unencoded vault, that encode (chunking and embedding every note) is included
in the observed load time and RSS; it is reported as
`includes_first_unencoded_vault: true` rather than excluded.

Every non-PENDING mode additionally reports the **three vault states
separately** in `phases`, each with its own elapsed time and vault digest, so
none can be averaged into an ambiguous single number:

| Phase key | What it measures |
| --- | --- |
| `first_unencoded_vault` | the first operation before any per-vault cache/vector artifact exists (kibitzer: cold snapshot build; semantic: chunk + embed every note; compact: cold complete closure) |
| `warm_vault` | the identical operation repeated against the warm in-process state |
| `changed_note` | one note mutated on disk and the operation repeated, proving the new bytes are discovered in the same process (`changed_note_visible`) |

The per-mode `phase_summary` reports min/median/max for each phase; a PENDING
mode declares all three phases as `n: 0` rather than fabricating a value. The
gate number `load_ms` is the whole fresh operation and is never smaller than the
sum of the phases and the product import, so no phase is silently excluded.

## Cleanup

Each run creates disposable practice vaults and, for the semantic mode, a
scoped `MNEMOSYNE_MODEL_CACHE`; per-vault cache artifacts
(`.mnemosyne-index.json`, `.mnemosyne-index.json.z`, `.mnemosyne-vectors.npz`)
are deleted by the child and asserted absent before the workspace is removed
(`residue_files: []`, `vault_cache_removed: true`). The probe never touches
`~/.cache/birkin-mnemosyne`, `~/.cache/huggingface`, or any installed omo
configuration.

## Three separate fresh-operation states

Initial (unencoded) work, warm-state work and changed-note work are three
separate observations, not one number with a caveat. The `compact` mode calls
the reader three times in one fresh process (cold closure, warm closure, and a
closure after mutating `handoff.md`); the semantic mode builds the service
once and calls `questions()` before any vault artifact exists (first unencoded
encode), again warm, and again after mutating a note; the `kibitzer` mode calls
`select()` cold, warm and after mutating a note. Each phase records its own
vault digest, so a reader can verify from the emitted JSON that the changed
phase really saw different bytes.

## Not claimed

The resource probe is a **data-surface** proof: real prepared-model load and a
finite, nonzero float32 encode of original practice text. It is not a
language-quality proof and not a detector proof: the semantic question
detector, its practice-calibrated thresholds and its frozen dual-author
evaluation are future product work (T11/T12, T15) and are reported as
`detector_status: PENDING` until implemented.
