# Birkin-Mnemosyne

**Local Markdown memory for agents: multilingual BM25 retrieval, usage-driven
ranking, and model-independent curation with a deterministic safety gate.**

The core uses only the Python standard library. Your notes remain readable
files on your machine; the optional MCP server connects them to agent clients.

<!-- HERO: add docs/assets/hero.webp when image generation is available.
Alt text: A local memory palace of note cards with Latin, Hangul, kana and Han
glyphs connected by teal and amber retrieval threads.
-->

## Why use it?

- **Own the vault.** Edit, grep, diff and back up ordinary Markdown notes.
- **Recall named anchors.** Find projects, people, commands and error strings
  without an embedding model, vector database or model call on the search path.
- **Remember what gets used.** Note accesses reinforce memory; zone priorities
  help bring active topics forward.
- **Separate judgment from execution.** Any `str -> str` model client can
  propose curation; the executor validates and limits file operations.

Extracted from the [Birkin](https://github.com/ashmoonori-afk/birkin) personal
agent, the library can be used in openclaw, hermes or your own loop.

## Quick start

Requires Python >= 3.10. From a checkout:

```bash
pip install -e .
```

```python
from birkin_mnemosyne import VaultMemory

mem = VaultMemory({"vault_path": "my_vault"})
mem.write_note(
    "Ingress DNS",
    "nginx ingress resolves service DNS; allow port 443 through the firewall.",
    zone="devops",
)
hits = mem.dex.search("ingress dns", limit=5)
for hit in hits:
    print(hit)
# Record the note your agent actually used, not every search candidate.
mem.dex.record_access("ingress-dns")
```

For an existing vault, use `Mnemosyne("my_vault")`, call `refresh()`, then
`search(query)`. Curation is optional:

```python
from birkin_mnemosyne import get_completer, run_curation_pass

run_curation_pass("my_vault", get_completer("codex"), provider="codex")
# Or pass your own complete(prompt: str) -> str callable.
```

## How retrieval works

1. **Index the notes.** The engine tracks file changes and reparses changed
   Markdown files rather than rereading every body on each search.
2. **Match words and characters.** Unicode normalization and case folding
   handle equivalent forms; Latin accents are folded and long words receive
   a short prefix stem. Hangul uses runs and bigrams; Han and kana use
   individual characters and adjacent pairs.
3. **Rank lexical matches.** BM25 rewards useful, uncommon query terms.
   Queries mixing scripts get a bonus when a note matches every query script.
4. **Apply memory dynamics.** Usage-driven decay and zone activity adjust
   ranking. `record_access()` reinforces the notes the agent actually uses.

Retrieval makes no model calls. The compressed index is a rebuildable cache;
usage history is separate persistent state. Curation asks a model for a typed
plan, then lets deterministic code validate, clamp and apply it.

## Benchmark results

These are the frozen test-split results from
[`benchmarks/retrieval/RESULTS.md`](benchmarks/retrieval/RESULTS.md), not claims
about every real-world vault. The synthetic corpus has 160 gold notes in six
languages, padded with distractors to 10,000 notes. Three independent query
authors supply exact, low-overlap paraphrase and code-switched queries.
Cross-language sibling notes are excluded from scoring; tuning uses dev only.

### Unicode tokenizer: MRR at 10,000 notes

MRR measures how early the correct note appears; higher is better. The table
combines all query kinds, with rankings evaluated at `k=10`.

| Language | Previous tokenizer | Unicode tokenizer |
|---|---|---|
| English | 0.523 | 0.568 |
| Korean | 0.569 | 0.559 |
| Japanese | 0.061 | 0.782 |
| Chinese | 0.000 | 0.764 |
| Spanish | 0.599 | 0.673 |
| German | 0.590 | 0.681 |

### Lossless compressed index: 10,000 notes

| Measurement | Plain JSON cache | Compressed cache |
|---|---|---|
| Index on disk (decimal MB) | 15.79 MB | 3.27 MB |
| Retrieval rankings | Reference | Unchanged on every measured query |

Compression changes storage, not the tokenizer or scoring. See the source
report for query counts, per-author results, timings and reproduction commands.

<!-- SEMANTIC-RESULTS -->

### Retrieval credit

Credit to **omo recall PR #9209** for the fused-tie-break idea and the
evaluation lesson **"English must never get worse, per query"**. This is an
evaluation requirement, not a claim that the Unicode tokenizer has no
per-query regressions: its English average improves, but some queries lose rank.

## Install extras

```bash
pip install -e .                 # stdlib-only core
pip install -e ".[dev]"          # pytest, ruff
pip install -e ".[bench]"        # fastembed, numpy: embedding baselines only
pip install -e ".[mcp]"          # official MCP SDK and server
```

The extras are optional. `[bench]` reproduces embedding baselines; it does not
enable a semantic retrieval mode in this checkout.

## Trade-offs and honest limits

- **Korean does not improve in zero-dependency core mode.** MRR changes by
  -0.004 to -0.010 versus the previous tokenizer. At 10,000 notes the losses
  come from code-switched queries: English prefix stems also match English
  distractor notes. Hangul tokenization itself is unchanged.
- **Paraphrase recall is low.** Across the measured corpus sizes, low-overlap
  paraphrase MRR is about 0.2-0.27. Lexical matching cannot reliably bridge
  different words for the same idea or translate concepts between languages.
- **Smaller caches cost more to save.** At 10,000 notes cache saves are about
  75 ms slower because every save compresses the whole cache. Peak memory
  during loading is also higher.
- **Personal scale is the target.** Refresh checks note files, and latency
  grows with vault size. The laptop timings are single-run observations, not
  service-level guarantees.
- **Unicode coverage is not universal.** Scripts with combining vowel signs,
  such as Devanagari and Thai, are split at those signs by the current tokenizer.
- **Curation safety is narrower than correctness.** The gate bounds file
  operations; model choice still affects placement and linking quality.
  Python's explicit `purge_expired()` maintenance call can delete expired
  notes and is not exposed over MCP.

## Reference

> **On the name.** "Mnemosyne" is also the name of an unrelated concurrent
> system (a graph memory for edge LLMs, [Jonelagadda et al. 2025](https://arxiv.org/abs/2510.08601)).
> The two share only the mythological name — this is a stdlib BM25 vault with a
> curation-safety interface, not a graph store. The package imports as
> `birkin_mnemosyne` to keep them apart.

## CurationPlan/1 — safe curation on any model

Letting an agent reorganize your memory nightly is where things get dangerous.
The first time we ran it on a raw coding CLI, the model archived the *entire*
vault. The fix is an interface, not a smarter prompt:

```
model  ──emits──▶  typed JSON plan  ──▶  deterministic executor  ──▶  vault
(judgment only)     (rezone/link/            (validate · clamp ·        (safe,
                     supersede/archive)        apply · audit)            auditable)
```

The model **never touches the vault, tools, or a shell.** It returns exactly one
`CurationPlan`; a stdlib executor enforces every safety rule in code:

1. **Never delete** — the schema has no delete op; `archive` only *moves* a note.
2. **Archive cap** — at most `max(2, ⌈0.20·active⌉)` archives per pass.
3. **Protected notes** — `polarity: negative` warnings and control notes are never archived.
4. **`_archive` is not a zone**; **path containment** — every move stays inside the vault.
5. **Summary is inert** — free text is never a control signal; injection canaries are sanitized.

Unparseable output degrades to an empty plan (a safe no-op). Dense linking is
mechanical too: the model decides *which zone*, the executor links all
co-placed notes.

### Safety comes from the layer, not the schema

**A JSON schema does not stop a mass-archive** — every op is individually
well-formed. Only the executor's clamp holds. (Path-traversal and invented
slugs are inert even raw, because the file mover and slug lookup handle them one
layer down — an honest null, not the gate's doing.) Reproduce with
`python benchmarks/bench_safety_matrix.py`.

### Curation accuracy is model-bound, safety is not

Different engines curate at different accuracy. Model choice affects placement
and linking quality; the deterministic layer enforces the file-safety rules
regardless of the provider.

### Providers

Every backend reduces to `complete(prompt: str) -> str`; only a ~10-line
adapter differs, and it exists only to put the engine into a safe, plan-only
mode.

| provider | invocation | writes vault? | plan-format constraint |
|---|---|---|---|
| `claude` | `claude -p` (empty tool allow-list) | no | prompt-specified |
| `codex` | `codex exec --sandbox read-only --output-schema` | **no (read-only)** | **enforced JSON schema** |
| `api` | Anthropic Messages API via stdlib `urllib` | n/a | prompt-specified |
| `gemini` | `gemini -p -` | CLI default | prompt-specified |
| `local` | `ollama run <model>` | n/a | prompt-specified |

Or skip the registry entirely and pass your own function — that's how you wire
in openclaw, hermes, or a hosted gateway (see below).

---

## Use from another agent (openclaw / hermes / your own loop)

The only model surface is a `str -> str` callable, so you plug in whatever your
runtime already has:

```python
from birkin_mnemosyne import Mnemosyne, run_curation_pass

# 1) retrieval — give your agent a memory tool
mem = Mnemosyne(vault_path)
mem.refresh()
def recall(query: str) -> list[dict]:
    return mem.search(query, limit=8)

# 2) record what the agent actually used (drives decay/priority)
mem.record_access(note_slug)

# 3) nightly curation with YOUR model client
def my_complete(prompt: str) -> str:
    return my_agent_llm.generate(prompt)          # openclaw / hermes / HTTP

outcome = run_curation_pass(vault_path, my_complete, provider="custom")
```

`run_curation_pass` returns a `CurationOutcome` with the accepted/dropped ops,
the archive cap, and an audit summary — nothing is applied that the executor
did not clamp. Already have a plan as data (for example from an agent's tool
call)? `evaluate_plan(vault_path, plan)` runs the same gate as a dry run;
pass `apply=True` to apply it.

## MCP server (Claude Code, Claude Desktop, Codex CLI, Cursor)

The vault can be served over the [Model Context Protocol](https://modelcontextprotocol.io)
so any MCP client can remember, recall and curate. The server is an optional
extra — the core library stays stdlib-only — and runs with one command over
stdio:

```bash
uvx --from "birkin-mnemosyne[mcp] @ git+https://github.com/ashmoonori-afk/birkin-mnemosyne" \
    mnemosyne-mcp --vault ~/mnemosyne
```

(or `pip install "birkin-mnemosyne[mcp] @ git+https://github.com/ashmoonori-afk/birkin-mnemosyne"`
and run `mnemosyne-mcp`). The first launch downloads the SDK; if your client
times out on that first start, run the command once in a terminal.

| setting | how |
|---|---|
| vault directory | `--vault PATH`, else `$MNEMOSYNE_VAULT`, else `~/.birkin-mnemosyne/vault` |
| require a `source` for new notes | `--evidence-required` or `MNEMOSYNE_EVIDENCE_REQUIRED=1` |

**Claude Code**

```bash
claude mcp add --scope user mnemosyne -- \
  uvx --from "birkin-mnemosyne[mcp] @ git+https://github.com/ashmoonori-afk/birkin-mnemosyne" \
  mnemosyne-mcp --vault ~/mnemosyne
```

**Claude Desktop** (`claude_desktop_config.json`) and **Cursor**
(`~/.cursor/mcp.json` or `.cursor/mcp.json`) use the same shape:

```json
{
  "mcpServers": {
    "mnemosyne": {
      "command": "uvx",
      "args": [
        "--from", "birkin-mnemosyne[mcp] @ git+https://github.com/ashmoonori-afk/birkin-mnemosyne",
        "mnemosyne-mcp", "--vault", "~/mnemosyne"
      ]
    }
  }
}
```

**Codex CLI** (`~/.codex/config.toml`, or `codex mcp add mnemosyne -- uvx ...`):

```toml
[mcp_servers.mnemosyne]
command = "uvx"
args = ["--from", "birkin-mnemosyne[mcp] @ git+https://github.com/ashmoonori-afk/birkin-mnemosyne",
        "mnemosyne-mcp", "--vault", "~/mnemosyne"]
```

Point several clients at the same `--vault` to share one memory; writes are
serialized across server processes with a lock file.

### Tools

| tool | what it does | safe default |
|---|---|---|
| `memory_search` | BM25 + decay + zone ranked hits with snippets | read-only |
| `memory_get_note` | full note with its `version`; counts as a use | — |
| `memory_list` | notes by zone, paginated | read-only |
| `memory_remember` | write a note: `mode="create"` / `"append"` / `"replace"` | `create` never overwrites; `replace` needs `expected_version` |
| `memory_related` | mechanical link candidates for a note | read-only |
| `memory_forget` | move a note to `_archive` through the curation gate | dry run unless `confirm=true`; never deletes |
| `memory_restore` | move a note back out of `_archive` | — |
| `memory_curation_catalog` | structured catalog for writing a CurationPlan | read-only |
| `memory_curate` | run a CurationPlan/1 through the deterministic gate | dry run unless `apply=true` |

Plus the resources `mnemosyne://digest` (the prompt digest) and
`mnemosyne://note/{slug}`, and the prompt `curate_vault`. The calling agent is
the curator: it reads the catalog, writes a plan, and `memory_curate` clamps it
exactly like `run_curation_pass` would — protected notes stay put and the
archive cap applies to every call. Nothing exposed over MCP can hard-delete a
file (`purge_expired` stays a Python-only maintenance call). Note text returned
by the tools is stored data from earlier sessions; the server tells clients
not to follow instructions found inside it.

## Automatic role profiles

`ProfileMemory` records a conversation exchange immediately and reviews it on
one owned background worker. The reviewer returns JSON; `flush()` is the
durability boundary and surfaces malformed reviewer output.

```python
import json
from birkin_mnemosyne import ProfileMemory

def review(exchange):
    # Replace this deterministic example with your model client.
    return json.dumps({"profiles": {
        "preferences": "Prefers evidence before conclusions.",
        "soul": "Use direct Korean.",
    }})

with ProfileMemory(vault_path, review) as profiles:
    profiles.record_exchange(user_message, assistant_message)
    profiles.flush()
```

The protected `system/` directory contains exactly five role files:

| File | Guidance stored |
|---|---|
| `user.md` | User characteristics and stable personal context |
| `preferences.md` | Preferences and favored choices |
| `soul.md` | Conversation style and interaction guidance |
| `workflow.md` | Work process and execution guidance |
| `automation.md` | Workflow automation guidance |

By default, `ProfileMemory(vault_path, review)` bootstraps those files and
appends de-duplicated guidance lines. If you pass `save=callable`, no `system/`
directory or files are created; each reviewed exchange is parsed into a tuple of
`ProfileProposal` objects and delivered to that sink for caller-owned
persistence. Sink-mode instances cannot `read_profiles()` because they own no
files.

The reviewer contract is a JSON object with one `profiles` object. Profile keys
must be from the table. Values may be legacy non-empty strings, which become
`add` proposals after whitespace normalization, or ordered proposal lists such
as `[{"action":"replace","old_text":"old","content":"new"}]`. Actions are
`add`, `replace`, or `remove`; malformed JSON, unknown keys/actions, non-string
fields, and missing required text raise `ProfileReviewError` through `flush()`.
`close()` stops new submissions and releases the worker; the context manager
flushes and closes automatically. Run `python examples/automatic_profiles.py`
for an offline end-to-end example.

## API surface

```python
from birkin_mnemosyne import (
    Mnemosyne,          # the mechanical index/ranking engine
    VaultMemory,        # ergonomic write_note / rezone / digest wrapper
    ProfileMemory,      # background-reviewed role-profile persistence
    ProfileReviewError, # invalid reviewer output
    run_curation_pass,  # the safe curation driver
    evaluate_plan,      # gate a structured plan (dry run by default)
    get_completer,      # provider registry (claude|codex|api|gemini|local)
    validate_clamp,     # the gate, if you want to inspect a plan without applying
    build_plan_prompt, extract_plan, mechanical_catalog,
    slug, tokenize, bm25_scores,
)
```

Key `Mnemosyne` methods: `refresh()`, `search(query, limit, zone)`,
`related(slug)`, `record_access(slug)`, `stale()`, `rezone(slug, zone)`,
`zone_priorities()`, `stats()`.

## Tests & benchmarks

```bash
pytest -q                                  # stdlib only; MCP tests skip without [mcp]
python examples/quickstart.py              # write, search, decay (offline)
python benchmarks/bench_safety_matrix.py   # the defense-layer ablation above
python benchmarks/bench_korean_embed.py    # Korean/mixed vs multilingual-e5 (needs [bench])
```

The LongMemEval retrieval / end-to-end-QA harnesses and the full synthetic
suite live with the companion paper; this repo ships the self-contained ones.

## How it works (one idea, three times)

The same **mechanical/judgment split** recurs throughout:

1. **Retrieval** spends arithmetic (BM25, decay, zone EMA) and *no* model.
2. **Curation** spends the model on *placement judgment* only; the executor does
   the arithmetic (dense linking) and enforces safety.
3. **Safety** is code, not prompt-compliance — every invariant is a clamp.

> Let arithmetic do what arithmetic can, enforce safety in code, and spend the
> model only where judgment is genuinely required.

## Prior art & positioning

We are **not** first to any single idea here — memory palaces, local-first /
file-based agent memory, Ebbinghaus forgetting, and BM25 as a strong retriever
all have prior art. What we haven't found combined elsewhere is *this* pairing:
a **stdlib-only lexical substrate** (BM25 + usage decay + zone priority) with a
**provider-agnostic, plan-only curation interface whose file-safety is enforced
by a deterministic executor**. Where we sit relative to close concurrent work:

| system | shares | how we differ |
|---|---|---|
| [ByteRover](https://arxiv.org/abs/2604.01599) | local markdown memory, **no vector/graph DB, no embeddings** | ByteRover lets the LLM curate *and* retrieve; we reduce the model to a typed-plan generator and let a deterministic executor make + bound every file change |
| [Infini Memory](https://arxiv.org/abs/2606.10677) | text topic-documents, no mandatory vector DB | it consolidates + does multi-step agentic retrieval; we keep the vault verbatim and retrieval a single mechanical BM25 pass |
| [MemPalace](https://github.com/mempalace/mempalace) | local-first memory-palace, high LongMemEval band | MemPalace uses ChromaDB + embeddings; an [independent analysis](https://arxiv.org/abs/2604.21284) attributes its band to verbatim+embedding, not the metaphor — we reach a comparable band with **no vector store at all** |
| [Structured Distillation](https://arxiv.org/abs/2603.13017) | one-user memory, thematic "room" assignments | it *compresses* exchanges 11× (and finds BM25 degrades under that); we keep full notes, where lexical retrieval stays strong |
| [A-MEM](https://arxiv.org/abs/2502.12110) | Zettelkasten links, memory evolution | A-MEM judges links at write time over embedding candidates; we defer judgment to an offline batch and keep the hot path deterministic |
| [MemoryBank](https://arxiv.org/abs/2305.10250) | Ebbinghaus forgetting | we wire forgetting into the BM25 **ranking**, not into delete/update |
| [CaMeL](https://arxiv.org/abs/2503.18813) | plan-then-execute safety boundary | general tool-injection defense; we specialize it to the narrow `rezone/link/supersede/archive` file operations of memory curation |

**Honest framing:** *To our knowledge this specific stdlib-lexical + plan-only
safe-curation combination is new; the individual ingredients are not.* The
load-bearing empirical claims are (1) the zero-dependency substrate reaches a
competitive retrieval band with no embedding stack, and (2) safety comes from
the clamping executor, not the model or the schema.

## Design notes / constants

`BM25 k1=1.5 b=0.75 · strength +0.25/access cap 5.0 · stability init 7d ×1.5/spaced-access cap 365d · eff floor 0.05 · spacing gate 1h · zone EMA decay 0.9/day · rank boost W_dyn=0.3 W_zone=0.2 · stale: eff<0.1 & >90d · archive cap max(2, ⌈0.20·active⌉)`

## Vault layout and configuration

Notes are slug-named Markdown files with YAML frontmatter and `[[wikilinks]]`.
Zones are one-level directories; the vault root is the inbox.

```text
my_vault/
  inbox-note.md
  devops/
    ingress-dns.md
  people/
  projects/
  identity/
  knowledge/
  journal/
  system/                       # protected role files owned by ProfileMemory
  _archive/                     # soft-forgotten notes
  .mnemosyne-index.json.z        # rebuildable compressed index cache
  .mnemosyne-dynamics.json       # persistent usage state
```

`VaultMemory({"vault_path": "my_vault"})` selects the vault. The legacy `vault`
configuration key is also accepted; without either key the default is
`./vault`. `Mnemosyne` takes the path directly. Set `zone=` when writing to
choose placement; otherwise note types map to zones:

| Note type | Default zone |
|---|---|
| `person` | `people` |
| `project` | `projects` |
| `preference` | `identity` |
| `fact`, `topic` | `knowledge` |
| `session` | `journal` |

`_archive` is not an active curation zone. The cache can be rebuilt without
discarding usage state; the legacy `.mnemosyne-index.json` cache is removed on
the next save. Mixing older and newer library versions on one vault causes
repeated cache rebuilding. MCP path and evidence settings are listed in the
[MCP server reference](#mcp-server-claude-code-claude-desktop-codex-cli-cursor).

## License

MIT; see [LICENSE](LICENSE) and the attribution in [NOTICE](NOTICE).
Extracted from the Birkin project. The retrieval + curation design is
described in the companion paper *"Birkin-Mnemosyne: A Zero-Dependency Lexical
Memory Palace with Safe, Provider-Portable Curation for Personal LLM Agents"*.
