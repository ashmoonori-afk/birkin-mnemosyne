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

## Compact index + stopwords (core, zero dependencies)

Two changes to what is stored, measured back to back against main (`git
9678ef4`'s tree) on the same machine and corpus:

1. **Compact format (lossless).** The index file stores each note as a
   positional row under a field header, one shared sorted vocabulary, and each
   note's postings as base64 varint pairs (term-id delta, term frequency),
   written as UTF-8 instead of `\u` escapes.
2. **Corpus-wide stopwords.** Terms that occur in more than
   `max(5 % of notes, 50)` notes are left out of the stored postings and
   skipped in queries (the list is kept in the index file and is sticky until
   `rebuild()`). Small vaults (the 160-note run) are untouched.

Stated tolerance for size changes: at most -0.02 MRR on any language slice.

#### main (JSON index v3) -> compact index v4 + stopwords (test split): R@5 and MRR per slice

| notes | slice | n | R@5 | MRR |
|---|---|---|---|---|
| 160 | en | 252 | 0.698 -> 0.698 (=0.000) | 0.591 -> 0.591 (=0.000) |
| 160 | ko | 243 | 0.654 -> 0.654 (=0.000) | 0.579 -> 0.579 (=0.000) |
| 160 | ja | 99 | 0.848 -> 0.848 (=0.000) | 0.794 -> 0.794 (=0.000) |
| 160 | zh | 135 | 0.867 -> 0.867 (=0.000) | 0.818 -> 0.818 (=0.000) |
| 160 | es | 108 | 0.769 -> 0.769 (=0.000) | 0.698 -> 0.698 (=0.000) |
| 160 | de | 135 | 0.756 -> 0.756 (=0.000) | 0.689 -> 0.689 (=0.000) |
| 160 | exact (all langs) | 324 | 1.000 -> 1.000 (=0.000) | 1.000 -> 1.000 (=0.000) |
| 160 | para (all langs) | 324 | 0.370 -> 0.370 (=0.000) | 0.269 -> 0.269 (=0.000) |
| 160 | mixed (all langs) | 324 | 0.855 -> 0.855 (=0.000) | 0.729 -> 0.729 (=0.000) |
| 1000 | en | 252 | 0.679 -> 0.655 (-0.024) | 0.581 -> 0.570 (-0.012) |
| 1000 | ko | 243 | 0.613 -> 0.663 (+0.049) | 0.554 -> 0.587 (+0.033) |
| 1000 | ja | 99 | 0.848 -> 0.848 (=0.000) | 0.782 -> 0.796 (+0.014) |
| 1000 | zh | 135 | 0.830 -> 0.822 (-0.007) | 0.766 -> 0.785 (+0.019) |
| 1000 | es | 108 | 0.694 -> 0.722 (+0.028) | 0.655 -> 0.693 (+0.038) |
| 1000 | de | 135 | 0.741 -> 0.756 (+0.015) | 0.664 -> 0.707 (+0.042) |
| 1000 | exact (all langs) | 324 | 1.000 -> 1.000 (=0.000) | 1.000 -> 1.000 (=0.000) |
| 1000 | para (all langs) | 324 | 0.302 -> 0.269 (-0.034) | 0.219 -> 0.210 (-0.009) |
| 1000 | mixed (all langs) | 324 | 0.830 -> 0.895 (+0.065) | 0.701 -> 0.769 (+0.068) |
| 10000 | en | 252 | 0.655 -> 0.643 (-0.012) | 0.568 -> 0.562 (-0.006) |
| 10000 | ko | 243 | 0.609 -> 0.679 (+0.070) | 0.559 -> 0.598 (+0.040) |
| 10000 | ja | 99 | 0.848 -> 0.889 (+0.040) | 0.782 -> 0.792 (+0.010) |
| 10000 | zh | 135 | 0.822 -> 0.830 (+0.007) | 0.764 -> 0.774 (+0.009) |
| 10000 | es | 108 | 0.704 -> 0.722 (+0.019) | 0.673 -> 0.696 (+0.023) |
| 10000 | de | 135 | 0.741 -> 0.748 (+0.007) | 0.681 -> 0.706 (+0.025) |
| 10000 | exact (all langs) | 324 | 1.000 -> 1.000 (=0.000) | 1.000 -> 1.000 (=0.000) |
| 10000 | para (all langs) | 324 | 0.281 -> 0.275 (-0.006) | 0.205 -> 0.202 (-0.002) |
| 10000 | mixed (all langs) | 324 | 0.830 -> 0.904 (+0.074) | 0.722 -> 0.774 (+0.052) |

#### MRR per query author (test split)

| notes | author | exact | para | mixed |
|---|---|---|---|---|
| 160 | claude-fable-5.1 | 1.000 -> 1.000 (=0.000) | 0.348 -> 0.348 (=0.000) | 0.707 -> 0.707 (=0.000) |
| 160 | claude-opus-5.5 | 1.000 -> 1.000 (=0.000) | 0.197 -> 0.197 (=0.000) | 0.820 -> 0.820 (=0.000) |
| 160 | gpt-6.1-sol | 1.000 -> 1.000 (=0.000) | 0.261 -> 0.261 (=0.000) | 0.660 -> 0.660 (=0.000) |
| 1000 | claude-fable-5.1 | 1.000 -> 1.000 (=0.000) | 0.301 -> 0.300 (-0.001) | 0.664 -> 0.777 (+0.113) |
| 1000 | claude-opus-5.5 | 1.000 -> 1.000 (=0.000) | 0.154 -> 0.139 (-0.015) | 0.780 -> 0.783 (+0.004) |
| 1000 | gpt-6.1-sol | 1.000 -> 1.000 (=0.000) | 0.203 -> 0.192 (-0.012) | 0.660 -> 0.747 (+0.086) |
| 10000 | claude-fable-5.1 | 1.000 -> 1.000 (=0.000) | 0.271 -> 0.289 (+0.018) | 0.698 -> 0.794 (+0.095) |
| 10000 | claude-opus-5.5 | 1.000 -> 1.000 (=0.000) | 0.146 -> 0.133 (-0.013) | 0.780 -> 0.782 (+0.001) |
| 10000 | gpt-6.1-sol | 1.000 -> 1.000 (=0.000) | 0.198 -> 0.185 (-0.013) | 0.686 -> 0.746 (+0.060) |

#### Footprint

| notes | index on disk | p50 | p95 | cold wall | peak RSS |
|---|---|---|---|---|---|
| 160 | 0.27 MB -> 0.14 MB | 0.5 -> 0.6 ms | 0.6 -> 0.7 ms | 36 -> 42 ms | 23 -> 23 MB |
| 1000 | 1.57 MB -> 0.52 MB | 3.1 -> 3.8 ms | 3.5 -> 4.6 ms | 53 -> 113 ms | 31 -> 29 MB |
| 10000 | 15.79 MB -> 4.39 MB | 38.5 -> 37.6 ms | 44.7 -> 43.4 ms | 308 -> 215 ms | 123 -> 86 MB |

Queries whose gold rank improved / worsened: 

| notes | en | ko | ja | zh | es | de |
|---|---|---|---|---|---|---|
| 1000 | 4 up / 15 down | 23 up / 0 down | 11 up / 10 down | 10 up / 8 down | 11 up / 3 down | 13 up / 4 down |
| 10000 | 5 up / 10 down | 24 up / 0 down | 9 up / 8 down | 11 up / 10 down | 7 up / 3 down | 11 up / 6 down |

Reading:

- The index at 10k notes shrinks from 15.8 MB to 4.4 MB (-72 %; the original
  BM25 v1 index was 9.6 MB), peak RSS from 123 to 86 MB and cold start from
  308 to 215 ms.
- The compact format alone changes no ranking (bit-identical results at 160
  notes, where no stopword applies).
- Stopwords help code-switched queries (+0.05-0.07 MRR) and Korean most
  (24 queries up, none down at 10k); Japanese, Chinese, Spanish and German
  gain too. **English pays within the stated tolerance**: MRR -0.012 at 1k and
  -0.006 at 10k, mostly paraphrase queries whose only lexical overlap with
  their note was a very common word. The rule was chosen on the dev split
  (English -0.002 there) and not re-tuned on these numbers.
- Measured and rejected on dev: pruning ultra-rare terms (df = 1). It saves
  0.2 MB of 5.5 MB but deletes the names exact queries look for (exact MRR
  0.996 -> 0.766).
