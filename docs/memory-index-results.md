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
