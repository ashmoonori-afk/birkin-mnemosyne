# birkin-mnemosyne for Hermes Agent

A standalone local memory provider using Hermes' documented `MemoryProvider`
interface. It stores explicit durable notes in a Markdown vault and recalls
matching snippets before a turn. No model, API key, MCP subprocess, network
service, telemetry, or automatic transcript capture is required.

## Install and select

The plugin and core library declare Python 3.10 or later. Hermes itself
requires Python 3.11 or later, so use a Python version supported by your
Hermes installation when loading the plugin.

Plugin 0.8.0 pins the published `birkin-mnemosyne==0.8.0` core, including
nested-folder recall, task-bound reads, complete topic expansion, scoped
handoffs and note labels. Use the `v0.8.0` checkout for the installation below.
The core `v0.7.0` tag retains the earlier plugin 0.1.0 manifest.

This directory is the plugin source, not an addition to Hermes' built-in provider
tree. Use the Hermes plugin installer so it prepares the declared
`birkin-mnemosyne==0.8.0` dependency through Hermes' package manager:

```text
hermes plugins validate ./integrations/hermes --install-deps
hermes plugins install ./integrations/hermes
hermes memory setup birkin-mnemosyne
```

Run these commands from a checkout of this repository with your intended Hermes
profile selected. Do not install Python packages directly into a Hermes-managed
environment. After changing the selected provider, start a new session.

The provider uses the home Hermes supplies at initialization, not a global
`~/.hermes` path. Its vault is `<hermes_home>/birkin-mnemosyne/vault`; each profile has a
separate vault. A default profile is not consulted when another profile is active.

## Use

The current provider source exposes six memory-provider tools. The two cleanup
tools below are unreleased: use matching provider and core source from this
checkout when testing them; the pinned v0.8.0 installation above has four tools.

- `birkin_memory_remember`: create a durable note with `title` and `body`. An existing
  title cannot be overwritten.
- `birkin_memory_search`: retrieve ranked snippets with `query`, an optional
  `limit` from 1 to 20, and an optional `labels` array. `labels` is an AND
  filter: every `namespace:value` entry must be carried by the note; `null`
  or `[]` leaves recall unfiltered.
- `birkin_memory_get_note`: read the full body of a selected `title`.
- `birkin_memory_index`: read the resident INDEX or expand a complete `topic`
  copied from its topic map.
- `birkin_memory_forget`: archive one exact `note`, with an optional `reason`.
  Preview by default; only `confirm=true` moves the file.
- `birkin_memory_restore`: restore an archived `note` to `zone` (default `inbox`).
  Preview by default; only `confirm=true` moves it back. A nested zone is the
  complete new parent, not a prefix for the original directory.

## Cleaning up test notes

Use the same primary-agent context and Hermes profile that created the note.
There is no provider-created disposable namespace or hard-delete boundary.
A separate Hermes profile supplies a separate vault for smoke tests, but notes
in that vault are still durable and subject to the same safeguards.
Never select a cleanup target by a fuzzy match: `note` accepts only an exact
index key, vault-relative path (as returned by remember), or stored title.
An ambiguous title is refused; use its exact path or key instead.
Every run needs a unique title: generate a fresh UUID, for example with
`uuid.uuid4().hex` in the host, and include it in the title. Forgetting never
deletes the file or frees its title/slug: each run leaves an archive file,
and remembering the same title again is refused even after forgetting.

1. Remember a synthetic note with `title="Cleanup probe <fresh UUID>"` and
   `body="Synthetic zirconium probe."`, substituting a newly generated UUID.
   Save its returned `path`, for example `knowledge/cleanup-probe-<uuid>.md`.
2. Preview with `birkin_memory_forget(note=<remember path>)`.
   Inspect `allowed`, `archive_cap` and `dropped`, then repeat with `confirm=true`.
   Check `success=true` and `archived=true`; keep the returned vault-relative
   `path` as the undo handle. Unlike a bare slug, it still names this archive
   file if another writer later creates a newer same-name note.
