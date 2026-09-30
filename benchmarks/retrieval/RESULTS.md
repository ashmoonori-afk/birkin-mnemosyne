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
test); Korean paraphrase-level gains need the optional semantic mode (next
section).

The same authors also wrote one more `exact` / `para` / `mixed` triple for each
zh and de dev note, the two thinnest dev slices (15 queries per author each).
They are used for tuning only; the frozen test questions are untouched.

## Vault scan at most once per 2 s during search (core, zero dependencies)

`search()` used to stat every note file on every call to notice edits made
outside the library. That stat pass was most of a search: the latency rows
above (38-43 ms at 10,000 notes) are almost entirely the scan, not BM25.
`search()` now scans at most once per `SCAN_TTL` (2 s); `refresh()` still
scans on every call, and notes written through the library are indexed when
they are written, so they never wait.

Warm latency per search, 300 dev queries, one process, macOS arm64, Python
3.11, 1-minute load 2.0; "before" is the same build with `SCAN_TTL = 0`:

| notes | scan on every search, p50 / p95 | at most once per 2 s, p50 / p95 | top-10 of the 300 queries |
|---|---|---|---|
| 1,000 | 3.04 / 3.52 ms | 0.20 / 0.41 ms | identical |
| 10,000 | 37.20 / 39.88 ms | 1.46 / 4.09 ms | identical |

Rankings are unchanged (the ranking code is untouched), so every quality
table in this file still holds. The latency columns of the footprint tables
above were measured before this change.

The cost: a note created, edited or deleted outside the library while a
long-lived process is running shows up in `search()` up to 2 s later (a
deleted note can still be returned during that window). The optional semantic
mode still scans on every search, through its own sync.

## Search-time query expansion (core, zero dependencies, opt-in per search)

`Mnemosyne.search(query, expansions=...)`, `VaultMemory.search` and the MCP
`memory_search` tool accept terms the caller adds to a query:

| tier | what the caller writes | weight |
|---|---|---|
| (the query itself) | - | 1.0 |
| `synonyms` | close synonyms or other wordings of the query's key words | 0.75 |
| `keywords` | the topic in the user's other working language(s) | 0.75 |
| `related` | looser terms a note answering the question might contain | 0.4 |
| `note_line` | one sentence written like a line of such a note | 0.4 |

Each added term scores as BM25 scaled by its tier's weight, so a literal match
counts most and a looser association least. A term already in the query is
not counted again, a term given in several tiers keeps its highest weight, and
a note that holds every original unit of the query stays ahead of every note
only an expansion found. Nothing is stored: the index, the cache file and the
ranking of a search without expansions are unchanged, and an existing vault
needs no re-indexing. The library calls no model; the host that writes the
tool call writes the expansions.

### How it was measured

Two writers, `claude-sonnet-5.5` and `gpt-6.1-sol`, were given only the query
texts (not the notes, the gold labels or the query kind) and wrote, for each of
the 1,537 query texts, 4-8 synonyms, 4-8 related terms, English keywords,
Korean keywords and one sentence. The committed `expansions_<writer>.json`
files hold what they wrote (the two keyword lists merged into `keywords`), and
the engines `expanded-claude` and `expanded-gpt` replay them through the real
library. The weights were chosen on the dev split:

| weights (synonyms and keywords / related and note_line), dev, 10,000 notes | para MRR, claude / gpt writer | slices below the core |
|---|---|---|
| 0.5 / 0.25 | 0.947 / - | none (claude) |
| **0.75 / 0.4** | **0.973 / 0.970** | none (claude); one at 160 notes (gpt), see below |
| 1.0 / 0.5 | 0.982 / - | dev counterexample questions at 160 notes |

### Test split (MRR, frozen; all three question authors pooled)

| notes | search | en | ko | ja | zh | es | de | exact | para | mixed |
|---|---|---|---|---|---|---|---|---|---|---|
| 160 | core | 0.591 | 0.579 | 0.794 | 0.818 | 0.698 | 0.689 | 1.000 | 0.269 | 0.729 |
| 160 | expansions by claude-sonnet-5.5 | 0.979 | 0.996 | 1.000 | 1.000 | 0.993 | 0.972 | 1.000 | 0.992 | 0.974 |
| 160 | expansions by gpt-6.1-sol | 0.984 | 0.981 | 0.957 | 0.961 | 0.927 | 0.884 | 1.000 | 0.970 | 0.901 |
| 1,000 | core | 0.581 | 0.554 | 0.782 | 0.766 | 0.655 | 0.664 | 1.000 | 0.219 | 0.701 |
| 1,000 | expansions by claude-sonnet-5.5 | 0.975 | 0.994 | 0.990 | 1.000 | 0.992 | 0.944 | 1.000 | 0.985 | 0.961 |
| 1,000 | expansions by gpt-6.1-sol | 0.977 | 0.976 | 0.946 | 0.960 | 0.918 | 0.865 | 1.000 | 0.964 | 0.883 |
| 10,000 | core | 0.568 | 0.559 | 0.782 | 0.764 | 0.673 | 0.681 | 1.000 | 0.205 | 0.722 |
| 10,000 | expansions by claude-sonnet-5.5 | 0.975 | 0.990 | 0.975 | 1.000 | 0.993 | 0.942 | 1.000 | 0.981 | 0.958 |
| 10,000 | expansions by gpt-6.1-sol | 0.967 | 0.973 | 0.957 | 0.956 | 0.931 | 0.871 | 1.000 | 0.952 | 0.894 |

Per question author (the writer of the expansions never saw who asked):

