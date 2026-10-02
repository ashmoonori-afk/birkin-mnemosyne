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
