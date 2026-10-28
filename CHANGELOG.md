# Changelog

## 0.8.0 - 2026-10-28

### Added

- Cross-language recall reranking: `KibitzerAdapter.select_crosslingual()` and
  `birkin_mnemosyne.crosslingual` (`opengateway_decider`, `translate_views`,
  `RerankError`), from #90. It takes the top-32 BM25 and TF-IDF cosine notes
  for the original and translated queries, scores them pointwise in packets of
  eight with a hosted judge, averages the scores to five, then orders the five
  by symmetric pairwise preference.
- `KibitzerAdapter.recall()` and the MCP tool `memory_kibitzer_candidates`
  rerank automatically when a judge is configured, through
  `MNEMOSYNE_RERANK_API_KEY` or `KibitzerAdapter(vault, decide=...)`.
  `MNEMOSYNE_RERANK_TRANSLATOR` adds English and Korean query views,
  `MNEMOSYNE_RERANK_TIMEOUT` sets seconds per request. The generic
  `OPENGATEWAY_API_KEY` does not enable it.
- `RecallResult` reports the `selector` used and the `fallback` reason; the
  MCP response gains a `fallback` field.

### Changed

- Judge requests run at most five at a time (they ran one at a time in #90),
  with results kept in input order. After the first failure, queued requests
  are cancelled.

### Safety

- Without a configured key nothing leaves the machine; `recall()` returns the
  BM25 ranking and logs one warning per adapter. A failed, timed-out or
  malformed judge or translation response returns the BM25 ranking with one
  warning, never a partial rerank. `MNEMOSYNE_RERANK=off` (or
  `recall(rerank=False)`) is an explicit off switch that sends nothing.
  `select()`, `search()` and the stdlib core still never call a model.

### Measurement

- Confirmed on an unseen holdout (research harness, October 25, 2026):
  initial-candidate Hit@5 rose from 298 to 1,028 of 1,432 six-language
  questions; equal-language macro 20.8% -> 71.8%, 3.45x, grouped 95% ratio
  interval 3.14-3.81. Every language and native subset passed the
  preregistered no-decline rule. Before scoring, two source questions whose
  translations failed the quality check were removed with all their copies,
  leaving 1,432 of 1,440 with unequal language counts.
- The earlier 2,400-question result (485 -> 1,602, 3.30x) reused questions
  during method selection and is selection evidence only.
- Judge cost averaged an estimated $0.0081 per query (not an invoice).
- Replaying all 58,498 saved holdout judge answers through this package's card,
  packet, merge and pairwise code gave the same five notes in the same order
  for 1,432 of 1,432 questions, every request byte-identical. Retrieval is not
  covered: the package uses its own tokenizer, the study the research
  retrievers.

## 0.7.2 - 2026-10-15

### Fixed

- Index every visible same-stem Markdown file instead of dropping all but one.
  The newest file retains the bare stem, with the existing sorted-path tie-break;
  other files use relative path keys. Writes, winner deletion and file renames
  refresh those keys without changing source files.
- Keep curation targets bound to their physical files across re-keying, return
  usable identifiers after MCP mutations, and attribute reads/writes to the
  actual note rather than another same-stem file.

### Measurement and release decision

- On 20,000 public round-two documents, heldout known-gold recall@2 improves
  from 270/1,011 to 537/1,011 (+26.41 percentage points; 274 gains, seven losses).
  The already-indexed development slice declines from 231/405 to 224/405.
- Independent source anchors show 28 gains and no losses (p=7.45e-9).
  The preregistered family interval was not computable because of singleton
  strata. The owner explicitly decided to ship on the paired evidence and
  waived that criterion; it is not claimed to have passed.
- Only the slug-indexing fix ships. The experimental ranking correction and
  taxonomy code remain excluded.

### Documentation

- Update English/Korean READMEs, release notes and both landing pages with the
  measured public aggregates, loss slice and statistical limitation.
- Align core 0.7.2 and the bundled plugin 0.2.3 install metadata.

## 0.7.1 - 2026-10-14

### Added

- Recursive vault discovery by default, including nested imports and folders
  with spaces or Unicode names. Hidden files/directories, dependency caches,
  symlinks and Windows reparse points are excluded. Duplicate filename stems
  select the newest file, with a warning; equal timestamps select the
  lexicographically smallest POSIX relative path.
- Complete relative zone paths across labels, INDEX routing, startup reads,
  curation and MCP. Archive moves preserve the original relative subpath;
  journal undo restores exact paths and bytes. MCP restore keeps its inbox
  default and accepts an explicit nested destination.
- Repeatable `--label namespace:value` filters for CLI `search` and `list`,
  matching MCP AND semantics before ranking, pagination and label counts.
- Read-only `mnemosyne search`, `list` and `show` print the same JSON fields as
  the MCP `memory_search`, `memory_list` and `memory_get_note` tools without
  recording a use or changing usage ranking.
- `mnemosyne undo --transaction ID` undoes an `init --apply`, fold or review
  transaction through the existing checked journal (`handoff undo` remains).
- `mnemosyne --version`, matching `mnemosyne-mcp --version`.
- `init` JSON output names the resolved absolute `vault`.

### Fixed

- Nested writes, moves and journal archive/undo refuse symlink or Windows
  reparse-point destinations and parent folders, preserving the source
  rather than following a link into another directory.
- Archived descendants, including case-variant archive components, stay out
  of active search, rendering, catalogs and curation limits. Nested rezone
  targets cannot bypass archive protection or caps.
- Path-bound consolidation answers validate the offered document rather
  than an unrelated duplicate-stem winner.
- Corrupt INDEX state still reports inventory and errors, but no longer
  classifies documents as orphaned when their routes cannot be read.
- Supported source extensions are recognized case-insensitively across recall,
  onboarding, imports, INDEX checking and splitting without renaming originals.
- Hidden Markdown files inside visible zones no longer enter ordinary recall.
- Curation inserts links into the actual Related section, respecting later
  sections, fenced examples and setext headings.
- INDEX token warnings no longer offer memory-retirement choices unless
  active-note or protected-note capacity is actually exceeded.
- Atomic writes use a short temporary sibling name instead of repeating the
  destination basename, so valid long paths do not fail during staging.
  Persistent handoff names and identifiers are unchanged.
- MCP startup reports invalid vault paths on stderr without a traceback or
  protocol output. Explicit budget flags override malformed values in the
  corresponding environment variables; unrelated invalid settings still fail.
- `memory_startup_read` and `memory_startup_verify` no longer require `paths`,
  so the documented resume call with only project/task keys (or only `task`)
  works. Reads with nothing to read still fail with the existing message.
- Every `mnemosyne` command resolves its vault as `--vault`, then
  `$MNEMOSYNE_VAULT`, then the `mnemosyne-mcp` default
  `~/.birkin-mnemosyne/vault` (`init` keeps the current directory as its
  fallback). `check`, `split` and `handoff` no longer fail without `--vault`.
- `~` is expanded in `--vault`, `$MNEMOSYNE_VAULT` and `init --import`, so a
  quoted `~/mnemosyne` no longer creates a literal `~` directory.

### Documentation

- English and Korean installation and quick-start examples use the published
  0.7.1 package rather than requiring a checkout for the terminal commands.
- English and Korean landing pages describe nested folders and read-only
  terminal inspection, with the existing measurement limits retained.
- Hermes plugin 0.2.2 pins core 0.7.1 through its matching manifests and
  documented plugin-manager installation. OpenClaw's install example also
  pins core 0.7.1.

## 0.7.0 - 2026-10-11

### Fixed

- Label annotation preserves receipt-bound split sources and topic documents,
  including explicitly requested paths and sources restored by undo. Apply
  revalidates coverage authority under the vault lock before changing notes.
- Pure journal moves and undo preserve late-arriving files and retain checked
  private snapshots instead of replacing or unlinking an unverified image.
- Scoped startup requires the INDEX even when a fresh reader has never seen
  its marker; losing the INDEX cannot silently downgrade a handoff startup.
- Installed-wheel CLI checks no longer prepend the checkout to subprocess
  imports (#66). Every INDEX CLI test subprocess verifies that its package
  origin matches the parent's interpreter before running the real command,
  so checkout or working-directory shadow packages fail provenance checks.
- Review merges and checked undo now work on filesystems without hard links
  (#65). Exclusive copies verify their complete bytes and destination identity
  after file synchronization, retaining original captured inodes and refusing
  to overwrite arrivals. A copy in progress can be visible to readers; an
  incomplete or changed publication remains `recovery-required`, with its
  original capture preserved, rather than risking destructive rollback.

### Added

- Immutable project/task handoff captures through Python, CLI and MCP, with
  stable checkpoint IDs, complete verified startup delivery and size warnings.
- Deterministic provider-free `namespace:value` note labels: readable,
  normalized labels inferred offline from metadata, typed wikilinks, real ISO
  dates, bounded script evidence and INDEX/path context — no model, clock or
  API credentials. Values keep their case while namespaces lower; manual
  labels and explicit `[]` stay user-owned, `None` keeps or infers only when
  absent, and explicit replacement/clearing are checked operations. Unknown
  Latin text is never assumed English.
- `mnemosyne label` previews or — with `--apply` — journals deterministic
  label annotation through the existing review journal: repeated `--path`
  restricts selection, repeated `--label` supplies an explicit replacement
  and `--clear-labels` clears. The JSON report exposes notes/changed counts
  and `label_counts`; the returned `undo_transaction` restores exact bytes
  through the shared `handoff undo --transaction`, refusing edited
  post-images. Generated catalogues, split receipts and managed handoffs are
  excluded; no-op applies write nothing.
- `init --import` accepts one external Markdown/text/JSON file or directory:
  Markdown keeps its original bytes, text/JSON become lossless fenced
  candidates, invalid JSON is retained with a warning, and invalid UTF-8,
  linked or ambiguous sources are refused before any plan. `--group-by-label
  <namespace>` optionally groups topic catalogues by a deterministic label
  value; reports carry a per-note `label_counts` histogram, manual labels are
  never overwritten and source files are never modified. Imported copies,
  catalogues and INDEX routes remain after undo (additive; only journaled
  byte edits revert).
- Label-aware recall and browsing: `Mnemosyne.search`, `Memory.search`, MCP
  `memory_search`/`memory_list` and Hermes
  `birkin_memory_search` accept `labels` with AND eligibility before any
  candidate cut or pagination; omitted/`[]` filters leave scores and ordering
  unchanged, returned hits expose stored labels, `memory_list` reports
  `label_counts` for the full eligible set, and malformed filters raise
  before lookup instead of broadening the search. Labels never become query
  words or ranking boosts; ordinary search keeps indexing root plus one zone
  level. MCP `memory_remember` accepts explicit labels on writes.
- Deterministic dated handoff folds through the existing curation gate, with
  archived originals, preview-bound apply, exact journal undo and checked replay.
- Opt-in Hermes session-end/pre-compression capture with stable project/task
  binding and complete scoped prefetch, including empty and unmatched queries.
- `init --enable-handoff` previews and explicitly enables session memory while
  retaining existing INDEX routes and handoff budgets.
- Task-bound startup reads return every lexically matched document in full
  and include complete topic views from one routing snapshot. Managed startup
  verification reports INDEX drift without removing routes.
- Resident INDEX rendering chooses a flat map or a complete two-level topic
  map, retaining every route and same-document alias. Budget warnings do not
  evict entries; topic expansion returns the complete registered view.
- First-run `mnemosyne init` through the existing INDEX CLI dispatcher.
  The default offline plan scans visible Markdown and optional external
  imports without writing files, reports existing review candidates, and
  shows deterministic topic catalogues and complete additive INDEX routes.
- Explicit `--apply` supports empty-vault INDEX enablement, conservative
  frontmatter completion through byte-exact journal/undo, safe reruns,
  retained existing aliases, resident startup verification and drift warnings.
  Original information is never automatically merged, archived or deleted;
  split-receipt bytes and ambiguous headers remain unchanged.

### Documentation

- English and Korean handoff usage, client-managed checkpoint conventions,
  init enablement, Hermes callbacks, archive recovery and a complete-context
  startup-cost estimate.
- English and Korean labeling usage: CLI preview/apply/replace/undo,
  label normalization and deterministic suggestions, external init imports
  with grouping, search/MCP AND filters and Hermes parameter examples,
  plus the measured label context cost (4,207 -> 4,303 UTF-8 bytes,
  1,052 -> 1,076 estimated tokens, `ceil(bytes/4)`) and the frozen
  candidate regression at `8b7ab156` (12 runs x 1,440 queries: every rank,
  metric and fixture hash unchanged on the labeled write path).
- English and Korean retrieval, expansion, INDEX, task-read and footprint
  results now share fresh 2026-10-11 measurements with explicit source
  revisions and separate-corpus caveats.
- Heading-bounded BM25 chunks were evaluated at 1000, 2000 and 4000 body
  characters but are not included: the dev-selected candidate failed the
  declared held-out quality and language-slice gates. Whole-note indexing
  remains unchanged.