| notes | search | question author | para | mixed | en | ko |
|---|---|---|---|---|---|---|
| 160 | core | claude-fable-5.1 | 0.348 | 0.707 | 0.643 | 0.530 |
| 160 | core | claude-opus-5.5 | 0.197 | 0.820 | 0.606 | 0.597 |
| 160 | core | gpt-6.1-sol | 0.261 | 0.660 | 0.524 | 0.612 |
| 160 | expansions by claude-sonnet-5.5 | claude-fable-5.1 | 0.991 | 0.979 | 0.976 | 0.994 |
| 160 | expansions by claude-sonnet-5.5 | claude-opus-5.5 | 0.995 | 0.965 | 0.976 | 1.000 |
| 160 | expansions by claude-sonnet-5.5 | gpt-6.1-sol | 0.991 | 0.978 | 0.984 | 0.994 |
| 160 | expansions by gpt-6.1-sol | claude-fable-5.1 | 0.991 | 0.868 | 0.982 | 0.979 |
| 160 | expansions by gpt-6.1-sol | claude-opus-5.5 | 0.935 | 0.919 | 0.982 | 0.984 |
| 160 | expansions by gpt-6.1-sol | gpt-6.1-sol | 0.985 | 0.917 | 0.988 | 0.981 |
| 1,000 | core | claude-fable-5.1 | 0.301 | 0.664 | 0.641 | 0.487 |
| 1,000 | core | claude-opus-5.5 | 0.154 | 0.780 | 0.592 | 0.565 |
| 1,000 | core | gpt-6.1-sol | 0.203 | 0.660 | 0.512 | 0.609 |
| 1,000 | expansions by claude-sonnet-5.5 | claude-fable-5.1 | 0.981 | 0.969 | 0.970 | 0.988 |
| 1,000 | expansions by claude-sonnet-5.5 | claude-opus-5.5 | 0.984 | 0.945 | 0.970 | 1.000 |
| 1,000 | expansions by claude-sonnet-5.5 | gpt-6.1-sol | 0.991 | 0.970 | 0.984 | 0.994 |
| 1,000 | expansions by gpt-6.1-sol | claude-fable-5.1 | 0.977 | 0.845 | 0.974 | 0.976 |
| 1,000 | expansions by gpt-6.1-sol | claude-opus-5.5 | 0.937 | 0.905 | 0.970 | 0.984 |
| 1,000 | expansions by gpt-6.1-sol | gpt-6.1-sol | 0.980 | 0.900 | 0.985 | 0.969 |
| 10,000 | core | claude-fable-5.1 | 0.271 | 0.698 | 0.621 | 0.493 |
| 10,000 | core | claude-opus-5.5 | 0.146 | 0.780 | 0.588 | 0.570 |
| 10,000 | core | gpt-6.1-sol | 0.198 | 0.686 | 0.496 | 0.613 |
| 10,000 | expansions by claude-sonnet-5.5 | claude-fable-5.1 | 0.981 | 0.965 | 0.970 | 0.981 |
| 10,000 | expansions by claude-sonnet-5.5 | claude-opus-5.5 | 0.975 | 0.942 | 0.970 | 0.994 |
| 10,000 | expansions by claude-sonnet-5.5 | gpt-6.1-sol | 0.986 | 0.967 | 0.985 | 0.994 |
| 10,000 | expansions by gpt-6.1-sol | claude-fable-5.1 | 0.961 | 0.861 | 0.960 | 0.972 |
| 10,000 | expansions by gpt-6.1-sol | claude-opus-5.5 | 0.923 | 0.914 | 0.962 | 0.978 |
| 10,000 | expansions by gpt-6.1-sol | gpt-6.1-sol | 0.971 | 0.908 | 0.979 | 0.969 |

Code-switched questions per language of the gold note:

| notes | search | mixed: en | mixed: ko | mixed: ja | mixed: zh | mixed: es | mixed: de |
|---|---|---|---|---|---|---|---|
| 160 | core | 0.604 | 0.577 | 0.896 | 0.917 | 0.850 | 0.827 |
| 160 | expansions by claude-sonnet-5.5 | 0.954 | 0.988 | 1.000 | 1.000 | 0.978 | 0.937 |
| 160 | expansions by gpt-6.1-sol | 0.970 | 0.954 | 0.896 | 0.882 | 0.804 | 0.779 |
| 1,000 | core | 0.598 | 0.555 | 0.865 | 0.856 | 0.808 | 0.800 |
| 1,000 | expansions by claude-sonnet-5.5 | 0.948 | 0.981 | 0.985 | 1.000 | 0.976 | 0.883 |
| 1,000 | expansions by gpt-6.1-sol | 0.959 | 0.945 | 0.867 | 0.881 | 0.755 | 0.746 |
| 10,000 | core | 0.588 | 0.578 | 0.880 | 0.875 | 0.856 | 0.854 |
| 10,000 | expansions by claude-sonnet-5.5 | 0.949 | 0.969 | 0.970 | 1.000 | 0.979 | 0.887 |
| 10,000 | expansions by gpt-6.1-sol | 0.957 | 0.935 | 0.903 | 0.878 | 0.806 | 0.785 |

Queries that moved, and the cost inside the ranking (macOS arm64, Python 3.11,
1-minute load about 6, latency pooled over dev + test queries):

| notes | search | queries up / down (of 972) | down: exact / para / mixed | index on disk | p50 | p95 |
|---|---|---|---|---|---|---|
| 160 | core | - | - | 0.07 MB | 0.08 ms | 0.16 ms |
| 160 | expansions by claude-sonnet-5.5 | 377 / 4 | 0 / 0 / 4 | 0.07 MB | 0.21 ms | 0.37 ms |
| 160 | expansions by gpt-6.1-sol | 362 / 29 | 0 / 0 / 29 | 0.07 MB | 0.20 ms | 0.29 ms |
| 1,000 | core | - | - | 0.35 MB | 0.22 ms | 0.44 ms |
| 1,000 | expansions by claude-sonnet-5.5 | 391 / 7 | 0 / 1 / 6 | 0.35 MB | 0.46 ms | 1.05 ms |
| 1,000 | expansions by gpt-6.1-sol | 369 / 30 | 0 / 2 / 28 | 0.35 MB | 0.46 ms | 1.00 ms |
| 10,000 | core | - | - | 3.27 MB | 1.83 ms | 4.93 ms |
| 10,000 | expansions by claude-sonnet-5.5 | 387 / 8 | 0 / 1 / 7 | 3.27 MB | 4.36 ms | 13.43 ms |
| 10,000 | expansions by gpt-6.1-sol | 366 / 25 | 0 / 1 / 24 | 3.27 MB | 3.46 ms | 10.28 ms |

