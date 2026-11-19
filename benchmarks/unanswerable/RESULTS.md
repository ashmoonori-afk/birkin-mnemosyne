# Unanswerable-question results

Measured 2026-11-03 KST on Linux x86_64 (WSL2), Python 3.14. Every number below is
from the held-out test split, scored once after the method was frozen.
Tuning used only the tune split, the retrieval dev split and `dev_extra`.

## Question

When a vault cannot answer a message, does recall stay silent, without losing the
right note when one exists?

## Method

- Arms: the hosted-judge path of `recall()`, with no translated query views. Both
  keep the five notes of the merge step; the gated arm then drops notes whose merged
  pointwise score is below 0.5 (`crosslingual.RELEVANCE_FLOOR`).
- Sets: `questions.json` (337 test messages, [PROVENANCE.md](PROVENANCE.md)) and the
  972 test questions of `benchmarks/retrieval`, on vaults of 160, 1,000 and 10,000
  notes. Declared cross-language siblings were excluded before retrieval.
- Large sets: the frozen 2,400-question and 1,432-question six-language sets from the
  0.8.0 study. These reuse the five notes the study saved for each question (selected
  with translated views on 718,911 passages) and score each note in its own request.
- Latency: real `recall()` including the pairwise step on a fixed 40-question tune
  sample (20 unanswerable, 20 answerable).
- Harness: `judge.py` and `compare.py` in this folder, at commit fe4eec1.

## Results

| Vault notes | Unanswerable, surfaced a note (before -> after) | Reduction (95% lower bound) | Offtopic | Near |
|---:|---:|---:|---:|---:|
| 160 | 325 -> 117 of 337 | 64.0% (58.8%) | 109 -> 1 of 121 | 216 -> 116 of 216 |
| 1,000 | 325 -> 116 of 337 | 64.3% (59.0%) | 109 -> 2 of 121 | 216 -> 114 of 216 |
| 10,000 | 327 -> 109 of 337 | 66.7% (61.2%) | 111 -> 4 of 121 | 216 -> 105 of 216 |

| Vault notes | Answerable: right note in top five (of 972) | Paraphrase slice | Notes shown per question |
|---:|---:|---:|---:|
| 160 | 865 -> 861 | 231 -> 227 | 4.19 -> 0.97 |
| 1,000 | 784 -> 781 | 156 -> 153 | 4.25 -> 1.00 |
| 10,000 | 750 -> 747 | 125 -> 122 | 4.32 -> 0.98 |

No exact-keyword answer was lost at any size. The worst language lost 1.48 points
(zh, 160 notes).

| Set | Hits before -> after | Lost | Native | Cross-language | Worst language |
|---|---:|---:|---:|---:|---:|
| 2,400 six-language questions | 1,602 -> 1,581 | 1.31% | 1.15% | 1.46% | es 2.26% |
| 1,432 unseen holdout questions | 1,028 -> 1,012 | 1.56% | 1.22% | 1.86% | ja 3.49% |

| 40-question sample | p50 | p95 | Judge requests | USD per question (catalog / list) |
|---|---:|---:|---:|---:|
| 1,000 notes, no floor | 2.43 s | 3.07 s | 23.3 | 0.00042 / 0.0083 |
| 1,000 notes, floor | 1.61 s | 2.24 s | 6.7 | 0.00036 / 0.0071 |
| 10,000 notes, no floor | 2.79 s | 3.84 s | 23.3 | 0.00040 / 0.0081 |
| 10,000 notes, floor | 1.96 s | 2.79 s | 6.8 | 0.00035 / 0.0069 |
| No key (local BM25), 1,000 / 10,000 notes | 32 / 359 ms | 35 / 445 ms | 0 | 0 |

Catalog price on 2026-11-03: USD 6.3e-9 per input token (95% off a 1.26e-7 list price).
A request with n cards bills close to n squared tokens (260, 770, 2,540 and 9,080
tokens for 1, 2, 4 and 8 short cards), which is most of the cost.

## Limits

- The floor needs the judge; recall without a key is unchanged.
- About half of the "near" messages, which share a note's subject, still surface it.
- Messages were written and checked by models; the vault is synthetic.
- A label-free lexical gate was tried first and could not meet the limits even in
  its best case on tune data, so it was not shipped.
