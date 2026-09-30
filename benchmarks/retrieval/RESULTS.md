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

The tokenizer now handles every script in the benchmark: NFKC + casefold;
Han/kana runs as character unigrams + bigrams; Hangul as before; every other
word accent-folded, plus a 5-letter truncation stem for words of 6+ letters
(`verlängerung` and `verlängert` meet at `verla~`); queries that mix scripts
(Hangul / CJK / Latin; digits are neutral) favour notes that match every
script; single Han/kana characters are left out of BM25 document length.
Every choice was made on the dev split (see the PR); the test numbers below
were measured once, back to back (before = main at `b8e68ca`'s tree, after =
this branch), same machine and corpus. Reproduce with
`python benchmarks/retrieval/compare.py before.json after.json`.

#### BM25 v1 (main) -> Unicode tokenizer (test split): R@5 and MRR per slice

| notes | slice | n | R@5 | MRR |
|---|---|---|---|---|
| 160 | en | 252 | 0.679 -> 0.698 (+0.020) | 0.552 -> 0.591 (+0.039) |
| 160 | ko | 243 | 0.658 -> 0.654 (-0.004) | 0.583 -> 0.579 (-0.004) |
| 160 | ja | 99 | 0.061 -> 0.848 (+0.788) | 0.061 -> 0.794 (+0.733) |
| 160 | zh | 135 | 0.000 -> 0.867 (+0.867) | 0.000 -> 0.818 (+0.818) |
| 160 | es | 108 | 0.722 -> 0.769 (+0.046) | 0.615 -> 0.698 (+0.083) |
| 160 | de | 135 | 0.733 -> 0.756 (+0.022) | 0.612 -> 0.689 (+0.077) |
| 160 | exact (all langs) | 324 | 0.778 -> 1.000 (+0.222) | 0.778 -> 1.000 (+0.222) |
| 160 | para (all langs) | 324 | 0.225 -> 0.370 (+0.145) | 0.137 -> 0.269 (+0.131) |
| 160 | mixed (all langs) | 324 | 0.583 -> 0.855 (+0.272) | 0.430 -> 0.729 (+0.298) |
| 1000 | en | 252 | 0.635 -> 0.679 (+0.044) | 0.529 -> 0.581 (+0.053) |
| 1000 | ko | 243 | 0.613 -> 0.613 (=0.000) | 0.558 -> 0.554 (-0.004) |
| 1000 | ja | 99 | 0.061 -> 0.848 (+0.788) | 0.061 -> 0.782 (+0.722) |
| 1000 | zh | 135 | 0.000 -> 0.830 (+0.830) | 0.000 -> 0.766 (+0.766) |
| 1000 | es | 108 | 0.648 -> 0.694 (+0.046) | 0.593 -> 0.655 (+0.062) |
| 1000 | de | 135 | 0.674 -> 0.741 (+0.067) | 0.579 -> 0.664 (+0.085) |
| 1000 | exact (all langs) | 324 | 0.778 -> 1.000 (+0.222) | 0.778 -> 1.000 (+0.222) |
| 1000 | para (all langs) | 324 | 0.139 -> 0.302 (+0.164) | 0.096 -> 0.219 (+0.123) |
| 1000 | mixed (all langs) | 324 | 0.552 -> 0.830 (+0.278) | 0.414 -> 0.701 (+0.288) |
| 10000 | en | 252 | 0.635 -> 0.655 (+0.020) | 0.523 -> 0.568 (+0.046) |
| 10000 | ko | 243 | 0.617 -> 0.609 (-0.008) | 0.569 -> 0.559 (-0.010) |
| 10000 | ja | 99 | 0.061 -> 0.848 (+0.788) | 0.061 -> 0.782 (+0.722) |
| 10000 | zh | 135 | 0.000 -> 0.822 (+0.822) | 0.000 -> 0.764 (+0.764) |
| 10000 | es | 108 | 0.648 -> 0.704 (+0.056) | 0.599 -> 0.673 (+0.073) |
| 10000 | de | 135 | 0.659 -> 0.741 (+0.081) | 0.590 -> 0.681 (+0.091) |
| 10000 | exact (all langs) | 324 | 0.778 -> 1.000 (+0.222) | 0.776 -> 1.000 (+0.224) |
| 10000 | para (all langs) | 324 | 0.117 -> 0.281 (+0.164) | 0.083 -> 0.205 (+0.122) |
| 10000 | mixed (all langs) | 324 | 0.571 -> 0.830 (+0.259) | 0.439 -> 0.722 (+0.283) |

