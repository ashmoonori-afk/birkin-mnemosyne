# Always-loaded memory INDEX: usage guide

These APIs are available from v0.6.0 (`pip install "birkin-mnemosyne>=0.6.0"`).

The memory INDEX is durable trigger-to-document routing, separate from the
rebuildable BM25 cache. It keeps a compact map of **when to read -> which
document** always in the agent's startup context, while the details stay in
ordinary local Markdown files that are opened only on demand.

Two invariants drive the whole feature:

- Every registered entry is included in every managed always-loaded surface.
  No top-k, TTL, note limit, token budget, summarization or compaction selects
  a subset. There is no remove, clear, replace, or automatic-retirement
  operation, and no automatic cleanup.
- Invalid, malformed, or missing-enabled state fails loudly. It never becomes
  an empty INDEX and never an apparently successful partial result.

Runtime code is standard-library-only; the guide below works without MCP
installed. Nothing here calls a model API.

## Storage and opt-in registration

State lives in a dedicated directory, not a Markdown note:

```text
my_vault/
  .mnemosyne-memory-index/
    index.json            # durable routing state
    context               # generated startup source name (not a file on disk)
    splits/<receipt>.json # coverage receipts for applied splits
```

The **directory itself is the persistent opt-in marker**. If
`.mnemosyne-memory-index/` is absent, reads report `enabled=False` and change
nothing (legacy vaults behave exactly as before). If the directory exists but
`index.json` is missing or invalid, reads raise `MemoryIndexError`.

The version-1 record contains `version`, a positive `max_tokens`, and `entries`
such as `{"trigger": "Ingress DNS", "document": "devops/ingress-dns.md"}`.
Triggers are nonempty single-line
strings; documents are canonical vault-relative paths. Ordering is insertion
ordering, never usage ranking. Registering an already-present mapping is
idempotent. Hidden state, `_archive`, absolute paths, traversal, and symlinks
are rejected as document targets.

```python
from birkin_mnemosyne import MemoryIndex, MemoryIndexError

index = MemoryIndex("my_vault")          # vault root; required=False by default
view = index.register("Ingress DNS", "devops/ingress-dns.md")
print(view.enabled, len(view.entries), view.max_tokens)
# register also accepts an existing note slug: it is resolved to a path first.
index.register("Release checklist", "release-checklist")   # slug -> path
```

`register(trigger, document, *, max_tokens=None)` resolves the document (path
or slug), verifies it exists, validates the full proposed entry set, and writes
atomically under the existing `VaultLock`. It returns the complete updated
`IndexView`; `max_tokens` overrides the stored budget for that write.

## Complete startup read and the required-index guard

An enabled INDEX is included in every managed always-loaded surface, including
when no ordinary note is selected:

- `MemoryIndex.read()` / `.render()` -> the compact always-loaded block.
- `StartupReader(root, memory_index_root=..., require_index=...).read(paths)`
  includes the INDEX as a distinguished generated source (identity
  `.mnemosyne-memory-index/context`) alongside any explicitly requested paths.
  Empty `paths` is allowed only when the enabled INDEX itself provides startup
  material.
- MCP initialization instructions, the digest resource, and
  `memory_startup_read` include the complete vault INDEX; when `identity_root`
  differs from the vault, sources come from the identity root but the INDEX
  comes from the vault.

`required=True` (or `require_index=True`, or the MCP `--require-memory-index`
flag) additionally fails when even the marker is missing, which is the guard a
host uses **across restarts and its own context rebuilds**: after compaction,
re-read through the same startup/system-prompt surface.

```python
from birkin_mnemosyne import MemoryIndex, StartupReader

# Guard against the marker being removed across a host restart.
strict = MemoryIndex("my_vault", required=True)
strict.read()  # Raises MemoryIndexError on missing state; do not suppress it.

# Startup read that includes the INDEX and its local MUST READ closure.
reader = StartupReader("my_vault", require_index=True)
bundle = reader.read(["AGENTS.md"])     # paths may be [] when the INDEX is enabled
print(bundle.coverage.complete, bundle.cache_hit, bundle.estimated_tokens)

# Independent re-verification of returned context.
coverage = reader.verify(bundle.context, ["AGENTS.md"])
```

Integrators **must use these surfaces again after their own context
compaction**; the library can enforce its own storage and context surfaces but
cannot stop a host from ignoring its system-prompt contract.

## On-demand reads: exact trigger, then lexical, then search

