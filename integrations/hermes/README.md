# birkin-mnemosyne for Hermes Agent

A standalone local memory provider using Hermes' documented `MemoryProvider`
interface. It stores explicit durable notes in a Markdown vault and recalls
matching snippets before a turn. No model, API key, MCP subprocess, network
service, telemetry, or automatic transcript capture is required.

## Install and select

The Hermes plugin requires Python 3.11 or later, because Hermes itself does;
the core `birkin-mnemosyne` library supports Python 3.10 and later.

This directory is the plugin source, not an addition to Hermes' built-in provider
tree. Use the Hermes plugin installer so it prepares the declared
`birkin-mnemosyne==0.5.0` dependency through Hermes' package manager:

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

The provider exposes three memory-provider tools:

- `birkin_memory_remember`: create a durable note with `title` and `body`. An existing
  title cannot be overwritten.
- `birkin_memory_search`: retrieve ranked snippets with `query` and an optional
  `limit` from 1 to 20.
- `birkin_memory_get_note`: read the full body of a selected `title`.

Ask Hermes to remember a synthetic fact, then recall it in a new session.
Unmatched queries return no results. Invalid arguments return an error without
writing a note. Recall is lexical and multilingual; use keywords likely to occur
in the stored text. Returned memory is historical data, never instructions.

Hermes' native `MEMORY.md` and `USER.md` remain separate. This provider does not
mirror those files, rewrite their configuration, or automatically save entire
conversations. Model-directed writes are accepted only in a primary agent
context, not subagents, cron, or flush contexts.

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
