# Use from IDEs and agent workspaces

Verification snapshot: **2026-10-11**. birkin-mnemosyne serves local Markdown
memory over **stdio MCP**, not an HTTP endpoint. The IDE's agent must support
local subprocess servers; an editor without such an agent is not itself a
memory client.

## What was actually verified

- PyPI `birkin-mnemosyne[mcp]==0.6.0` and a separately built main checkout at
  `876ad40` ran on macOS (Python 3.14.4) and Windows 11 (Python 3.13).
- Official Python MCP SDK 2.3.0 launched each installed package using the
  absolute Python command and module arguments shown below. Both
  `MNEMOSYNE_VAULT` and `--vault` worked with paths containing spaces.
- Each package/OS combination passed both legacy `initialize`
  (protocol `2025-11-25`) and automatic discovery (protocol `2026-07-28`),
  listed 22 tools, found a fixture with `memory_search`, read it completely
  with `memory_startup_read`, and passed `memory_startup_verify`.
  A missing search query returned a tool error. Temporary vaults were removed.
- A real omo agent in a new isolated Herdr 0.9.3 pane successfully called
  `memory_search` and `memory_startup_read`. The owner's existing sessions
  were preserved and the temporary session was deleted.
- Cursor 3.17.19 and Antigravity 2.0.6 installation metadata was inspected
  read-only on Windows. With owner approval, only Cursor's global MCP file
  was backed up, given a temporary server using a throwaway venv/vault, and
  restored **byte-identical** to the backup. Existing server values were
  preserved. The fixture passed SDK search/startup reads, but an actual
  in-Cursor call remains **NEED existing login**. After a further owner-approved
  headless attempt, official Cursor Agent CLI `2026.10.01-e373342` ran from a
  temporary user-level directory. Its actual `status` returned `Not logged in`,
  so no login or model/tool call was attempted. No Windows GUI was driven,
  no running app was restarted, and Antigravity's configuration was unchanged.
  Temporary installations and newly generated CLI settings were cleaned.

**Protocol verification is not an IDE launch test.** The matrix distinguishes
the shared server launch contract from each application's own configuration
and permission handling. No IDE application was installed for these checks.
No package incompatibility was reproduced, so no runtime fix was needed.

## Install and choose paths

Install before enabling the IDE server, to avoid an initial package download
inside the IDE's startup timeout:

```bash
python3 -m venv ~/.venvs/mnemosyne
~/.venvs/mnemosyne/bin/python -m pip install "birkin-mnemosyne[mcp]==0.6.0"
```

Windows PowerShell equivalent:

```powershell
py -3.13 -m venv "$HOME/.venvs/mnemosyne"
& "$HOME/.venvs/mnemosyne/Scripts/python.exe" -m pip install "birkin-mnemosyne[mcp]==0.6.0"
```

The configuration examples use replaceable **absolute paths**. Set `command`
to the Python executable you just installed and `MNEMOSYNE_VAULT` to your
chosen memory directory. On Windows, for example:

```json
{
  "command": "C:/Users/your-user/.venvs/mnemosyne/Scripts/python.exe",
  "args": ["-m", "birkin_mnemosyne.mcp_server"],
  "env": {"MNEMOSYNE_VAULT": "C:/Users/your-user/memory vault"}
}
```

Do not put extra shell quotes inside a JSON path, even when it contains
spaces. Each `args` element is one argument. `--vault` can replace the env
entry: `["-m", "birkin_mnemosyne.mcp_server", "--vault", "/absolute/memory vault"]`.
Several clients can share a vault; the server serializes writes across
processes. A remote SSH/container agent needs paths and installation in the
environment where its server actually runs.

## Client matrix

The configuration letters refer to complete snippets below. All source links
were consulted on 2026-10-11. "Docs + protocol" means the official client
schema was checked and its server launch tuple passed the SDK checks above,
**not** that the IDE loaded the configuration.

