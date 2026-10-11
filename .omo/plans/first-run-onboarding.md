# First-run onboarding

Owner approved planning and immediate execution. Tier: HEAVY; final gate is
an independent GPT-6.1 Sol APPROVE on the exact committed head, every CI job
green, and --match-head-commit. Base is the verified README merge
bfe0a9ac18d75e954f664b9a75fe0202102738b4. No version or issue fix belongs in
this PR. Binding delivery order: onboarding, #65, #66, release, Hermes.

## Users and required outcome

A person starting with no vault or existing Markdown wants a preview of
what will be imported, normalized and organized before approving writes.
The original information must remain recoverable, previous INDEX routes
must remain available, and repeating initialization must not duplicate work.
No model, API key, semantic extra or MCP extra is required for this sequence.

Extend memory_index_cli, the existing check/split dispatcher, and expose
mnemosyne init through that implementation rather than a parallel CLI.
The sequence scans existing notes and optional plain-Markdown imports,
reports existing duplicate/overlap/conflict candidates, safely normalizes,
creates complete deterministic topic documents and always-loaded INDEX,
then runs startup verification including current drift diagnostics.
Both README languages explain First run; CHANGELOG gets an Unreleased entry.

## Confirmed foundations

- Preview must not instantiate a source-writing scan/review flow on either
  input tree: Mnemosyne.refresh and Consolidation.questions update cache.
- Reuse the existing review candidate algorithm, not a second detector.
  Preserve path identities despite slug collisions and the scan's one-zone
  depth limit. Overlap-or-conflict is a candidate, not a semantic conclusion.
- Frontmatter.parse is a forgiving, lossy subset parser. Never serialize its
  result over arbitrary existing headers or alter original body bytes.
- Use existing exclusive publication and byte-exact journal/recovery APIs
  for permitted mutations. Differing destinations must never be replaced.
- Existing INDEX routes and enabled markers must never be removed or reset.
  Existing render_index_view supplies grouped views and budget warnings.
- Add MemoryIndex.enable(max_tokens=None), serialized by VaultLock, to
  support an enabled zero-route vault. It retains all existing entries,
  preserves the budget unless explicitly changed, validates a supplied
  budget before any write, and performs no write for unchanged state.
- StartupReader.read([]) and verify(context, []) already accept an enabled
  zero-route INDEX and include fresh consistency warnings.

## Verification and evidence

The unmodified related baseline passed 156 tests in 5.37 seconds:
tests/test_memory_index.py, test_memory_index_cli.py,
test_memory_index_migration.py, test_consolidation.py,
test_mcp_memory_index.py. Evidence: ../evidence/onboarding-baseline-tests.log.
The dedicated .venv has dev/mcp/semantic extras; core functionality must
also pass the repository's existing stdlib-only CI matrix.

Required final scenarios:

1. Preview an absent and an empty vault; no directory or file appears.
2. Explicitly initialize an empty vault; INDEX is enabled with zero routes
   and independent startup verification is complete.
3. Preview/apply a messy fixture with duplicates, missing frontmatter,
   Korean/Japanese, BOM/CRLF and no final newline; all information survives.
4. Repeat successful initialization; no duplicate outputs or changed bytes.
5. Preview with an import folder; both complete input trees stay identical.
6. Exercise Windows separators, Unicode and colliding path identities in
   the existing Windows Python 3.10/3.12/3.14 CI jobs.
7. Refuse differing destinations and stale source images without clobbering.
   Demonstrate checked undo of permitted normalization changes.
8. Preserve all previous routes; report budget and drift warnings without
   hiding them or claiming that semantic conflicts were automatically fixed.
9. Run real CLI scenarios, touched-file diagnostics, related regressions,
   full installed-extra suite, git diff --check, and both README parity.
10. Commit the complete feature, create one PR, capture exact-head Sol review
    and all-green CI, merge with the approved head, verify green main, and
    remove owned test/review resources while retaining evidence.

## Locked implementation decisions

The independent read-only GPT-6 Astra design is complete. Its important
counter-case is an original restored by split undo: it still participates
in a byte-offset coverage receipt and must not be normalized. Root adopts
that exclusion and additive catalogues, not source-replacing split_note.
The newer owner instruction inserts #65/#66 before release despite the
review's stale final ordering sentence.

### Interfaces and ownership

Expose mnemosyne init --vault PATH [--import DIRECTORY] [--max-tokens N]
[--apply] through memory_index_cli. Preserve existing --vault PATH check/
split and accept --vault either before command or after init, rejecting
duplicate specification. Preview returns a JSON plan with verification
scope resident-index and status planned; apply returns its actual status.
Exit 0 for valid preview/verified apply, 1 for completed apply with drift/
failed verification, and 2 for unsafe inputs, collisions or I/O failures.

onboarding_notes.py owns immutable path-keyed notes, raw-byte inventory,
conservative header completion and catalogue bytes. onboarding_plan.py
owns captured inputs, proposed imports/catalogues/routes, review snapshots,
coverage protection and projected INDEX. onboarding.py owns explicit apply,
source/state revalidation, existing journal use and actual verification.
Small additional modules are allowed only to keep distinct responsibilities
under 250 pure LOC rather than hiding a large implementation in one file.

The pure similarity scorer belongs in consolidation_questions.py, without
imports from the review service. The typed questions_from_snapshots wrapper
in consolidation.py retains existing bounded candidates/constants and IDs;
Consolidation.questions delegates after its existing eligibility/cache scan.
This is a one-directional import graph, without dynamic imports or casts.
No new detector, temporary-vault scanner, model dependency or provider option
is needed. Provider wording is optional permission in the owner's request;
existing hosts can still add custom trigger aliases through MemoryIndex.

