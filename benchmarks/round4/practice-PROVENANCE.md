# Round 4 practice provenance

This directory holds the round-4 **practice** protocol. Practice determines
algorithm and threshold choices; it is not a held-out evaluation set. The frozen
round-3 evaluation inputs and scorers are never read here.

## Files

| File | Role |
| --- | --- |
| `practice.json` | Schema-validated practice protocol: author payloads preserved verbatim, plus explicit tuning/validation topic groups and provenance. |
| `qa.py` | Practice schema/provenance CLI and the QA-2/QA-3/QA-4 public-API scenarios. |
| `practice-PROVENANCE.md` | This document. |

## Authors and preserved provenance

`practice.json` carries two independently authored payloads. Each payload's
`pairs` array is byte-for-byte semantically identical to the delivered source
file; only wrapper metadata was added. Authorship was not fabricated, rewritten
or re-labeled, and no row text, category or `related` label was modified.

| Author identity | Source file | Delivered SHA256 | Pairs |
| --- | --- | --- | --- |
| `chatgpt-subscription/gpt-6.1-sol` | `.omo/drafts/round4-sol-practice.json` | `61d59faf31580c402ab2181ead830bb7b90913a05dc44b609cf9505e03fbc508` | 48 |
| `anthropic-subscription/claude-opus-5-5` | `.omo/drafts/round4-claude-practice.json` | `cd24ed0509428f2a9d2738102cdbdde91e3b7714da7186998ccca2b355350eac` | 136 |

The main Sol payload is self-authored practice written before implementation: its
author knows the public requirements and the proposed algorithm, so it is
practice and explicitly **not** an independent held-out set. The Claude payload is
independently authored source-blind practice produced from
`.omo/drafts/round4-claude-practice-spec.md`; its model identity and digest are
recorded above and verified by `qa.py --check-practice`. If that material were
absent or misattributed, the protocol would fail closed rather than invent an
author.

Both payloads are licensed CC0-1.0.

`qa.load_practice` also binds the actual `pairs` arrays, not merely their claimed
source-digest fields. SHA256 is computed over UTF-8 JSON with sorted object keys,
no separator spaces, and unescaped Unicode:

| Author | Canonical pairs SHA256 |
| --- | --- |
| Sol | `8f710cebd2e87eb55262a1daf3aff1f0e8fe8b8e8492ab82c198fd3aa0b07b0a` |
| Claude | `fdf0037925c8a8c0011d85c1641f118b6c73f707bd5681a2185467a70bc58ec0` |

These pins were derived from the original delivered arrays and compared with
the packaged arrays without changing any row. Editing notes, labels, categories
or partitions cannot be hidden by retaining a valid-looking source digest.

## Tuning / validation separation

Each author's topic groups are split into `tuning` and `validation` disjoint
partitions. Topic groups never cross the partition boundary within an author, and
every pair's `partition` agrees with its topic group. Threshold selection uses
tuning groups only; validation groups are untouched until choices are locked.

| Author | Tuning groups | Validation groups | Tuning +/- | Validation +/- |
| --- | --- | --- | --- | --- |
| Sol | 24 | 24 | 12 / 12 | 12 / 12 |
| Claude | 34 | 34 | 34 / 34 | 34 / 34 |

Tuning reports (`qa.tuning_report`) emit tuning pair ids, labels, counts and
digests only. They reject any row that references a validation pair or carries
note text, so validation bodies and labels cannot leak into a selection report.

## Scope boundaries

* The protocol validates schema, provenance, author identity, topic-group
  disjointness and nonempty positive/negative inventories, and exercises the
  public APIs through `qa.py`.
* Nothing in this directory reads frozen questions, gold, fixtures or the round-3
  retrieval corpus. QA-2/QA-3/QA-4 use synthetic roots, synthetic scale/edge
  notes and the practice protocol's own inventory.
* Author separation is always preserved: per-author confusion matrices and
  recall are never averaged across authors.

## Executable QA-4 drivers (corrective revision)

The QA-4 driver is executable rather than declarative. Each of these runs the
real public `Consolidation` on a materialized vault and counts pairs from what
the pipeline actually offered:

* **Semantic mode** — `questions_scenario(semantic=True)` inspects the shipped
  public constructor for the `semantic`/`thresholds` keywords and, when present,
  constructs the service with the locked tuning configuration and requires an
  actual `ready` status after discovery. It reports `PENDING` only for a
  genuinely absent surface (no locked thresholds file today, no semantic
  constructor today); it is never an unconditional stub. Both branches are
  covered by `tests/test_round4_practice.py`, including a ready service that
  must reach `PASS`.
* **Mixed vaults** — `mixed_vault_fixture` selects exactly one authored case per
  disjoint topic for the requested label, then adds the opposite-label decoy per
  topic and one explicit cross-topic pair. The fixture records its complete
  authored pair inventory, so cross-topic pairs are labeled false by the
  fixture's own disjoint-topic scope instead of by a product's output.
* **Crowded neighborhood** — `crowded_vault_fixture` materializes a genuinely
  >32-note crowd whose full unordered pair inventory is authored positive, and
  `crowded_neighborhood_plan` reports the same fixture's notes, gold pairs and
  drivability status. There is no count-only plan.
* **Scale/translation regressions** — `recall_capture_scenarios` builds an 8-note
  topic (28 authored true pairs), the 40-note crowd (780 authored true pairs)
  and English/Korean/Japanese translations, invoking the pipeline at the
  complete, public-20 and MCP-100 limits. Complete and capped recall are
  reported separately; capped recall never substitutes for complete recall.

Every fixture's TP/FP/FN comes from offered paths, including abstentions; a
service that offers nothing scores zero true positives regardless of the
authored inventory. Successful driver execution and backend readiness never
claim product quality.
