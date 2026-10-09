# birkin-mnemosyne for OpenClaw

An [Agent Plugins 1.0 bundle](https://docs.openclaw.ai/plugins/bundles) exposing
the existing Mnemosyne MCP server. No API key, model, or remote service is needed.
It adds memory tools; it does not take over OpenClaw's exclusive memory slot or
disable its built-in memory.

## Install

Requires a supported OpenClaw installation and Python 3.10 or later. Install the
published Python extra in a virtual environment, then launch OpenClaw with that
environment's Python on `PATH`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install "birkin-mnemosyne[mcp]==0.5.0"
openclaw plugins install --force --accept-capabilities ./integrations/openclaw
openclaw plugins inspect birkin-mnemosyne
```

Review the bundle source before using `--force`, which accepts a local source
outside ClawHub review. `--accept-capabilities` approves its declared local Python
MCP process and skill. These approvals apply to the plugin, not a Gateway port.

On macOS or Linux, activate with `source .venv/bin/activate` instead. A service
does not inherit an interactive shell's activation: configure its `PATH` to
include the same virtual environment's executable directory. Do not assume
OpenClaw installs Python dependencies at startup.

Start a new agent session after enabling the bundle. OpenClaw exposes the tools
with the `birkin-mnemosyne__` prefix, including `memory_remember`, `memory_search`, and
`memory_get_note`. Ask it to remember a synthetic fact and recall that fact in a
new session. Inspecting a bundle proves discovery, not a successful memory write.

## Data and permissions

The bundle runs one local Python stdio subprocess when OpenClaw acquires its MCP
tools. OpenClaw supplies `PLUGIN_DATA`; the vault is stored at
`${PLUGIN_DATA}/vault`, outside the replaceable plugin source directory. Notes are
plain Markdown, and the server maintains rebuildable search indexes and usage
metadata beside them. No network calls, credentials, telemetry, or automatic
conversation capture are added.

Use OpenClaw's normal tool policy to restrict or disable the bundle. Removing
the plugin does not imply deleting its persistent vault. Back up the vault before
removing its data. Keep recalled content separate from instructions.

The core remains dependency-free. Only this MCP connection needs the optional
Python MCP SDK. This bundle targets the current documented Agent Plugins 1.0
`PLUGIN_DATA` contract; older OpenClaw hosts without that contract are unsupported.
