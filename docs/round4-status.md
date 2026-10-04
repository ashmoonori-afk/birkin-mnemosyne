# Round 4 status (wrap-up, 2026-10-04)

Round 4 is not complete, and there is no release. This page records what
landed, what was measured, what failed and what is still open.

## Scope

Round 4 aimed to close the round-3 gaps under the .omo plan
`round4-close-gaps` (IS-1..IS-10). The targets were:

- lossless compact startup that is smaller and faster than a plain full read;
- baseline-or-better Kibitzer recall;
- high-recall, precise overlap/conflict questions;
- a sealed dual-author frozen evaluation.

The authors are GPT-6.1 Sol and Claude Opus 5.5.

## Landed in this change

This is protocol work, independently reviewed.

- Portable frozen-manifest metadata derived from pinned Git blobs. The
  original Windows bootstrap hashes and the LF policy are kept.
- A canonical QA root that refuses escapes.
- Resource-probe repetitions that start from identical pristine bytes and
  cache state.
- Fully typed round-4 harnesses: basedpyright reports 0 errors and 0 warnings
  on `run.py`, `qa.py`, `resource_probe.py` and `_startup_probe.py`, with no
  suppressions.
- Protocol tests that accept a real compact startup reader and a real semantic
  consolidation surface. A compact runner refuses formats the base reader
  can't honor.
- `StaticModel` is typed without changing its output. Encode output is
  bitwise identical and runtime imports are unchanged.
- Frozen inputs and scorers are unchanged.

## Measured results

These are practice data only. The frozen evaluation was not run.

### Compact startup (separate branch)

Exact-byte QA passes. Whole-context o200k BPE is 178 for compact against 186
for the full read, on the 6-note practice fixture. Size passes.

Startup speed fails. Medians of 10 fresh paired runs on the practice fixture:

| Condition | Full read | Compact |
|---|---|---|
| Bytecode absent | 0.148 ms | 7.378 ms |
| Installed bytecode present (allowed by owner decision) | 0.169 ms | 3.128 ms |

The plain full read only reads bytes and serializes JSON. Compact must import
product code and verify fresh sources inside the timer, so under the current
definition it can't be strictly faster.

### Kibitzer recall (separate branch)

Public QA passes with no ordering regressions, and 767 tests pass. Per-author
frozen recall metrics were not measured.

### Overlap/conflict questions (IS-6)

IS-6 fails, at precision 1.0 for both authors.

| Measure | Sol | Claude |
|---|---|---|
| Practice tuning complete recall | 5/12 (0.42) | 2/34 (0.06) |
| Practice validation, locked thresholds | 3/12 | 2/34 |

Validation was measured once, with locked thresholds (cosine 0.98, margin
0.20).

The cause is twofold. The prepared static multilingual model
(potion-multilingual-128M) scores translation pairs below the 0.50 floor
(Sol translations 0.12 to 0.27). And the structured subject/attribute parser
doesn't handle de/en/es/ja/ko/zh frames.

A feasibility study found that models fitting the 150 MB / 1000 ms limits cap
Claude at 28/34 even with a perfect parser. E5/MiniLM-class models could reach
the target, but they use about 600 MB and seconds of load time.

### Combined integration branch

1034 tests pass. Compact startup QA passes, Kibitzer QA passes, and the
question harness passes, with quality below target.

## Open decision

The owner approved this in principle. It has not been started.

Run cross-language overlap/conflict detection as an opt-in background batch
job. The job loads an E5/MiniLM-class model only inside the job, unloads it
afterward, and caches results. The default and startup paths keep the 150 MB /
1000 ms limits. The job's memory and duration are reported plainly. IS-6 is
judged on that mode, per author.

## Unmerged work

These branches are pushed but not independently approved as PR heads. Don't
merge them without review.

| Branch | Head | Content |
|---|---|---|
| `round4/startup-on-protocol` | d5e5715 | compact startup formats v2 and file-root-order/3 |
| `round4/recall-on-protocol` | 8b570d1 | Kibitzer ranking/freshness and typed index entries |
| `round4/questions-on-protocol` | cc26010 | assertion witnesses, opt-in semantic detector, locked practice thresholds marked IS-6 FAIL |
| `round4/frozen-evaluator` | e74a40d | sealed frozen evaluation mode |
| `round4/integration` | 09b4c79 | all of the above merged, for verification only |

The latest review of `round4/frozen-evaluator` asked for two fixes:

- validate the output path before scoring, and preserve results on save
  failure;
- enforce owner-only files on Windows.

## Evidence

Evidence lives outside this repository, in the orchestrator's
`.omo/evidence/round4/`:

- `detection-semantic-worker.md`
- `multilingual-representation-study.md`
- `c003-review/`
