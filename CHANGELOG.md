# Changelog

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
