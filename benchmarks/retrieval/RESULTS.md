# Retrieval benchmark results

Corpus: `retrieval_corpus.py` - 160 gold notes in six languages (40 English,
40 Korean, 20 each Japanese / Chinese / Spanish / German; every 4th note padded
into a long note); people, companies and events are invented. Each note has 3
queries (`exact` keyword, `para` low-overlap paraphrase, `mixed`
code-switched) from each of three independent authors (see "Query authors"), split into dev and test by topic (a note and its
cross-language siblings always share a split). Padding adds deterministic
template distractors in all six languages up to 1k / 10k notes. Notes that
cover the same topic in another language are declared siblings and removed from
a query's ranking before scoring. All numbers are the **test split**; dev is
reserved for tuning.

Reproduce:

```bash
python benchmarks/retrieval/bench_retrieval.py --sizes 160 1000 10000 --install-size
```

How to read the numbers:

- `n` is the number of queries behind a row (3 authors x 3 kinds per
  test note). A language x kind cell for ja/zh/es/de rests on 33-45 queries;
  a single author's cell on 11-15, where one query moves MRR by up to ~0.09.
- Latency, build and cold-start numbers are wall clock on a laptop and move
  with machine load; compare engines only within one run (later PRs re-run
  both engines back to back). Latency is pooled over dev + test queries.
- Ties in score fall back to directory-scan order, which differs slightly
  between filesystems.

## Baseline: BM25 + Hangul bigrams (core, zero dependencies)

Measured 2026-09-30 on Apple M1, Python 3.11, macOS (harness at 8298f0c plus
the author sets of this PR; library unchanged).

#### Quality by language (test split, all query kinds, k=10)

| engine | notes | lang | n | R@1 | R@5 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|
| bm25 | 160 | en | 252 | 0.468 | 0.679 | 0.552 | 0.598 |
| bm25 | 160 | ko | 243 | 0.523 | 0.658 | 0.581 | 0.612 |
| bm25 | 160 | ja | 99 | 0.061 | 0.081 | 0.065 | 0.069 |
| bm25 | 160 | zh | 135 | 0.000 | 0.000 | 0.000 | 0.000 |
| bm25 | 160 | es | 108 | 0.620 | 0.731 | 0.667 | 0.702 |
| bm25 | 160 | de | 135 | 0.593 | 0.770 | 0.661 | 0.693 |
| bm25 | 1000 | en | 252 | 0.456 | 0.631 | 0.528 | 0.562 |
| bm25 | 1000 | ko | 243 | 0.514 | 0.613 | 0.559 | 0.577 |
| bm25 | 1000 | ja | 99 | 0.071 | 0.071 | 0.072 | 0.074 |
| bm25 | 1000 | zh | 135 | 0.000 | 0.000 | 0.000 | 0.000 |
| bm25 | 1000 | es | 108 | 0.602 | 0.676 | 0.634 | 0.651 |
| bm25 | 1000 | de | 135 | 0.593 | 0.711 | 0.639 | 0.664 |
| bm25 | 10000 | en | 252 | 0.448 | 0.635 | 0.523 | 0.557 |
| bm25 | 10000 | ko | 243 | 0.535 | 0.621 | 0.571 | 0.588 |
| bm25 | 10000 | ja | 99 | 0.071 | 0.071 | 0.071 | 0.071 |
| bm25 | 10000 | zh | 135 | 0.000 | 0.000 | 0.000 | 0.000 |
| bm25 | 10000 | es | 108 | 0.593 | 0.676 | 0.633 | 0.644 |
| bm25 | 10000 | de | 135 | 0.578 | 0.696 | 0.633 | 0.662 |

#### Quality by query kind (test split, all languages)

| engine | notes | kind | n | R@1 | R@5 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|
| bm25 | 160 | exact | 324 | 0.778 | 0.778 | 0.778 | 0.778 |
| bm25 | 160 | para | 324 | 0.074 | 0.225 | 0.137 | 0.179 |
| bm25 | 160 | mixed | 324 | 0.377 | 0.608 | 0.468 | 0.511 |
| bm25 | 1000 | exact | 324 | 0.778 | 0.778 | 0.778 | 0.778 |
| bm25 | 1000 | para | 324 | 0.062 | 0.139 | 0.096 | 0.118 |
| bm25 | 1000 | mixed | 324 | 0.370 | 0.577 | 0.455 | 0.491 |
| bm25 | 10000 | exact | 324 | 0.775 | 0.778 | 0.776 | 0.777 |
| bm25 | 10000 | para | 324 | 0.052 | 0.117 | 0.083 | 0.100 |
| bm25 | 10000 | mixed | 324 | 0.383 | 0.602 | 0.472 | 0.511 |

#### MRR by language x kind (test split)

| engine | notes | lang | exact | para | mixed |
|---|---|---|---|---|---|
| bm25 | 160 | en | 1.000 | 0.169 | 0.487 |
| bm25 | 160 | ko | 1.000 | 0.148 | 0.596 |
| bm25 | 160 | ja | 0.182 | 0.000 | 0.014 |
| bm25 | 160 | zh | 0.000 | 0.000 | 0.000 |
| bm25 | 160 | es | 1.000 | 0.212 | 0.791 |
| bm25 | 160 | de | 1.000 | 0.238 | 0.744 |
| bm25 | 1000 | en | 1.000 | 0.110 | 0.473 |
| bm25 | 1000 | ko | 1.000 | 0.104 | 0.572 |
| bm25 | 1000 | ja | 0.182 | 0.000 | 0.035 |
| bm25 | 1000 | zh | 0.000 | 0.000 | 0.000 |
| bm25 | 1000 | es | 1.000 | 0.136 | 0.766 |
| bm25 | 1000 | de | 1.000 | 0.190 | 0.728 |
| bm25 | 10000 | en | 1.000 | 0.081 | 0.487 |
| bm25 | 10000 | ko | 1.000 | 0.098 | 0.616 |
| bm25 | 10000 | ja | 0.182 | 0.000 | 0.030 |
| bm25 | 10000 | zh | 0.000 | 0.000 | 0.000 |
| bm25 | 10000 | es | 1.000 | 0.111 | 0.787 |
| bm25 | 10000 | de | 0.989 | 0.180 | 0.732 |

