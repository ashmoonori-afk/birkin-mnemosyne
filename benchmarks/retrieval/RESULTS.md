# Retrieval benchmark results

Corpus: `retrieval_corpus.py` - 160 gold notes in six languages (40 English,
40 Korean, 20 each Japanese / Chinese / Spanish / German; every 4th note padded
into a long note); people, companies and events are invented. Each note has 3
queries (`exact` keyword, `para` low-overlap paraphrase, `mixed`
code-switched), split into dev and test by topic (a note and its
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

- `n` is the number of queries behind a row. A language x kind cell for
  ja/zh/es/de rests on 11-15 queries, so one query moves its MRR by up to
  ~0.09; treat cell differences below ~0.09 as noise.
- Latency, build and cold-start numbers are wall clock on a laptop and move
  with machine load; compare engines only within one run (later PRs re-run
  both engines back to back). Latency is pooled over dev + test queries.
- Ties in score fall back to directory-scan order, which differs slightly
  between filesystems.

## Baseline: BM25 + Hangul bigrams (core, zero dependencies)

Measured 2026-09-30 on Apple M1, Python 3.11, macOS (harness at 601fdff plus
the split fix in this PR; library unchanged).

#### Quality by language (test split, all query kinds, k=10)

| engine | notes | lang | n | R@1 | R@5 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|
| bm25 | 160 | en | 84 | 0.500 | 0.726 | 0.587 | 0.629 |
| bm25 | 160 | ko | 81 | 0.556 | 0.691 | 0.614 | 0.645 |
| bm25 | 160 | ja | 33 | 0.061 | 0.061 | 0.061 | 0.061 |
| bm25 | 160 | zh | 45 | 0.000 | 0.000 | 0.000 | 0.000 |
| bm25 | 160 | es | 36 | 0.667 | 0.778 | 0.718 | 0.739 |
| bm25 | 160 | de | 45 | 0.622 | 0.778 | 0.684 | 0.712 |
| bm25 | 1000 | en | 84 | 0.500 | 0.679 | 0.570 | 0.603 |
| bm25 | 1000 | ko | 81 | 0.531 | 0.642 | 0.584 | 0.605 |
| bm25 | 1000 | ja | 33 | 0.061 | 0.061 | 0.061 | 0.061 |
| bm25 | 1000 | zh | 45 | 0.000 | 0.000 | 0.000 | 0.000 |
| bm25 | 1000 | es | 36 | 0.639 | 0.667 | 0.659 | 0.673 |
| bm25 | 1000 | de | 45 | 0.622 | 0.711 | 0.663 | 0.680 |
| bm25 | 10000 | en | 84 | 0.488 | 0.702 | 0.569 | 0.602 |
| bm25 | 10000 | ko | 81 | 0.531 | 0.630 | 0.577 | 0.593 |
| bm25 | 10000 | ja | 33 | 0.061 | 0.061 | 0.061 | 0.061 |
| bm25 | 10000 | zh | 45 | 0.000 | 0.000 | 0.000 | 0.000 |
| bm25 | 10000 | es | 36 | 0.639 | 0.667 | 0.653 | 0.656 |
| bm25 | 10000 | de | 45 | 0.600 | 0.711 | 0.655 | 0.679 |

#### Quality by query kind (test split, all languages)

| engine | notes | kind | n | R@1 | R@5 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|
| bm25 | 160 | exact | 108 | 0.778 | 0.778 | 0.778 | 0.778 |
| bm25 | 160 | para | 108 | 0.046 | 0.185 | 0.102 | 0.136 |
| bm25 | 160 | mixed | 108 | 0.481 | 0.722 | 0.581 | 0.621 |
| bm25 | 1000 | exact | 108 | 0.778 | 0.778 | 0.778 | 0.778 |
| bm25 | 1000 | para | 108 | 0.037 | 0.093 | 0.060 | 0.076 |
| bm25 | 1000 | mixed | 108 | 0.463 | 0.676 | 0.558 | 0.594 |
| bm25 | 10000 | exact | 108 | 0.769 | 0.778 | 0.773 | 0.774 |
| bm25 | 10000 | para | 108 | 0.028 | 0.093 | 0.053 | 0.067 |
| bm25 | 10000 | mixed | 108 | 0.463 | 0.685 | 0.558 | 0.592 |

#### MRR by language x kind (test split)

| engine | notes | lang | exact | para | mixed |
|---|---|---|---|---|---|
| bm25 | 160 | en | 1.000 | 0.140 | 0.620 |
| bm25 | 160 | ko | 1.000 | 0.080 | 0.763 |
| bm25 | 160 | ja | 0.182 | 0.000 | 0.000 |
| bm25 | 160 | zh | 0.000 | 0.000 | 0.000 |
| bm25 | 160 | es | 1.000 | 0.196 | 0.958 |
| bm25 | 160 | de | 1.000 | 0.170 | 0.883 |
| bm25 | 1000 | en | 1.000 | 0.105 | 0.605 |
| bm25 | 1000 | ko | 1.000 | 0.056 | 0.697 |
| bm25 | 1000 | ja | 0.182 | 0.000 | 0.000 |
| bm25 | 1000 | zh | 0.000 | 0.000 | 0.000 |
| bm25 | 1000 | es | 1.000 | 0.019 | 0.958 |
| bm25 | 1000 | de | 1.000 | 0.123 | 0.867 |
| bm25 | 10000 | en | 1.000 | 0.082 | 0.624 |
| bm25 | 10000 | ko | 1.000 | 0.056 | 0.676 |
| bm25 | 10000 | ja | 0.182 | 0.000 | 0.000 |
| bm25 | 10000 | zh | 0.000 | 0.000 | 0.000 |
| bm25 | 10000 | es | 1.000 | 0.000 | 0.958 |
| bm25 | 10000 | de | 0.967 | 0.132 | 0.867 |

#### Footprint (latency pooled over dev + test queries)

| engine | notes | index on disk | build | p50 | p95 | cold wall | cold load | peak RSS |
|---|---|---|---|---|---|---|---|---|
| bm25 | 160 | 167.3 KB | 0.06 s | 0.8 ms | 2.6 ms | 63 ms | 15 ms | 20.5 MB |
| bm25 | 1000 | 949.8 KB | 0.21 s | 7.2 ms | 26.0 ms | 213 ms | 43 ms | 25.4 MB |
| bm25 | 10000 | 9.2 MB | 1.43 s | 54.5 ms | 123.0 ms | 360 ms | 243 ms | 77.5 MB |

install size (core, no extras, uv): 145.2 KB

### Reading

- Keyword queries are solved for every script the tokenizer understands. The
  tokenizer keeps only `[a-z0-9]+` and Hangul, so **Japanese and Chinese
  text is dropped entirely** (ja exact MRR 0.18 comes only from ASCII anchors
  such as `PostgreSQL`; zh is 0.00) and accented Latin words are split
  (`azafrán` -> `azafr`, `n`).
- Paraphrases share no content words with their note; the small non-zero
  paraphrase scores come from function words (`the`, `my`, `die`, ...)
  that the engine does not filter, plus two tolerated overlaps (de `beim`,
  es `antes`).
- Code-switched queries score through the native words they keep; for
  English notes (asked about in Korean) only through the single English word.
- Latency grows with the number of notes; the per-query index refresh (a
  stat of every note file) is the likely driver but is not isolated here.
