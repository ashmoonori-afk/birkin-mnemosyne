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
  read-only on Windows. Neither application was opened, closed or configured.

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
| [Cursor](https://prod.cursor.com/docs/mcp) | Project `.cursor/mcp.json` or global `~/.cursor/mcp.json`, **B**. | Docs + protocol; installed Windows 3.17.19 metadata checked. | Config and agent approval still need an actual client test. Cloud agents cannot assume a local PC's paths. |
| [JetBrains AI Assistant](https://www.jetbrains.com/help/ai-assistant/mcp.html) | Settings > Tools > AI Assistant > Model Context Protocol (MCP); add STDIO JSON **B**, select global/project scope. | Docs + protocol: subprocess stdio supported. | UI-managed configuration; no undocumented config-file path asserted. Server enablement and tool approvals apply; no IDE launch test. |
| [Zed](https://zed.dev/docs/ai/mcp) | User settings JSON (`~/.config/zed/settings.json` on macOS/Linux), **C**. | Docs + protocol: compatible launch contract. | Enable the context server and allow agent tools; no Zed launch test. |
| [Windsurf / Cascade](https://docs.windsurf.com/windsurf/cascade/mcp) | Cascade's menu > MCPs > Open MCP config file, **B**. Current official page redirects to Devin's legacy-Cascade docs: `~/.config/devin/mcp_config.json` on macOS/Linux, `%APPDATA%/devin/mcp_config.json` on Windows. | Docs + protocol: Cascade stdio supported. | Version-dependent location: open the installed build's config from its UI rather than assuming the current path. Devin Local uses a different config; enterprise MCP may require admin enablement. No Windsurf launch test. |
| [Google Antigravity](https://www.antigravity.google/docs/mcp?tab=ide) | Antigravity 2.0: global `~/.gemini/config/mcp_config.json` or project `.agents/mcp_config.json`, **B**. | Docs + protocol; installed Windows 2.0.6 metadata checked. | Refresh/enable the server and approve tools. Older IDE versions may use another path; no application launch or config edits. |
| [Herdr](https://herdr.dev/llms.txt) | Configure the agent inside its pane; no separate Herdr Mnemosyne MCP-client file. Tested omo project `.omo/mcp.json`, **E**. | **Real agent launch + two successful memory tool calls**, Herdr 0.9.3. | Herdr's integrations report agent lifecycle/session metadata; memory belongs to the agent's MCP setup, not terminal scrollback. |
| Orca | Product name ambiguous; see candidates below. | Primary sources only; child-agent stdio launch contract tested independently. | No Orca application installed/launched. Identify the intended product before choosing a config surface. |
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

## Which Orca?

The name alone does not uniquely identify an AI coding product:

| Candidate / primary source | What it is | Mnemosyne connection / evidence |
|---|---|---|
| [stablyai/orca](https://github.com/stablyai/orca) / [onorca.dev](https://www.onorca.dev/) | Desktop/mobile workspace for parallel terminal coding agents, each in a worktree. | Configure its Claude Code/Codex/other child agent using that agent's MCP file. Docs-only host compatibility; not tested in Orca. |
| [Haroon966/Orca](https://github.com/Haroon966/Orca) | Self-hosted web IDE focused on Claude Code, with MCP management. | Claude Code's MCP configuration, **B**, or its MCP management UI. Product-specific persistence/UI not independently verified. |
| [orca-cli/orca](https://github.com/orca-cli/orca) | Go agent orchestrator which also serves its own MCP tools. | Its `orca mcp serve` is a server, not the Mnemosyne client configuration. Configure the child agent separately. Do not copy its Codex examples over the official Codex TOML contract. |
| [echoVic/orca-agent](https://github.com/echoVic/orca-agent) | DeepSeek-native Rust coding agent with MCP support. | Potential direct host; its exact installed-version config schema and launch remain unverified. |
| [mcp-com-ai/orca](https://github.com/mcp-com-ai/orca) | OrcA VS Code extension converting OpenAPI/Arazzo contracts into MCP servers. | Not the same product as an agent workspace. No verified general-client setup for this memory server; use a documented IDE MCP agent instead. |

## Using memory after connection

Ask the agent to call `memory_search` for a known note, then
`memory_startup_read` with a vault-relative file in `paths`, for example
`{"paths": ["knowledge/team-rules.md"]}`. This reads the complete source rather
than a search snippet. `memory_startup_verify` can check its returned context.
Connecting a server does not prove the IDE will automatically read memory
on every session or retain all server instructions in its model context;
the host's agent workflow must actually use the tools.