#### MRR per query author (test split)

| notes | author | exact | para | mixed |
|---|---|---|---|---|
| 160 | claude-fable-5.1 | 0.778 -> 1.000 (+0.222) | 0.183 -> 0.348 (+0.164) | 0.391 -> 0.707 (+0.316) |
| 160 | claude-opus-5.5 | 0.778 -> 1.000 (+0.222) | 0.102 -> 0.197 (+0.095) | 0.581 -> 0.820 (+0.239) |
| 160 | gpt-6.1-sol | 0.778 -> 1.000 (+0.222) | 0.128 -> 0.261 (+0.134) | 0.319 -> 0.660 (+0.341) |
| 1000 | claude-fable-5.1 | 0.778 -> 1.000 (+0.222) | 0.144 -> 0.301 (+0.157) | 0.367 -> 0.664 (+0.298) |
| 1000 | claude-opus-5.5 | 0.778 -> 1.000 (+0.222) | 0.060 -> 0.154 (+0.094) | 0.558 -> 0.780 (+0.222) |
| 1000 | gpt-6.1-sol | 0.778 -> 1.000 (+0.222) | 0.084 -> 0.203 (+0.120) | 0.316 -> 0.660 (+0.345) |
| 10000 | claude-fable-5.1 | 0.778 -> 1.000 (+0.222) | 0.121 -> 0.271 (+0.150) | 0.403 -> 0.698 (+0.296) |
| 10000 | claude-opus-5.5 | 0.773 -> 1.000 (+0.227) | 0.053 -> 0.146 (+0.093) | 0.558 -> 0.780 (+0.223) |
| 10000 | gpt-6.1-sol | 0.778 -> 1.000 (+0.222) | 0.074 -> 0.198 (+0.124) | 0.356 -> 0.686 (+0.330) |

#### Footprint

| notes | index on disk | p50 | p95 | cold wall | peak RSS |
|---|---|---|---|---|---|
| 160 | 0.17 MB -> 0.27 MB | 0.5 -> 0.6 ms | 0.6 -> 0.7 ms | 35 -> 40 ms | 22 -> 23 MB |
| 1000 | 0.97 MB -> 1.57 MB | 3.0 -> 3.1 ms | 3.8 -> 3.9 ms | 52 -> 58 ms | 27 -> 31 MB |
| 10000 | 9.61 MB -> 15.79 MB | 37.1 -> 37.6 ms | 39.8 -> 42.2 ms | 198 -> 340 ms | 81 -> 122 MB |

Queries whose gold rank improved / worsened (test split):

| notes | en | ko | ja | zh | es | de |
|---|---|---|---|---|---|---|
| 160 | 26 up / 16 down of 252 | 12 up / 15 down of 243 | 91 up / 0 down of 99 | 124 up / 0 down of 135 | 23 up / 8 down of 108 | 26 up / 9 down of 135 |
| 1000 | 33 up / 10 down of 252 | 8 up / 11 down of 243 | 82 up / 0 down of 99 | 114 up / 0 down of 135 | 16 up / 3 down of 108 | 26 up / 5 down of 135 |
| 10000 | 28 up / 12 down of 252 | 6 up / 10 down of 243 | 80 up / 0 down of 99 | 114 up / 0 down of 135 | 14 up / 0 down of 108 | 25 up / 5 down of 135 |

Reading:

- Japanese and Chinese go from unretrievable to MRR 0.76-0.82; exact keyword
  queries are solved in every language; English, Spanish and German gain
  0.04-0.09 MRR at every size; every query author gains on every query kind.
