# birkin-mnemosyne for Hermes Agent

A standalone local memory provider using Hermes' documented `MemoryProvider`
interface. It stores explicit durable notes in a Markdown vault and recalls
matching snippets before a turn. No model, API key, MCP subprocess, network
service, telemetry, or automatic transcript capture is required.

## Install and select

The plugin and core library declare Python 3.10 or later. Hermes itself
requires Python 3.11 or later, so use a Python version supported by your
Hermes installation when loading the plugin.

Plugin 0.2.3 pins the published `birkin-mnemosyne==0.7.2` core, including
nested-folder recall, task-bound reads, complete topic expansion, scoped
handoffs and note labels. Use the `v0.7.2` checkout for the installation below.
The core `v0.7.0` tag retains the earlier plugin 0.1.0 manifest.

This directory is the plugin source, not an addition to Hermes' built-in provider
tree. Use the Hermes plugin installer so it prepares the declared
`birkin-mnemosyne==0.7.2` dependency through Hermes' package manager:

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

The 0.7.2 provider source exposes four memory-provider tools:

- `birkin_memory_remember`: create a durable note with `title` and `body`. An existing
  title cannot be overwritten.
- `birkin_memory_search`: retrieve ranked snippets with `query`, an optional
  `limit` from 1 to 20, and an optional `labels` array. `labels` is an AND
  filter: every `namespace:value` entry must be carried by the note; `null`
  or `[]` leaves recall unfiltered.
- `birkin_memory_get_note`: read the full body of a selected `title`.
- `birkin_memory_index`: read the resident INDEX or expand a complete `topic`
  copied from its topic map.

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
