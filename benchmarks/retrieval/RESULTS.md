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
  test note). A language x kind cell for ja/zh/es/de rests on 33-45 queries
  (one query moves MRR by up to ~0.03); a single author's language cell on
  33-84 queries, an author x kind cell on 108.
- Latency, build and cold-start numbers are wall clock on a laptop and move
  with machine load; compare engines only within one run (later PRs re-run
  both engines back to back). Latency is pooled over dev + test queries.
- Ties in score fall back to directory-scan order, which differs slightly
  between filesystems.

## Baseline: BM25 + Hangul bigrams (core, zero dependencies)

Measured 2026-09-30 on Apple M1, Python 3.11, macOS (`git 660cfbe · python 3.11.15 · Darwin arm64`; library unchanged).

#### Quality by language (test split, all query kinds, k=10)

| engine | notes | lang | n | R@1 | R@5 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|
| bm25 | 160 | en | 252 | 0.468 | 0.679 | 0.552 | 0.598 |
| bm25 | 160 | ko | 243 | 0.523 | 0.658 | 0.583 | 0.615 |
| bm25 | 160 | ja | 99 | 0.061 | 0.061 | 0.061 | 0.061 |
| bm25 | 160 | zh | 135 | 0.000 | 0.000 | 0.000 | 0.000 |
| bm25 | 160 | es | 108 | 0.546 | 0.722 | 0.615 | 0.660 |
| bm25 | 160 | de | 135 | 0.533 | 0.733 | 0.612 | 0.650 |
| bm25 | 1000 | en | 252 | 0.456 | 0.635 | 0.529 | 0.564 |
| bm25 | 1000 | ko | 243 | 0.510 | 0.613 | 0.558 | 0.577 |
| bm25 | 1000 | ja | 99 | 0.061 | 0.061 | 0.061 | 0.061 |
| bm25 | 1000 | zh | 135 | 0.000 | 0.000 | 0.000 | 0.000 |
| bm25 | 1000 | es | 108 | 0.556 | 0.648 | 0.593 | 0.617 |
| bm25 | 1000 | de | 135 | 0.519 | 0.674 | 0.579 | 0.611 |
| bm25 | 10000 | en | 252 | 0.448 | 0.635 | 0.523 | 0.557 |
| bm25 | 10000 | ko | 243 | 0.531 | 0.617 | 0.569 | 0.586 |
| bm25 | 10000 | ja | 99 | 0.061 | 0.061 | 0.061 | 0.061 |
| bm25 | 10000 | zh | 135 | 0.000 | 0.000 | 0.000 | 0.000 |
| bm25 | 10000 | es | 108 | 0.556 | 0.648 | 0.599 | 0.614 |
| bm25 | 10000 | de | 135 | 0.533 | 0.659 | 0.590 | 0.621 |

#### Quality by query kind (test split, all languages)

| engine | notes | kind | n | R@1 | R@5 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|
| bm25 | 160 | exact | 324 | 0.778 | 0.778 | 0.778 | 0.778 |
| bm25 | 160 | para | 324 | 0.074 | 0.225 | 0.137 | 0.179 |
| bm25 | 160 | mixed | 324 | 0.327 | 0.583 | 0.430 | 0.479 |
| bm25 | 1000 | exact | 324 | 0.778 | 0.778 | 0.778 | 0.778 |
| bm25 | 1000 | para | 324 | 0.062 | 0.139 | 0.096 | 0.118 |
| bm25 | 1000 | mixed | 324 | 0.318 | 0.552 | 0.414 | 0.455 |
| bm25 | 10000 | exact | 324 | 0.775 | 0.778 | 0.776 | 0.777 |
| bm25 | 10000 | para | 324 | 0.052 | 0.117 | 0.083 | 0.100 |
| bm25 | 10000 | mixed | 324 | 0.346 | 0.571 | 0.439 | 0.478 |

#### MRR by language x kind (test split)