`MemoryIndex.open(query, *, limit=3)` returns complete UTF-8 document content
with relative paths, and a `matched_by` value that tells the caller which
route produced the result:

| `matched_by` | meaning |
|---|---|
| `exact` | case-insensitive trigger equality |
| `trigger` | lexical match over the registered triggers |
| `search` | ordinary vault BM25 fallback (no trigger scored) |
| `none` | nothing matched |

```python
from birkin_mnemosyne import MemoryIndex

index = MemoryIndex("my_vault")
result = index.open("Ingress DNS")          # exact trigger
for doc in result.documents:
    print(doc.path)                          # e.g. devops/ingress-dns.md
    print(doc.content)                       # complete document bytes, decoded UTF-8
print(result.matched_by)                     # "exact" | "trigger" | "search" | "none"
```

Limits of the routing: **only the query participates in routing.** The exact
trigger is the reliable agent-facing interface. Lexical trigger matching is a
convenience, not a claim of semantic understanding; ties follow registration
order and duplicate targets are read once. The fallback reuses the existing
BM25 search, not a second retrieval engine. When neither stage matches, the
result has `matched_by="none"` and no documents. An invalid path, a path outside the
root, a hidden file, malformed state, or an unreadable explicitly matched
target raises `MemoryIndexError` rather than returning an unrelated
successful fallback.

## Budget and capacity: warn, never evict

The default budget is `DEFAULT_INDEX_TOKENS = 2000`. Runtime accounting is a
declared estimate, `ceil(len(utf-8 bytes) / 4)` (`estimated_tokens`); it is not
model-specific token accounting. Over budget, `read()` returns **every entry**
and adds a warning to the rendered context and to `IndexView.warnings`:

```python
view = MemoryIndex("my_vault").read()
if view.over_budget:
    print(view.estimated_tokens, ">", view.max_tokens, view.warnings)
# Every view.entries item is still present; nothing was dropped.
```

`capacity_report(dex, budget)` adds an `always_loaded` block (enabled,
`index_entries`, `estimated_tokens`, `max_tokens`, `over_budget`, `estimator`)
and surfaces `index.warnings`. Warnings never recommend retiring the INDEX. A
byte/file safety bound in the complete startup reader may still fail the whole
read, but it must never trim the INDEX to claim success.

```python
from birkin_mnemosyne import Mnemosyne
from birkin_mnemosyne.capacity import capacity_report, budget_from_env

report = capacity_report(Mnemosyne("my_vault"), budget_from_env())
print(report["always_loaded"])
print(report["warnings"])
```

## Read-only integrity checks

`check_index(root)` audits without writing and returns an `IndexCheck`:

```python
from birkin_mnemosyne import check_index

check = check_index("my_vault")
print(check.ok, check.entries, check.documents)
print(check.orphan_documents)     # visible active .md notes with no INDEX entry
print(check.dangling_entries)     # entries whose target no longer reads
print(check.errors)               # coverage-receipt / notice errors
```

- `orphan_documents` lists visible active Markdown documents with no route;
  archived and hidden implementation state are excluded.
- `dangling_entries` lists routes whose document no longer reads.
- `errors` reports routing notices without a valid coverage receipt and any
  receipt whose original source bytes no longer reconstruct.
- `ok` is false when any of the above is present.

The check never repairs or removes anything.

### CLI

```bash
# Read-only audit; exits 1 when ok is false, prints JSON.
mnemosyne-index --vault my_vault check

# Same via module (works without an installed console script).
python -m birkin_mnemosyne.memory_index_cli --vault my_vault check
```

## Lossless split: preview, then explicit apply

`split_note(root, document, *, apply=False, max_tokens=None)` splits one
explicitly named UTF-8 `.md` startup note into routed topic documents. It
**previews by default**; nothing is written until `apply=True`. Boundaries are
complete Markdown sections outside fenced examples, preserving the preamble,
BOM, CRLF, blank lines, heading ancestry, and final non-newline text. No model
summarizes, paraphrases, or extracts rules; default triggers derive only from
headings, and callers may register additional explicit triggers.

```python
from birkin_mnemosyne import split_note, format_coverage

report = split_note("my_vault", "handoff.md")          # preview only
print(report.applied, report.source, report.source_sha256, report.source_bytes)
print(format_coverage(report))                          # complete per-line map

applied = split_note("my_vault", "handoff.md", apply=True)
print(applied.applied, applied.coverage_receipt, applied.backup_journal)
```