- **Korean does not improve in this mode** (MRR -0.004 / -0.004 / -0.010,
  i.e. 3, 3 and 4 more queries worsened than improved). At 10k notes all 10
  Korean queries that lost rank are code-switched ones: their English words
  now also match English notes through the truncation stems. Korean text
  itself is tokenized exactly as before. Paraphrase-level gains for Korean need
  the optional semantic leg.
- The accent folding that fixes split words (`azafr` + `n`) also costs some
  Spanish paraphrase queries on its own (measured on the test split without the truncation
  stem, as a diagnostic after the fact: paraphrase MRR 0.146 folded vs 0.194
  unfolded at 160 notes); the truncation
  stem more than recovers it (Spanish +0.06-0.08 overall).
- The index grows by ~65 % (CJK unigrams + bigrams, stems, JSON escapes) and
  cold start by ~140 ms at 10k notes.

How the design was chosen (dev split, 1k notes, MRR; the test split was not
used for any decision):

| variant | en | ko | ja | zh | es | de |
|---|---|---|---|---|---|---|
| BM25 v1 (main) | 0.482 | 0.605 | 0.096 | 0.000 | 0.589 | 0.661 |
| Unicode tokenizer without stems | 0.481 | 0.602 | 0.708 | 0.794 | 0.581 | 0.623 |
| + 5-letter truncation stem (this PR) | 0.536 | 0.594 | 0.702 | 0.780 | 0.656 | 0.714 |

Rejected on dev: suffix stemmers, Hangul unigrams, title weighting, k1/b
changes, Korean particle stripping, Japanese script segmentation, a
term-coverage bonus, per-script average document length.

## Compressed index cache (core, zero dependencies)