| engine | notes | lang | exact | para | mixed |
|---|---|---|---|---|---|
| bm25 | 160 | en | 1.000 | 0.169 | 0.488 |
| bm25 | 160 | ko | 1.000 | 0.148 | 0.602 |
| bm25 | 160 | ja | 0.182 | 0.000 | 0.000 |
| bm25 | 160 | zh | 0.000 | 0.000 | 0.000 |
| bm25 | 160 | es | 1.000 | 0.212 | 0.633 |
| bm25 | 160 | de | 1.000 | 0.238 | 0.598 |
| bm25 | 1000 | en | 1.000 | 0.110 | 0.476 |
| bm25 | 1000 | ko | 1.000 | 0.104 | 0.570 |
| bm25 | 1000 | ja | 0.182 | 0.000 | 0.000 |
| bm25 | 1000 | zh | 0.000 | 0.000 | 0.000 |
| bm25 | 1000 | es | 1.000 | 0.136 | 0.643 |
| bm25 | 1000 | de | 1.000 | 0.190 | 0.548 |
| bm25 | 10000 | en | 1.000 | 0.081 | 0.488 |
| bm25 | 10000 | ko | 1.000 | 0.098 | 0.609 |
| bm25 | 10000 | ja | 0.182 | 0.000 | 0.000 |
| bm25 | 10000 | zh | 0.000 | 0.000 | 0.000 |
| bm25 | 10000 | es | 1.000 | 0.111 | 0.687 |
| bm25 | 10000 | de | 0.989 | 0.180 | 0.602 |

#### MRR by query author (test split)

| engine | notes | author | exact | para | mixed | en | ko | ja | zh | es | de |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bm25 | 160 | claude-fable-5.1 | 0.778 | 0.183 | 0.391 | 0.607 | 0.525 | 0.061 | 0.000 | 0.636 | 0.614 |
| bm25 | 160 | claude-opus-5.5 | 0.778 | 0.102 | 0.581 | 0.587 | 0.614 | 0.061 | 0.000 | 0.718 | 0.684 |
| bm25 | 160 | gpt-6.1-sol | 0.778 | 0.128 | 0.319 | 0.463 | 0.611 | 0.061 | 0.000 | 0.491 | 0.537 |
| bm25 | 1000 | claude-fable-5.1 | 0.778 | 0.144 | 0.367 | 0.574 | 0.490 | 0.061 | 0.000 | 0.662 | 0.564 |
| bm25 | 1000 | claude-opus-5.5 | 0.778 | 0.060 | 0.558 | 0.570 | 0.584 | 0.061 | 0.000 | 0.659 | 0.663 |
| bm25 | 1000 | gpt-6.1-sol | 0.778 | 0.084 | 0.316 | 0.441 | 0.600 | 0.061 | 0.000 | 0.459 | 0.511 |
| bm25 | 10000 | claude-fable-5.1 | 0.778 | 0.121 | 0.403 | 0.564 | 0.499 | 0.061 | 0.000 | 0.650 | 0.605 |
| bm25 | 10000 | claude-opus-5.5 | 0.773 | 0.053 | 0.558 | 0.569 | 0.577 | 0.061 | 0.000 | 0.653 | 0.655 |
| bm25 | 10000 | gpt-6.1-sol | 0.778 | 0.074 | 0.356 | 0.436 | 0.631 | 0.061 | 0.000 | 0.495 | 0.510 |

#### Footprint (latency pooled over dev + test queries)

| engine | notes | index on disk | build | p50 | p95 | cold wall | cold load | peak RSS |
|---|---|---|---|---|---|---|---|---|
| bm25 | 160 | 167.3 KB | 0.02 s | 0.5 ms | 0.6 ms | 36 ms | 8 ms | 20.3 MB |
| bm25 | 1000 | 949.8 KB | 0.07 s | 3.2 ms | 4.2 ms | 49 ms | 20 ms | 25.3 MB |
| bm25 | 10000 | 9.2 MB | 0.71 s | 38.0 ms | 43.0 ms | 185 ms | 154 ms | 77.0 MB |

### Reading

- Keyword queries are solved for every script the tokenizer understands. The
  tokenizer keeps only `[a-z0-9]+` and Hangul, so **Japanese and Chinese
  text is dropped entirely** (ja exact MRR 0.18 comes only from ASCII anchors
  such as `SIM` and `nit`; zh is 0.00) and accented Latin words are split
  (`azafrán` -> `azafr`, `n`).
- Paraphrases are low-overlap, not overlap-free: tests allow at most 30 % of
  a paraphrase's content units to appear in its note (mean at most 5-6 % per
  language). Part of the small non-zero paraphrase scores comes from those
  shared units and from function words the engine does not filter.
- Code-switched queries score through the native words they keep; for
  English notes (asked about in Korean) only through the single English word.
- Latency grows with the number of notes; the per-query index refresh (a
  stat of every note file) is the likely driver but is not isolated here.
- Authors differ in style, not in rule compliance (every set passes the same
  exact / paraphrase / code-switching audits): see the per-author table.

## Query authors

