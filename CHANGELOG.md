# Changelog

## 0.7.0 - 2026-10-11

### Fixed

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

- English and Korean retrieval, expansion, INDEX, task-read and footprint
  results now share fresh 2026-10-11 measurements with explicit source
  revisions and separate-corpus caveats.
- Heading-bounded BM25 chunks were evaluated at 1000, 2000 and 4000 body
  characters but are not included: the dev-selected candidate failed the
  declared held-out quality and language-slice gates. Whole-note indexing
  remains unchanged.