### Reading

- Both writers lift every language and both low-overlap query kinds at every
  size, for the questions of all three authors. Exact keyword queries do not
  move.
- With the expansions written by `claude-sonnet-5.5` no slice is below the
  core at any size: pooled language, pooled kind, author x language, author x
  kind and language x kind.
- With the expansions written by `gpt-6.1-sol`, code-switched questions whose
  gold note is Spanish or German are **below the core** at every size (about
  -0.05 MRR; Chinese too at 160 notes), and one pooled slice is below at 160
  notes (`claude-opus-5.5` code-switched R@5 0.972 -> 0.963, one query). These
  questions are mostly English with one word of the note's language; this
  writer answered with English and Korean terms, which favours English notes.
  An expansion helps only as far as the writer guesses the note's language.
- The index on disk is unchanged. A search with about 65 added terms costs
  about twice the core's time in the ranking (10,000 notes: p50 1.8 -> 3.5-4.4
  ms).
- Writing the expansions cost 201 (claude) and 115 (gpt) output tokens per
  query, plus about 91 input tokens, in calls of 30 queries. A host pays that
  per search it chooses to widen.

### What these numbers are not

- **An upper bound, not a forecast.** The questions and the expansions are
  both written by language models, and the benchmark's notes are about
  everyday topics a model can guess vocabulary for. Human questions about
  private notes will gain less. The literature's figure for query expansion
  over BM25 with human queries is +3 % to +15 % (query2doc,
  https://arxiv.org/abs/2303.07678).
- **The full-match rule was added after a first look at the test split.** The
  weights were frozen on dev without it, and that first test run showed 1-3 of
  324 exact queries losing rank 1 (exact MRR 0.995-0.998, R@5 unchanged). The
  rule is the one the semantic mode already uses, it changes no dev result,
  and the tables above are a second run, of what ships. Outside the exact
  rows the two runs differ by at most 0.011 MRR in any language.
- The expansion quality depends on the host model; a weak or careless writer
  was not measured.

### Alternatives measured and not shipped

Measured in a research harness outside this repository (same corpus, same
split; not reproducible from the committed files):

| alternative | result | why not |
|---|---|---|
| aliases written when a note is saved, indexed as a weighted field | test, 10,000 notes, claude / gpt aliases: en 0.926 / 0.925, ko 0.937 / 0.909, para 0.892 / 0.841, mixed 0.922 / 0.914, exact unchanged | lower than expansions on this split; index, memory and cold start about 2x; every existing note must be backfilled, and a half-backfilled vault ranks notes without aliases below the core |
| aliases and expansions together | dev, 10,000 notes: en 0.989, ko 1.000, para 1.000, mixed 0.993 | +0.01 to +0.06 over expansions alone, for the costs above |
| expansions from a bundled synonym list (WordNet, English only) | dev: en +0.000 to +0.021, code-switched -0.004 to -0.032, 10-27 slices below the core | no gain; no such list for the other five languages |
| expansions from the vault itself (pseudo-relevance feedback, co-occurrence) | dev: every setting loses on exact or code-switched queries | no gain |

Reproduce (the second command prints the before / after tables):

```bash
python benchmarks/retrieval/bench_retrieval.py --engines bm25 expanded-claude expanded-gpt --sizes 160 1000 10000 --json run.json
python benchmarks/retrieval/compare.py run.json run.json --engine-before bm25 --engine-after expanded-claude
```

## Optional semantic mode (`[semantic]` extra)

The core stays standard library only. The `[semantic]` extra (numpy,
safetensors, huggingface_hub) adds a second ranking that finds notes by
meaning and is fused with the lexical one:

```bash
pip install -e ".[semantic]"
python -m birkin_mnemosyne.semantic    # once: download (~530 MB) and convert the model
```

A search never downloads or converts anything. The mode is off unless it is
asked for (`Mnemosyne(vault, semantic=True)` or `MNEMOSYNE_SEMANTIC=1`); when
it is asked for but the extra is missing or the model is not prepared, search
is the core ranking and one log line says why.

How it works:

- **Model**: `minishlab/potion-multilingual-128M`, static embeddings (500k
  Unigram pieces x 256 dimensions), no transformer at query time.
- **Runtime** (`static_model.py`): the model is converted once into an int8
  table (128 MB on disk, memory-mapped, only the rows of tokens actually seen
  are paged in) plus a sorted table of 64-bit piece hashes; tokenizing is a
  pure-Python Unigram Viterbi search whose token ids equal the reference
  tokenizer's on all 2,440 corpus and query texts of this benchmark. The
  reference stack (model2vec + `tokenizers`) holds ~770 MB for the tokenizer
  alone.
- **Index**: each note is cut into chunks of about 400 characters (a longer
  paragraph is cut); a chunk is stored as the sign bits of its vector, 32
  bytes. A query is scored against the packed bytes through a 32 x 256 lookup
  table; a note scores its best chunk.
- **Fusion**: reciprocal-rank fusion (k = 5) of the top 100 of each ranking.
  The lexical ranking is the core's, usage and zone boosts included, and
  nothing multiplies the fused score. The semantic vote counts 0.4 (1.0 for
  queries written mostly in Han/kana). Notes that contain every original unit
  of the query keep their lexical order ahead of everything else, so exact
  keyword lookups keep their lexical order; fused ties go to the lexical
  rank (both ideas follow the "never worse than today, per query" rule and the
  exact-phrase floor of oh-my-openagent PR #9209).

Measured once on the frozen test split with the configuration above, after it
was fixed on dev (`git c0657fb`, Apple M1, Python 3.13, macOS). Reproduce with
`python benchmarks/retrieval/bench_retrieval.py --engines bm25 hybrid --sizes 160 1000 10000 --json run.json --install-size --install-extras semantic`
and `python benchmarks/retrieval/compare.py run.json run.json --engine-before bm25 --engine-after hybrid`;
the committed run is `semantic_test_run.json`.

#### core -> semantic mode (test split): R@5 and MRR per slice

| notes | slice | n | R@5 | MRR |
|---|---|---|---|---|
| 160 | en | 252 | 0.698 -> 0.746 (+0.048) | 0.591 -> 0.640 (+0.049) |
| 160 | ko | 243 | 0.654 -> 0.728 (+0.074) | 0.579 -> 0.640 (+0.060) |
| 160 | ja | 99 | 0.848 -> 0.899 (+0.051) | 0.794 -> 0.843 (+0.049) |
| 160 | zh | 135 | 0.867 -> 0.926 (+0.059) | 0.818 -> 0.871 (+0.053) |
| 160 | es | 108 | 0.769 -> 0.861 (+0.093) | 0.698 -> 0.744 (+0.046) |
| 160 | de | 135 | 0.756 -> 0.822 (+0.067) | 0.689 -> 0.749 (+0.060) |
| 160 | exact (all langs) | 324 | 1.000 -> 1.000 (=0.000) | 1.000 -> 1.000 (=0.000) |
| 160 | para (all langs) | 324 | 0.370 -> 0.525 (+0.154) | 0.269 -> 0.383 (+0.115) |
| 160 | mixed (all langs) | 324 | 0.855 -> 0.892 (+0.037) | 0.729 -> 0.775 (+0.046) |
| 1000 | en | 252 | 0.679 -> 0.714 (+0.036) | 0.581 -> 0.620 (+0.038) |
| 1000 | ko | 243 | 0.613 -> 0.683 (+0.070) | 0.554 -> 0.614 (+0.061) |
| 1000 | ja | 99 | 0.848 -> 0.909 (+0.061) | 0.782 -> 0.809 (+0.027) |
| 1000 | zh | 135 | 0.830 -> 0.881 (+0.052) | 0.766 -> 0.823 (+0.058) |
| 1000 | es | 108 | 0.694 -> 0.713 (+0.019) | 0.655 -> 0.686 (+0.031) |
| 1000 | de | 135 | 0.741 -> 0.770 (+0.030) | 0.664 -> 0.708 (+0.044) |
| 1000 | exact (all langs) | 324 | 1.000 -> 1.000 (=0.000) | 1.000 -> 1.000 (=0.000) |
| 1000 | para (all langs) | 324 | 0.302 -> 0.417 (+0.114) | 0.219 -> 0.307 (+0.087) |
| 1000 | mixed (all langs) | 324 | 0.830 -> 0.855 (+0.025) | 0.701 -> 0.750 (+0.049) |
| 10000 | en | 252 | 0.655 -> 0.675 (+0.020) | 0.568 -> 0.604 (+0.035) |
| 10000 | ko | 243 | 0.609 -> 0.658 (+0.049) | 0.559 -> 0.608 (+0.049) |
| 10000 | ja | 99 | 0.848 -> 0.879 (+0.030) | 0.782 -> 0.816 (+0.033) |
| 10000 | zh | 135 | 0.822 -> 0.815 (-0.007) | 0.764 -> 0.782 (+0.018) |
| 10000 | es | 108 | 0.704 -> 0.704 (=0.000) | 0.673 -> 0.681 (+0.009) |
| 10000 | de | 135 | 0.741 -> 0.748 (+0.007) | 0.681 -> 0.708 (+0.027) |
| 10000 | exact (all langs) | 324 | 1.000 -> 1.000 (=0.000) | 1.000 -> 1.000 (=0.000) |
| 10000 | para (all langs) | 324 | 0.281 -> 0.321 (+0.040) | 0.205 -> 0.262 (+0.057) |
| 10000 | mixed (all langs) | 324 | 0.830 -> 0.852 (+0.022) | 0.722 -> 0.761 (+0.039) |

#### MRR per query author (test split)

| notes | author | exact | para | mixed |
|---|---|---|---|---|
| 160 | claude-fable-5.1 | 1.000 -> 1.000 (=0.000) | 0.348 -> 0.459 (+0.111) | 0.707 -> 0.772 (+0.065) |
| 160 | claude-opus-5.5 | 1.000 -> 1.000 (=0.000) | 0.197 -> 0.314 (+0.117) | 0.820 -> 0.856 (+0.037) |
| 160 | gpt-6.1-sol | 1.000 -> 1.000 (=0.000) | 0.261 -> 0.378 (+0.116) | 0.660 -> 0.696 (+0.036) |
| 1000 | claude-fable-5.1 | 1.000 -> 1.000 (=0.000) | 0.301 -> 0.368 (+0.068) | 0.664 -> 0.738 (+0.074) |
| 1000 | claude-opus-5.5 | 1.000 -> 1.000 (=0.000) | 0.154 -> 0.230 (+0.076) | 0.780 -> 0.815 (+0.035) |
| 1000 | gpt-6.1-sol | 1.000 -> 1.000 (=0.000) | 0.203 -> 0.322 (+0.118) | 0.660 -> 0.697 (+0.037) |
| 10000 | claude-fable-5.1 | 1.000 -> 1.000 (=0.000) | 0.271 -> 0.318 (+0.048) | 0.698 -> 0.763 (+0.064) |
| 10000 | claude-opus-5.5 | 1.000 -> 1.000 (=0.000) | 0.146 -> 0.214 (+0.068) | 0.780 -> 0.810 (+0.029) |
| 10000 | gpt-6.1-sol | 1.000 -> 1.000 (=0.000) | 0.198 -> 0.253 (+0.055) | 0.686 -> 0.711 (+0.025) |

#### MRR per query author and language (test split)

| notes | author | en | ko | ja | zh | es | de |
|---|---|---|---|---|---|---|---|
| 160 | claude-fable-5.1 | 0.643 -> 0.691 (+0.048) | 0.530 -> 0.581 (+0.051) | 0.781 -> 0.876 (+0.095) | 0.822 -> 0.884 (+0.062) | 0.775 -> 0.814 (+0.039) | 0.761 -> 0.844 (+0.082) |
| 160 | claude-opus-5.5 | 0.606 -> 0.672 (+0.066) | 0.597 -> 0.668 (+0.071) | 0.773 -> 0.812 (+0.039) | 0.820 -> 0.852 (+0.032) | 0.692 -> 0.707 (+0.015) | 0.694 -> 0.739 (+0.045) |
| 160 | gpt-6.1-sol | 0.524 -> 0.559 (+0.035) | 0.612 -> 0.671 (+0.060) | 0.827 -> 0.840 (+0.013) | 0.811 -> 0.877 (+0.066) | 0.628 -> 0.711 (+0.083) | 0.612 -> 0.663 (+0.052) |
| 1000 | claude-fable-5.1 | 0.641 -> 0.673 (+0.032) | 0.487 -> 0.548 (+0.061) | 0.742 -> 0.781 (+0.039) | 0.785 -> 0.829 (+0.044) | 0.736 -> 0.761 (+0.025) | 0.726 -> 0.804 (+0.077) |
| 1000 | claude-opus-5.5 | 0.592 -> 0.644 (+0.053) | 0.565 -> 0.622 (+0.056) | 0.784 -> 0.795 (+0.011) | 0.750 -> 0.794 (+0.044) | 0.653 -> 0.646 (-0.007) | 0.671 -> 0.692 (+0.021) |
| 1000 | gpt-6.1-sol | 0.512 -> 0.542 (+0.030) | 0.609 -> 0.674 (+0.064) | 0.821 -> 0.851 (+0.030) | 0.762 -> 0.847 (+0.085) | 0.577 -> 0.652 (+0.075) | 0.595 -> 0.629 (+0.034) |
| 10000 | claude-fable-5.1 | 0.621 -> 0.655 (+0.035) | 0.493 -> 0.548 (+0.055) | 0.759 -> 0.790 (+0.032) | 0.770 -> 0.807 (+0.037) | 0.756 -> 0.763 (+0.007) | 0.749 -> 0.787 (+0.039) |
| 10000 | claude-opus-5.5 | 0.588 -> 0.639 (+0.051) | 0.570 -> 0.608 (+0.038) | 0.763 -> 0.828 (+0.065) | 0.746 -> 0.764 (+0.017) | 0.653 -> 0.639 (-0.014) | 0.671 -> 0.687 (+0.016) |
| 10000 | gpt-6.1-sol | 0.496 -> 0.517 (+0.020) | 0.613 -> 0.668 (+0.055) | 0.826 -> 0.828 (+0.003) | 0.777 -> 0.776 (-0.001) | 0.609 -> 0.643 (+0.034) | 0.622 -> 0.648 (+0.026) |

#### R@5 per query author and language (test split)

| notes | author | en | ko | ja | zh | es | de |
|---|---|---|---|---|---|---|---|
| 160 | claude-fable-5.1 | 0.762 -> 0.821 (+0.060) | 0.580 -> 0.679 (+0.099) | 0.879 -> 0.909 (+0.030) | 0.889 -> 0.933 (+0.044) | 0.833 -> 0.972 (+0.139) | 0.822 -> 0.911 (+0.089) |
| 160 | claude-opus-5.5 | 0.726 -> 0.786 (+0.060) | 0.704 -> 0.765 (+0.062) | 0.848 -> 0.909 (+0.061) | 0.844 -> 0.911 (+0.067) | 0.778 -> 0.833 (+0.056) | 0.756 -> 0.800 (+0.044) |
| 160 | gpt-6.1-sol | 0.607 -> 0.631 (+0.024) | 0.679 -> 0.741 (+0.062) | 0.818 -> 0.879 (+0.061) | 0.867 -> 0.933 (+0.067) | 0.694 -> 0.778 (+0.083) | 0.689 -> 0.756 (+0.067) |
| 1000 | claude-fable-5.1 | 0.750 -> 0.774 (+0.024) | 0.556 -> 0.617 (+0.062) | 0.818 -> 0.879 (+0.061) | 0.867 -> 0.867 (=0.000) | 0.750 -> 0.806 (+0.056) | 0.822 -> 0.889 (+0.067) |
| 1000 | claude-opus-5.5 | 0.702 -> 0.750 (+0.048) | 0.617 -> 0.704 (+0.086) | 0.848 -> 0.939 (+0.091) | 0.800 -> 0.822 (+0.022) | 0.667 -> 0.667 (=0.000) | 0.733 -> 0.756 (+0.022) |
| 1000 | gpt-6.1-sol | 0.583 -> 0.619 (+0.036) | 0.667 -> 0.728 (+0.062) | 0.879 -> 0.909 (+0.030) | 0.822 -> 0.956 (+0.133) | 0.667 -> 0.667 (=0.000) | 0.667 -> 0.667 (=0.000) |
| 10000 | claude-fable-5.1 | 0.738 -> 0.750 (+0.012) | 0.543 -> 0.593 (+0.049) | 0.818 -> 0.848 (+0.030) | 0.867 -> 0.844 (-0.022) | 0.778 -> 0.778 (=0.000) | 0.800 -> 0.822 (+0.022) |
| 10000 | claude-opus-5.5 | 0.690 -> 0.738 (+0.048) | 0.617 -> 0.654 (+0.037) | 0.848 -> 0.909 (+0.061) | 0.778 -> 0.800 (+0.022) | 0.667 -> 0.667 (=0.000) | 0.733 -> 0.733 (=0.000) |
| 10000 | gpt-6.1-sol | 0.536 -> 0.536 (=0.000) | 0.667 -> 0.728 (+0.062) | 0.879 -> 0.879 (=0.000) | 0.822 -> 0.800 (-0.022) | 0.667 -> 0.667 (=0.000) | 0.689 -> 0.689 (=0.000) |

#### MRR per language and query kind (test split)

| notes | lang | exact | para | mixed |
|---|---|---|---|---|
| 160 | en | 1.000 -> 1.000 (=0.000) | 0.169 -> 0.272 (+0.103) | 0.604 -> 0.649 (+0.045) |
| 160 | ko | 1.000 -> 1.000 (=0.000) | 0.162 -> 0.253 (+0.091) | 0.577 -> 0.667 (+0.090) |
| 160 | ja | 1.000 -> 1.000 (=0.000) | 0.485 -> 0.642 (+0.157) | 0.896 -> 0.886 (-0.010) |
| 160 | zh | 1.000 -> 1.000 (=0.000) | 0.535 -> 0.708 (+0.173) | 0.917 -> 0.905 (-0.013) |
| 160 | es | 1.000 -> 1.000 (=0.000) | 0.246 -> 0.334 (+0.089) | 0.850 -> 0.898 (+0.049) |
| 160 | de | 1.000 -> 1.000 (=0.000) | 0.239 -> 0.352 (+0.113) | 0.827 -> 0.894 (+0.067) |
| 1000 | en | 1.000 -> 1.000 (=0.000) | 0.147 -> 0.230 (+0.084) | 0.598 -> 0.629 (+0.031) |
| 1000 | ko | 1.000 -> 1.000 (=0.000) | 0.107 -> 0.173 (+0.066) | 0.555 -> 0.670 (+0.115) |
| 1000 | ja | 1.000 -> 1.000 (=0.000) | 0.482 -> 0.601 (+0.119) | 0.865 -> 0.826 (-0.038) |
| 1000 | zh | 1.000 -> 1.000 (=0.000) | 0.441 -> 0.608 (+0.167) | 0.856 -> 0.863 (+0.007) |
| 1000 | es | 1.000 -> 1.000 (=0.000) | 0.158 -> 0.205 (+0.046) | 0.808 -> 0.854 (+0.046) |
| 1000 | de | 1.000 -> 1.000 (=0.000) | 0.193 -> 0.256 (+0.063) | 0.800 -> 0.869 (+0.069) |
| 10000 | en | 1.000 -> 1.000 (=0.000) | 0.118 -> 0.178 (+0.060) | 0.588 -> 0.633 (+0.046) |
| 10000 | ko | 1.000 -> 1.000 (=0.000) | 0.098 -> 0.147 (+0.049) | 0.578 -> 0.677 (+0.099) |
| 10000 | ja | 1.000 -> 1.000 (=0.000) | 0.468 -> 0.588 (+0.121) | 0.880 -> 0.859 (-0.021) |
| 10000 | zh | 1.000 -> 1.000 (=0.000) | 0.418 -> 0.487 (+0.068) | 0.875 -> 0.860 (-0.015) |
| 10000 | es | 1.000 -> 1.000 (=0.000) | 0.161 -> 0.166 (+0.005) | 0.856 -> 0.878 (+0.022) |
| 10000 | de | 1.000 -> 1.000 (=0.000) | 0.188 -> 0.236 (+0.047) | 0.854 -> 0.887 (+0.033) |

#### R@5 per language and query kind (test split)

| notes | lang | exact | para | mixed |
|---|---|---|---|---|
| 160 | en | 1.000 -> 1.000 (=0.000) | 0.298 -> 0.429 (+0.131) | 0.798 -> 0.810 (+0.012) |
| 160 | ko | 1.000 -> 1.000 (=0.000) | 0.210 -> 0.370 (+0.160) | 0.753 -> 0.815 (+0.062) |
| 160 | ja | 1.000 -> 1.000 (=0.000) | 0.576 -> 0.727 (+0.152) | 0.970 -> 0.970 (=0.000) |
| 160 | zh | 1.000 -> 1.000 (=0.000) | 0.622 -> 0.822 (+0.200) | 0.978 -> 0.956 (-0.022) |
| 160 | es | 1.000 -> 1.000 (=0.000) | 0.389 -> 0.583 (+0.194) | 0.917 -> 1.000 (+0.083) |
| 160 | de | 1.000 -> 1.000 (=0.000) | 0.378 -> 0.489 (+0.111) | 0.889 -> 0.978 (+0.089) |
| 1000 | en | 1.000 -> 1.000 (=0.000) | 0.238 -> 0.345 (+0.107) | 0.798 -> 0.798 (=0.000) |
| 1000 | ko | 1.000 -> 1.000 (=0.000) | 0.136 -> 0.272 (+0.136) | 0.704 -> 0.778 (+0.074) |
| 1000 | ja | 1.000 -> 1.000 (=0.000) | 0.576 -> 0.758 (+0.182) | 0.970 -> 0.970 (=0.000) |
| 1000 | zh | 1.000 -> 1.000 (=0.000) | 0.600 -> 0.733 (+0.133) | 0.889 -> 0.911 (+0.022) |
| 1000 | es | 1.000 -> 1.000 (=0.000) | 0.167 -> 0.222 (+0.056) | 0.917 -> 0.917 (=0.000) |
| 1000 | de | 1.000 -> 1.000 (=0.000) | 0.333 -> 0.400 (+0.067) | 0.889 -> 0.911 (+0.022) |
| 10000 | en | 1.000 -> 1.000 (=0.000) | 0.202 -> 0.238 (+0.036) | 0.762 -> 0.786 (+0.024) |
| 10000 | ko | 1.000 -> 1.000 (=0.000) | 0.111 -> 0.210 (+0.099) | 0.716 -> 0.765 (+0.049) |
| 10000 | ja | 1.000 -> 1.000 (=0.000) | 0.576 -> 0.667 (+0.091) | 0.970 -> 0.970 (=0.000) |
| 10000 | zh | 1.000 -> 1.000 (=0.000) | 0.556 -> 0.533 (-0.022) | 0.911 -> 0.911 (=0.000) |
| 10000 | es | 1.000 -> 1.000 (=0.000) | 0.194 -> 0.194 (=0.000) | 0.917 -> 0.917 (=0.000) |
| 10000 | de | 1.000 -> 1.000 (=0.000) | 0.311 -> 0.311 (=0.000) | 0.911 -> 0.933 (+0.022) |

#### Queries whose gold rank improved / worsened (test split)

| notes | en | ko | ja | zh | es | de | exact | para | mixed |
|---|---|---|---|---|---|---|---|---|---|
| 160 | 55 up / 9 down of 252 | 58 up / 8 down of 243 | 16 up / 10 down of 99 | 24 up / 3 down of 135 | 27 up / 3 down of 108 | 27 up / 5 down of 135 | 0 up / 0 down of 324 | 142 up / 21 down of 324 | 65 up / 17 down of 324 |
| 1000 | 42 up / 6 down of 252 | 41 up / 4 down of 243 | 12 up / 10 down of 99 | 19 up / 5 down of 135 | 17 up / 1 down of 108 | 18 up / 5 down of 135 | 0 up / 0 down of 324 | 91 up / 14 down of 324 | 58 up / 17 down of 324 |
| 10000 | 28 up / 4 down of 252 | 32 up / 3 down of 243 | 9 up / 9 down of 99 | 10 up / 8 down of 135 | 5 up / 1 down of 108 | 9 up / 2 down of 135 | 0 up / 0 down of 324 | 53 up / 16 down of 324 | 40 up / 11 down of 324 |

#### Footprint: size and memory (core -> semantic mode)

| notes | index on disk | peak RSS, search in a fresh process | peak RSS, indexing the whole vault in a fresh process |
|---|---|---|---|
| 160 | 0.07 MB -> 0.09 MB | 25 -> 48 MB (+23) | 26 -> 83 MB (+57) |
| 1000 | 0.35 MB -> 0.43 MB | 34 -> 56 MB (+22) | 40 -> 101 MB (+61) |
| 10000 | 3.27 MB -> 4.08 MB | 138 -> 159 MB (+21) | 170 -> 231 MB (+61) |

The memory budget for this mode was 150 MB on top of the core; the largest
measured addition is 61 MB, while indexing. Peak RSS was the same within 8 MB
in a second identical run. Install size: core 0.18 MB, with the extra 38.2 MB
(numpy, safetensors, huggingface_hub and their dependencies).

#### Footprint: start-up and latency (core -> semantic mode)

Measured apart from the run above, on vaults that already existed, with the
1-minute load average between 5.6 and 7.8: start-up is the wall time of a fresh
process (`_probe.py`: interpreter start, import, index load, first query), 10
processes per cell; latency is 300 test queries in a warm process.

| notes | start-up, median (max) | p50 | p95 |
|---|---|---|---|
| 160 | 41 ms (42) -> 89 ms (95) | 0.5 -> 1.6 ms | 0.6 -> 3.4 ms |
| 1000 | 65 ms (98) -> 125 ms (132) | 3.1 -> 7.4 ms | 3.9 -> 8.4 ms |
| 10000 | 307 ms (547) -> 382 ms (439) | 35.4 -> 75.6 ms | 37.8 -> 79.4 ms |

The start-up budget for this mode was 1 s with the model prepared; the slowest
of the 30 starts took 439 ms. The timing fields inside
`semantic_test_run.json` are not the reference: that run was taken on a busy
machine (1-minute load 7.6 to 10.7), and in a repeat at a load near 13 the
start-up of the 10k vault reached 1.09 s. Search latency roughly doubles at
1k and 10k notes (about 3x at 160 notes, still under 4 ms).

Reading:

- **The mode is opt-in and is not the recommended default.** The bar for it was
  "no slice below the core". On the test split it misses that bar in one
  pooled slice, three author slices and six language x kind cells:
  - Chinese at 10k notes: R@5 0.822 -> 0.815 (one query of 135), while MRR
    rises 0.764 -> 0.782. By author: gpt-6.1-sol R@5 0.822 -> 0.800 (MRR
    0.777 -> 0.776), claude-fable-5.1 R@5 0.867 -> 0.844 (MRR 0.770 -> 0.807),
    claude-opus-5.5 R@5 0.778 -> 0.800.
  - Spanish, claude-opus-5.5's questions: MRR 0.653 -> 0.646 at 1k and
    0.653 -> 0.639 at 10k (R@5 unchanged), while the other two authors gain.
  - By language and query kind (33-45 queries per cell): Japanese
    code-switched queries lose MRR at every size (0.896 -> 0.886, 0.865 ->
    0.826, 0.880 -> 0.859; R@5 unchanged at 0.970); Chinese code-switched
    queries at 160 notes (MRR 0.917 -> 0.905, R@5 0.978 -> 0.956) and at 10k
    (MRR 0.875 -> 0.860); Chinese paraphrases lose R@5 at 10k (0.556 -> 0.533)
    while their MRR rises.

  The same configuration had no slice below the core for any author on dev at
  160, 1k and 10k notes. It was frozen before this run and not retuned after
  it. Turn the mode on with `Mnemosyne(vault, semantic=True)` or
  `MNEMOSYNE_SEMANTIC=1` when questions are usually worded differently from
  the notes; leave it off when lookups are mostly keywords.
- Pooled by language or by kind, everything else gains: MRR is higher in every
  language at every size (+0.009 to +0.061), R@5 is higher or equal in every
  other pooled slice, and
  paraphrase queries go from 0.269 / 0.219 / 0.205 to 0.383 / 0.307 / 0.262
  MRR at 160 / 1k / 10k notes. Korean, flat in the core, gains 0.049-0.061 MRR.
- Exact keyword queries are untouched: no query moves at any size (the
  full-match rule), where plain fusion lost rank on several.
- Gains shrink with corpus size, and single queries do get worse: at 10k notes
  Japanese is 9 up / 9 down and Chinese 10 up / 8 down.

Limits:

- The first use needs a ~530 MB download and a one-time conversion, both only
  through the explicit prepare command; the compact model is ~140 MB on disk.
- Footprint was measured on macOS arm64 only. CI runs the tests of this mode
  on Linux, macOS and Windows but measures nothing there.
- Token ids were compared with the reference tokenizer on this benchmark's
  2,440 texts only, and vocabulary pieces longer than 24 characters are not
  used.
- With the mode on, the semantic ranking always contributes its best notes,
  so a query with no lexical match still returns results (there is no
  relevance floor).
- The tokenizer caches up to 65,536 segmented words per process; its memory in
  a long-lived process with varied CJK text was not measured.
- `semantic_test_run.json` is the run re-serialised compactly (same values);
  it was produced at `c0657fb`, before the mode became opt-in, by engines that
  pass `semantic=` explicitly.
- The benchmark is synthetic, and its dev slices for Chinese and German are
  small (5 notes each): the dev gate passed where the test split did not.

How the design was chosen (dev split only, all three authors, plus the extra
zh/de dev triples; "below core" lists every slice - six languages, three
kinds - whose MRR or R@5 is lower than the core's for at least one author):

| fusion rule | below core at 160 | at 1k | at 10k | 10k MRR: en / ko / ja / zh / es / de | exact | para |
|---|---|---|---|---|---|---|
| core (no semantic mode) | - | - | - | 0.528 / 0.597 / 0.694 / 0.710 / 0.646 / 0.685 | 0.996 | 0.169 |
| plain RRF, vote 1.0 | exact (all authors), mixed R@5 (opus), zh (fable) | exact (all), ja (sol), mixed R@5 (opus, fable), zh (fable) | exact (all), ja (sol) | 0.586 / 0.687 / 0.734 / 0.739 / 0.740 / 0.789 | 0.974 | 0.320 |
| + full-match tier, vote 1.0 | mixed R@5 (opus), zh R@5 (fable) | mixed R@5 (opus, fable) | none | 0.586 / 0.687 / 0.761 / 0.770 / 0.740 / 0.789 | 1.000 | 0.320 |
| + tier, vote 0.5 (1.0 for Han/kana) | mixed R@5 (opus) | none | none | 0.578 / 0.657 / 0.763 / 0.779 / 0.713 / 0.759 | 1.000 | 0.274 |
| **+ tier, vote 0.4 (1.0 for Han/kana)** | **none** | **none** | **none** | **0.569 / 0.657 / 0.759 / 0.779 / 0.703 / 0.750** | **1.000** | **0.259** |
| + tier, vote 0.3 (1.0 for Han/kana) | en (fable) | none | none | 0.569 / 0.643 / 0.758 / 0.779 / 0.697 / 0.742 | 1.000 | 0.252 |
| + tier, vote 0.4 for every query | zh (sol) | none | none | 0.569 / 0.657 / 0.732 / 0.734 / 0.703 / 0.750 | 1.000 | 0.228 |

The chosen rule is the largest semantic vote with no slice below the core for
any author at any size. A larger vote gains more on paraphrases and costs
single queries in the code-switched and Chinese slices.

Measured and rejected (dev, 1k notes, MRR averaged over the six languages
unless stated; core 0.664; plain-fusion hybrid on the reference runtime 0.741
with 400-character chunks; the reranker and margin rows were measured against
an earlier 200-character-chunk hybrid at 0.752):

| option | memory / time | quality | why not |
|---|---|---|---|
| reference runtime (model2vec + `tokenizers`) | 666-970 MB peak RSS, 5.7-7.3 s cold start | 0.741 | 4-6x over the memory budget |
| vocabulary pruned to the top 32k / 64k / 128k pieces | 51 / 90 / 181 MB | 0.625 / 0.658 / 0.678 | English falls below the core |
| `static-similarity-mrl-multilingual-v1`, 256 dims, int8 | 36 MB | 0.691 | zh 0.780 -> 0.753, es 0.656 -> 0.653 |
| 128 or 64 sign bits per chunk | - | semantic ranking alone 0.694 -> 0.556 / 0.407 | too lossy |
| cross-encoder reranker on the top 20 (`mmarco-mMiniLMv2-L12-H384-v1`) | ~1 GB with PyTorch, 47 s first load, +200 ms per query | en 0.622 -> 0.729, ko 0.705 -> 0.833, but es 0.790 -> 0.747 | one language worse, far over budget |
| semantic vote only when the lexical top-2 margin is small | - | exact 0.997, but para 0.393 -> 0.343, es 0.790 -> 0.744 | trades slices |
| vote 0.7 instead of 1.0 for Han/kana queries | - | 10k notes: ja 0.759 -> 0.748, zh 0.779 -> 0.765 | Han/kana queries want the full vote |