Every gold note has three query sets written independently:

| author | how it was written |
|---|---|
| `claude-opus-5.5` | written together with the corpus (inline in `retrieval_corpus.py`) |
| `gpt-6.1-sol` | `queries_gpt-6.1-sol.json` - written by GPT-6.1 Sol from a notes-only export (titles + bodies), without seeing any other author's queries |
| `claude-fable-5.1` | `queries_claude-fable-5.1.json` - written by Claude Fable 5.1 under the same rules and isolation |

All authors got the same rules: `exact` = keywords copied from the note (2-7 tokens);
`para` = a question in the note's language sharing no content word with it;
`mixed` = code-switched (Korean with at most one English word for English
notes; English plus one or two native words otherwise). Tests audit every
author: exact queries must be lexical, paraphrases may share at most 30 % of
their content units with the note (mean <= 6 % per language). The GPT set leans
toward specific fact questions, the Fable set toward longer multi-part
questions, the inline set toward short topical questions; reporting per author
shows whether a ranker only wins on one author's style.

Code-switched queries are audited too: no standalone numbers (tested), one or
two native words (tested; for es/de: at most three words shared with the note,
names included), and no restated answer such as an amount or a duration
(checked by review, since number words cannot be matched reliably). Violations were sent back to their own
author, who rewrote them in isolation; nobody edited another author's
queries. The test split (108 notes) and its 972 query texts are pinned by
checksum tests and were frozen before any tuning; tuning uses dev only.

## Unicode tokenizer (core, zero dependencies)

The tokenizer now reads every script: NFKC + casefold, Han/kana runs as
character unigrams + bigrams, Hangul as before, accent-folded words for every
other script; queries that mix scripts favour notes matching every script;
single Han/kana characters are left out of BM25 document length. Both runs
below were measured back to back (before = main, after = this branch,
`git 56b5566`), same machine, same corpus. Reproduce with
`python benchmarks/retrieval/compare.py before.json after.json`.

#### BM25 v1 (main) -> Unicode tokenizer (test split): R@5 and MRR per slice

| notes | slice | n | R@5 | MRR |
|---|---|---|---|---|
| 160 | en | 252 | 0.679 -> 0.675 (-0.004) | 0.552 -> 0.550 (-0.003) |
| 160 | ko | 243 | 0.658 -> 0.654 (-0.004) | 0.583 -> 0.592 (+0.009) |
| 160 | ja | 99 | 0.061 -> 0.848 (+0.788) | 0.061 -> 0.803 (+0.742) |
| 160 | zh | 135 | 0.000 -> 0.867 (+0.867) | 0.000 -> 0.822 (+0.822) |
| 160 | es | 108 | 0.722 -> 0.694 (-0.028) | 0.615 -> 0.594 (-0.021) |
| 160 | de | 135 | 0.733 -> 0.733 (=0.000) | 0.612 -> 0.609 (-0.003) |
| 160 | exact (all langs) | 324 | 0.778 -> 1.000 (+0.222) | 0.778 -> 1.000 (+0.222) |
| 160 | para (all langs) | 324 | 0.225 -> 0.361 (+0.136) | 0.137 -> 0.252 (+0.115) |
| 160 | mixed (all langs) | 324 | 0.583 -> 0.812 (+0.228) | 0.430 -> 0.659 (+0.228) |
| 1000 | en | 252 | 0.635 -> 0.643 (+0.008) | 0.529 -> 0.533 (+0.004) |
| 1000 | ko | 243 | 0.613 -> 0.617 (+0.004) | 0.558 -> 0.564 (+0.006) |
| 1000 | ja | 99 | 0.061 -> 0.869 (+0.808) | 0.061 -> 0.803 (+0.742) |
| 1000 | zh | 135 | 0.000 -> 0.837 (+0.837) | 0.000 -> 0.779 (+0.779) |
| 1000 | es | 108 | 0.648 -> 0.639 (-0.009) | 0.593 -> 0.586 (-0.007) |
| 1000 | de | 135 | 0.674 -> 0.674 (=0.000) | 0.579 -> 0.581 (+0.002) |
| 1000 | exact (all langs) | 324 | 0.778 -> 1.000 (+0.222) | 0.778 -> 1.000 (+0.222) |
| 1000 | para (all langs) | 324 | 0.139 -> 0.287 (+0.148) | 0.096 -> 0.204 (+0.108) |
| 1000 | mixed (all langs) | 324 | 0.552 -> 0.784 (+0.231) | 0.414 -> 0.640 (+0.227) |
| 10000 | en | 252 | 0.635 -> 0.639 (+0.004) | 0.523 -> 0.528 (+0.005) |
| 10000 | ko | 243 | 0.617 -> 0.621 (+0.004) | 0.569 -> 0.575 (+0.006) |
| 10000 | ja | 99 | 0.061 -> 0.869 (+0.808) | 0.061 -> 0.805 (+0.744) |
| 10000 | zh | 135 | 0.000 -> 0.830 (+0.830) | 0.000 -> 0.768 (+0.768) |
| 10000 | es | 108 | 0.648 -> 0.639 (-0.009) | 0.599 -> 0.600 (=0.000) |
| 10000 | de | 135 | 0.659 -> 0.674 (+0.015) | 0.590 -> 0.600 (+0.010) |
| 10000 | exact (all langs) | 324 | 0.778 -> 1.000 (+0.222) | 0.776 -> 1.000 (+0.224) |
| 10000 | para (all langs) | 324 | 0.117 -> 0.259 (+0.142) | 0.083 -> 0.190 (+0.107) |
| 10000 | mixed (all langs) | 324 | 0.571 -> 0.809 (+0.238) | 0.439 -> 0.668 (+0.229) |

