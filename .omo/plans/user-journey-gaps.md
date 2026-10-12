# User-journey gaps: ideal state, gaps, plan, QA

Base: main `4b258d8` (0.7.0 + #79). Evidence captured 2026-10-12 on Windows 11,
Python 3.12.11, mcp 2.3.0, in a fresh `.venv` (`uv pip install -e .[dev,mcp]`).

## Who uses this and how

1. **Agent user (main persona).** Installs `birkin-mnemosyne[mcp]`, adds
   `mnemosyne-mcp --vault ~/mnemosyne` to Claude Code / Codex / Cursor, and lets
   the agent remember, search and hand off sessions. Follows the README literally.
   Often Korean-speaking, often on Windows.
2. **Terminal check.** The same user opens a terminal to see what the agent
   stored, to resume a handoff, or to undo something: `mnemosyne ...`.
3. **Library user.** Imports `Mnemosyne` / `VaultMemory` in Python (unchanged here).

## Ideal state (user's point of view)

- I1. Every call the README tells an agent to make succeeds as written.
- I2. The terminal command and the MCP server agree on which vault they use
  with the same settings (`--vault`, `$MNEMOSYNE_VAULT`, default), and `~` works.
- I3. I can see what my agent remembered from the terminal (search, list, show)
  without writing Python and without changing usage ranking.
- I4. I can undo what `mnemosyne init --apply` did from the terminal.
- I5. `mnemosyne --version` answers like every other CLI (and like `mnemosyne-mcp`).
- I6. An agent user finds "install -> connect -> check" near the top of the
  README (EN and KO in parity), and every documented command matches the code.
- I7. No existing command, flag, JSON key, exit code or test changes behavior
  except where listed below (no regressions).

## Gaps found (evidence)

| # | Gap | Evidence |
|---|---|---|
| G1 | `memory_startup_read` / `memory_startup_verify` require `paths`; the README resume flow ("call `memory_startup_read` with the same project/task keys") and a `task`-only read fail with `paths Field required` | MCP stdio client, `{"project_key":"example/project","task_key":"release"}` -> is_error=True; same with `{"paths":[]}` added -> complete=true |
| G2 | `mnemosyne check/split/handoff` without `--vault` exit 2 (`--vault is required`) and ignore `$MNEMOSYNE_VAULT`; `mnemosyne-mcp` uses `--vault > $MNEMOSYNE_VAULT > ~/.birkin-mnemosyne/vault`; `init` uses cwd and also ignores the env | `MNEMOSYNE_VAULT=<vault> mnemosyne check` -> exit 2; `memory_index_cli.py` main() |
| G3 | CLI does not expand `~` in `--vault` (MCP does), so `--vault ~/mnemosyne` from PowerShell/quoted shells creates a literal `~` directory | `git grep expanduser`: only mcp_server.py and memory.py |
| G4 | No terminal way to search/list/show notes | `mnemosyne search dns` -> `invalid choice: 'search'` |
| G5 | Init undo is documented as Python-only (`Consolidation(vault).undo`), while `handoff undo` already calls the same function but is described as fold-only | README "First run"; handoff_cli.py `_undo` |
| G6 | `mnemosyne --version` -> exit 2 `the following arguments are required: command` | CLI run |
| G7 | README is ~1,000 lines; the MCP connection steps sit after all benchmark tables (~line 590); `init` output does not name the vault path it acted on | README read; init JSON keys |

Out of scope, reported as follow-ups: `ruff check .` reports 68 findings with
ruff 0.17 and no ruff gate exists in CI; `memory_get_note` takes `note` while
search results name the field `slug` (renaming would break clients).

## Target behavior (binding for implementation)

- B1 (G1). `paths` defaults to an empty list in `memory_startup_read` and
  `memory_startup_verify` (still `max_length=64`). Calls with keys/task and no
  `paths` behave exactly like the same call with `paths: []`. Empty reads with
  nothing to read keep the existing error text.
- B2 (G2, G3). One CLI resolver: `--vault` (either position) > `$MNEMOSYNE_VAULT`
  > for `init`: current directory (unchanged documented default); for every other
  command: `~/.birkin-mnemosyne/vault` (the `mnemosyne-mcp` default, reuse
  `mcp_server.DEFAULT_VAULT`). `~` is expanded for `--vault` and `--import`.
  The CLI never creates the vault directory for read commands. `init` JSON adds
  one key `"vault"` with the resolved absolute path (additive).
- B3 (G4). New read-only commands, JSON on stdout, UTF-8:
  `mnemosyne search QUERY [--limit N=10] [--zone Z]` -> `{"results":[...]}`
  same item shape as MCP `memory_search`; `mnemosyne list [--zone Z]
  [--limit N] [--offset N]` -> same shape as MCP `memory_list`;
  `mnemosyne show NOTE` -> same shape as MCP `memory_get_note`, exit 1 when
  absent. None of them records access or changes `.mnemosyne-dynamics.json`
  or note files; a nonexistent vault directory is exit 2 with a clear message.
- B4 (G5). `mnemosyne undo --transaction ID` runs the same checked undo as
  `handoff undo` (identical output and exit codes); `handoff undo` stays.
- B5 (G6). `mnemosyne --version` prints `birkin-mnemosyne <version>` exit 0.
- B6 (G7). README.md and README.ko.md gain a short agent quick start near the
  top and document B1-B5; CHANGELOG gains an Unreleased section.

## QA scenarios (binary)

- Q1 MCP stdio (official SDK client): `memory_handoff_capture` then
  `memory_startup_read {"project_key":"example/project","task_key":"release"}`
  -> is_error False, complete True, context contains the capture path;
  `memory_startup_read {"task":"Check release"}` on an INDEX-enabled vault ->
  is_error False. `memory_startup_read {}` on an empty vault -> is_error True
  with the existing "nonempty list" text.
- Q2 CLI resolution: with `MNEMOSYNE_VAULT=<V>` and no `--vault`,
  `mnemosyne check` exit 0 reports V's INDEX; `mnemosyne handoff latest
  --project-key p` exit 0 returns the capture; `--vault ~/<tmpname>` resolves
  under the home dir (no `./~` created); `init` JSON `vault` == abs(V).
- Q3 CLI notes: after MCP `memory_remember` of a Korean note, `mnemosyne search
  릴리스` exit 0 lists it with Korean intact under a cp1252 console setting;
  `.mnemosyne-dynamics.json` sha256 unchanged by search/list/show;
  `mnemosyne show missing` exit 1; `mnemosyne search x --vault <nonexistent>`
  exit 2 and the directory still does not exist.
- Q4 Undo: `mnemosyne init --apply` on a vault with a frontmatter-less note,
  then `mnemosyne undo --transaction <undo_transaction>` exit 0 and the note
  bytes equal the original sha256.
- Q5 Version: `mnemosyne --version` stdout `birkin-mnemosyne 0.7.0`, exit 0.
- Q6 Regression: full `pytest -q` matches the baseline counts plus new tests,
  zero new failures; `ruff check` on changed files reports nothing new.
- Q7 Docs: every new command in README.md/README.ko.md runs as printed;
  `tests/test_readme_links.py` green.
