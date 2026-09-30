# Retrieval benchmark results

Corpus: `retrieval_corpus.py` - 160 gold notes in six languages (40 English,
40 Korean, 20 each Japanese / Chinese / Spanish / German; every 4th note padded
into a long note); people, companies and events are invented. Each note has 3
queries (`exact` keyword, `para` low-overlap paraphrase, `mixed`
code-switched), split by note into dev and test. Padding adds deterministic
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
  ja/zh/es/de rests on 13 queries, so one query moves its MRR by up to 0.077;
  treat cell differences below ~0.08 as noise.
- Latency, build and cold-start numbers are wall clock on a shared laptop and
  move with machine load; compare engines only within one run. This baseline
  run shared the CPU with another benchmark, so its timings are pessimistic;
  before/after comparisons in later PRs re-run both engines back to back.
- Ties in score fall back to directory-scan order, which differs slightly
  between filesystems.

## Baseline: BM25 + Hangul bigrams (core, zero dependencies)

Measured 2026-09-30 on Apple M1, Python 3.11, macOS (harness at 8ab8ecb plus
the review fixes in this PR; library unchanged).

#### Quality by language (test split, all query kinds, k=10)

| engine | notes | lang | n | R@1 | R@5 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|
| bm25 | 160 | en | 78 | 0.487 | 0.705 | 0.575 | 0.619 |
| bm25 | 160 | ko | 78 | 0.577 | 0.692 | 0.632 | 0.664 |
| bm25 | 160 | ja | 39 | 0.077 | 0.077 | 0.077 | 0.077 |
| bm25 | 160 | zh | 39 | 0.000 | 0.000 | 0.000 | 0.000 |
| bm25 | 160 | es | 39 | 0.641 | 0.744 | 0.694 | 0.729 |
| bm25 | 160 | de | 39 | 0.641 | 0.795 | 0.688 | 0.714 |
| bm25 | 1000 | en | 78 | 0.487 | 0.667 | 0.561 | 0.594 |
| bm25 | 1000 | ko | 78 | 0.551 | 0.641 | 0.598 | 0.615 |
| bm25 | 1000 | ja | 39 | 0.077 | 0.077 | 0.077 | 0.077 |
| bm25 | 1000 | zh | 39 | 0.000 | 0.000 | 0.000 | 0.000 |
| bm25 | 1000 | es | 39 | 0.615 | 0.641 | 0.634 | 0.647 |
| bm25 | 1000 | de | 39 | 0.641 | 0.718 | 0.679 | 0.695 |
| bm25 | 10000 | en | 78 | 0.474 | 0.679 | 0.555 | 0.589 |
| bm25 | 10000 | ko | 78 | 0.551 | 0.628 | 0.590 | 0.603 |
| bm25 | 10000 | ja | 39 | 0.077 | 0.077 | 0.077 | 0.077 |
| bm25 | 10000 | zh | 39 | 0.000 | 0.000 | 0.000 | 0.000 |
| bm25 | 10000 | es | 39 | 0.564 | 0.641 | 0.603 | 0.613 |
| bm25 | 10000 | de | 39 | 0.641 | 0.718 | 0.678 | 0.694 |

#### Quality by query kind (test split, all languages)

| engine | notes | kind | n | R@1 | R@5 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|
| bm25 | 160 | exact | 104 | 0.779 | 0.779 | 0.779 | 0.779 |
| bm25 | 160 | para | 104 | 0.038 | 0.183 | 0.100 | 0.141 |
| bm25 | 160 | mixed | 104 | 0.490 | 0.692 | 0.574 | 0.612 |
| bm25 | 1000 | exact | 104 | 0.779 | 0.779 | 0.779 | 0.779 |
| bm25 | 1000 | para | 104 | 0.029 | 0.096 | 0.061 | 0.076 |
| bm25 | 1000 | mixed | 104 | 0.471 | 0.644 | 0.551 | 0.584 |
| bm25 | 10000 | exact | 104 | 0.769 | 0.779 | 0.774 | 0.775 |
| bm25 | 10000 | para | 104 | 0.019 | 0.096 | 0.053 | 0.066 |
| bm25 | 10000 | mixed | 104 | 0.462 | 0.644 | 0.541 | 0.571 |

#### MRR by language x kind (test split)

| engine | notes | lang | exact | para | mixed |
|---|---|---|---|---|---|
| bm25 | 160 | en | 1.000 | 0.141 | 0.585 |
| bm25 | 160 | ko | 1.000 | 0.074 | 0.822 |
| bm25 | 160 | ja | 0.231 | 0.000 | 0.000 |
| bm25 | 160 | zh | 0.000 | 0.000 | 0.000 |
| bm25 | 160 | es | 1.000 | 0.185 | 0.896 |
| bm25 | 160 | de | 1.000 | 0.185 | 0.881 |
| bm25 | 1000 | en | 1.000 | 0.106 | 0.578 |
| bm25 | 1000 | ko | 1.000 | 0.038 | 0.755 |
| bm25 | 1000 | ja | 0.231 | 0.000 | 0.000 |
| bm25 | 1000 | zh | 0.000 | 0.000 | 0.000 |
| bm25 | 1000 | es | 1.000 | 0.017 | 0.885 |
| bm25 | 1000 | de | 1.000 | 0.179 | 0.857 |
| bm25 | 10000 | en | 1.000 | 0.080 | 0.586 |
| bm25 | 10000 | ko | 1.000 | 0.038 | 0.731 |
| bm25 | 10000 | ja | 0.231 | 0.000 | 0.000 |
| bm25 | 10000 | zh | 0.000 | 0.000 | 0.000 |
| bm25 | 10000 | es | 0.962 | 0.000 | 0.846 |
| bm25 | 10000 | de | 1.000 | 0.189 | 0.846 |

#### Footprint

| engine | notes | index on disk | build | p50 | p95 | cold wall | cold load | peak RSS |
|---|---|---|---|---|---|---|---|---|
| bm25 | 160 | 167.3 KB | 0.04 s | 1.7 ms | 4.3 ms | 129 ms | 30 ms | 20.9 MB |
| bm25 | 1000 | 949.9 KB | 0.22 s | 8.5 ms | 17.1 ms | 96 ms | 40 ms | 25.5 MB |
| bm25 | 10000 | 9.2 MB | 11.00 s | 94.9 ms | 212.1 ms | 943 ms | 498 ms | 75.5 MB |

install size (core, no extras, uv): 145.2 KB

### Reading

- Keyword queries are solved for every script the tokenizer understands. The
  tokenizer keeps only `[a-z0-9]+` and Hangul, so **Japanese and Chinese
  text is dropped entirely** (ja exact MRR 0.23 comes only from ASCII anchors
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