#### MRR by query author (test split)

| engine | notes | author | exact | para | mixed | en | ko | ja | zh | es | de |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bm25 | 160 | claude-fable-5.1 | 0.778 | 0.183 | 0.497 | 0.606 | 0.525 | 0.074 | 0.000 | 0.761 | 0.760 |
| bm25 | 160 | claude-opus-5.5 | 0.778 | 0.102 | 0.581 | 0.587 | 0.614 | 0.061 | 0.000 | 0.718 | 0.684 |
| bm25 | 160 | gpt-6.1-sol | 0.778 | 0.128 | 0.326 | 0.463 | 0.605 | 0.061 | 0.000 | 0.523 | 0.538 |
| bm25 | 1000 | claude-fable-5.1 | 0.778 | 0.144 | 0.485 | 0.571 | 0.491 | 0.096 | 0.000 | 0.767 | 0.743 |
| bm25 | 1000 | claude-opus-5.5 | 0.778 | 0.060 | 0.558 | 0.570 | 0.584 | 0.061 | 0.000 | 0.659 | 0.663 |
| bm25 | 1000 | gpt-6.1-sol | 0.778 | 0.084 | 0.323 | 0.441 | 0.601 | 0.061 | 0.000 | 0.477 | 0.511 |
| bm25 | 10000 | claude-fable-5.1 | 0.778 | 0.121 | 0.497 | 0.563 | 0.508 | 0.091 | 0.000 | 0.731 | 0.731 |
| bm25 | 10000 | claude-opus-5.5 | 0.773 | 0.053 | 0.558 | 0.569 | 0.577 | 0.061 | 0.000 | 0.653 | 0.655 |
| bm25 | 10000 | gpt-6.1-sol | 0.778 | 0.074 | 0.363 | 0.436 | 0.629 | 0.061 | 0.000 | 0.514 | 0.514 |

#### Footprint (latency pooled over dev + test queries)

| engine | notes | index on disk | build | p50 | p95 | cold wall | cold load | peak RSS |
|---|---|---|---|---|---|---|---|---|
| bm25 | 160 | 167.3 KB | 0.02 s | 0.7 ms | 5.3 ms | 101 ms | 13 ms | 20.8 MB |
| bm25 | 1000 | 949.8 KB | 0.14 s | 9.4 ms | 48.7 ms | 103 ms | 30 ms | 25.2 MB |
| bm25 | 10000 | 9.2 MB | 3.17 s | 38.4 ms | 52.5 ms | 186 ms | 142 ms | 77.0 MB |

install size (core, no extras, uv): 145.2 KB

### Reading

- Keyword queries are solved for every script the tokenizer understands. The
  tokenizer keeps only `[a-z0-9]+` and Hangul, so **Japanese and Chinese
  text is dropped entirely** (ja exact MRR 0.18 comes only from ASCII anchors
  such as `SIM` and `nit`; zh is 0.00) and accented Latin words are split
  (`azafrán` -> `azafr`, `n`).
- Paraphrases share no content words with their note; the small non-zero
  paraphrase scores come from function words (`the`, `my`, `die`, ...)
  that the engine does not filter, plus two tolerated overlaps (de `beim`,
  es `antes`).
- Code-switched queries score through the native words they keep; for
  English notes (asked about in Korean) only through the single English word.
- Latency grows with the number of notes; the per-query index refresh (a
  stat of every note file) is the likely driver but is not isolated here.
- Authors differ: GPT-6.1 Sol's code-switched queries lead with English
  words and are the hardest for BM25 (mixed MRR 0.33-0.36 vs 0.50-0.58 for
  the two Claude sets); Fable's longer paraphrases leak slightly more
  vocabulary (para MRR 0.12-0.18 vs 0.05-0.13).

## Query authors

Every gold note has three query sets written independently:

| author | how it was written |
|---|---|
| `claude-opus-5.5` | written together with the corpus (inline in `retrieval_corpus.py`) |
| `gpt-6.1-sol` | `queries_gpt-6.1-sol.json` - written by GPT-6.1 Sol from a notes-only export (titles + bodies), without seeing any other author's queries |
| `claude-fable-5.1` | `queries_claude-fable-5.1.json` - written by Claude Fable 5.1 under the same rules and isolation |

All authors got the same rules: `exact` = 2-5 keywords copied from the note;
`para` = a question in the note's language sharing no content word with it;
`mixed` = code-switched (Korean with at most one English word for English
notes; English plus one or two native words otherwise). Tests audit every
author: exact queries must be lexical, paraphrases may share at most 30 % of
their content units with the note (mean <= 6 % per language). The GPT set leans
toward specific fact questions, the Fable set toward longer multi-part
questions, the inline set toward short topical questions; reporting per author
shows whether a ranker only wins on one author's style.

The test split (108 notes) is pinned by a checksum test and was frozen before
any tuning; tuning uses the dev split only.