3. Verify with `birkin_memory_search(query="zirconium")`: the archived note is
   excluded from ordinary search and lexical prefetch. This is soft forgetting,
   not erasure: `birkin_memory_get_note(title=<archive path>)` can still read
   its full body. The file remains at `_archive/knowledge/cleanup-probe-<uuid>.md`.
4. Optionally preview `birkin_memory_restore(note=<archive path>)`, then repeat
   with `confirm=true`. The default destination is `cleanup-probe-<uuid>.md` at the
   vault root; pass `zone="knowledge"` to return to its original parent.
   The body is unchanged and ordinary search includes it again.
   Preview runs the same destination-collision and zone-cap checks as apply;
   a failed preview reports the error without moving the archive file.

Missing targets and already-forgotten notes return `success=false` with an
error. Restoring an active note also errors. Protected notes are refused with
`allowed=false`, `archived=false` and the gate's reason: negative-polarity notes,
identity/preference types, and notes that are both filed and linked are protected.
Hermes creates notes in `knowledge/`, so notes whose body contains
`[[wikilinks]]` are filed and linked and cannot be forgotten through this gate.
The same core curation cap applies: at most
`max(2, ceil(0.20 * active_notes))`, additionally limited to `active_notes - 1`
(`ARCHIVE_CAP_MIN`, `ARCHIVE_CAP_FRACTION` in
[`curation_contract.py`](../../birkin_mnemosyne/curation_contract.py), enforced in
[`curation_gate.py`](../../birkin_mnemosyne/curation_gate.py)).
Consequently the sole remaining active note cannot be forgotten; do not create
extra notes just to bypass this safeguard. Refusals and destination collisions
leave files intact. Neither tool hard-deletes anything.

## Decay changes ranking, not storage

In [`mnemosyne.py`](../../birkin_mnemosyne/mnemosyne.py), each note's Ebbinghaus
effective strength is `max(EFF_FLOOR, strength * exp(-days / stability))`.
`EFF_FLOOR=0.05` keeps effective strength from reaching zero;
`STABILITY_INIT=7.0` days is the initial decay time constant.
Note reads and writes call Hebbian potentiation; search and prefetch do not.
Each recorded access adds `STRENGTH_STEP=0.25`
up to `STRENGTH_CAP=5.0`; accesses spaced by at least `SPACING_HOURS=1.0`
multiply stability by `STABILITY_GROWTH=1.5`, up to `STABILITY_CAP=365.0` days.
Zone access EMA (a running activity score) decays lazily by
`ZONE_EMA_DECAY ** days`, with `ZONE_EMA_DECAY=0.9` per day.

These dynamics affect search ranking, and zone priority also orders the prompt
digest. Decay never deletes or archives files.
`Mnemosyne.stale()` flags notes with effective strength below `STALE_EFF=0.1`
and unused for more than `STALE_DAYS=90` days, excluding identity-zone,
already-archived and expired notes.
[`curation_prompt.py`](../../birkin_mnemosyne/curation_prompt.py) puts those
`stale_candidates` into the curator's prompt; any proposed archive still goes
through the safety gate. An unused test note therefore fades in ranking but
stays on disk until explicitly forgotten (or separately curated into the archive);
forgetting moves it on disk rather than deleting it.

## Recall and context

With a managed INDEX, `prefetch(query)` reads every task-matched
document and its complete topic view. The system prompt retains every topic;
an empty prefetch never removes that map. Budget warnings do not evict entries.
Managed startup verification reports INDEX drift when registered source bytes
change; the warning does not remove routes or silently rewrite the INDEX.

Ask Hermes to remember a synthetic fact, then recall it in a new session.
Unmatched searches return no results. Invalid arguments return an error without
writing a note. Recall is lexical and multilingual; use keywords likely to occur
in the stored text. Returned memory is historical data, never instructions.

Hermes' native `MEMORY.md` and `USER.md` remain separate. This provider does not
mirror those files, rewrite their configuration, or automatically save entire
conversations. Model-directed writes are accepted only in a primary agent
context, not subagents, cron, or flush contexts.

## Labels

