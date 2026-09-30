# Retrieval benchmark results

Corpus: `retrieval_corpus.py` - 160 fictional gold notes in six languages
(40 English, 40 Korean, 20 each Japanese / Chinese / Spanish / German; every
4th note padded into a long note), 3 queries each (`exact` keyword, `para`
low-overlap paraphrase, `mixed` code-switched), split by note into dev and
test. Padding adds deterministic template distractors in all six languages up
to 1k / 10k notes. All numbers below are the **test split**; dev is reserved
for tuning. Latency is wall-clock on a shared laptop - compare engines within
one run, not across runs.

Reproduce:

```bash
python benchmarks/retrieval/bench_retrieval.py --sizes 160 1000 10000 --install-size
```

## Baseline: BM25 + Hangul bigrams (core, zero dependencies)

Measured 2026-09-30 on Apple M1, Python 3.11, macOS.

#### Quality by language (test split, all query kinds, k=10)

| engine | notes | lang | R@1 | R@5 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| bm25 | 160 | en | 0.487 | 0.705 | 0.574 | 0.618 |
| bm25 | 160 | ko | 0.564 | 0.692 | 0.622 | 0.657 |
| bm25 | 160 | ja | 0.077 | 0.077 | 0.077 | 0.077 |
| bm25 | 160 | zh | 0.000 | 0.000 | 0.000 | 0.000 |
| bm25 | 160 | es | 0.410 | 0.744 | 0.578 | 0.643 |
| bm25 | 160 | de | 0.410 | 0.795 | 0.572 | 0.628 |
| bm25 | 1000 | en | 0.474 | 0.667 | 0.555 | 0.589 |
| bm25 | 1000 | ko | 0.551 | 0.641 | 0.595 | 0.612 |
| bm25 | 1000 | ja | 0.077 | 0.077 | 0.077 | 0.077 |
| bm25 | 1000 | zh | 0.000 | 0.000 | 0.000 | 0.000 |
| bm25 | 1000 | es | 0.385 | 0.641 | 0.519 | 0.562 |
| bm25 | 1000 | de | 0.410 | 0.718 | 0.563 | 0.610 |
| bm25 | 10000 | en | 0.462 | 0.679 | 0.549 | 0.585 |
| bm25 | 10000 | ko | 0.551 | 0.628 | 0.587 | 0.600 |
| bm25 | 10000 | ja | 0.077 | 0.077 | 0.077 | 0.077 |
| bm25 | 10000 | zh | 0.000 | 0.000 | 0.000 | 0.000 |
| bm25 | 10000 | es | 0.359 | 0.641 | 0.496 | 0.534 |
| bm25 | 10000 | de | 0.410 | 0.718 | 0.563 | 0.609 |

#### Quality by query kind (test split, all languages)

| engine | notes | kind | R@1 | R@5 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| bm25 | 160 | exact | 0.779 | 0.779 | 0.779 | 0.779 |
| bm25 | 160 | para | 0.038 | 0.183 | 0.100 | 0.141 |
| bm25 | 160 | mixed | 0.308 | 0.692 | 0.478 | 0.542 |
| bm25 | 1000 | exact | 0.769 | 0.779 | 0.774 | 0.775 |
| bm25 | 1000 | para | 0.029 | 0.096 | 0.061 | 0.076 |
| bm25 | 1000 | mixed | 0.298 | 0.644 | 0.462 | 0.518 |
| bm25 | 10000 | exact | 0.760 | 0.779 | 0.769 | 0.772 |
| bm25 | 10000 | para | 0.019 | 0.096 | 0.053 | 0.066 |
| bm25 | 10000 | mixed | 0.298 | 0.644 | 0.455 | 0.508 |

#### MRR by language x kind (test split)

| engine | notes | lang | exact | para | mixed |
|---|---|---|---|---|---|
| bm25 | 160 | en | 1.000 | 0.141 | 0.581 |
| bm25 | 160 | ko | 1.000 | 0.074 | 0.793 |
| bm25 | 160 | ja | 0.231 | 0.000 | 0.000 |
| bm25 | 160 | zh | 0.000 | 0.000 | 0.000 |
| bm25 | 160 | es | 1.000 | 0.185 | 0.548 |
| bm25 | 160 | de | 1.000 | 0.185 | 0.531 |
| bm25 | 1000 | en | 0.981 | 0.106 | 0.578 |
| bm25 | 1000 | ko | 1.000 | 0.038 | 0.745 |
| bm25 | 1000 | ja | 0.231 | 0.000 | 0.000 |
| bm25 | 1000 | zh | 0.000 | 0.000 | 0.000 |
| bm25 | 1000 | es | 1.000 | 0.017 | 0.538 |
| bm25 | 1000 | de | 1.000 | 0.179 | 0.511 |
| bm25 | 10000 | en | 0.981 | 0.080 | 0.586 |
| bm25 | 10000 | ko | 1.000 | 0.038 | 0.721 |
| bm25 | 10000 | ja | 0.231 | 0.000 | 0.000 |
| bm25 | 10000 | zh | 0.000 | 0.000 | 0.000 |
| bm25 | 10000 | es | 0.962 | 0.000 | 0.526 |
| bm25 | 10000 | de | 1.000 | 0.189 | 0.500 |

#### Footprint

| engine | notes | index on disk | build | p50 | p95 | cold start | peak RSS |
|---|---|---|---|---|---|---|---|
| bm25 | 160 | 163.4 KB | 0.03 s | 0.6 ms | 1.9 ms | 7 ms | 24.3 MB |
| bm25 | 1000 | 925.4 KB | 0.09 s | 5.4 ms | 8.8 ms | 16 ms | 28.8 MB |
| bm25 | 10000 | 8.9 MB | 1.29 s | 69.5 ms | 129.7 ms | 450 ms | 69.2 MB |

install size (core, no extras): 145.2 KB

### Reading

- Keyword queries are solved for every script the tokenizer understands; the
  tokenizer keeps only `[a-z0-9]+` and Hangul, so **Japanese and Chinese
  text is dropped entirely** (ja MRR 0.08 comes only from ASCII anchors such
  as `PostgreSQL`; zh is 0.00) and accented Latin words are split
  (`azafrán` -> `azafr`, `n`).
- Paraphrases that share no content words are close to invisible to a
  lexical engine (MRR 0.05-0.10).
- Code-switched queries score only through the one or two native words they
  keep.
- Latency is dominated by the per-query stat pass of `refresh()`, which
  scales with the number of files.
