# Evaluation provenance and licenses

New Sol questions are original fictional material authored by this session's
main agent (Polaris, `chatgpt-subscription/gpt-6.1-sol`) on 2026-10-02, before
feature tuning. Repository MIT licensing applies; no private owner runbooks,
handoffs, registry entries or third-party questions were copied.

| Input | Author/source | License | Purpose |
|---|---|---|---|
| `frozen_sol.json` | Main-agent Sol, initial round-3 authoring | MIT | Consolidation and supplemental section reading |
| `frozen_sol_startup.json` | Main-agent Sol, complete-startup owner clarification | MIT | Headline startup completeness and constrained answers |
| `practice.json` | Main-agent practice only | MIT | Development, never reported as held-out results |
| `frozen_claude_consolidation.json`, `frozen_claude_startup.json`, `frozen_claude_identity.json` | `anthropic-subscription/claude-opus-5-5`, source-blind omo/senpi invocation on 2026-10-02; source recorded in each original file | CC0-1.0 | Independent required consolidation/startup slices and optional supplemental excerpts |
| Existing retrieval corpus and author JSONs | `claude-opus-5.5`, `gpt-6.1-sol`, `claude-fable-5.1`, already frozen in `../retrieval/` | Repository MIT | Recall only, not substitute startup/consolidation coverage |

The complete-startup question inventory and fixed context-only answerer are
frozen separately. Exact field/list/JSON-pointer answers measure **constrained
answer accuracy**, not general conversational compliance. Coverage verifies
the actual returned bytes against the supplied local closure independently of
question answers. Gains count only if present on both independent author sets.

Token measurements use the optional benchmark-only `tiktoken` `o200k_base`
encoder over the **entire returned context**, including indexes/certificates.
These are measured BPE counts for that declared encoding, not observed model
billing or a claim that GPT-6.1/Claude use that exact vocabulary. Characters and
UTF-8 bytes are also reported; earlier QA characters/4 values are explicitly
estimates and are not substituted for BPE measurements.

Tokenizer documentation: [tiktoken README](https://github.com/openai/tiktoken).
Tokenizer license: [MIT](https://github.com/openai/tiktoken/blob/main/LICENSE).
It is not imported by the core package or required by runtime tools.

Kibitzer contracts were studied in installed omo 5.1.9 and upstream revision
`61086739c3b00f0990cbcdcdfde9146791e243db`, whose license is SUL-1.0.
No upstream implementation or question set is vendored. The adapter implements
compatible shapes independently; candidate-selection metrics are not resident
nudge judgement or installed-omo end-to-end integration evidence.

The delivered Claude files match `SHA256SUMS.txt` and remain unchanged.
Both authors' complete-startup runs preserve all supplied files with zero
missing required items and 100% constrained answer accuracy. These do not prove
automatic precedence decisions or a speed/token gain.

Consolidation detection precision is 1.0 for both authors, but recall is 1.0
for Sol and 2/7 for Claude. Supplemental excerpt accuracy is 12/12 for Sol and
11/12 for Claude, versus 12/12 with full reads. Historical sibling-filtered
rank metrics retain their original scorer and are explicitly distinguished
from raw exact-gold precision@1. All regressions remain visible in
`results.json`; no held-out questions, answers or scorers were changed to
improve these values.
