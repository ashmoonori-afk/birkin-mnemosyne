![birkin-mnemosyne - tiny multilingual memory for agents: three note cards linked by glowing threads to a search lens](https://raw.githubusercontent.com/ashmoonori-afk/birkin-mnemosyne/main/docs/assets/hero.png)

# birkin-mnemosyne

[Landing page](https://birkin-mnemosyne.vercel.app)

birkin-mnemosyne is local Markdown memory for personal agents: multilingual
BM25 retrieval, usage-driven decay and zone priorities, plus provider-portable
curation whose file operations are bounded by a deterministic executor. The
core has zero runtime dependencies and needs no model or API key to store or
search notes. Notes stay readable, greppable and diffable; an optional MCP
server connects the vault to agent clients, and an opt-in semantic mode adds
meaning-based retrieval.

## 0.7.2: keep same-name notes searchable

Notes in different folders no longer disappear from the index when they share
a filename stem, such as `index.md` or `README.md`. The newest keeps the bare
stem; the others use their relative path without `.md` as an index key
(`./name` for a root note). Equal timestamps keep the existing sorted-path
tie-break. The fix does not rename or rewrite notes.

On the public round-two corpus of 20,000 documents, heldout known-gold recall@2
rose from **270/1,011 (26.71%) to 537/1,011 (53.12%)**, +26.41 percentage points:
274 paired gains and seven losses. Development recall rose from 231/524 to
263/524, but the already-indexed development slice fell from **231/405 to
224/405**. More indexed candidates can still displace a previously found note.

The 69 preselected independent source anchors had 28 gains and no losses
(exact two-sided p=7.45e-9). A preregistered family-interval criterion was
**not computable** because some strata had only one source family. The owner
decided to ship on the paired evidence, explicitly waiving that criterion;
it is not reported as passed. This is a reused question set with incomplete
alternative-answer coverage, not proof of semantic answer accuracy.
Only the indexing fix ships; the experimental ranking correction and taxonomy
features do not. [Release evidence and limits](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/docs/releases/0.7.2.md).

## 0.7.1: nested folders and terminal reads

Visible Markdown notes are discovered recursively, including nested imports
and folders with spaces or Unicode names. Hidden files, cache folders and
links remain excluded. Zones use the complete relative parent; archive moves
keep the original subpath, and checked undo restores exact paths and bytes.
In 0.7.1, duplicate filename stems selected only the newest file; 0.7.2 retains
the other files under path keys.

The published package also includes read-only `search`, `list` and `show`,
repeatable CLI label filters, `--version`, and journaled `undo`. Terminal and
MCP commands share the documented vault defaults. These changes do not add
a model requirement or turn labels into ranking terms.

## Install

Requires Python >= 3.10. Install from PyPI:

```bash
pip install "birkin-mnemosyne==0.7.2"
```

From a checkout, the existing development and benchmark commands are:

```bash
pip install -e .                 # standard-library-only core
pip install -e ".[dev]"          # pytest, ruff
pip install -e ".[bench]"        # fastembed, numpy: embedding baselines only
pip install -e ".[mcp]"          # official MCP SDK and server
pip install -e ".[semantic]"     # optional meaning-based retrieval
```

The extras are optional. `[bench]` reproduces embedding baselines; it does
not enable semantic retrieval. See below for explicit semantic preparation.

## Quick start for agent users

The commands below ship in 0.7.2. Install the published MCP extra to connect
your agent; a source checkout is not required.
Give your coding agent a memory, then check from a terminal what it stored:

```bash
pip install "birkin-mnemosyne[mcp]==0.7.2"
claude mcp add --scope user mnemosyne -- mnemosyne-mcp --vault ~/mnemosyne

# Start a new agent session and ask it to remember a note titled
# "Release checklist" before inspecting that note below.
mnemosyne --version
mnemosyne --vault ~/mnemosyne search "release checklist"
mnemosyne --vault ~/mnemosyne list
mnemosyne --vault ~/mnemosyne show release-checklist
```

Other clients (Claude Desktop, Cursor, Codex CLI, IDEs) are in the
[MCP server section](#mcp-server-claude-code-claude-desktop-codex-cli-cursor).
`search`, `list` and `show` print JSON with the same fields as the MCP tools
`memory_search`, `memory_list` and `memory_get_note`. They are read-only:
they never count as a use, so they do not change usage ranking. `show` exits 1
when the note does not exist; a vault directory that does not exist exits 2 and
is not created.

For label-aware recall, add `--label namespace:value` to `search` or `list`.
Repeat `--label` to require every label (AND). Filtering happens before ranking
or pagination; `list` reports `label_counts` for all matching notes, not just
the returned page.

User-provided Markdown extensions are case-insensitive (`.md`, `.MD`, `.Md`);
imports also recognize `.txt` and `.json` without regard to extension case.
Original filenames and source bytes are retained. Hidden dot files remain
outside ordinary recall, including files inside a visible zone.

Every `mnemosyne` command finds its vault the same way: `--vault` (before or
after the command name), else `$MNEMOSYNE_VAULT`, else
`~/.birkin-mnemosyne/vault`, the same default as `mnemosyne-mcp`. Only `init`
falls back to the current directory instead. `~` is expanded even when the
shell leaves it quoted. Set `MNEMOSYNE_VAULT` once and the terminal and the
MCP server use the same vault without repeating `--vault`.

## First run

From v0.7.0, `mnemosyne init` previews first-run organization
without changing any files. It works offline with the standard-library-only
core and needs no model or API key:

```bash
mnemosyne init --vault my_vault
mnemosyne init --vault my_vault --apply

# Optional external Markdown import: keep the option when applying its plan.
mnemosyne init --vault my_vault --import ./markdown_export
mnemosyne init --vault my_vault --import ./markdown_export --apply
```

Without `--vault`, `init` uses `$MNEMOSYNE_VAULT` when it is set, otherwise
the current directory; the JSON output's `vault` key names the absolute
directory it acted on. The existing
`mnemosyne-index --vault my_vault init` command uses the same dispatcher.
The JSON output lists the plan and reports notes, topics, INDEX token
estimates, warnings, and verification status. A preview says `planned`;
an applied run independently verifies the resident INDEX and checks drift.
This does not claim that every note fits into one startup bundle.

Initialization reports duplicate and possible overlap/conflict candidates,
but never chooses a winner, merges, archives, or deletes notes. It completes
missing `title`, `type`, and `tags` through the existing byte-exact review
journal, preserving existing fields and body bytes; ambiguous headers and
bytes bound by split receipts are retained with warnings. If the output has
an `undo_transaction`, run
`mnemosyne --vault my_vault undo --transaction <undo_transaction>` (or call
`Consolidation(vault).undo(transaction_id)` or the `memory_review_undo` tool)
to restore the original source images. The same command undoes an applied
handoff fold or review answer. Added imports, topic catalogues, and INDEX routes remain after undo.

Topic documents are deterministic source-link catalogues, grouped by tag,
source directory, or note type. Every source stays routed alongside its
catalogue. Existing aliases are retained; large INDEX views use the existing
complete topic map or warn about the UTF-8-bytes/4 budget without dropping
routes. `--max-tokens` changes that warning budget. Unchanged reruns reuse
outputs and create no additional journal. Changed destinations are refused
rather than overwritten; an unfinished journal requires checked recovery.

## 30-second usage

```python
from birkin_mnemosyne import VaultMemory

mem = VaultMemory({"vault_path": "my_vault"})
mem.write_note(
    "Ingress DNS",
    "nginx ingress resolves service DNS; allow HTTPS through the firewall.",
    zone="devops",
)
for hit in mem.dex.search("ingress dns"):
    print(hit)
# Reinforce the note your agent actually used, not every search candidate.
mem.dex.record_access("ingress-dns")
```

For an existing vault, use `Mnemosyne("my_vault")`, call `refresh()`, then
`search(query)`. Unicode normalization, accent folding, Latin prefix stems,
and Hangul/Han/kana bigrams support multilingual lexical matching. File
changes refresh the index: notes written through the library are searchable
at once, and `search()` looks for edits made outside it (for example in
Obsidian) at most once every 2 seconds (`refresh()` looks immediately). The
compressed cache is rebuildable, while usage
history persists separately. Usage decay and zone activity adjust ranking.

### Widen a query at search time (optional)

Matching is lexical, so a question worded differently from the note can miss
it. A host model can widen its own query when it searches. Nothing is stored,
the index is untouched, and a search without `expansions` ranks as before:

```python
mem.search(
    "why can't the pods find each other by name",
    expansions={
        "synonyms": ["service discovery", "name resolution"],  # weight 0.75
        "keywords": ["Namensauflösung", "Dienst"],   # 0.75: your other language(s)
        "related": ["ingress", "firewall"],                    # 0.4
        "note_line": "The ingress resolves service DNS names.",  # 0.4
    },
)
```

The query's own words weigh 1.0, and a note that contains all of them stays
first. Over MCP the same four fields are parameters of `memory_search`. On
the benchmark's test split at 10,000 notes, expansions written by two models
that saw only the question moved paraphrase MRR from 0.204 to 0.981 and
0.952. Questions and expansions are both model-written, so read that as an
upper bound: see
[Search-time query expansion](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/benchmarks/retrieval/RESULTS.md#latest-main-replay-2026-10-11).

## Cross-language recall reranking (opt-in, hosted)

`KibitzerAdapter.select_crosslingual()` adds a reranking stage for recall
across languages. It is off unless you call it with a `decide` client, and
each call sends paid requests to a hosted decision model. `select()`, `search()`
and the stdlib core are unchanged.

```python
from birkin_mnemosyne import KibitzerAdapter, get_completer, opengateway_decider, translate_views

adapter = KibitzerAdapter("my_vault")
query = "클러스터 오토스케일러는 언제 노드를 추가하나요?"
views = translate_views(query, "ko", get_completer("api"))   # English view
decide = opengateway_decider()          # OPENGATEWAY_API_KEY, sionic-ai/jev-omni
for hit in adapter.select_crosslingual(query, decide=decide, views=views):
    print(hit.path, hit.score)          # lower score is better
```

The pipeline has five steps:

1. Take the top 32 notes for the original query and for each translated view,
   once with BM25 and once with TF-IDF cosine. Keep the original query's notes
   first and drop repeats.
2. Score every card with the judge in packets of at most 8. A card is the
   note description plus the 1,500-character excerpt richest in the query's
   rare terms. The judge only sees the original query.
3. Average the two retrievers' scores and keep five notes.
4. Compare every pair of the five in both orders and sort by the summed,
   order-symmetrised preference. Exact ties keep the step-3 order.
5. Raise `RerankError` on any malformed or failed judge response. There is no
   partial fallback and no automatic retry.

A query costs `ceil(n_bm25/8) + ceil(n_cosine/8) + 20` judge requests.

**Measured result (kib-bm25 study, October 2026).** The research harness ran
this method on a fixed set of 2,400 questions in six languages (zh, ja, ko, es,
fr, en; 400 per language, half native and half cross-language). A labeled
relevant document appeared among the five initial candidates for 1,602
questions, up from 485 for the installed Kibitzer recall baseline. That is
3.30x, with a grouped 95% ratio interval of 3.05 to 3.58. Every language rose,
and so did every native-language subset. On older top-2 checks it reached
452/524 (floor 425), SciFact 231/300 (floor 224) and Korean MIRACL 137/213
(floor 107).

The earlier method without the pairwise step scored 142 on that Korean set but
failed SciFact with 215. So the pairwise step costs five Korean hits while
clearing every floor.

The extra pairwise requests over all 3,437 cases cost an estimated $1.85
(68,600 requests at $0.0000000378 per input token). That is not an invoice,
and it excludes the earlier pointwise stage.

These figures come from the research harness and its retrievers, not from
rerunning this module. The module ports the union, excerpt, packet, merge and
pairwise stages exactly, but uses this package's tokenizer for retrieval.
The question sets were reused during method selection, so they are not
untouched holdouts.

## Always-loaded memory INDEX (opt-in)

Keep a complete **when to read -> which document** map available from startup
context, then open the details only when needed. The INDEX is available from
v0.6.0. Task-bound reads and the two-level topic map described below are
available from v0.7.0.

```python
from birkin_mnemosyne import MemoryIndex

# Register an existing note, such as the one created in the example above.
index = MemoryIndex("my_vault")
index.register("Ingress DNS", "devops/ingress-dns.md")
print(index.render())                 # complete always-loaded map
opened = index.open("Ingress DNS")     # exact trigger; complete document
```

The `.mnemosyne-memory-index/` directory is the opt-in marker. A vault
without that directory keeps its legacy behavior. Managed startup/digest/host
surfaces retain the complete resident map. Over-budget reads warn but never
remove a route or topic. There is no INDEX removal, expiry, or automatic cleanup
operation. Hosts should retain `required=True` or `--require-memory-index`
across restarts and re-read the complete INDEX after context compaction.
Exact triggers are reliable; lexical matching and BM25 fallback are not
semantic guarantees.

From v0.7.0, task-bound reads let a host call
`StartupReader("my_vault").read([], task="Check Ingress DNS")` before acting.
They return every lexically matched document in full, without the optional
lookup's top-k cutoff or search fallback. Pass the same `task` to
`memory_startup_read` / `memory_startup_verify` over MCP; indexed Hermes
`prefetch` uses this path automatically. See the usage guide below for the
lexical limits and complete-read failure behavior.

From v0.7.0, the renderer also chooses between a flat INDEX and a smaller two-level
topic map. Topics follow complete parent-directory paths; every route remains
in its complete topic view. `index.read(topic="dir:devops")` and MCP
`memory_index_read(topic="dir:devops")` expand that topic. Task-bound startup
automatically includes matched topic views and their documents from one
routing snapshot. Same-document aliases share a label only when shorter;
no condition or target is removed. The selected layout uses the declared
bytes/4 estimate, not a model-specific tokenizer.

Use `.render()` or `view.context` for compact resident text. The default
`read().entries` still returns all original mappings; its complete structured
result is not claimed to have the same cost as the resident text.

```bash
mnemosyne-index --vault my_vault check
mnemosyne-index --vault my_vault split handoff.md          # read-only preview
mnemosyne-index --vault my_vault split handoff.md --apply  # explicit migration
```

The splitter preserves every source byte and prints a complete per-line
coverage table. The checker reports orphans, dangling routes and lost
coverage. MCP exposes `memory_index_register`, `memory_index_read`,
`memory_open_trigger`, `memory_index_check`, and `memory_index_split`.
Keep `.mnemosyne-memory-index/` and `.mnemosyne-reviews/`, including captured
source revisions, when backing up a vault.

The latest public replay on **2026-10-11**, main `876ad40`, reduced the
fictional large-note whole startup payload from **45,128 to 1,297 o200k_base
tokens**. The resident INDEX alone is 144 tokens; all 30 routes and 155,749
source bytes remain intact. Separate frozen Sol and Claude answer sets both
stay at **12/12**, not an accuracy gain. Small-note combined task costs are
199-221 tokens for Sol (12/12 cost more than the full original) and 229-432
for Claude (0/12 cost more). These are separate measurements, not task
accuracy on the large corpus.

| Current public task-delivery replay | Result |
|---|---:|
| Positive tasks with complete required bodies | 12/12 |
| Negative tasks correctly empty | 4/4 |
| All tasks with byte-exact bodies and fresh verification | 16/16 |
| Extra document deliveries | 1 |
| Grown fixture whole startup / resident INDEX, o200k_base tokens | 1,036 / 814 |

The grown fixture preserves all 480 routes across 240 documents and 12 topics.
These are mechanical delivery checks, not model obedience or semantic
precision.

The separately measured **2026-10-11 replacement private snapshot** published
only as anonymous aggregates has startup **2,193 -> 2,193** and full-run
**211,935 -> 177,359** o200k_base tokens over 26 tasks (16.3% less).
Complete delivery improves **25/26 -> 26/26**, with extra document deliveries
**30 -> 12**. Its full-run sum counts complete task inner contexts, not tool
JSON or JSON-RPC framing. It is a different corpus from the historical
private snapshot and was not rerun for the public replay.

See the [usage and recovery guide](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/docs/memory-index-guide.md) and
[measurements, denominators and regressions](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/docs/memory-index-results.md).

## Deterministic note labels (0.7.0)

Notes can carry readable `namespace:value` labels in their frontmatter
`labels` field, like `project:Infra` or `lang:ko`. Labels are derived
deterministically without a model, an API key or the clock, and are exposed
by storage, search, list and MCP surfaces. Labels are not query
words and never enter the text that scores ranking; tags, titles and bodies
keep being searched exactly as before.

The pure inference/editing boundary lives in `birkin_mnemosyne.labels`
(`read_labels`, `suggest_labels`, `annotate_labels`); `plan_labels` /
`run_labeling` in `birkin_mnemosyne.labeling` are the vault I/O and journal
integration built on it, and write/search integration is on
`VaultMemory.write_note` and `search()`. The pure boundary itself never
imports memory, mnemosyne, memory_index or onboarding.

### Format and normalization

A label is a nonempty namespace and value split at the first colon. Stored
labels are NFC-normalized, trimmed, **namespace-lowercased**, sorted and
deduplicated, while the **value spelling and case are preserved** —
`Project:Zed` stores as `project:Zed`, so distinct project values are never
silently conflated. The namespace is lowercase ASCII `[a-z][a-z0-9_-]*`; the
value must be nonempty and free of control characters. Malformed explicit
labels raise `LabelError` at the boundary instead of being filtered out.

The `labels` field is user-owned: `[]` (an explicit empty field) is owned
too; `labels=None` (or omitting it) keeps existing labels and only infers
deterministic suggestions when the field is absent. An explicit list is a
checked replacement; `[]` clears. Existing valid manual labels are never
rewritten merely to normalize their bytes or ordering. Header editing changes
only the `labels:` field (or adds it), preserving every other byte, comment,
BOM, line ending and body; tags are retained.

### Deterministic suggestions (no model)

Suggestions are inferred from the source bytes and INDEX routing state only
— no provider call and no network request:

- `type`, explicit `zone` or the visible path zone, and explicit `topic`
  metadata; the exact INDEX triggers already routed to the note's path also
  become `topic:` suggestions
- explicit `project`, `people`/`person`, `entities`/`entity` and typed
  wikilinks `[[project:...]]`, `[[person:...]]`, `[[entity:...]]`
- real ISO calendar dates from `created`/`updated`/`date`/`dates` and ISO
  date mentions in the body (`date:YYYY-MM-DD`); the current clock is never
  an inference input
- language — explicit `language`/`lang` wins; otherwise conservative script
  evidence identifies unmistakable non-Latin scripts (Hangul → `lang:ko`,
  kana → `lang:ja`, and so on). **Latin text alone is never proof of
  English**, so unknown Latin text stays without a `lang:` label
- a `type: project` note derives its `project:` value from title/path, and a
  `type: person` note derives `person:` likewise
- the first path directory → `zone:`; imported candidates also get the
  original relative path → `source:` and the source format → `format:`

### CLI: preview, apply, replace, undo

`mnemosyne label` only previews by default: it scans without creating a
directory, lock, cache or journal, proposes annotation only where the labels
field is absent, and skips generated catalogues, split receipts, archives and
managed handoffs. Sources and topic documents bound to a split receipt are
also excluded, even when explicitly requested, so original-byte coverage
remains valid. User-owned manual and empty fields are included in the
report but not modified. For a
test vault holding `notes/alpha.md` (`---` / `title: Alpha` / `---` /
`Body of Alpha.`), the read-only JSON report is:

```bash
mnemosyne --vault my_vault label
```

```json
{"mode": "preview", "ok": true, "notes": 1, "changed": 1, "warnings": [],
 "label_counts": [["zone:notes", 1]], "undo_transaction": null}
```

`--apply` holds the shared vault lock, re-checks the captured byte images and
routing against the live vault, and commits only the actual label changes
through the existing review journal. A no-op apply writes nothing and creates
no transaction:

```bash
mnemosyne --vault my_vault label --apply
```

```json
{"mode": "applied", "ok": true, "notes": 1, "changed": 1, "warnings": [],
 "label_counts": [["zone:notes", 1]],
 "undo_transaction": "65c5b7ca23004a5daa41b692f58e7a6e"}
```

Application inserts only the `labels:` line, preserving every other byte:

```markdown
---
title: Alpha
labels: ["zone:notes"]
---
Body of Alpha.
```

Pass that run's `undo_transaction` to the existing shared journal undo — label
apply uses the same `Consolidation.undo` path as handoff folds, so there is no
dedicated undo command:

```bash
mnemosyne --vault my_vault handoff undo --transaction 65c5b7ca23004a5daa41b692f58e7a6e
```

```json
{"transaction_id": "65c5b7ca23004a5daa41b692f58e7a6e", "state": "undone",
 "journal_path": ".mnemosyne-reviews/65c5b7ca23004a5daa41b692f58e7a6e.json"}
```

If a note was edited after apply so the on-disk image differs from the
journaled post-image, undo refuses with `post-image changed; refusing undo`
rather than clobbering the edit.

Repeated `--path` restricts selection; repeated `--label` supplies an
explicit replacement; `--clear-labels` requests an explicit clear.
`--label` and `--clear-labels` are mutually exclusive (exit code 2, nothing
written), and a requested path with no eligible note only warns:

```bash
mnemosyne --vault my_vault label --path notes/alpha.md \
  --label Project:Zed --label Person:Jane
```

```json
{"mode": "preview", "ok": true, "notes": 1, "changed": 1, "warnings": [],
 "label_counts": [["person:Jane", 1], ["project:Zed", 1]],
 "undo_transaction": null}
```

The explicit labels are normalized, sorted and written as the replacement;
applying `--clear-labels` stores `labels: []`, and its undo restores the
previous manual labels byte-exactly.

### init --import: external files and directories

`init --import` accepts one `.md`/`.txt`/`.json` file or one directory
outside the vault. Hidden files, `_archive`, other suffixes and paths that
overlap the vault are excluded or refused. Preview first, apply explicitly;
`--group-by-label` is opt-in:

```bash
mnemosyne --vault my_vault init --import ./markdown_export
mnemosyne --vault my_vault init --import ./markdown_export --apply \
  --group-by-label project
```

- **Markdown** keeps its original bytes; only missing frontmatter fields are
  added. Complete unlabeled Markdown gains labels exactly like vault notes.
- **`.txt`/`.json`** become one lossless candidate each, wrapped verbatim
  inside a backtick fence longer than the longest backtick run in the source
  so the body cannot close it. The original suffix is retained
  (`export.txt` → `export.txt.md`), so formats never overwrite each other.
- Invalid JSON is retained as text with a warning (`invalid JSON retained as
  text`) — never extracted or rewritten.
- Invalid UTF-8, symlinks/reparse points and destinations that collide by
  converted name or Unicode case folding are refused before any plan forms.
- **Source files are never modified**; the raw-source digest and the
  converted-candidate digest are separate. If an owner edits a copy's bytes
  other than its labels after apply, a rerun refuses with `import destination
  changed` and leaves both the original and the edited copy alone. Label-only
  edits are retained. Unchanged reruns create no journal.
- Imported notes get `source:` (original relative path) and `format:` labels;
  Markdown that already has a labels field keeps its manual labels.
- `--group-by-label <namespace>` groups topic catalogues by the
  deterministic lexicographically-first existing value in that namespace,
  else the existing topic; default routing behavior is unchanged.

The report's `label_counts` is a per-note histogram: each normalized label
counts once per note, preserving value case. The following **selected fields
from the preview report** use the `notes/alpha.md` fixture above and three
export files: `x.md` with title `Infra` and type `project`, `notes.txt` with
plain text, and `data.json` containing `{"project": "Infra"}`. The full CLI
report also includes source hashes, routes, mutations and verification fields:
`<digest>` below abbreviates the import's actual 64-character digest.

```json
{"mode": "preview", "ok": true, "notes": 4, "imports": 3, "topics": 3,
 "warning_count": 0, "warnings": [],
 "label_counts": [["format:json", 1], ["format:md", 1], ["format:txt", 1],
   ["project:Infra", 1], ["source:data.json", 1], ["source:notes.txt", 1],
   ["source:x.md", 1], ["type:project", 1], ["type:topic", 3],
   ["zone:imports/init-<digest>", 3], ["zone:notes", 1]],
 "undo_transaction": null}
```

An init `undo_transaction` reverts only the journaled frontmatter/label byte
edits. Imported copies, topic catalogues and INDEX routes are additive and
remain after undo.

### Search and MCP: AND eligibility, ranking unchanged

`Mnemosyne.search` and `Memory.search` accept `labels` with **AND**
semantics: only notes whose stored labels carry every requested label become
candidates, applied **before** any candidate cut or pagination. `None` or an
empty list leaves scoring and ordering untouched; hits carry their stored
labels; a malformed request raises `LabelError` before any lookup and never
broadens into an unfiltered search. Malformed on-disk label metadata indexes
that note as label-less rather than breaking ordinary recall or matching.

```python
from birkin_mnemosyne import Mnemosyne, VaultMemory

mem = VaultMemory({"vault_path": "my_vault"})
mem.write_note(
    "Ingress DNS",
    "nginx ingress resolves service DNS; allow HTTPS through the firewall.",
    zone="devops", labels=["project:Infra", "lang:en"],
)
for hit in mem.search("ingress dns", labels=["project:Infra"]):
    print(hit["title"], hit["labels"])
# ingress-dns ['lang:en', 'project:Infra']

mem.write_note("Deploy runbook", "It rolls out the ingress.", zone="devops")
print([hit["title"] for hit in mem.search("deploy runbook", labels=["zone:devops"])])
# ['deploy-runbook']
```

Over MCP the same filter is a tool argument. `memory_search`'s `labels`
omitted or `[]` means no filter:

```json
{
  "name": "memory_search",
  "arguments": {"query": "ingress dns", "labels": ["project:Infra"]}
}
```

`memory_remember`'s `labels` is `None`/omitted to keep or infer when absent,
`[]` to clear explicitly. This creation example requires a new title:

```json
{
  "name": "memory_remember",
  "arguments": {
    "title": "Ingress DNS",
    "body": "nginx ingress resolves service DNS.",
    "labels": ["project:Infra", "lang:en"]
  }
}
```

`memory_list` applies its `labels` filter before pagination and returns
`label_counts` for the **whole eligible set** — not just the returned page —
alongside the full eligible count, so labels alone can browse the vault:

```json
{
  "name": "memory_list",
  "arguments": {"zone": "devops", "labels": ["project:Infra"]}
}
```

Ordinary search recursively indexes visible Markdown at every depth, including
the copies `init --import` places under `imports/init-<digest>/...`. INDEX
routes still retain each exact relative path and grouped catalogues. Newly
inferred `zone:` labels use the complete parent path; existing manual labels
are retained.

### Hermes

The Hermes provider's `birkin_memory_search` also accepts an optional
`labels` array: an AND filter, where `null` or `[]` leaves recall unfiltered.
Install, selection and lifecycle follow the existing 0.7.0 guidance in the
[integrations/hermes/README.md](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/integrations/hermes/README.md):

```json
{
  "name": "birkin_memory_search",
  "arguments": {"query": "ingress dns", "limit": 8, "labels": ["zone:devops"]}
}
```

### Context cost (measured fixture)

On a representative synthetic fixture — a full startup JSON with one
registered project note and an existing scoped handoff — labels grow the
context from UTF-8 **4,207 to 4,303 bytes**, an estimated **1,052 to 1,076
tokens (+24)**. These are `ceil(bytes / 4)` estimates, not a model tokenizer,
and they come from a different fixture than the handoff measurement below
(+756) — never add them into a universal total. The invariant that labels
are not ranking terms stands independently of this cost.

**Frozen candidate regression (`8b7ab156`).** Production labeling was applied
to disposable benchmark vaults of 160, 1,000 and 10,000 notes before running
BM25, hybrid and both frozen expansion engines: 12 runs with 1,440 queries
each, three public query authors, six languages and all five metric/slice
families. Every rank and metric matches the unlabeled baseline exactly, and
the frozen corpus, query and expansion fixture hashes are unchanged. This
is a regression check on that fixed corpus, not a recall guarantee for
arbitrary private documents.

## Scoped session handoffs (0.7.0)

Capture work, decisions, open items, open questions, next step and links without
a model or API key. Each checkpoint is immutable and belongs to an exact
`project_key` / optional `task_key` pair. Keys preserve case, Unicode and slash
spelling, including Windows-shaped keys; they are data, not filesystem paths.
An identical `capture_id` retry returns the original record. Changed content
needs a new ID.

```bash
export MNEMOSYNE_PROJECT_KEY='example/project'
export MNEMOSYNE_TASK_KEY='release'
mnemosyne --vault my_vault handoff capture \
  --capture-id 'cli-session-1:checkpoint-1' \
  --work 'Packaging is ready; release checks remain.' \
  --decision 'Keep the original notes.' \
  --open-item 'Run Windows CI.' \
  --open-question 'Is the final review approved?' \
  --next-step 'Run the remaining checks.' \
  --link 'https://example.invalid/release'
mnemosyne --vault my_vault handoff latest
mnemosyne --vault my_vault handoff resume
mnemosyne --vault my_vault handoff fold --keep 3
```

To enable session memory during onboarding, preview first and apply explicitly:

```bash
mnemosyne --vault my_vault init --enable-handoff
mnemosyne --vault my_vault init --enable-handoff --apply
```

The preview reports the requested and current enabled state without writing.
Capture also additively enables handoffs and an absent INDEX, preserving existing
routes and budgets. `--json-stdin` accepts the equivalent JSON fields:
`work`, `next_step`, `decisions`, `open_items`, `open_questions`, `links`,
`project_key`, `task_key`, `capture_id`, and optional `event`, `session_id`,
`source`. List families are arrays. Use stdin or field flags, not both.
Exit codes are 0 for success, 1 for an absent latest record, and 2 for invalid
input. An explicit `--project-key` selects project-wide scope unless
`--task-key` is also supplied; it never inherits a different task from the
process defaults.

```python
from birkin_mnemosyne import HandoffFields, HandoffScope, HandoffStore, StartupReader

scope = HandoffScope("example/project", "release")
receipt = HandoffStore("my_vault").capture(
    scope, HandoffFields("Reviewing the release.", next_step="Check the final head."),
    capture_id="api-session-1:checkpoint-1",
)
reader = StartupReader("my_vault")
bundle = reader.read([], project_key=scope.project_key, task_key=scope.task_key)
assert reader.verify(
    bundle.context, [], project_key=scope.project_key, task_key=scope.task_key,
).complete
print(receipt.path, bundle.estimated_tokens)
```

Startup always includes the complete latest active capture beside the complete
INDEX and a verified scope/selection receipt. Missing or corrupt required state
fails the read; soft budgets never truncate it. `task_key` selects a handoff
namespace; the separate `task` argument matches INDEX routes. Ordinary note
search does not index managed handoff files.

The optional [Hermes provider](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/integrations/hermes/README.md#session-handoffs)
captures at real session-end and pre-compression callbacks when enabled and
bound to a project. It preserves the last user/assistant text and explicit
marked fields without a model. Bound prefetch includes the full latest handoff
and INDEX even for an empty or unmatched query. Other hosts use the explicit
API, CLI or MCP calls below.

In omo, Claude Code and other MCP clients, call `memory_handoff_capture` at the
chosen session or pre-compaction checkpoint, then `memory_startup_read` with the
same project/task keys when resuming; `paths` may be omitted when the INDEX and
the handoff provide the startup material. This lifecycle is caller-managed. For
example, the parameters to `tools/call` are:

```json
{
  "name": "memory_handoff_capture",
  "arguments": {
    "project_key": "example/project",
    "task_key": "release",
    "capture_id": "mcp-session-1:checkpoint-1",
    "work": "Reviewing the release.",
    "next_step": "Check the final head."
  }
}
```

`memory_handoff_read` returns the latest fields, active count and warnings.
`memory_handoff_fold` previews by default. It keeps the newest three captures
and always pins latest; the existing curation gate still protects notes and
limits archival against the whole vault. Apply a nonempty preview using its
`plan_id` (`handoff fold --apply --plan-id` or MCP `apply=true`). Originals move
to the scope's `archive/`; only accepted inputs enter the dated summary.
Pass the resulting `transaction_id` to `handoff undo --transaction` or
`memory_review_undo(confirm=true)` to restore exact originals. Changed images
refuse undo. An undone plan needs a fresh preview.

The Python equivalent is `HandoffRetention` from
`birkin_mnemosyne.handoff_retention`: `preview(scope, keep=3)` and
`apply(scope, plan_id, keep=3)`; existing `Consolidation.undo(transaction_id)`
handles recovery. Preserve `.mnemosyne-handoffs/` and `.mnemosyne-reviews/`
when backing up. Captures, archive records and retained journal snapshots are
plain files; ordinary note edits and init normalization do not rewrite them.

The default per-record soft budget is 2,000 estimated tokens, configurable with
`HandoffStore(vault).enable(max_tokens=...)`. Complete records and summaries
must fit 1 MiB; startup also enforces its existing 64-file / 2 MiB source
budget. Oversized summaries fail before any archival.

**Measured example:** the six-field Windows-shaped CLI fixture grew from
650 to 3,675 UTF-8 bytes of complete serialized startup context:
**163 -> 919 estimated tokens (+756)**. Empty scope binding accounts for 140
of that increase; the raw handoff alone is 194. These are `ceil(bytes / 4)`
estimates, not model-tokenizer counts or the separate retrieval measurements
below. Cost varies with the captured content.

## What the numbers say

All retrieval quality below is the **final frozen test split**, replayed on
**2026-10-11**, main `876ad40` (Linux x86_64/WSL2, Python 3.14.4), from
[RESULTS.md](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/benchmarks/retrieval/RESULTS.md#latest-main-replay-2026-10-11).
The synthetic corpus has 160 gold notes in six languages, padded with
invented distractors to 1,000 and 10,000 notes. **Three independent query
authors** (claude-opus-5.5, gpt-6.1-sol, claude-fable-5.1) supply exact,
low-overlap paraphrase and code-switched questions. Cross-language sibling
notes are removed before scoring; tuning uses dev only.

MRR measures how early the correct note appears; R@5 measures whether it is
in the first five hits. Higher is better. Each arrow is **default core ->
optional semantic mode**, not an earlier draft result. Bold values mark a
loss. Language codes: en English, ko Korean, ja Japanese, zh Chinese,
es Spanish, de German.

### Per language, all query kinds

#### 160 notes

| Language | MRR: core -> semantic | R@5: core -> semantic |
|---|---|---|
| en | 0.591 -> 0.640 | 0.698 -> 0.746 |
| ko | 0.578 -> 0.640 | 0.654 -> 0.728 |
| ja | 0.794 -> 0.843 | 0.848 -> 0.899 |
| zh | 0.818 -> 0.871 | 0.867 -> 0.926 |
| es | 0.698 -> 0.744 | 0.769 -> 0.861 |
| de | 0.690 -> 0.749 | 0.763 -> 0.822 |

#### 1,000 notes

| Language | MRR: core -> semantic | R@5: core -> semantic |
|---|---|---|
| en | 0.581 -> 0.620 | 0.679 -> 0.714 |
| ko | 0.552 -> 0.614 | 0.613 -> 0.683 |
| ja | 0.782 -> 0.809 | 0.848 -> 0.909 |
| zh | 0.766 -> 0.823 | 0.830 -> 0.881 |
| es | 0.655 -> 0.686 | 0.694 -> 0.713 |
| de | 0.667 -> 0.709 | 0.748 -> 0.778 |

#### 10,000 notes

| Language | MRR: core -> semantic | R@5: core -> semantic |
|---|---|---|
| en | 0.568 -> 0.604 | 0.655 -> 0.675 |
| ko | 0.557 -> 0.608 | 0.609 -> 0.658 |
| ja | 0.782 -> 0.816 | 0.848 -> 0.879 |
| zh | 0.764 -> 0.782 | **0.822 -> 0.815** |
| es | 0.673 -> 0.681 | 0.704 -> 0.704 |
| de | 0.683 -> 0.708 | 0.741 -> 0.748 |

### Per independent query author and language

These MRR tables keep every author and corpus size separate. Semantic mode
loses Spanish MRR for claude-opus-5.5 at 1,000 and 10,000 notes, and Chinese
MRR for gpt-6.1-sol at 10,000 notes; those cells are bold, not averaged away.

#### claude-opus-5.5

| Notes | Language | Core MRR | Semantic MRR |
|---|---|---|---|
| 160 | en | 0.606 | 0.672 |
| 160 | ko | 0.597 | 0.668 |
| 160 | ja | 0.773 | 0.812 |
| 160 | zh | 0.820 | 0.852 |
| 160 | es | 0.692 | 0.707 |
| 160 | de | 0.694 | 0.739 |
| 1000 | en | 0.592 | 0.644 |
| 1000 | ko | 0.565 | 0.622 |
| 1000 | ja | 0.784 | 0.795 |
| 1000 | zh | 0.750 | 0.794 |
| 1000 | es | 0.653 | **0.646** |
| 1000 | de | 0.672 | 0.692 |
| 10000 | en | 0.588 | 0.639 |
| 10000 | ko | 0.570 | 0.608 |
| 10000 | ja | 0.763 | 0.828 |
| 10000 | zh | 0.746 | 0.764 |
| 10000 | es | 0.653 | **0.639** |
| 10000 | de | 0.672 | 0.687 |

#### gpt-6.1-sol

| Notes | Language | Core MRR | Semantic MRR |
|---|---|---|---|
| 160 | en | 0.524 | 0.559 |
| 160 | ko | 0.607 | 0.671 |
| 160 | ja | 0.827 | 0.840 |
| 160 | zh | 0.811 | 0.877 |
| 160 | es | 0.628 | 0.711 |
| 160 | de | 0.615 | 0.663 |
| 1000 | en | 0.512 | 0.542 |
| 1000 | ko | 0.605 | 0.674 |
| 1000 | ja | 0.821 | 0.851 |
| 1000 | zh | 0.762 | 0.847 |
| 1000 | es | 0.577 | 0.652 |
| 1000 | de | 0.599 | 0.629 |
| 10000 | en | 0.496 | 0.517 |
| 10000 | ko | 0.609 | 0.668 |
| 10000 | ja | 0.826 | 0.828 |
| 10000 | zh | 0.777 | **0.776** |
| 10000 | es | 0.609 | 0.643 |
| 10000 | de | 0.626 | 0.648 |

#### claude-fable-5.1

| Notes | Language | Core MRR | Semantic MRR |
|---|---|---|---|
| 160 | en | 0.643 | 0.691 |
| 160 | ko | 0.529 | 0.581 |
| 160 | ja | 0.781 | 0.876 |
| 160 | zh | 0.822 | 0.884 |
| 160 | es | 0.775 | 0.814 |
| 160 | de | 0.762 | 0.844 |
| 1000 | en | 0.641 | 0.673 |
| 1000 | ko | 0.485 | 0.548 |
| 1000 | ja | 0.742 | 0.781 |
| 1000 | zh | 0.785 | 0.829 |
| 1000 | es | 0.736 | 0.761 |
| 1000 | de | 0.729 | 0.804 |
| 10000 | en | 0.621 | 0.655 |
| 10000 | ko | 0.492 | 0.547 |
| 10000 | ja | 0.759 | 0.790 |
| 10000 | zh | 0.770 | 0.807 |
| 10000 | es | 0.756 | 0.763 |
| 10000 | de | 0.751 | 0.788 |

The Chinese author-level R@5 losses at 10,000 notes are also explicit:

| Author | R@5: core -> semantic |
|---|---|
| claude-fable-5.1 | **0.867 -> 0.844** |
| gpt-6.1-sol | **0.822 -> 0.800** |

### Where semantic mode falls below the core

**The mode is opt-in and is not the recommended default.** The bar was
"no slice below the core". It misses that bar on the test split in one
pooled slice, three author slices and six language x kind cells. The pooled
Chinese and author losses are above; every language x kind loss is below.
`mixed` means code-switched; `para` means low-overlap paraphrase.

| Notes | Language / kind | MRR: core -> semantic | R@5: core -> semantic |
|---|---|---|---|
| 160 | ja / mixed | **0.896 -> 0.886** | 0.970 -> 0.970 |
| 160 | zh / mixed | **0.917 -> 0.905** | **0.978 -> 0.956** |
| 1000 | ja / mixed | **0.865 -> 0.826** | 0.970 -> 0.970 |
| 10000 | ja / mixed | **0.880 -> 0.859** | 0.970 -> 0.970 |
| 10000 | zh / mixed | **0.875 -> 0.860** | 0.911 -> 0.911 |
| 10000 | zh / para | 0.418 -> 0.487 | **0.556 -> 0.533** |

The configuration passed the dev gate, was frozen before this test run and
was not retuned afterward. Exact keyword queries keep their lexical order;
no exact query moved at any corpus size. Turn semantic mode on when questions
are usually worded differently from the notes; leave it off when lookups are
mostly keywords.

### Footprint

Latest main replay on **2026-10-11**, Linux x86_64/WSL2, Python 3.14.4;
not service-level guarantees. Every arrow is **core -> semantic**. Install
size is **0.38 MB -> 80.24 MB**, excluding the model files. The pinned raw
model files are **531.0 MB**, the compact model **138.1 MB**, together
**669.1 MB** (decimal MB). The Hugging Face cache is `$HF_HUB_CACHE`, or
`$HF_HOME/hub`, or `~/.cache/huggingface/hub`; compact files are under
`$MNEMOSYNE_MODEL_CACHE` or `~/.cache/birkin-mnemosyne`. Newer Hugging Face
versions can share blobs outside the model folder, so deleting that folder
alone is not a reclaim-size guarantee; use its cache-management tools.
The prepared model and vectors sidecar record the pinned model revision.
The original additional-memory budget was 150 MB; the largest measured
indexing addition here is **163 MB**, exceeding it on this platform.
The slowest semantic start is **617 ms** with the model prepared, below the
original 1 s target in this run.

#### Index and memory

| Notes | Index on disk | RSS: search | RSS: indexing |
|---|---|---|---|
| 160 | 0.06 MB -> 0.08 MB | 21 -> 59 MB | 22 -> 185 MB |
| 1000 | 0.33 MB -> 0.42 MB | 26 -> 64 MB | 34 -> 196 MB |
| 10000 | 3.22 MB -> 4.03 MB | 81 -> 120 MB | 157 -> 298 MB |

#### Start-up and latency

| Notes | Start-up median (max) | p50 | p95 |
|---|---|---|---|
| 160 | 53 ms (62) -> 211 ms (260) | 0.1 -> 0.9 ms | 0.2 -> 1.7 ms |
| 1000 | 82 ms (94) -> 234 ms (254) | 0.2 -> 2.8 ms | 0.4 -> 4.1 ms |
| 10000 | 366 ms (395) -> 570 ms (617) | 1.3 -> 25.2 ms | 3.7 -> 33.0 ms |

RSS is peak in separate fresh search/build processes spawned by a small
standard-library-only parent. Start-up includes interpreter start, import,
index load and first query: 10 processes per cell. Warm latency uses the first
300 frozen test queries; index size is measured after that run. These are
separate measurements from quality-run latency (dev + test pooled). The
quality runner's Linux RSS can inherit its parent's earlier high-water mark,
so those RSS/timing fields in `main_test_run.json` are **not** the reference;
use `main_footprint.json` and RESULTS.md. Latency grows with vault size and
machine load; platform and methodology differ from the historical macOS run.

## Honest limits

- **Earlier tokenizer experiments did not establish a Korean recall gain.** The earlier macOS
  tokenizer run measured MRR **0.569**
  at 10,000 notes; the latest Linux core replay is **0.557**. These are
  separate measurements, not an isolated cross-platform comparison.
  English stems also match English distractors for code-switched Korean questions; Korean
  tokenization itself is unchanged. Stem reweighting traded English for
  Korean, and a minority-script boost hurt independently authored mirror
  questions. Neither was shipped: see
  [Code-switched queries in the core](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/benchmarks/retrieval/RESULTS.md#code-switched-queries-in-the-core-measured-not-changed).
- **This is a synthetic personal-scale benchmark.** It does not establish
  superiority over other memory projects, answer accuracy, or universal
  multilingual coverage. Low-overlap paraphrases remain difficult for the
  lexical core. Scripts with combining vowel signs, such as Devanagari and
  Thai, are split at those signs by the current tokenizer.
- **Query expansion is only as good as its writer.** The expansion numbers
  come from model-written questions and model-written expansions. With one of
  the two writers, code-switched questions about Spanish and German notes fell
  about 0.05 MRR below the core, because it answered in English and Korean.
  Each widened search costs the host about 115-200 output tokens and about
  twice the ranking time.
- **Semantic results can be irrelevant.** With the mode on, even a query
  without a lexical match receives semantic candidates; there is no relevance
  floor. Tokenizer equivalence was checked on this benchmark only, and memory
  in a long-lived process with varied CJK text was not measured. Current footprint
  measurements cover Linux x86_64/WSL2 only; historical ones cover macOS arm64.
- **Compression has a write cost.** Saving recompresses the whole index;
  loading briefly holds compressed and decoded text together. Mixing older
  and newer library versions on a vault causes repeated cache rebuilding.
  Index cache writes after single-note changes are coalesced (at most one
  every 2 seconds, plus a flush at exit); after a crash the cache is rebuilt
  from the note files on the next refresh.
- **Curation safety is narrower than correctness.** The executor bounds file
  operations; model choice still affects placement and linking quality.
  Python's explicit `purge_expired()` maintenance call can delete expired
  notes and is not exposed over MCP.
- The earlier LongMemEval retrieval and end-to-end QA harnesses are **not yet
  public** in this repository. Their numbers are omitted here. The companion
  paper is not a substitute for a committed reproduction harness.

## Reproduce the benchmark

Core (no optional runtime dependencies):

```bash
python benchmarks/retrieval/bench_retrieval.py --sizes 160 1000 10000 --install-size
```

`--install-size` needs network access: it builds and installs the package
into a fresh virtual environment (with uv when `uv` is on PATH, otherwise
pip) to measure the footprint. Offline, run the same benchmark without it:

```bash
python benchmarks/retrieval/bench_retrieval.py --sizes 160 1000 10000
```

Search-time query expansion, replaying the committed expansions of two
writers (no model call, no optional dependency):

```bash
python benchmarks/retrieval/bench_retrieval.py --engines bm25 expanded-claude expanded-gpt --sizes 160 1000 10000 --json run.json
python benchmarks/retrieval/compare.py run.json run.json --engine-before bm25 --engine-after expanded-claude
```

Semantic mode uses `minishlab/potion-multilingual-128M` static embeddings,
with no transformer at query time. Install the extra and explicitly prepare
its model once:

```bash
pip install "birkin-mnemosyne[semantic]"
python -m birkin_mnemosyne.semantic
```

Opt in with `Mnemosyne(vault, semantic=True)` or `MNEMOSYNE_SEMANTIC=1`.
Search never downloads or converts a model. If requested with the extra
missing or the model unprepared, search uses the core ranking and logs one
line explaining why. Semantic chunks are fused with lexical ranking;
full lexical matches stay first and fused ties use lexical rank.

From a checkout with the model prepared:

```bash
python benchmarks/retrieval/bench_retrieval.py --engines bm25 hybrid --sizes 160 1000 10000 --json run.json --install-size --install-extras semantic
python benchmarks/retrieval/compare.py run.json run.json --engine-before bm25 --engine-after hybrid
```

The committed quality run is
[main_test_run.json](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/benchmarks/retrieval/main_test_run.json).
The separately measured reference footprint is
[main_footprint.json](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/benchmarks/retrieval/main_footprint.json):

```bash
python benchmarks/retrieval/measure_footprint.py --output footprint-main.json
```
See RESULTS.md for the full query-kind tables, query counts, rejected ideas
and footprint methodology. Additional checks and offline examples:

```bash
pytest -q                                # MCP, semantic and static-model suites skip
                                         # without [mcp] / [semantic]; output names them
python examples/quickstart.py            # write, search, decay
python examples/automatic_profiles.py    # profile review and persistence
python benchmarks/bench_safety_matrix.py # defense-layer ablation
python benchmarks/bench_korean_embed.py  # embedding baseline; needs [bench]
```

## CurationPlan/1: bounded curation with any model

A model proposes typed JSON operations (rezone, link, supersede, archive);
a deterministic executor validates, clamps, applies and audits them. The
curation schema has no delete operation: archive moves a note. Archives are
capped per pass using `ARCHIVE_CAP_MIN` and `ARCHIVE_CAP_FRACTION` of active
notes; negative-polarity warnings and control notes are protected. Every move
stays inside the vault, `_archive` is not an active zone, and free-text
summaries are inert rather than control signals. Unparseable output becomes
an empty plan. Placement is model judgment; linking co-placed notes is
mechanical. Schema validation alone does not prevent mass archiving; the
executor's clamp limits each call, so repeated calls can archive more (archives
stay reversible). Path containment and slug lookup also protect the
lower-level file operations.

```python
from pathlib import Path

from birkin_mnemosyne import Mnemosyne, run_curation_pass, get_completer

vault = Path("my_vault")
mem = Mnemosyne(vault)
mem.refresh()
hits = mem.search("kubernetes ingress dns")

# the vault argument must be a pathlib.Path
outcome = run_curation_pass(vault, get_completer("codex"), provider="codex")
# Or pass your own complete(prompt: str) -> str callable.
```

For openclaw, hermes or your own loop, expose `mem.search(query)` as a recall
tool, call `mem.record_access(note_slug)` for notes actually used, and pass
your existing model client to `run_curation_pass(vault_path, my_complete,
provider="custom")`. It returns a `CurationOutcome` with accepted/dropped
operations, archive cap and audit summary. Already have a plan as data?
`evaluate_plan(vault_path, plan)` runs the same gate as a dry run; pass
`apply=True` to apply it.

| Provider | Invocation | Plan constraint |
|---|---|---|
| `claude` | `claude -p`, empty tool allow-list | prompt-specified |
| `codex` | `codex exec --sandbox read-only --output-schema` | enforced JSON schema |
| `api` | Anthropic Messages API via stdlib `urllib` | prompt-specified |
| `gemini` | `gemini -p -`, CLI defaults | prompt-specified |
| `local` | `ollama run <model>` | prompt-specified |

## MCP server (Claude Code, Claude Desktop, Codex CLI, Cursor)

The vault can be served over the [Model Context Protocol](https://modelcontextprotocol.io)
so any MCP client can remember, recall and curate. The server is an optional
extra — the core library stays stdlib-only — and runs with one command over
stdio:

```bash
uvx --from "birkin-mnemosyne[mcp]" \
    mnemosyne-mcp --vault ~/mnemosyne
```

(or `pip install "birkin-mnemosyne[mcp]"`
and run `mnemosyne-mcp`). The first launch downloads the SDK; if your client
times out on that first start, run the command once in a terminal.

| setting | how |
|---|---|
| vault directory | `--vault PATH`, else `$MNEMOSYNE_VAULT`, else `~/.birkin-mnemosyne/vault` |
| require a `source` for new notes | `--evidence-required` or `MNEMOSYNE_EVIDENCE_REQUIRED=1` |
| identity/startup read root | `--identity-root PATH`, else `$MNEMOSYNE_IDENTITY_ROOT`, else the vault; `memory_identity_read` and `memory_startup_*` can read files under this root (paths are confined to it); point it at a directory that holds only files you want an agent to read |
| protected-note budget (default 1000, `0` = no limit) | `--max-protected-notes N` or `MNEMOSYNE_MAX_PROTECTED_NOTES=N` |
| active-note byte budget (default 104857600, `0` = no limit) | `--max-vault-bytes N` or `MNEMOSYNE_MAX_VAULT_BYTES=N` |

**Claude Code**

```bash
claude mcp add --scope user mnemosyne -- \
  uvx --from "birkin-mnemosyne[mcp]" \
  mnemosyne-mcp --vault ~/mnemosyne
```

**Claude Desktop** (`claude_desktop_config.json`) and **Cursor**
(`~/.cursor/mcp.json` or `.cursor/mcp.json`) use the same shape:

```json
{
  "mcpServers": {
    "mnemosyne": {
      "command": "uvx",
      "args": [
        "--from", "birkin-mnemosyne[mcp]",
        "mnemosyne-mcp", "--vault", "~/mnemosyne"
      ]
    }
  }
}
```

**Codex CLI** (`~/.codex/config.toml`, or `codex mcp add mnemosyne -- uvx ...`):

```toml
[mcp_servers.mnemosyne]
command = "uvx"
args = ["--from", "birkin-mnemosyne[mcp]",
        "mnemosyne-mcp", "--vault", "~/mnemosyne"]
```

Point several clients at the same `--vault` to share one memory; writes are
serialized across server processes with a lock file.

### Use from IDEs

IDE agents that support local **stdio MCP** can use the same vault. Install
`birkin-mnemosyne[mcp]` in a dedicated virtual environment first, then point the
IDE at that environment's Python. For example, VS Code's `.vscode/mcp.json`:

```json
{
  "servers": {
    "mnemosyne": {
      "type": "stdio",
      "command": "/absolute/path/to/mnemosyne-venv/bin/python",
      "args": ["-m", "birkin_mnemosyne.mcp_server"],
      "env": {"MNEMOSYNE_VAULT": "/absolute/path/to/memory-vault"}
    }
  }
}
```

Replace both paths. On Windows, use the venv's `Scripts/python.exe`; forward
slashes work in JSON paths. Keep a path containing spaces as one JSON value,
without adding shell quotes inside it. Enable the server and approve its tools
in your IDE.

PyPI 0.6.0 and main at `876ad40` passed official MCP SDK stdio checks on macOS
and Windows, including search and complete startup reads. A real omo agent
also called both tools inside Herdr. These checks do **not** claim an actual
launch in every IDE. See the [client matrix, exact configuration variants and
official sources](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/docs/ide-compatibility.md)
for Cursor, JetBrains, Zed, Windsurf, Antigravity, Orca and CLI agents.
Here, Orca means the [Orca IDE](https://www.onorca.dev/docs): configure the
MCP-capable agent it launches in the active worktree, not an invented
Orca-specific MCP file.

### Tools

| tool | what it does | safe default |
|---|---|---|
| `memory_search` | BM25 + decay + zone ranked hits with snippets; optional `labels` (AND) require every label before ranking; `synonyms` / `keywords` / `related` / `note_line` widen the query | read-only |
| `memory_get_note` | full note with its `version`; counts as a use | — |
| `memory_list` | notes by zone, paginated; optional `labels` (AND) filter before pagination, `label_counts` cover the full eligible set | read-only |
| `memory_remember` | write a note: `mode="create"` / `"append"` / `"replace"`; optional `labels` (`None` keeps/infers, `[]` clears) | `create` never overwrites; `replace` needs `expected_version` |
| `memory_related` | mechanical link candidates for a note | read-only |
| `memory_forget` | move a note to `_archive` through the curation gate | dry run unless `confirm=true`; never deletes |
| `memory_restore` | move a note back out of `_archive` | — |
| `memory_curation_catalog` | structured catalog for writing a CurationPlan | read-only |
| `memory_curate` | run a CurationPlan/1 through the deterministic gate | dry run unless `apply=true` |
| `memory_review_questions` | list possible duplicate, overlapping or conflicting note pairs as questions for the user | read-only |
| `memory_review_apply` | apply one explicit user answer to a review question (`drop-*` archives a note, `merge` writes the approved body); journals both original byte images | dry run unless `confirm=true` |
| `memory_review_undo` | restore the byte-exact originals of a review transaction if every post-image is unchanged | dry run unless `confirm=true` |
| `memory_identity_read` | read SOUL/AGENTS-style Markdown under the identity root as a catalog, ranked sections, one section, or the full file | read-only |
| `memory_kibitzer_candidates` | ranked live note candidates for a query, with short excerpts; archive, system and expired notes are skipped | read-only |
| `memory_startup_read` | read startup files (and the local files they MUST READ) under the identity root completely, with coverage checks | read-only |
| `memory_startup_verify` | re-read the same files and verify a returned startup context against them | read-only |
| `memory_handoff_capture` | persist an immutable project/task checkpoint with all six handoff fields | identical capture-ID retries reuse the original |
| `memory_handoff_read` | latest scoped capture, active count and size warnings | read-only |
| `memory_handoff_fold` | curation-gated dated summary and archive, with existing journal undo | preview unless `apply=true` and a fresh `plan_id` |
| `memory_index_register` | add one `trigger -> document` mapping to the always-loaded INDEX; additive and idempotent, no remove or delete | additive write |
| `memory_index_read` | read all INDEX entries or one complete topic, without a ranked cutoff | read-only |
| `memory_open_trigger` | open the documents an exact trigger points to; fall back to ordinary search | read-only |
| `memory_index_check` | audit the always-loaded INDEX for orphans, dangling routes and coverage errors, without writing | read-only |
| `memory_index_split` | preview or apply a lossless split of one note into routed topic documents | preview unless `apply=true` |
| `memory_capacity` | active and protected note counts and index bytes against the budget | read-only |

Plus the resources `mnemosyne://digest` (the prompt digest) and
`mnemosyne://note/{slug}`, and the prompt `curate_vault`. The calling agent is
the curator: it reads the catalog, writes a plan, and `memory_curate` clamps it
exactly like `run_curation_pass` would — protected notes stay put and the
archive cap is recomputed for each call, so repeated calls can archive more.
Forget and curation only archive notes. `memory_review_undo` restores original
bytes and withdraws a moved archive into retained private snapshots, refusing
changed or racing images; `purge_expired` stays a Python-only
maintenance call. Note text returned
by the tools is stored data from earlier sessions; the server tells clients
not to follow instructions found inside it.

**Capacity.** The protection rule is unchanged: negative-polarity,
identity/preference and filed + linked notes stay out of reach of
`memory_forget` and `memory_curate`. So that protected memory cannot grow
without bound, the server compares the active vault with a budget (the two
settings above; an invalid value stops the server at start). Over budget,
`memory_capacity` and `memory_remember` (`capacity_warning`) say so, and
`memory_review_questions` adds `retire_questions` for the oldest, least-used
protected notes, which the agent must ask the user (`keep` or `retire`).
Nothing is ever deleted automatically: `retire` archives the note through the
journaled `memory_review_apply` path, and `memory_review_undo` restores it.
When neither capacity nor INDEX warnings apply, existing clients see no new
keys. An INDEX token warning can attach a capacity report without retirement
questions or choices; it does not mean the note-count or byte budget is exceeded.

## Automatic role profiles

`ProfileMemory` records a conversation exchange immediately and reviews it on
one owned background worker. The reviewer returns JSON; `flush()` is the
durability boundary and surfaces malformed reviewer output.

```python
import json
from birkin_mnemosyne import ProfileMemory

def review(exchange):
    # Replace this deterministic example with your model client.
    return json.dumps({"profiles": {
        "preferences": "Prefers evidence before conclusions.",
        "soul": "Use direct Korean.",
    }})

with ProfileMemory(vault_path, review) as profiles:
    profiles.record_exchange(user_message, assistant_message)
    profiles.flush()
```

The `system/` directory, owned by `ProfileMemory`, contains exactly five role
files (the curation gate does not special-case them):

| File | Guidance stored |
|---|---|
| `user.md` | User characteristics and stable personal context |
| `preferences.md` | Preferences and favored choices |
| `soul.md` | Conversation style and interaction guidance |
| `workflow.md` | Work process and execution guidance |
| `automation.md` | Workflow automation guidance |

By default, `ProfileMemory(vault_path, review)` bootstraps those files and
appends de-duplicated guidance lines. If you pass `save=callable`, no `system/`
directory or files are created; each reviewed exchange is parsed into a tuple of
`ProfileProposal` objects and delivered to that sink for caller-owned
persistence. Sink-mode instances cannot `read_profiles()` because they own no
files.

The reviewer contract is a JSON object with one `profiles` object. Profile keys
must be from the table. Values may be legacy non-empty strings, which become
`add` proposals after whitespace normalization, or ordered proposal lists such
as `[{"action":"replace","old_text":"old","content":"new"}]`. Actions are
`add`, `replace`, or `remove`; malformed JSON, unknown keys/actions, non-string
fields, and missing required text raise `ProfileReviewError` through `flush()`.
`close()` stops new submissions and releases the worker; the context manager
flushes and closes automatically. Run `python examples/automatic_profiles.py`
for an offline end-to-end example.

## API surface

```python
from birkin_mnemosyne import (
    Mnemosyne,          # the mechanical index/ranking engine
    MemoryIndex,        # the opt-in always-loaded memory INDEX
    StartupReader,      # verified host startup reads, with task-bound complete reads
    HandoffStore, HandoffScope, HandoffFields,  # immutable scoped session checkpoints
    VaultMemory,        # ergonomic write_note / rezone / digest wrapper
    ProfileMemory,      # background-reviewed role-profile persistence
    ProfileReviewError, # invalid reviewer output
    run_curation_pass,  # the safe curation driver
    evaluate_plan,      # gate a structured plan (dry run by default)
    get_completer,      # provider registry (claude|codex|api|gemini|local)
    validate_clamp,     # the gate, if you want to inspect a plan without applying
    build_plan_prompt, extract_plan, mechanical_catalog,
    slug, tokenize, bm25_scores,
    KibitzerAdapter,    # Kibitzer-shaped recall; select_crosslingual() is opt-in
    opengateway_decider, translate_views, RerankError,  # hosted reranking parts
)
```

Key `Mnemosyne` methods: `refresh()`,
`search(query, limit=8, zone=None, expansions=None, labels=None)`,
`related(slug)`, `record_access(slug)`, `stale()`, `rezone(slug, zone)`,
`zone_priorities()`, `stats()`.

## Vault layout and configuration

Notes are slug-named Markdown files with YAML frontmatter and `[[wikilinks]]`.
Zones are complete relative directory paths; the vault root is the inbox.

```text
my_vault/
  inbox-note.md
  devops/
    ingress-dns.md
  people/
  projects/
    Active Work/
      roadmap.md
  identity/
  knowledge/
  journal/
  system/                       # role files owned by ProfileMemory
  _archive/                     # soft-forgotten notes
    projects/Active Work/       # archive moves retain the original parent
  .mnemosyne-memory-index/       # opt-in; index.json routing and the resident context map
  .mnemosyne-handoffs/           # immutable scoped captures, summaries, archives and opt-in settings
  .mnemosyne-index.json.z        # rebuildable compressed index cache
  .mnemosyne-dynamics.json       # persistent usage state
  .mnemosyne-vectors.npz         # rebuildable semantic vector cache
  .mnemosyne-reviews/            # review undo journal (<transaction-id>.json)
  .mnemosyne-mcp.lock            # cross-process writer lock
```

Discovery is recursive by default. Hidden files and directories (including
`.git` and `.obsidian`), `node_modules`, `__pycache__`, symlinks and Windows
reparse points are not followed. Filename stems remain note keys: if several
files share a stem, the newest modification time wins and a warning names
the collision. Equal timestamps select the lexicographically smallest POSIX
relative path. INDEX routes remain exact paths rather than stem keys.

For example, `zone="projects/Active Work"` selects that complete parent for
writes and zone-filtered search. Nested and human-named folders retain their
spelling; legacy simple names still normalize (`"Projects"` to `"projects"`).
Absolute, drive/UNC, traversal, backslash and hidden/cache paths are refused,
as are Windows-invalid filename characters and trailing dots/spaces.
Writes, moves and journal operations also refuse linked destination files
or parent folders, including Windows reparse points.

Archiving `projects/Active Work/roadmap.md` moves it to
`_archive/projects/Active Work/roadmap.md`. Archive components at any depth,
case-insensitively, are excluded from active views; `zone="_archive"` searches
the archive tree. MCP `memory_restore` still defaults to the inbox; pass
`zone="projects/Active Work"` to choose the nested parent. Journal undo
restores the original path and bytes and refuses changed post-images.

The index cache, the vectors file and the lock file are safe to delete only
while no Mnemosyne process is using the vault. The caches are rebuilt
automatically (without the vectors file, the next semantic search re-embeds the
whole vault) and the lock file is recreated, but deleting the lock file while
another process holds it breaks mutual exclusion on Linux and macOS. Keep the
lock file and the vectors file out of git and file sync. Keep
`.mnemosyne-dynamics.json` (usage history) and `.mnemosyne-reviews/` (needed to
undo review answers) when backing up or syncing a vault.

`VaultMemory({"vault_path": "my_vault"})` selects the vault. The legacy `vault`
configuration key is also accepted; without either key the default is
`./vault`. `Mnemosyne` takes the path directly. Set `zone=` when writing to
choose placement; otherwise note types map to zones:

| Note type | Default zone |
|---|---|
| `person` | `people` |
| `project` | `projects` |
| `preference` | `identity` |
| `fact`, `topic` | `knowledge` |
| `session` | `journal` |

`_archive` is not an active curation zone. The cache can be rebuilt without
discarding usage state; the legacy `.mnemosyne-index.json` cache is removed on
the next save. Mixing older and newer library versions on one vault causes
repeated cache rebuilding. MCP path and evidence settings are listed in the
[MCP server reference](#mcp-server-claude-code-claude-desktop-codex-cli-cursor).

## Upstream contributions

Gwanghoon started this work because he was unhappy with how agent harnesses
and agent memory handled Korean. He ran an agent team to investigate the
gaps, test changes and contribute fixes upstream rather than keep them only
in his own setup. Findings from birkin-mnemosyne's retrieval work and its
memory adapters became contributions to the projects below.

These are contributions authored by `ashmoonori-afk` to **other repositories
that derive from birkin-mnemosyne**, with their source links and status as of
**2026-10-11 KST**. Internal birkin-mnemosyne PRs and unrelated harness work
are excluded. Open proposals are not shipped improvements, and approval does
not mean merged. Closed work is labeled explicitly. The linked retrieval
gains use synthetic benchmarks, not guarantees for real conversations.

| Project | Contribution | Status | How it improves that project, or what is proposed | Basis in birkin-mnemosyne and Korean relevance |
|---|---|---|---|---|
| oh-my-openagent | [PR #9209](https://github.com/code-yeongyu/oh-my-openagent/pull/9209) | Merged | Recall automatically uses CJK-aware BM25 or hybrid ranking so inflected and unsegmented queries can find notes that substring matching missed, with English recall guards added during maintainer review. | The PR explicitly credits birkin-mnemosyne's Korean-aware bigram BM25 approach; Korean inflections, Japanese and Chinese benefit. |
| oh-my-openagent | [PR #9341](https://github.com/code-yeongyu/oh-my-openagent/pull/9341) | Merged | Recall matches individual Han characters and shows matching excerpts, helping Chinese and Japanese kanji queries find notes through shared characters. | Ports the Han-character finding from birkin-mnemosyne's tokenizer work and benchmark; Korean hanja is covered, ordinary Hangul behavior unchanged. |
| oh-my-openagent | [PR #9342](https://github.com/code-yeongyu/oh-my-openagent/pull/9342) | Merged | Optional weighted synonyms, keywords and related terms help recall find differently worded notes while keeping exact matches first; it is off by default and falls back to plain recall for invalid expansions. | Adapts query expansion first measured in birkin-mnemosyne; Korean paraphrase gains were measured, but expansions cost tokens and some mixed-language queries regress. |
| oh-my-openagent | [PR #9275](https://github.com/code-yeongyu/oh-my-openagent/pull/9275) | Closed; split into #9341 and #9342 | The combined Han-matching and query-expansion proposal became two focused PRs that subsequently merged; this closed PR did not ship independently. | Both parts derive from birkin-mnemosyne's tokenizer and retrieval experiments, including Korean query expansion. |
| Hermes Agent | [PR #131586](https://github.com/NousResearch/hermes-agent/pull/131586) | Merged | The community catalog now offers an external memory provider with a pinned source version, local Markdown storage and a separate vault per Hermes profile. | Catalogs birkin-mnemosyne's Hermes adapter, making multilingual memory available without a Korean-specific core change. |
| HOL Guard | [PR #3441](https://github.com/hashgraph-online/hol-guard/pull/3441) | Approved; still open | Proposes an initially disabled MCP contribution with permission disclosures and review defaults for note mutations, so users can opt into local memory under Guard's policies. | Registers the published birkin-mnemosyne MCP server and its actual tool permissions; not a Korean-specific Guard fix. |
| OpenClaw | [PR #163588](https://github.com/openclaw/openclaw/pull/163588) | Open | Proposes Python stdio bundle guidance covering dependencies, the Gateway service's PATH, persistent data and actual agent-session verification, rather than treating bundle detection as proof of execution. | Derived from exercising birkin-mnemosyne's Python MCP bundle in OpenClaw; generic setup guidance, not a new core memory backend or Korean-specific fix. |
| Awesome Agent Memory | [PR #122](https://github.com/TeleAI-UAGI/Awesome-Agent-Memory/pull/122) | Closed; [landed by hand](https://github.com/TeleAI-UAGI/Awesome-Agent-Memory/commit/e5755368c00e4d21289c197e773966b6e6ed28a7) | The maintainer added a local Markdown memory option to Emerging projects with co-authorship preserved, helping readers discover its retrieval and bounded curation. | The accepted birkin-mnemosyne listing explicitly describes Korean bigrams. |

## Credits

Extracted from the [Birkin](https://github.com/ashmoonori-afk/birkin) personal
agent. The CJK-bigram BM25 approach was adopted by oh-my-openagent's memory
recall in [PR #9209](https://github.com/code-yeongyu/oh-my-openagent/pull/9209),
written by the same author. The lexical tie-break and keeping full lexical
matches first follow that PR's review.

The hero image was AI-generated (ChatGPT image generation).

Local file memory, memory palaces, BM25, Ebbinghaus forgetting and
plan-then-execute safety have prior art; the individual ingredients are not
new. birkin-mnemosyne combines a standard-library lexical substrate with
provider-portable, plan-only curation bounded by code. It is unrelated to the
concurrent graph-memory project sharing the mythological name. The Python
package imports as `birkin_mnemosyne`.

## License

MIT; see [LICENSE](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/LICENSE) and [NOTICE](https://github.com/ashmoonori-afk/birkin-mnemosyne/blob/main/NOTICE).