### Source normalization and identity

Inventory all visible active .md files recursively, without following any
symlink/reparse point. Hidden trees and _archive are excluded. Canonical
relative POSIX paths, not basenames/slugs, identify notes. Reject ambiguous
case-insensitive destination identities and paths escaping their root.
Record source bytes and hashes; never call refresh or acquire a file-backed
lock during preview.

Frontmatter completion adds only missing title, type and tags, in that order:
filename stem, topic and []. Preserve existing values, unknown fields,
comments, order and body bytes. Newly inserted scalars reuse _one_line and
_yaml_str. Preserve CRLF framing and no-final-newline bodies. Handle BOM
explicitly; retain the exact pre-image in the existing journal. Do not
invent dates, confidence, provenance, polarity or versions. Ambiguous or
unsupported headers are retained unchanged with path-specific warnings.

Validate split receipts with check_index; receipt-bound original sources and
topic documents are excluded from normalization. Invalid coverage blocks
apply. Routing notices are managed infrastructure, not grouping inputs.
Advisory questions cover eligible source snapshots, including nested equal
basenames; report up to 20 plus the existing candidate limitations. No
question is automatically answered by apply and no semantic truth verdict
is inferred from an overlap-or-conflict label.

### Imports and complete topic catalogues

An import directory must exist outside and not overlap the vault. Retain
external bytes and relative directory structure. Destination namespace is
imports/init-<digest-of-canonical-host-normalized-root>/<relative-path>.
Existing destinations are reusable only when they equal the raw external
original or its expected normalized post-image. Otherwise fail without
replacement. Recognize that namespace without a subsequent --import flag.

Group by first nonempty sorted string tag, otherwise first logical source
directory, otherwise valid type/default topic. Catalogue text contains sorted
source titles and local links, canonical frontmatter and a format marker.
Destination is onboarding-topics/init-<sha256-of-catalogue-bytes>.md.
Do not include timestamps or body hashes: ordinary body edits and header
completion must not create another catalogue. Recognize generated outputs
only when reserved name, marker and full byte digest agree; edited generated
outputs block apply rather than becoming new source notes.

Register topic trigger to catalogue, topic trigger to every member, and
source title trigger to its source. Preserve every existing alias. This
keeps retained originals indexed, not merely linked from a catalogue.
Existing INDEX rendering chooses grouped resident/topic views when smaller
and warns without evicting routes. Token estimates are UTF-8 bytes/4.

### Ordered apply and retry

1. Read-only planning captures inventory, existing INDEX/receipt/journal
   bytes, imports, source pre/post-images, catalogues, routes and warnings.
2. Explicit apply acquires VaultLock and revalidates all captured inputs
   and destination identities. A stale plan fails, rather than silently
   changing what the owner approved.
3. Reject prepared/recovery-required journals and identify their receipt.
   Existing checked recovery must finish before further mutations.
4. Enable INDEX. For first creation prepare complete state in an owned
   temporary sibling directory, then publish it under the vault lock and
   fsync its parent. A creation failure leaves no invalid opt-in marker.
   Invalid existing state fails closed; valid updates use existing writer.
5. Exclusively create missing raw imports and catalogue documents. Reuse
   byte-identical artifacts after partial progress; never replace differing
   files or invent a second destination name to evade a collision.
6. Register additive routes, including retained source routes.
7. Journal the batch of eligible changed source frontmatter with existing
   commit, Change(path, path, before, after), deterministic question digest,
   and choice mnemosyne-init-normalize. Preserve original bytes before any
   source change. Existing checked undo restores those exact source bytes;
   it does not remove imports, catalogues or INDEX routes.
8. StartupReader(require_index=True).read([]), independently verify the
   returned context with [], and check_index. Report resident INDEX
   verification, not proof of every note in one bounded startup bundle.
   Print counts for notes/imports/topics/INDEX tokens/warnings and actual
   verification/drift results.

Unchanged reruns have no new files, routes, cache changes or journals.
Partial additive writes can remain after an error and are explicitly
reported/reusable. Rolled-back journals permit retry; prepared/recovery-
required journals block it; changed post-images refuse undo. This uses
existing handled-failure recovery, not a new multi-file power-loss promise.

### Additional exact acceptance scenarios

- Inject first INDEX-state write failure: marker absent, retry succeeds;
  pre-existing corrupt or missing-index markers remain unchanged.
- Normalize neither topic nor original from a split receipt, including
  restored-original state after undo; original coverage remains valid.
- Compare bytes and mtimes on a second apply and after import followed by
  rerun without import; no additional journal or derived output.
- Inject failures after imports/catalogues, routes and journal publication;
  preserve sources and retry remaining additive work deterministically.
- Hook concurrent source edits/destination arrivals before publication:
  owner arrivals survive and stale plans refuse without clobbering.
- Preserve comments, unknown nested fields, protection metadata, Windows
  strings and original body framing; warn on unsupported ambiguous headers.
- Retain existing dangling aliases and report drift/nonzero apply status;
  all successfully onboarded active source paths have INDEX routes.
- Exercise the installed console alias and old CLI/module dispatcher with
  no API keys; use existing native Windows/Linux/macOS CI matrices.

Final evidence stays in /home/hp/work/mn-readme-results/evidence/.
One complete onboarding PR, independent exact-head GPT-6.1 Sol APPROVE,
all CI green, --match-head-commit, green merged main, and owned QA cleanup
are required before the separate issue fixes and release sequence.
