# Memory INDEX measurements

The fictional large-note case drops from **45,128 to 1,781 o200k_base
tokens** for the whole startup payload, a reduction of 43,347 tokens (96.1%).
All 30 INDEX entries remain present, and all 155,749 original bytes reconstruct
exactly. The two separately authored frozen question sets each retain 12/12
correct answers. There is no accuracy gain, and small-note task costs can rise.

These are separate measurements: byte coverage and startup cost on a large
synthetic corpus, and constrained answer extraction on small frozen fixtures.
Task accuracy on the large synthetic corpus was not measured.

## Artifacts and reproduction

- [Frozen protocol](../benchmarks/memory_index/PROTOCOL.md), recorded before
  product evaluation.
- [Original preimplementation baseline](../benchmarks/memory_index/baseline.json).
- [Complete measured results](../benchmarks/memory_index/results.json),
  including every selected path, context hash, answer and task cost.
- [Runner](../benchmarks/memory_index/run.py) and
  [fictional corpus generator](../benchmarks/memory_index/sample.py).
- [Frozen 14-file input/scorer manifest](../benchmarks/round4/frozen-manifest.json)
  and [recorded question authorship](../benchmarks/round3/PROVENANCE.md).

The product subtree measured is
`97cf12942083ab3619207b017cc90a7c074f0002`, delivered by PR 60. The artifact
also binds the benchmark files and every validated frozen input by SHA256.
Corpus formatting and type annotations were cleaned up after the first run;
the original generated-document hashes are unchanged and checked by a test.
Neither routing nor questions were tuned against these results.

Use an isolated Python environment from this checkout:

```bash
python -m pip install -e . tiktoken==0.14.0
python -m benchmarks.round4.run --check-inputs-only
python -m benchmarks.memory_index.run --output memory-index-results.json
```

The runner refuses a dirty product subtree, validates frozen inputs before
scoring, disables semantic retrieval, and removes its temporary vaults.
`tiktoken` is benchmark-only; production runtime dependencies remain empty.
The recorded run uses Python 3.14.4, Linux x86_64/WSL2, and tiktoken 0.14.0.

## Large-note startup cost

The generator uses fictional service/rule/incident templates, not private
memory. Actual source sizes differ from the approximate 10K/8K/21K targets:

| Original document | UTF-8 bytes | o200k_base tokens | Covered lines | Topic documents |
|---|---:|---:|---:|---:|
| `memory.md` | 39,902 | 9,598 | 345 | 10 |
| `manual.md` | 32,204 | 7,776 | 313 | 11 |
| `handoff.md` | 83,643 | 23,203 | 715 | 9 |
| Total | 155,749 | 40,577 | 1,373 | 30 |

Before and after both count **the entire `StartupReader.context`**, including
rendered instructions, routing notices and coverage certificates:

| Measure | Before | After |
|---|---:|---:|
| o200k_base tokens | 45,128 | 1,781 |
| Characters | 165,667 | 5,079 |
| UTF-8 bytes | 165,667 | 5,079 |
| Runtime estimate, `ceil(UTF-8 bytes / 4)` | 41,417 | 1,270 |

The complete INDEX alone is 630 measured tokens (487 estimated), with 30
entries and a stored warning budget of 2,000 estimated tokens. The headline
uses 1,781, not 630: it includes the rest of the startup payload. This case
meets the approximately 2,000-token startup target without trimming entries.
Over-budget behavior remains warning-only and is independently tested.

Every source byte reconstructs from the recorded topic ranges, every original
line has a coverage row, and the post-split checker reports no orphan,
dangling route or coverage error. This establishes mechanical preservation;
it does not establish that an arbitrary agent will obey every stored rule.

## Frozen task accuracy, kept separate by author

The Sol identity slice and Claude identity fixture each contain 12 questions.
Before, the unchanged answerer receives the full original Markdown document.
After, splitting derives triggers only from source headings and the router
receives only the frozen natural-language `query`, with `limit=3`.
Only after loading does the unchanged answerer receive `section` and `field`.
Expected answers never select documents.

| Author | Exact answers, before -> after | Positive answers | Abstentions | Accuracy regressions | Accuracy gains |
|---|---|---|---|---:|---:|
| GPT-6.1 Sol | 12/12 -> 12/12 | 11/11 -> 11/11 | 1/1 -> 1/1 | 0 | 0 |
| Claude Opus | 12/12 -> 12/12 | 10/10 -> 10/10 | 2/2 -> 2/2 | 0 | 0 |

