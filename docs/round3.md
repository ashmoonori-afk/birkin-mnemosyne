# Explicit memory review

`Consolidation(vault).questions()` returns conservative duplicate and
overlap-or-possible-conflict candidates, with immutable path/content snapshots,
source evidence and concise question text. A lexical overlap is not proof of
semantic contradiction. Empty and archived notes are not proposed.

```python
from birkin_mnemosyne import Answer, Consolidation

review = Consolidation("my_vault")
questions = review.questions()
if questions:
    question = questions[0]
    print(question.text)  # Present through the host's ask-user-questions tool.
    # Only after the user explicitly chooses "first is current":
    receipt = review.apply(question, Answer(question.id, "current-first"))
    review.undo(receipt.transaction_id)
```

Choices are `keep-both`, `keep-first`, `keep-second`, `current-first`,
`current-second`, `drop-first`, `drop-second`, and `merge`. Keeping/current
selects a survivor and archives the other note. Dropping archives the selected
note. Merge requires explicit user-approved `merged_body` and a `survivor`
(`first` by default). It does not generate facts or decide which fact is true.
Survivor metadata is retained, version increments, sources are combined;
retired metadata, body, path and bytes remain in the archive and journal.

MCP provides `memory_review_questions`, `memory_review_apply`, and
`memory_review_undo`. The host asks the user; it must not invent the answer.
Apply and undo are dry-run unless `confirm=true`. Apply rejects a stale or
unknown question; undo checks every changed image before restoring anything.
Archive collisions and edited post-images are refused rather than overwritten.

The versioned `.mnemosyne-reviews/<transaction-id>.json` journal contains
the explicit answer, original/post-image hashes and byte images, paths and
transaction state. It is sensitive memory data, not disposable index cache.
Do not delete it while undo/recovery is needed. Handled write/index/receipt
failures roll back; rollback failure retains recovery evidence. `undo(id)` can
recover a prepared/recovery-required transaction if every current image still
matches its before/post state. Journaling does not claim power-loss atomicity.

One answer is applied at a time. User-confirmed decisions can archive protected
notes; automatic curation protections remain intact. Cooperating library,
profile, curation and MCP writers share a reentrant thread/interprocess vault
lock. External editors do not participate: finish their edits before applying
or undoing a review. Derived indexes are rebuilt, not rolled back over unrelated
usage history.

# Identity-file reading

```python
from birkin_mnemosyne import IdentityReader

reader = IdentityReader("workspace")
result = reader.search("AGENTS.md", "release approval", limit=2)
print(result.context)  # Partial, ranked, whole-section context.
section = reader.read_section("AGENTS.md", result.sections[0].anchor, result.revision)
full = reader.read_full("AGENTS.md")  # Required for comprehensive instructions.
```

Sections preserve exact source text and one-based inclusive line spans.
ATX/setext headings, backtick/tilde fences, ancestry and pre-heading global
guidance are indexed; frontmatter is excluded from section ranking. Full reads
retain frontmatter and examples. Catalog results expose headings, anchors and
revision; the MCP catalog omits body text.

Anchors are deterministic within a document revision, not permanent IDs:
body edits preserve heading-derived anchors, while duplicate insertions or
ancestor renames can change them. Anchor reads require the content SHA256 and
reject stale revisions. Normal reads check nanosecond stat fingerprints;
`force_refresh=True` unconditionally rereads bytes for preserved-metadata edits.
No-match searches return empty context. Excerpts are partial and can omit a rule
or exception elsewhere; use full access for complete instructions.

The cache holds at most four files and one MiB of source in total; a single
larger file is refused rather than silently truncated. No embeddings,
dependencies, subprocesses or persistent index are added.

MCP `memory_identity_read` supports `catalog`, `search`, `section` and `full`.
The root defaults to the vault. To expose separate workspace identity files,
start `mnemosyne-mcp --vault <vault> --identity-root <workspace>` (or
`MNEMOSYNE_IDENTITY_ROOT`). Paths cannot escape that configured read-only root.

# Kibitzer adapter

```python
from birkin_mnemosyne import KibitzerAdapter, RecallNudge, admit, render_recall

adapter = KibitzerAdapter("my_vault")
candidates = adapter.select("release approval", surfaced={"already-seen.md"})
# A host judges the candidates; the adapter does not invent a factual nudge.
if candidates:
    path = candidates[0].path
    decision = admit(
        [RecallNudge(path, "The note records that releases require approval.")],
        offered={c.path for c in candidates}, surfaced=set(), max_items=1,
    )
    for nudge in decision.accepted:
        print(render_recall(nudge))
adapter.export("separate-memory-export")
```

Documents have `path`, `description`, `body`. Candidates have `path`,
`description`, `excerpt`, `score`; lower score is better, and the excerpt is
at most 200 UTF-16 code units, matching JavaScript's budget. Descriptions are
preserved when present; legacy notes receive a deterministic title/body fallback.
Selection uses the core's multilingual lexical BM25 over description and body.
MCP `memory_kibitzer_candidates` exposes the same candidates.

Root `system/`, `_archive/`, expired and hidden notes are excluded.
`reference/system/` is ordinary topical memory, not a protected root profile.
Surfaced/additional paths are excluded before the cap. Edited files invalidate
the snapshot; `force_refresh=True` rereads preserved-metadata changes.

`admit` checks offered paths, surfaced/duplicate paths, item cap, single-line
200-UTF16-unit hints, upstream address/imperative/commentary restrictions,
XML-invalid characters and conservative secret-like patterns. Rejected hints
are not silently truncated or rewritten. Accepted paths and hints are escaped
in recalled-memory envelopes. These lexical rules cannot prove truth,
one-sentence semantics or complete absence of secrets. Candidate/export text
uses conservative redaction, which can also mask benign examples.

Export writes described Markdown plus `mnemosyne_source` to a separate explicit
directory, with exclusive creation and no overwrites. The source vault is
unchanged. Commit the exported files in the host memory repository if its
provider reads committed HEAD; configure ingestion outside this adapter.

This is live-vault Mnemosyne selection with Kibitzer-compatible shapes, not an
implementation of upstream selector/provider parity or a resident advisor.
Installed omo/configuration is untouched. Recall benchmark scores describe
candidate selection, not model nudge judgement or parent-agent answer gains.
Contracts studied:
[installed persona upstream counterpart](https://github.com/code-yeongyu/oh-my-openagent/blob/61086739c3b00f0990cbcdcdfde9146791e243db/packages/memory-core/src/recall/assets/kibitzer-persona.md),
[selection](https://github.com/code-yeongyu/oh-my-openagent/blob/61086739c3b00f0990cbcdcdfde9146791e243db/packages/memory-core/src/recall/select.ts),
[admission](https://github.com/code-yeongyu/oh-my-openagent/blob/61086739c3b00f0990cbcdcdfde9146791e243db/packages/memory-core/src/recall/gate.ts).
The upstream source uses the
[Sustainable Use License](https://github.com/code-yeongyu/oh-my-openagent/blob/61086739c3b00f0990cbcdcdfde9146791e243db/LICENSE.md).
No upstream implementation is vendored; this adapter independently implements
the documented data shapes and conservative admission rules.
