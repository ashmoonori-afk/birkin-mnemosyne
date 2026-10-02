# Independent Claude evaluation authoring

NEED_CLAUDE_QUESTIONS: author a new independent held-out test set. Do not read
`frozen_sol.json`, production source, practice cases, results or implementation.
The available Claude CLI is not logged in; the omo Anthropic provider has no key.

Return JSON at `benchmarks/round3/frozen_claude.json`:

- `author`: exact actual Claude model ID, not a claimed proxy identity.
- `split`: `test`; `version`: `1`.
- `consolidation`: 12 independently authored cases, each with `id`, `titles`
  (two distinct note titles), `bodies` (two Markdown note texts), `related`
  (boolean). Cover duplicates, overlap, possibly conflicting values/negation,
  unrelated facts on a shared topic, empty notes, Korean and English.
- `identity.document`: synthetic SOUL/AGENTS Markdown, at least 10 sections,
  including obsolete contradictory instructions, fenced heading-like examples,
  multilingual text and exceptions. Facts use `Field: value`.
- `identity.questions`: 12 independently authored objects with `id`, `query`,
  `section`, `field`, `answer` (string or null). Query names the intended topic;
  section/field are structured question inputs. Include absent-field abstention.

The frozen context-only answerer extracts the field from the named section
and compares it with the expected answer. Report constrained exact-answer
accuracy, not generative model correctness. Compare full-file context against
ranked section context with the same answerer. Token counts are explicitly
estimated characters/4; also report actual characters and UTF-8 bytes.

The questions must be frozen and hashed before any evaluation tuning.
Practice questions remain separate. Existing Claude retrieval questions are
already frozen and are reused for the recall benchmark, not substituted for
these two feature-specific sets.