Per-question regression and improvement lists are empty for both authors.
The full-read baseline already scores 100%, so preserved accuracy cannot be
called an accuracy improvement. Positive answers and abstentions are shown
separately because returning nothing can satisfy an abstention without proving
that the relevant document was retrieved.

The Claude fixture was authored before this work and is replayed unchanged.
No Claude model was invoked. Authorship comes from the repository's existing
provenance record; these are reused public questions, not newly unseen trials.
The deterministic extractor is not a generative model or general agent
compliance evaluation.

## Small-document costs and regressions

For the question fixtures, before residency is the complete original Markdown;
after residency is the complete rendered INDEX. Combined task cost includes
that INDEX plus the entire serialized `OpenResult`, including paths and
complete returned document bodies. These scopes are recorded separately from
the whole-startup comparison above.

| Author | Resident before | Resident after | Combined task after, min-max | Tasks costing more than full original |
|---|---:|---:|---:|---:|
| GPT-6.1 Sol | 146 | 210 | 268-290 | 12/12 |
| Claude Opus | 441 | 304 | 387-590 | 7/12 |

All figures are o200k_base tokens. Every Sol question costs more with routing
and payload overhead than loading that tiny original note. Claude task-cost
increases occur on `i01`, `i03`, `i04`, `i05`, `i06`, `i07`, and `i08`; the
remaining five tasks cost less. The JSON artifact preserves every denominator
and per-question cost rather than pooling these differences away.

There is no both-author task-cost win on these tiny fixtures. The large-corpus
startup reduction does not justify automatically migrating every small note;
the behavior remains opt-in.

## Accounting and scope

`o200k_base` is a declared BPE unit, not GPT or Claude billing. The runtime's
byte-based estimate is labelled separately. Host system prompts, tool-schema
overhead, and JSON-RPC transport envelopes are not billing measurements here.
The synthetic corpus is patterned and repetitive; production corpora can have
different routing density and costs.

See the [usage guide](memory-index-guide.md) for the required-INDEX guard,
exact-trigger behavior, error handling, filesystem hard-link requirement,
and journal/captured-source recovery.

## Unreleased task reads and two-level indexes

### Task matching on the replacement snapshot (2026-10-11)

This comparison uses a new private snapshot, not the private corpus in the
historical table below. The old snapshot was deleted and could not be restored.
Baseline is current main `2dbecaeb1021fd0cd490c9b578d72841b508a6a5`; both sides
use identical replacement source bytes and frozen task inputs.
The matching code measured at
`10fb76631449913d3573cf9dee67492d0451f9e1` has production tree
`324c990f79f98daca34d8a569d24cf07cfd49722` and Python source SHA-256
`07d496fb4ce5b4d3a5f8e52d96941cc1faed7a4573b088a9ada08081902b2e78`.

| Corpus | Startup before | Startup after | Full-run before | Full-run after |
|---|---:|---:|---:|---:|
| Replacement private snapshot, 26 tasks | 2,193 | 2,193 | 211,935 | 177,359 |

Units are `o200k_base` tokens. Startup is one complete no-task
`memory_startup_read` inner context with the explicit resident source. Full-run
is the sum of all 26 complete task inner contexts through real MCP read/verify,
including the resident source, index, selected topic maps, receipt and bodies.
The 34,576-token reduction is 16.3%; startup does not change. Tool result JSON,
initialization instructions and JSON-RPC framing are separate scopes.

| Replacement delivery check | Before | After |
|---|---:|---:|
| All frozen tasks | 25/26 | 26/26 |
| Positive tasks | 22/23 | 23/23 |
| Negative tasks correctly empty | 3/3 | 3/3 |
| Distinct required documents delivered in full | 19/19 | 19/19 |
| Extra document deliveries | 30 | 12 |

The unchanged baseline misses one newly authored synonym-only paraphrase; the
candidate repairs it rather than changing the task or expected documents.
Required-body integrity and fresh verification pass for every candidate task.
All 20 original route pairs remain expandable across 11 conditions; no route,
index, selected topic map or required body is removed. The existing public
16-case full-body fixture also passes unchanged.

