# Birkin-Mnemosyne

**A zero-dependency memory palace + safe, provider-portable curation for LLM agents.**

> **On the name.** "Mnemosyne" is also the name of an unrelated concurrent
> system (a graph memory for edge LLMs, [Jonelagadda et al. 2025](https://arxiv.org/abs/2510.08601)).
> The two share only the mythological name — this is a stdlib BM25 vault with a
> curation-safety interface, not a graph store. The package imports as
> `birkin_mnemosyne` to keep them apart.

Long-term memory for an LLM agent usually means infrastructure — an embedding
model, a vector database, a graph server, and an LLM call on every write.
Birkin-Mnemosyne asks how much a *personal-scale* agent (one user, one machine,
thousands of notes) actually needs, and answers with the Python standard
library alone:

- **Retrieval** — Markdown notes in *zone* directories, an Okapi-BM25 inverted
  index with a Korean-aware bigram tokenizer, and a usage-driven Ebbinghaus
  decay wired straight into the ranking. Greppable, diffable, no dependencies.
- **Curation** — *CurationPlan/1*: the model emits only a typed JSON plan; a
  deterministic executor validates, clamps, and applies it under **file-safety
  invariants enforced in code**, so a weak or adversarial model *cannot* delete,
  mass-archive, escape the vault, or archive a protected note.

It is the memory subsystem extracted from the [Birkin](https://github.com/ashmoonori-afk/birkin)
personal agent, packaged so it can be dropped into **any** agent runtime —
openclaw, hermes, or your own loop.

```python
from birkin_mnemosyne import Mnemosyne, run_curation_pass, get_completer

mem = Mnemosyne("my_vault"); mem.refresh()
hits = mem.search("kubernetes ingress dns")          # BM25 + usage/zone boosts

run_curation_pass("my_vault", get_completer("codex"), provider="codex")
# ...or pass any complete(prompt: str) -> str you already have.
```

- 🧱 **Zero runtime dependencies** (stdlib only). `fastembed`/`numpy` are needed
  *only* to reproduce the embedding baselines.
- 🔌 **Any model**: Claude / Codex / Gemini / Ollama CLIs, the Anthropic API, or
  your own `str -> str` function.
- 🛡️ **Safe by construction**: the executor clamps every plan; safety does not
  depend on the model following instructions.
- 📄 Backed by a benchmark suite and a companion paper (excerpts below).

---

## Why lexical, at personal scale?

Personal-memory queries are dominated by named anchors — project names, people,
commands, error strings — exactly the high-idf tokens BM25 rewards. We did not
just *assume* the embedding stack was unnecessary; we **measured what it would
have added**, in the same harness over the identical sessions.

### Session retrieval — LongMemEval-S (470 questions, cleaned split)

| system | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|
| BM25 + bigram (this library) | 0.870 | 0.968 | 0.981 | 0.910 |
| dense embedding, truncated (bge-small) | 0.770 | 0.932 | 0.966 | 0.842 |
| dense embedding, chunked + max-pool | 0.855 | 0.968 | 0.981 | 0.908 |
| best hybrid (RRF k=20, BM25 + chunked) | 0.894 | 0.977 | **0.994** | 0.931 |
| **tuned lexical stack (no encoder)** | **0.900** | **0.977** | 0.981 | **0.933** |
| substring scan (the naive baseline) | 0.089 | 0.343 | 0.577 | 0.223 |

Read honestly, in three steps. (1) BM25 beats *truncated* dense retrieval
(+0.10 R@1) — but that gap is a **truncation artifact**: chunked dense ties
BM25. (2) A tuned RRF hybrid buys a small, real margin (+0.02 MRR) over BM25.
(3) A dev-tuned, arithmetic-only lexical stack (query-side idf weighting,
user-turn field weighting, a relative-date prior — every ingredient classic
IR) **buys that margin back with no encoder at all**: parity with the best
embedding hybrid we measured. Fairness control: rerun BM25 on the *same*
6k-char-truncated text the embedder saw and it still wins (R@5 0.953 vs
0.932) — the lexical edge over truncated dense is not an input-length
artifact.

### From retrieval to answers (end-to-end QA)

BM25 top-5 → a cheap reader (Claude haiku) → an LLM judge vs the gold answer,
all 500 questions:

| condition | n | accuracy |
|---|---|---|
| answerable questions | 470 | **0.538** |
| abstention questions | 30 | **0.80** |

Retrieval finds the evidence for 96.8 % of questions but the small reader
answers 53.8 % — **the binding constraint is usually the reader, not the memory
layer.** An oracle-evidence control (hand the reader the labeled sessions)
decomposes the two losses:

| condition | single-session-user | multi-session |
|---|---|---|
| BM25 top-5 → reader | 0.72 | 0.41 |
| oracle evidence → reader | **0.80** | **0.67** |

Single-evidence questions are reader-bound (0.72 already near the 0.80 ceiling);
multi-session questions are where retrieval *also* costs ~26 points and a higher
`k` or a stronger reader would pay off.

### Korean & code-switched queries

BM25 + Hangul bigrams vs a real multilingual encoder (`multilingual-e5-large`),
16 notes × 3 query styles:

| Korean query style | BM25 + bigram R@5 | multilingual-e5 R@5 |
|---|---|---|
| exact | 1.00 | 1.00 |
| partial / reworded | 1.00 | 1.00 |
| mixed (Korean + English) | 0.94 | 1.00 |

The bigram tokenizer ties the multilingual model on monolingual Korean; the
model's only edge is **code-switching**, where an English word must map to a
Korean concept — the one case a lexical tokenizer can't bridge. (Dropping the
bigrams leaves the English numbers unchanged: the feature costs English
nothing.)

### The ranking signals do their job

Identical-body twin notes, one rehearsed and in a hot zone; fraction of pairs
where it outranks its cold twin:

| ranking | wins | ties |
|---|---|---|
| BM25 only | 0.00 | 1.00 |
| BM25 + decay | 1.00 | 0.00 |
| BM25 + zone priority | 1.00 | 0.00 |
| BM25 + decay + zone | 1.00 | 0.00 |

With identical text BM25 is a dead tie; either usage-decay or zone-priority
breaks it deterministically. Forgetting is a *ranking signal* — a well-rehearsed
note (5 spaced reads) stays retrievable ~166 days; an untouched one fades toward
the floor in ~2–3 weeks.

---

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

Five attack plans × three defense levels on a 6-note vault (one protected note):

| attack | raw apply | schema-only | **full executor** |
|---|---|---|---|
| mass-archive-all | all 6 gone, protected GONE | all 6 gone, protected GONE | **capped at 2, protected safe** |
| archive protected note | protected GONE | protected GONE | **intact** |
| injection-canary plan | all 6 gone, protected GONE | all 6 gone, protected GONE | **capped at 2, protected safe** |
| path-traversal zone/slug | intact | intact | intact |
| invented slugs | intact | intact | intact |

**A JSON schema does not stop a mass-archive** — every op is individually
well-formed. Only the executor's clamp holds. (Path-traversal and invented
slugs are inert even raw, because the file mover and slug lookup handle them one
layer down — an honest null, not the gate's doing.) Reproduce with
`python benchmarks/bench_safety_matrix.py`.

### Curation accuracy is model-bound, safety is not

On a deliberately hard 232-pair fixture (13 clusters with overlapping
vocabulary + 15 distractors), scored with a decontaminated prompt, over 3 runs
each:

| engine | link recall | link precision | distractor links |
|---|---|---|---|
| Claude · sonnet | 0.87 | **0.85** | 0 |
| Claude · haiku | 0.88 | 0.76 | 0 |
| Codex · gpt-5.3-codex-spark | 0.83 | 0.74 | ≤6 |

Different engines curate at different accuracy — but **every pass from every
engine stayed within the file-safety invariants.** Model choice maximizes
accuracy; the deterministic layer guarantees safety.

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

## Install

```bash
pip install -e .                 # zero runtime deps
pip install -e ".[dev]"          # + pytest, ruff
pip install -e ".[bench]"        # + fastembed, numpy (embedding baselines only)
```

Requires Python ≥ 3.10.

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
did not clamp.

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
pytest -q                                  # 93 tests, stdlib only
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

## License

MIT. Extracted from the Birkin project. The retrieval + curation design is
described in the companion paper *"Birkin-Mnemosyne: A Zero-Dependency Lexical
Memory Palace with Safe, Provider-Portable Curation for Personal LLM Agents"*.
