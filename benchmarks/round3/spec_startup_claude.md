# Independent Claude complete-startup evaluation (headline feature 2)

This supersedes the isolated section-excerpt interpretation of feature 2.
Read only this specification, never implementations, Sol fixtures, practice
questions, or results. Author a new independent held-out startup bundle/set.

The agent must read session-start material FAST and WITHOUT MISSING ANYTHING:
a long MODE.md runbook, handoff.md with stacked TOP NOTE blocks, persona/human/
system memory fragments and a monitor-registry JSON. Completeness is primary;
latency and tokens are secondary. All binding rules, decisions, pending items
and first steps must surface. Old/superseded material is annotated, not deleted.

Return JSON `{author: <actual Claude model>, split: "test", version: 1,
source: <invocation/date>, license: <publication permission>, startup: {...}}`.
`startup.files` is a list of `{path, text}` for 5-8 fictional original files.
Include realistic long material, duplicated-but-distinct facts, global rules,
current and old TOP NOTE blocks with ISO dates (at least one oldest-first
input), an explicit `Supersedes: TOP NOTE ...` declaration, fenced fake headings,
pending/first-step bullet lists and JSON monitor objects with active/retired
states. Optional `MUST READ: relative/path.md` declares a local required file;
all declared files must be provided.

`startup.required_items`: independently label 25+ `{source, text}` required
rule/decision/pending/first-step strings, including buried and boundary items.
`startup.questions`: 12+ objects with `id`, `source`, `section`, `field`, `answer`
for Markdown field/list questions; JSON questions instead use `json_pointer`
and `answer`. Section/field/source/pointer are question inputs, not gold data
leaked to the answerer. Include abstention, current-versus-old and global/local
qualifications. Values may be string/list/number/boolean/null.

A fixed context-only answerer scores exact structured answers from the actual
returned context. Coverage independently checks every original source line and
required item, not just answers. No generative-model compliance claim.

Use original fictional material; record source and license (MIT or CC0-1.0 is
suitable if publication is permitted). Freeze before evaluation tuning.
Drop into `C:/Users/HP/work/birkin-mnemosyne/benchmarks/round3/frozen_claude_startup.json`.
Gains count only when they hold independently on both author sets; expose all
regressions and limits.