The source manifest SHA-256 is
`af3bc123e01773a82f8ccdee9299b0d69fd2d85da8f26e4317e75bfe6a2a0dd9`;
the replacement task fixture SHA-256 is
`5fa2fc8c5e76cc14031e19617cde251bb29c62074455caa7de017ca8d325d385`.
The original 24 task wordings map by condition text to current required
documents; two additional tasks cover the new condition. Source and detailed
responses remain private and are deleted at completion. This is mechanical
full-body delivery, not model obedience or arbitrary semantic understanding.

`lexical-v2` excludes repeated generic-action terms only when a trigger retains
other content, and uses bounded task-side technical equivalents through the
existing search expansion tokenizer. See the
[exact matching policy](memory-trigger-design.md#task-matching).
Invisible session dedupe and header-only confirmation were rejected because
each task requires an independently complete full-body response.

### Historical two-level-index comparison

These later measurements compare the already-managed 0.6.0 INDEX with the
unreleased implementation, not with the original 45,128-token full-note
baseline. The measured production tree is
`de9b03bdaace85a3054d9299733baf0f821186fe`; its Python source SHA-256 is
`e59696724cc428308cc9c385fc68da1d6e464b31c82928bd8d889ee2f9b65ce5`.
Measurements ran on commit `c88383dad2ff9ae4f9e439a75b6ed9ac34d0fbef`.
No package version, release, or runtime dependency changed.

| Corpus and identical scope | Managed 0.6.0 | Unreleased | Change |
|---|---:|---:|---:|
| Existing large-note whole startup | 1,781 | 1,297 | -27.2% |
| Existing large-note resident INDEX | 630 | 144 | -77.1% |
| Grown fixture whole startup | 9,603 | 1,036 | -89.2% |
| Grown fixture resident INDEX | 9,420 | 814 | -91.4% |
| Small public fixture whole startup | 358 | 358 | unchanged |
| Private frozen corpus managed whole startup | 2,425 | 2,121 | -12.5% |
| Private frozen corpus resident INDEX | 629 | 316 | -49.8% |

All figures are `o200k_base` tokens. The grown fixture has 240 documents,
480 original routes and 12 complete topics. Every route expands exactly once;
no topic is omitted from residency. A complete topic text costs 756 tokens;
its full compact-JSON `IndexView` result costs 1,944-1,952 tokens. These
different payload scopes are not interchangeable.

The small public fixture remains flat. The private corpus retains 18 routes
through four topics and its unchanged 982-token original resident source.
Its unregistered original startup was 1,618 tokens; 2,121 is compared with
the matching registered 2,425-token envelope, not with that smaller original.
Only anonymous private aggregates are reported; source contents are not
reproducible from this repository.

| Frozen delivery cases | Release automatic delivery | Unreleased automatic delivery |
|---|---:|---:|
| Public positives | 0/12 | 12/12 |
| Public negatives correctly empty | 4/4 | 4/4 |
| Private positives | 0/21 | 21/21 |
| Private negatives correctly empty | 3/3 | 3/3 |

These are full-body transport checks, not model obedience or semantic
precision. The private run still has eight positive tasks with 21 extra
document deliveries. Its total task-response cost increases from 161,332
after the read-only increment to 174,647 with complete topic material (+8.3%).
Reduced residency does not mean every task response gets smaller.
The existing Sol and Claude answer sets remain 12/12 each, with no changed
questions, scorer, or per-question regressions.

Reproduce the public comparison with
`python -m benchmarks.memory_index.run --output index-after.json` and
`python -m benchmarks.memory_triggers.run --output triggers-after.json`.
The latter uses the unchanged
[`a482f7f3...` fixture](../benchmarks/memory_triggers/fixture.json) and
[records complete topic and task costs](../benchmarks/memory_triggers/PROTOCOL.md).
Release comparison uses its explicit `--baseline` mode with the 0.6.0 product.

Lead-owned installed-wheel QA also exercised real MCP stdio and the shipped
Hermes provider: grouped initialization, explicit expansion, separate roots,
four complete task bodies, rehashed partial-map rejection, stale source
rejection, empty selection, restart and missing-target failure. The synthetic
Hermes prompt and late-match prefetch measured 680 and 2,163 tokens; their
actually concatenated strings measured 2,843. Those are separate QA inputs,
not the frozen corpus above or a provider billing estimate. Clients, providers
and temporary vaults were closed. External Hermes discovery was not exercised.