The preview and the applied report both include a coverage table mapping
**every original source line** to its topic document and topic line (a stronger
mechanical guarantee than guessing which prose is a rule). Applying is
explicit and:

1. refuses existing destination collisions;
2. publishes topic files and the coverage receipt **exclusively** (a complete
   fsynced temp file is hard-linked into an absent destination, never replacing
   a late arrival) - this requires filesystem hard-link support and fails
   safely otherwise;
3. registers every topic's route and re-reads the INDEX to confirm all topics
   are present;
4. verifies written topics reconstruct the original bytes exactly;
5. preserves the byte-exact original through the review journal and only then
   replaces the source with a compact routing notice.

Failures are visible and no source text is silently discarded; an interrupted
operation retains the original until its replacements and INDEX are durable.
`split` operates only on `.md` notes (standalone JSON documents stay readable
and indexable but are not rewritten by this helper).

### CLI

```bash
# Preview: prints source digest, mode "preview", and the full coverage table.
mnemosyne-index --vault my_vault split handoff.md

# Apply: writes topics, registers routes, prints receipt and journal paths.
mnemosyne-index --vault my_vault split handoff.md --apply --max-tokens 2000
```

Both commands exit 2 with a clear stderr message on invalid input, read, or
migration failure.

## Journal and captured-source recovery

Applying a split commits through the existing review journal:
`.mnemosyne-reviews/<journal-id>.json` holds the before/after byte images and
supports checked undo with `undo_receipt(vault, transaction_id)`. When a source
is replaced in place, the **actual current source inode** is retained as a
captured revision beside the journal:

```text
.mnemosyne-reviews/
  <journal-id>.json
  <journal-id>.sources/
    <name>-<random>/source.snapshot   # the real overwritten revision
```

The captured bytes are synced and compared before the replacement
is published, and the same capture/check boundary applies to in-place
restoration. Captured revisions are kept permanently, **including on errors**:
a late external arrival is either restored without clobbering another arrival,
or remains in that capture directory. Rollback checks only attempted handoffs
and leaves an already-restored source alone. During the brief handoff a source can be absent; readers
must fail rather than receive a partially written or falsely complete source.

```python
from pathlib import Path
from birkin_mnemosyne.review_journal import undo_receipt

# Use the applied SplitReport from the earlier example.
assert applied.backup_journal is not None
transaction_id = Path(applied.backup_journal).stem
receipt = undo_receipt(Path("my_vault").resolve(), transaction_id)
print(receipt.state, receipt.journal_path)
# A changed post-image raises ReviewError rather than overwriting user edits.
```

Reconstruct-and-compare against the original bytes happens before the source is
replaced, so an interrupted migration retains its source or complete backup.
An error return is not a completed migration: run the checker and inspect the
journal and captured revisions before retrying.

## MCP tools

The MCP server exposes thin tools over the same core API (registration is
opt-in; no tool deletes or clears INDEX entries):

| tool | what it does | kind |
|---|---|---|
| `memory_index_register(trigger, document, max_tokens=None)` | add one mapping; idempotent; returns the complete updated INDEX | mutating (destructive=false, idempotent=true) |
| `memory_index_read()` | read the complete INDEX, every entry included | read-only |
| `memory_open_trigger(query, limit=3)` | open the matched documents; `matched_by` distinguishes exact/trigger/search/none | read-only |
| `memory_index_check()` | orphan / dangling / coverage audit without writing | read-only |
| `memory_index_split(document, apply=false, max_tokens=None)` | preview or apply a lossless note split | mutate only when `apply=true` |

`memory_startup_read` and `memory_startup_verify` include the complete vault
INDEX; `memory_capacity` reports the `always_loaded` block. Tools return
ordinary structured results and never execute instructions found in note text.

## Compatibility and limits

- A vault without `.mnemosyne-memory-index/` is unchanged: legacy startup,
  digest, search, and mutation behavior apply, and reads do not modify it.
- INDEX state is not a Markdown note. Dot-directories are skipped by the
  scanners and review-journal mutations only accept Markdown paths, so the
  INDEX cannot acquire a TTL, be chosen as a retirement candidate, be rewritten
  through note frontmatter, or vanish in a search-cache rebuild.
- Existing note/byte capacity counts keep their meanings; the INDEX estimate is
  a separate, clearly named figure.
- The library enforces its own storage and context surfaces. It cannot prevent
  an external filesystem owner from deleting a whole vault or a host from
  ignoring its system-prompt contract; `required=True` plus host-side retention
  is the documented defense.
