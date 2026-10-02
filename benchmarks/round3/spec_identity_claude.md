# Independent Claude identity-reader evaluation

Author source-blind held-out SOUL/AGENTS reading questions. Do not read source,
Sol questions, practice questions, or results. Read only this specification.

Return `{author: <actual model>, split: "test", version: 1, identity: {document:
<Markdown>, questions: [...]}}`. Write a fictional identity/instructions
document with at least ten sections: obsolete conflicting values, global/local
qualifications, fenced-code fake headings, Korean/English and exceptions.
Facts are `Field: value`; repeated fields under different sections must differ.

Write twelve independent `{id, query, section, field, answer: string|null}`
questions. Section and field are structured question inputs, not hidden labels.
Queries name intended topic/section; include absent-field abstention.
A fixed context-only section/field answerer scores exact answers, including
abstention. This is constrained extractive accuracy, not generative-model
compliance. Full-file and ranked-section runs use the same answerer.

Record `source` (model invocation/date) and `license` (publication permission).
Use fictional original material. Suggested fixture license: CC0-1.0.

Drop into `benchmarks/round3/frozen_claude_identity.json` in
`C:/Users/HP/work/birkin-mnemosyne`, or supply it to 폴라리스. No universal-win
claim: gains must hold separately on both authors; disclose every regression.