| Client | Connection / configuration location | Verified how / result | Gaps or required setup |
|---|---|---|---|
| [VS Code Copilot agent](https://code.visualstudio.com/docs/agent-customization/mcp-servers) | Local stdio; project `.vscode/mcp.json`, **A**. Current docs also support portable project `.mcp.json`, **B**. | Docs + protocol: compatible launch contract. | Trust/enable the server and approve tools. Agent Host handling differs from the extension host; no VS Code launch test. |
| [Cursor](https://prod.cursor.com/docs/mcp) | Project `.cursor/mcp.json` or global `~/.cursor/mcp.json`, **B**. | Docs + protocol; Windows 3.17.19 config added/restored byte-identical; actual temporary Agent CLI version/status executed. | **NEED existing login**: CLI returned `Not logged in`, so actual Cursor-agent tool calls were not performed. No sign-in or Windows GUI action; see the headless section below. |
| [JetBrains AI Assistant](https://www.jetbrains.com/help/ai-assistant/mcp.html) | Settings > Tools > AI Assistant > Model Context Protocol (MCP); add STDIO JSON **B**, select global/project scope. | Docs + protocol: subprocess stdio supported. | UI-managed configuration; no undocumented config-file path asserted. Server enablement and tool approvals apply; no IDE launch test. |
| [Zed](https://zed.dev/docs/ai/mcp) | User settings JSON (`~/.config/zed/settings.json` on macOS/Linux), **C**. | Docs + protocol: compatible launch contract. | Enable the context server and allow agent tools; no Zed launch test. |
| [Windsurf / Cascade](https://docs.windsurf.com/windsurf/cascade/mcp) | Cascade's menu > MCPs > Open MCP config file, **B**. Current official page redirects to Devin's legacy-Cascade docs: `~/.config/devin/mcp_config.json` on macOS/Linux, `%APPDATA%/devin/mcp_config.json` on Windows. | Docs + protocol: Cascade stdio supported. | Version-dependent location: open the installed build's config from its UI rather than assuming the current path. Devin Local uses a different config; enterprise MCP may require admin enablement. No Windsurf launch test. |
| [Google Antigravity](https://www.antigravity.google/docs/mcp?tab=ide) | Antigravity 2.0: global `~/.gemini/config/mcp_config.json` or project `.agents/mcp_config.json`, **B**. | Docs + protocol; installed Windows 2.0.6 metadata checked. | Refresh/enable the server and approve tools. Older IDE versions may use another path; no application launch or config edits. |
| [Herdr](https://herdr.dev/llms.txt) | Configure the agent inside its pane; no separate Herdr Mnemosyne MCP-client file. Tested omo project `.omo/mcp.json`, **E**. | **Real agent launch + two successful memory tool calls**, Herdr 0.9.3. | Herdr's integrations report agent lifecycle/session metadata; memory belongs to the agent's MCP setup, not terminal scrollback. |
| [Orca IDE](https://www.onorca.dev/docs) | Its [agent picker launches CLI processes](https://www.onorca.dev/docs/agents/supported); configure the chosen agent in the active worktree: Claude `.mcp.json`, **B**, or trusted-project Codex `.codex/config.toml`, **D**. | Official IDE docs + shared agent stdio protocol; no Orca application installed/launched. | No standalone Orca MCP file asserted. Agent permissions, account-managed homes and local/SSH/WSL runtime paths matter; see the Orca section below. |
| [Claude Code](https://code.claude.com/docs/en/mcp) | Project `.mcp.json`, **B**; user scope can be managed with `claude mcp add`. | Docs + protocol: compatible launch contract. | Project-server approval and tool permissions apply; no Claude Code launch test. |
| [Codex CLI](https://developers.openai.com/codex/mcp/) | `~/.codex/config.toml` or trusted project `.codex/config.toml`, **D**. | Docs + protocol: compatible launch contract. | Confirm MCP startup and tool permissions in the actual CLI; no Codex launch test. |

### A: VS Code format

```json
{
  "servers": {
    "mnemosyne": {
      "type": "stdio",
      "command": "/absolute/path/to/mnemosyne-venv/bin/python",
      "args": ["-m", "birkin_mnemosyne.mcp_server"],
      "env": {"MNEMOSYNE_VAULT": "/absolute/path/to/memory-vault"}
    }
  }
}
```

### B: mcpServers format

Cursor, JetBrains, Cascade, Antigravity and Claude Code use this local
command/args/env structure. VS Code also supports it in portable `.mcp.json`.
Cursor's documented stdio entry includes `type`; the other clients' local
examples infer stdio from `command`, so omit `type` there.

```json
{
  "mcpServers": {
    "mnemosyne": {
      "command": "/absolute/path/to/mnemosyne-venv/bin/python",
      "args": ["-m", "birkin_mnemosyne.mcp_server"],
      "env": {"MNEMOSYNE_VAULT": "/absolute/path/to/memory-vault"}
    }
  }
}
```

For Cursor, add `"type": "stdio"` to `mnemosyne`. Keep any other existing
servers when adding this entry; these examples are not instructions to replace
an entire configuration file.

### C: Zed

```json
{
  "context_servers": {
    "mnemosyne": {
      "command": "/absolute/path/to/mnemosyne-venv/bin/python",
      "args": ["-m", "birkin_mnemosyne.mcp_server"],
      "env": {"MNEMOSYNE_VAULT": "/absolute/path/to/memory-vault"}
    }
  }
}
```

### D: Codex CLI

```toml
[mcp_servers.mnemosyne]
command = "/absolute/path/to/mnemosyne-venv/bin/python"
args = ["-m", "birkin_mnemosyne.mcp_server"]

[mcp_servers.mnemosyne.env]
MNEMOSYNE_VAULT = "/absolute/path/to/memory-vault"
```

### E: omo inside Herdr

This is an **omo** configuration, not a Herdr configuration:

```json
{
  "mcpServers": {
    "mnemosyne": {
      "type": "stdio",
      "command": "/absolute/path/to/mnemosyne-venv/bin/python",
      "args": ["-m", "birkin_mnemosyne.mcp_server"],
      "env": {"MNEMOSYNE_VAULT": "/absolute/path/to/memory-vault"},
      "includeTools": ["memory_search", "memory_startup_read"],
      "exposure": "direct",
      "lifecycle": "eager"
    }
  }
}
```

The verification intentionally exposed only these two read tools. Omit
`includeTools` to expose other memory tools according to omo's configuration
and permissions. Claude Code or Codex running inside Herdr instead uses its
own configuration above. Herdr exposes pane/agent CLI and socket APIs plus
[agent lifecycle integrations](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.3/docs/next/website/src/content/docs/integrations.mdx);
that is distinct from being a general MCP client.

## Orca IDE at onorca.dev

The selected product is the [Orca IDE](https://www.onorca.dev/docs), not an
unidentified same-name CLI/server/extension. Its official docs say every task
has a worktree, agent terminal and browser tab, and the agent picker launches
CLI processes. Use the agent's MCP configuration, not a guessed `.orca/mcp.json`.

For **Claude Code**, put this in `.mcp.json` in the **active Orca worktree**,
replace the absolute paths, and approve the project server in the agent:

```json
{
  "mcpServers": {
    "mnemosyne": {
      "command": "/absolute/path/to/mnemosyne-venv/bin/python",
      "args": ["-m", "birkin_mnemosyne.mcp_server"],
      "env": {"MNEMOSYNE_VAULT": "/absolute/path/to/memory-vault"}
    }
  }
}
```

For **Codex**, the **trusted active worktree's** `.codex/config.toml` can use
the complete **D** snippet. Orca supports managed account homes; do not assume
every account resolves `~/.codex` to the same directory. A config in the
original checkout is not necessarily present in a new worktree: copy it to the
active worktree or deliberately manage it with the repository. For SSH/WSL
agents, install the venv and use vault paths in that execution environment.

Relevant first-party sources, accessed 2026-10-11:

- [Supported agents](https://www.onorca.dev/docs/agents/supported): any CLI
  agent; configurable launch arguments/environment. Orca currently defaults
  supported agents to bypass permissions; use **Settings > Agents > Agent
  Permissions > Manual** when you want prompts.
- [Hooks and memory](https://www.onorca.dev/docs/agents/hooks-memory): respects
  `.claude/` / `.codex/` conventions and agent-owned `CLAUDE.md` / `AGENTS.md`.
  These files/hooks are not themselves a Mnemosyne MCP connection.
- [Native chat](https://www.onorca.dev/docs/agents/native-chat): tool activity
  includes MCP work; [Claude integration](https://www.onorca.dev/docs/agents/claude-code)
  retains shared MCP sign-ins across account swaps.
- [Codex integration](https://www.onorca.dev/docs/agents/codex): account-managed
  homes and Windows/WSL behavior; [Cursor CLI integration](https://www.onorca.dev/docs/agents/cursor-cli)
  uses the separately installed agent CLI.
- [Editor](https://www.onorca.dev/docs/editing/monaco): Monaco editing and
  language features. No general VS Code extension-install or Orca-specific
  MCP extension API was established from these docs; no extension is required
  for the documented agent-side stdio setup.
- Agent-side schema: [Claude MCP](https://code.claude.com/docs/en/mcp) and
  [Codex MCP](https://developers.openai.com/codex/mcp/).

This is **docs + independently tested agent launch contract**, not a tool
call inside an installed Orca instance.

## Cursor headless Agent follow-up

The approved Windows file test demonstrated safe addition and exact
restoration, not that Cursor loaded the server. Its temporary memory/identity
roots both pointed to the throwaway vault, and the separate empty GUI workspace
did not contain the original-config backup. Everything was cleaned afterward.

The installed desktop `cursor` command and bundled files did not provide the
needed supported headless Agent entrypoint. With owner approval, the official
native Windows payload was installed into a temporary user directory, without
executing the default installer's PATH changes or existing-install deletion.
The actual CLI returned version `2026.10.01-e373342`; `agent status` returned
**`Not logged in`**. Its exit code was 0, which does not imply authentication.
The attempt stopped at that explicit boundary: no login, API-key creation,
credential import, model invocation, scheduled task or desktop workaround.

For a future already-authenticated run, prefer the empty test workspace's
`.cursor/mcp.json` (**B**) and a throwaway vault. The planned calls are only
`memory_search({"query":"CURSOR_NATIVE_SENTINEL_20261011"})` and
`memory_startup_read({"paths":["knowledge/cursor-compatibility-fixture.md"]})`.
[CLI permissions](https://cursor.com/docs/cli/reference/permissions) use
`Mcp(server:tool)` tokens; project-specific permissions live in
`<project>/.cursor/cli.json`. Do not substitute broad `--approve-mcps` approval
for the two requested tools. Actual completed tool events must contain the
marker and `complete: true`; a model's prose is not evidence.

Because authentication was absent, this trial did not provision the new
workspace MCP setup or run those calls. The earlier SDK/config test remains
valid, but **native tool calls by Cursor Agent CLI are not available in this
tested unauthenticated state**. The temporary package was removed; a default
CLI config created by version/status was removed because it was absent before
the test. The original global MCP file remained unchanged.

Official sources, accessed 2026-10-11:
[installation](https://cursor.com/docs/cli/installation),
[authentication/status](https://cursor.com/docs/cli/reference/authentication),
[configuration](https://cursor.com/docs/cli/reference/configuration),
[headless output](https://cursor.com/docs/cli/headless).

## Using memory after connection

Ask the agent to call `memory_search` for a known note, then
`memory_startup_read` with a vault-relative file in `paths`, for example
`{"paths": ["knowledge/team-rules.md"]}`. This reads the complete source rather
than a search snippet. `memory_startup_verify` can check its returned context.
Connecting a server does not prove the IDE will automatically read memory
on every session or retain all server instructions in its model context;
the host's agent workflow must actually use the tools.