#### MRR per query author (test split)

| notes | author | exact | para | mixed |
|---|---|---|---|---|
| 160 | claude-fable-5.1 | 0.778 -> 1.000 (+0.222) | 0.183 -> 0.326 (+0.142) | 0.391 -> 0.614 (+0.223) |
| 160 | claude-opus-5.5 | 0.778 -> 1.000 (+0.222) | 0.102 -> 0.201 (+0.100) | 0.581 -> 0.816 (+0.235) |
| 160 | gpt-6.1-sol | 0.778 -> 1.000 (+0.222) | 0.128 -> 0.230 (+0.102) | 0.319 -> 0.546 (+0.226) |
| 1000 | claude-fable-5.1 | 0.778 -> 1.000 (+0.222) | 0.144 -> 0.271 (+0.127) | 0.367 -> 0.580 (+0.214) |
| 1000 | claude-opus-5.5 | 0.778 -> 1.000 (+0.222) | 0.060 -> 0.154 (+0.094) | 0.558 -> 0.790 (+0.231) |
| 1000 | gpt-6.1-sol | 0.778 -> 1.000 (+0.222) | 0.084 -> 0.187 (+0.104) | 0.316 -> 0.551 (+0.235) |
| 10000 | claude-fable-5.1 | 0.778 -> 1.000 (+0.222) | 0.121 -> 0.245 (+0.125) | 0.403 -> 0.614 (+0.212) |
| 10000 | claude-opus-5.5 | 0.773 -> 1.000 (+0.227) | 0.053 -> 0.143 (+0.090) | 0.558 -> 0.795 (+0.237) |
| 10000 | gpt-6.1-sol | 0.778 -> 1.000 (+0.222) | 0.074 -> 0.181 (+0.107) | 0.356 -> 0.596 (+0.240) |

#### Footprint

| notes | index on disk | p50 | p95 | cold wall | peak RSS |
|---|---|---|---|---|---|
| 160 | 0.17 MB -> 0.25 MB | 0.5 -> 0.6 ms | 0.7 -> 0.7 ms | 44 -> 43 ms | 22 -> 23 MB |
| 1000 | 0.97 MB -> 1.49 MB | 3.7 -> 3.8 ms | 5.4 -> 5.8 ms | 49 -> 61 ms | 27 -> 31 MB |
| 10000 | 9.61 MB -> 15.03 MB | 39.0 -> 39.1 ms | 46.4 -> 45.9 ms | 201 -> 302 ms | 81 -> 117 MB |

Reading:

- Japanese and Chinese go from unretrievable to MRR 0.77-0.80; exact keyword
  queries are solved in every language; every query author gains on every
  query kind.
- English, Korean and German are flat to slightly up. **Spanish does not
  improve in this mode**: MRR -0.021 at 160 notes (about 3 of 108 queries move
  down), -0.007 at 1k, 0.000 at 10k. Spanish tokens are unchanged apart from
  accent folding; the shift comes from global BM25 statistics (average length
  and term weights now include the Japanese/Chinese notes that were invisible
  before). The design choices were made on the dev split (Spanish +0.005 there)
  and were not re-tuned on these test numbers.
- The index grows by ~57 % (CJK unigrams + bigrams, JSON escapes); the
  compact index format in the next change more than reverses this.