The index cache is now level-1 zlib over the same JSON layout
(`.mnemosyne-index.json.z`, format v4; an old `.mnemosyne-index.json` is
removed on the next save). It is lossless: measured back to back against main
(`9678ef4`'s tree), every R@1/R@5/MRR/nDCG value on every language, query kind
and author slice is identical at 160, 1k and 10k notes, and no query changed
rank (compressed run at `6b326b3`; later commits touch tests, docs and
snippets only). Stated tolerance for size-only changes was at most -0.02 MRR on any
slice; the chosen change uses none of it.

#### Footprint, main -> compressed cache (decimal MB; latency pooled over dev + test queries)

| notes | index on disk | p50 | p95 | cold wall | peak RSS |
|---|---|---|---|---|---|
| 160 | 0.27 MB -> 0.07 MB | 0.6 -> 0.5 ms | 0.6 -> 0.7 ms | 37 -> 38 ms | 23 -> 23 MB |
| 1000 | 1.57 MB -> 0.35 MB | 3.1 -> 3.7 ms | 3.7 -> 5.3 ms | 55 -> 63 ms | 31 -> 33 MB |
| 10000 | 15.79 MB -> 3.27 MB | 38.2 -> 39.4 ms | 48.0 -> 46.6 ms | 322 -> 309 ms | 123 -> 138 MB |

Cost of saving (median of 20 `note_written` calls, one edited note):

| notes | main | compressed |
|---|---|---|
| 1000 | 10.0 ms | 19.5 ms |
| 10000 | 108.7 ms | 184.3 ms |

Reading: the cache is 74-79 % smaller (74 % at 160 notes, 79 % at 10k; 3.27 MB
at 10k vs 9.6 MB for the original BM25 v1 index). Search never reads the
cache file, and decompressing it costs ~1 ms per 0.35 MB; the p50 / p95 /
cold-start differences in the table (largest: +1.6 ms p95 and +8 ms cold at
1k) come from single runs and were not repeated to bound noise. Saving a note costs ~75 ms more at 10k
notes because the whole cache is compressed on every save, and peak RSS during
load is ~15 MB higher at 10k (compressed and decoded text are briefly held
together). A vault shared by an older and a newer version keeps rebuilding:
the old version writes `.mnemosyne-index.json`, the new one deletes it.

Alternatives measured at 10k notes (same machine; encode / decode time of the
cache alone):

| cache format | size | encode | decode |
|---|---|---|---|
| plain JSON (main) | 15.79 MB | 98 ms | 132 ms |
| delta + varint postings, shared vocabulary (no zlib) | 5.52 MB | 243 ms | 205 ms |
| vocabulary + delta layout + zlib level 1 | 2.21 MB | 318 ms | 178 ms |
| **main layout + zlib level 1 (chosen)** | **3.26 MB** (3.27 MB with the vault's own run) | **184 ms** | **168 ms** |
| main layout + zlib level 6 | 2.60 MB | 388 ms | 128 ms |

The hand-written varint codec was 70 % larger than zlib and slower on both
paths (a first version of this PR used it: saves at 10k took 279 ms and cold
start 369 ms); the vocabulary + zlib variant saves another 1 MB but adds
~130 ms to every save and a second codec to port. Level 6 saves 0.7 MB for
twice the encode time.

Pruning, measured and rejected:

- **Corpus-wide stopwords** (terms in more than `max(5 % of notes, 50)` notes
  dropped from postings and queries; 4.39 MB with the varint codec): higher MRR for Korean (+0.04) and code-switched queries
  (+0.05-0.07), but English lost rank per query (1k: 15 down / 4 up; 10k:
  10 down / 5 up), queries made only of common words returned nothing, and the
  stop list made a live index and a reloaded one rank differently. English
  must not get worse (the lesson from omo PR #9209), so it was reverted.
- **Ultra-rare terms** (df = 1): saves 0.2 MB of 5.5 MB but deletes the names
  exact queries look for (dev exact MRR 0.996 -> 0.766).

## Code-switched queries in the core: measured, not changed

The Unicode tokenizer left one slice below BM25 v1: Korean, MRR 0.569 -> 0.559
at 10k notes (test split), all of it on code-switched queries. Three ways to
win it back in the zero-dependency core were measured on the dev split. None
is shipped; the core ranks exactly as before. The numbers below are dev, MRR,
all three authors pooled unless a row names an author; "up / down" counts
queries whose gold note moved up or down against the current core.

**1. Re-weighting the truncation stems trades English for Korean, one for
one.** In a query that mixes scripts, a Hangul word counts about three times
(the run plus its bigrams) and a Latin word twice (the word plus its stem).
Removing or shrinking the Latin double count moves rank from English gold notes
to Korean ones:

| variant (10k notes) | en | ko | zh |
|---|---|---|---|
| current core | 0.528 | 0.597 | 0.756 |
| stems x 0 on notes with no native-script match | 0.482 (1 up / 11 down) | 0.629 (10 up / 0 down) | 0.778 (2 up / 0 down) |
| stems x 0.25 on notes with no native-script match | 0.511 (1 up / 7 down) | 0.617 (6 up / 0 down) | 0.778 (2 up / 0 down) |
| stems x 0.5 on notes with no native-script match | 0.519 (1 up / 5 down) | 0.609 (4 up / 0 down) | 0.756 |
| `max(word, stem)` instead of word + stem, stem weight 0.25 or 0.5 | 0.481-0.482 (0-1 up / 11 down) | 0.629 (10 up / 0 down) | 0.778 (2 up / 0 down) |

("Native-script match" = the note matched a Hangul or Han/kana term of the
query. `max` with stem weight 1.0 was measured at 160 and 1k notes only and
stays within 0.002 English MRR of the `max` row there.) The same trade appears
at 160 and 1k notes. The script coordination bonus is no lever either:
`SCRIPT_BONUS` from 0 to 2.0 changes no gold rank at 1k notes.

**2. Boosting the minority script looks like a free win on this benchmark.**
Of the 117 `mixed` dev queries for en/ko/ja/zh notes, 109 mix two scripts (the
other 8 ask about an English note in Korean only), and in every one of the 109
the gold note is written in the script the query uses least ("English plus one
Korean word" targets the Korean note; pinned by
`test_mixed_dev_queries_target_the_minority_script`). Multiplying the idf of the minority-script terms
(ties and single-script queries untouched) helps every language it touches and
lowers no query, for every author:

| notes | boost | en | ko | ja | zh | queries up / down per author (opus, sol, fable) |
|---|---|---|---|---|---|---|
| 160 | 1.0 | 0.549 | 0.604 | 0.720 | 0.815 | - |
| 160 | 1.5 | 0.593 | 0.650 | 0.726 | 0.837 | 7 / 0, 7 / 0, 12 / 0 |
| 160 | 2.0 | 0.603 | 0.673 | 0.726 | 0.837 | 11 / 0, 7 / 0, 13 / 0 |
| 1000 | 1.0 | 0.536 | 0.594 | 0.702 | 0.780 | - |
| 1000 | 1.5 | 0.578 | 0.638 | 0.709 | 0.819 | 8 / 0, 6 / 0, 12 / 0 |
| 1000 | 2.0 | 0.591 | 0.669 | 0.709 | 0.819 | 12 / 0, 7 / 0, 14 / 0 |
| 10000 | 1.0 | 0.528 | 0.597 | 0.694 | 0.756 | - |
| 10000 | 1.5 | 0.565 | 0.632 | 0.694 | 0.793 | 7 / 0, 3 / 0, 14 / 0 |
| 10000 | 2.0 | 0.582 | 0.674 | 0.694 | 0.793 | 11 / 0, 6 / 0, 14 / 0 |

Spanish, German, exact and paraphrase queries do not move.

**3. The win comes from how the `mixed` queries were authored, and it costs
the opposite kind of question.** The authoring rule for `mixed` ("Korean with
at most one English word for English notes; English plus one or two native
words otherwise") makes the gold note the minority-script one by construction,
for all three authors. The mirror case also occurs in real use: a
question in the note's own language with one foreign word dropped in, where
that word is the asker's gloss and is not in the note. Two authors wrote such
`counter` questions for the 39 en/ko/ja/zh dev notes, from a notes-only export
and independently of each other (`dev_extra_*.json`, loaded by
`retrieval_corpus.dev_extra_queries()`, audited by the tests, never part of
`queries()` or of any reported table). Korean counter questions (13 per
author), MRR and queries that lost rank against the current core:

| boost | claude-opus-5.5, 160 / 1k / 10k | gpt-6.1-sol, 160 / 1k / 10k |
|---|---|---|
| 1.0 | 1.000 / 1.000 / 1.000 | 1.000 / 0.962 / 0.962 |
| 1.25 | unchanged | 0.962 (1 down) / 0.962 / 0.962 |
| 1.5 | unchanged | 0.962 (1 down) / 0.962 / 0.962 |
| 1.75 | unchanged | 0.962 (1 down) / 0.923 (1 down) / 0.962 |
| 2.0 | unchanged | 0.923 (2 down) / 0.923 (1 down) / 0.923 (1 down) |

Every lost query goes from rank 1 to rank 2 (R@5 stays 1.000): the boosted
English word ("routine", "checklist") lets an English note that contains it
overtake the Korean note the question is about. English, Japanese and
Chinese counter questions do not move for either author. Switching the boost
off when some note already holds a given share (0.3 to 0.7) of the query's
majority-script terms removes part of the dev gains and never the loss at 160
notes.

Decision: the two authors disagree (one unaffected, one lower at every boost
for at least one corpus size), so the boost is not an improvement under the
rule that a change must hold on every author's questions, and it is not
shipped. A Korean sentence with one English word has the same surface form
whether the word is quoted from an English note or glosses a Korean one; a
lexical ranker cannot tell the two apart, and only the size of the boost
trades them. The Korean number in the core therefore stays at 0.559 (10k,
test); Korean paraphrase-level gains need the optional semantic mode, which is
measured in its own PR.

The same authors also wrote one more `exact` / `para` / `mixed` triple for each
zh and de dev note, the two thinnest dev slices (15 queries per author each).
They are used for tuning only; the frozen test questions are untouched.
