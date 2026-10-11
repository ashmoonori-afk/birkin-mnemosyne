# Changelog

## Unreleased

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

- First-run `mnemosyne init` through the existing INDEX CLI dispatcher.
  The default offline plan scans visible Markdown and optional external
  imports without writing files, reports existing review candidates, and
  shows deterministic topic catalogues and complete additive INDEX routes.
- Explicit `--apply` supports empty-vault INDEX enablement, conservative
  frontmatter completion through byte-exact journal/undo, safe reruns,
  retained existing aliases, resident startup verification and drift warnings.
  Original information is never automatically merged, archived or deleted;
  split-receipt bytes and ambiguous headers remain unchanged.
