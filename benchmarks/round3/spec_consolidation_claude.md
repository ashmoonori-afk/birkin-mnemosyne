# Independent Claude consolidation evaluation

Author source-blind evaluation questions for explicit user-approved memory
consolidation. Do not read implementations, Sol questions, practice questions,
or results. You may read only this specification.

Return a JSON object with actual `author` model ID, `split: "test"`, `version: 1`
and `consolidation`: 12 cases `{id, titles: [two distinct titles], bodies: [two
Markdown texts], related: boolean}`. Include exact duplicate, partial overlap,
changed numeric/current fact, negation, unrelated same-topic facts, empty and
Korean/English cases. A true label means a concise user question is warranted,
not that a lexical detector proves semantic conflict. Supply each related case
an explicit user choice and expected remaining facts if practical.

Record `source` (model invocation/date) and `license` (permission to publish).
Use fictional original material; do not copy third-party private questions.
Suggested license: CC0-1.0 for model-authored fictional fixture data.

Drop this set into `benchmarks/round3/frozen_claude_consolidation.json` in
`C:/Users/HP/work/birkin-mnemosyne`, or supply it to 폴라리스. Gain counts only
when the unchanged test protocol shows it on both Sol and Claude sets.
