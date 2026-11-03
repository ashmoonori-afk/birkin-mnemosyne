# Unanswerable question set provenance

`questions.json` holds 560 messages that the benchmark vault cannot answer. It is
a separate addition: every older question set stays byte-identical. Text is
stored as ASCII JSON escapes.

SHA-256 of `questions.json`: `beffff1ef0009ff5b2270f422b9c8562f8703da75fbcc19a84119c31ef053a5e`

## How it was made (2026-11-03 KST)

1. An independent model author (GPT-6 Astra, high) received only the 160 gold
   notes of `benchmarks/retrieval`. It saw no gate design and no ship limits.
2. A second independent worker (GPT-6 Astra, high) checked each item against its
   source note, that note's cross-language siblings, and the top 10 baseline BM25
   notes on the 10,000-note vault. BM25 was only a lookup for likely answers.
   Result: 560 kept, 0 dropped. The lead then read 18 randomly chosen tune-split
   `near` items with their notes, and all 18 were unanswerable.
3. Splits were fixed before any gate ran on these questions.

## Strata

| Stratum | Items | Tune | Test | Definition |
|---|---:|---:|---:|---|
| `near` | 320 | 104 | 216 | Same subject and vocabulary as a note, asks for a fact the note lacks |
| `offtopic` | 240 | 119 | 121 | Questions and task requests about personal or project facts absent from the vault |

Languages: en, ko, ja, zh, es, de. `near` has two items per note. `offtopic` has 40
per language, half questions and half task requests.

## Split rule

`near` follows the source note's existing dev/test split, so tuning never touches
a test note. `offtopic` uses the lowest bit of SHA-256 of
`mn-gate-1103:<id>`: zero is tune, one is test.

Every note surfaced for one of these messages counts as wrong.