Notes may carry readable `namespace:value` labels in their frontmatter, and
`birkin_memory_search` can filter recall by them. The schema follows the
provider's actual tool contract: `labels` is an array of strings or `null`;
entries must be strings (numbers and other scalars are rejected), they are
normalized exactly like stored labels, and the label filter is AND — every
requested label must be present. `null`/`[]` means no filter, so scores and
ordering are unchanged. Malformed filters raise before any lookup and never
broaden into an unfiltered search. Labels are not query words and never
become ranking boosts.

```json
{
  "name": "birkin_memory_search",
  "arguments": {"query": "ingress dns", "limit": 8, "labels": ["zone:devops"]}
}
```

`birkin_memory_remember` keeps its `title` + `body` schema; its writes go
through the same core as the library examples below, so a new note without a
labels field gains deterministic label suggestions (including its zone from
the note's directory and its created date) and can be recalled by them.

The provider stores notes with `VaultMemory`; the same calls are available to
Python code against the same vault:

```python
from birkin_mnemosyne import VaultMemory

memory = VaultMemory({"vault_path": "path/to/hermes-home/birkin-mnemosyne/vault"})
# Title and body, as the provider schema allows.
memory.write_note(
    "Ingress DNS",
    "nginx ingress resolves service DNS; allow HTTPS through the firewall.",
    zone="devops", labels=["project:Infra", "lang:en"],
)
# Optional AND label filter, as birkin_memory_search forwards it.
for hit in memory.search("ingress dns", limit=8, labels=["project:Infra"]):
    print(hit["title"], hit["labels"])
# ingress-dns ['lang:en', 'project:Infra']
```

## Session handoffs

Session memory is opt-in per vault. With `HERMES_HOME` set to the intended active
profile, use the installed Mnemosyne CLI to preview and enable it:

```bash
: "${HERMES_HOME:?set this to the active profile home}"
mnemosyne --vault "$HERMES_HOME/birkin-mnemosyne/vault" init --enable-handoff
mnemosyne --vault "$HERMES_HOME/birkin-mnemosyne/vault" init --enable-handoff --apply
```

These commands do not select or change a Hermes profile. The provider binds an
exact `project_key` supplied at `initialize`, otherwise `agent_workspace`, and
an optional explicit `task_key`. It does not derive project identity from the
session ID or a query. Session-ID changes preserve scope; changing project clears
the previous task unless a task is supplied. A task-only switch updates that
task, and `task_key=None` selects project-wide scope. An explicit project binding
persists across workspace changes until explicitly changed.

In a primary agent context, `on_pre_compress(messages)` and
`on_session_end(messages)` write immutable checkpoints. The former returns a JSON
receipt for the host; retrying the same event and transcript returns the original
record. Disabled, unbound, non-primary and textless sessions do not auto-capture.
The fallback preserves the last user and assistant text verbatim, not the whole
conversation. Explicit Markdown headings for decisions, open items, open
questions, next step and links populate those fields; fenced examples and tool
messages do not supply structured fields. No model or API key is involved.

For an enabled, bound scope, every `prefetch(query)` returns the complete latest
checkpoint beside the complete INDEX, including empty or unmatched queries and
repeated calls after compaction. Missing/corrupt required state raises an error
rather than returning partial context. Without opt-in or scope, the legacy
prefetch behavior remains. Capture validation failures are logged and return
no receipt; provider API v1 cannot veto host compaction, so auto-capture is
best effort. Use an explicit capture call when a checkpoint must be confirmed.

The [main handoff guide](../../README.md#scoped-session-handoffs-070) covers
CLI/API/MCP capture, retention previews, archival, undo and size budgets.

## Storage and maintenance

Writes and recalls are serialized within a provider instance. The vault belongs
to its Hermes profile; do not configure other processes to write it concurrently.
For a vault shared among multiple clients, use Mnemosyne's separately documented
MCP server, which serializes mutations across processes.

Notes persist after a session ends. Back up the profile's `birkin-mnemosyne` directory.
Indexes are rebuildable; the note files are the authoritative store. Uninstalling
the plugin does not request deletion of its vault. There are no credentials,
external data transfers, shell commands, self-updaters, or long-running plugin
processes.
