# Memory INDEX measurement protocol (frozen before implementation)

Status: frozen 2026-10-09, recorded before any evaluation run.
Design context: [`docs/memory-index-design.md`](../../docs/memory-index-design.md).

This protocol fixes how the always-loaded memory INDEX is measured before the
feature is implemented. It is not tuned against results: the algorithm,
inputs, scorers, and reporting rules below are locked first, and evaluation
follows them unchanged.

## 1. Frozen dual-author inputs

Reuse the existing separately authored fixtures and scorers with no edits:

- GPT-6.1 Sol identity slice, 12 questions:
  [`benchmarks/round3/frozen_sol.json`](../round3/frozen_sol.json).
- Claude Opus identity set, 12 questions:
  [`benchmarks/round3/frozen_claude_identity.json`](../round3/frozen_claude_identity.json).
- Both runs use the unchanged scorer
  [`benchmarks/round3/answerer.py`](../round3/answerer.py).

The existing Claude data is reused as-is. No Claude model is called: the
Claude identity set was authored before this task, and replaying the frozen
file respects the prohibition on new Claude calls. Provenance is the
repository's recorded authorship
([`benchmarks/round3/PROVENANCE.md`](../round3/PROVENANCE.md)), not a newly
authenticated authoring session.

## 2. Before/after routing algorithm (fixed)

- **Before**: the answerer receives the full original document.
- **After**: only source headings are used to create the topic documents and
  their default triggers. Splitting is by source headings only.
- The router receives the frozen `query` only, never the section label, field
  name, gold document identifier, or expected answer.
- The open limit is fixed at `limit=3`.

## 3. Token measurement

- Report actual BPE counts using the benchmark-only `tiktoken` `o200k_base`
  encoder. This encoding is a declared measurement unit, not a claim about
  GPT/Claude billing, and is not imported by production code.
- Also report characters, UTF-8 bytes, and the runtime token estimate
  (`ceil(len(text.encode("utf-8")) / 4)`), which is explicitly an estimate.
- Count the whole startup payload: the complete previous startup context versus
  the complete INDEX-based always-loaded block, in both cases including any
  rendered instructions, warnings, and certificates.
- Additionally count the index plus the actually loaded task context (the
  documents opened for the question), and the combined task tokens.

## 4. Reporting rules

- Report the two authors separately. Within each author, report exact-answer
  counts, positive-answer counts, and abstention counts.
- Report every per-question regression and every per-question gain; do not
  hide regressions in a pooled average.
- Do not tune the routing algorithm against the frozen failures.
- Distinguish cost gain from accuracy gain: a cost gain is lower startup cost
  at preserved accuracy, not an accuracy improvement. An accuracy gain is
  claimed only if both author sets improve.
- Make no general agent-compliance claim. These are reused public fixtures and
  constrained extraction, not proof of general agent compliance.

## 5. Immutable input binding

- Record immutable input SHAs by referring to the existing pinned manifest
  [`benchmarks/round4/frozen-manifest.json`](../round4/frozen-manifest.json)
  rather than copying hashes into this document. The manifest is the single
  source of truth, so the protocol never restates a hash that could drift.
- The same input and scorer hashes bind both the before and after runs.

## 6. Corpus

- The realistic cost sample is generated from fictional patterns and contains
  no private data. Report actual sizes rather than claiming the generated
  sample hits an exact token count.

## 7. Language and tests

- English only.
- Add no new tests that pin prose. The protocol is documentation; nothing here
  is asserted by a prose-pinning test.
