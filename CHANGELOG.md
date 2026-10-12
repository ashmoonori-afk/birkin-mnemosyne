# Changelog

## Unreleased

### Added

- Read-only `mnemosyne search`, `list` and `show` print the same JSON fields as
  the MCP `memory_search`, `memory_list` and `memory_get_note` tools without
  recording a use or changing usage ranking.
- `mnemosyne undo --transaction ID` undoes an `init --apply`, fold or review
  transaction through the existing checked journal (`handoff undo` remains).
- `mnemosyne --version`, matching `mnemosyne-mcp --version`.
- `init` JSON output names the resolved absolute `vault`.

### Fixed

- `memory_startup_read` and `memory_startup_verify` no longer require `paths`,
  so the documented resume call with only project/task keys (or only `task`)
  works. Reads with nothing to read still fail with the existing message.
- Every `mnemosyne` command resolves its vault as `--vault`, then
  `$MNEMOSYNE_VAULT`, then the `mnemosyne-mcp` default
  `~/.birkin-mnemosyne/vault` (`init` keeps the current directory as its
  fallback). `check`, `split` and `handoff` no longer fail without `--vault`.
- `~` is expanded in `--vault`, `$MNEMOSYNE_VAULT` and `init --import`, so a
  quoted `~/mnemosyne` no longer creates a literal `~` directory.

## 0.7.0 - 2026-10-11

### Fixed

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
- English and Korean retrieval, expansion, INDEX, task-read and footprint
  results now share fresh 2026-10-11 measurements with explicit source
  revisions and separate-corpus caveats.
- Heading-bounded BM25 chunks were evaluated at 1000, 2000 and 4000 body
  characters but are not included: the dev-selected candidate failed the
  declared held-out quality and language-slice gates. Whole-note indexing
  remains unchanged.
