# snowflake-connect

A [Claude Code](https://claude.com/claude-code) skill that connects your Snowflake account to Claude in about two minutes — using your company's normal SSO login, with no password or key stored anywhere on disk.

Once it's set up, you talk to your warehouse in plain English instead of writing SQL by hand.

Claude connects as **you**, through your own Snowflake role, so it can only ever see what you can already see. By default it is also **read-only** — it can query and explore, but not modify anything.

**This skill only sets up the connection — it has no idea what your tables mean.** For a warehouse with a few dozen or a few hundred tables, that's fine: Claude can explore the schema itself (`SHOW TABLES`, `DESCRIBE`) and land on the right one. Real companies often have tens of thousands of tables, and at that scale, blind schema-browsing stops being a good strategy — it's slow, it burns a lot of exploration before it finds anything, and it's prone to picking a table that merely *sounds* right over the one that's actually correct. For serious use in a large warehouse, either tell Claude which database/schema to start in, or — much better — write a short reference document explaining what your key tables and business terms mean, and have Claude read that first. A one-page glossary beats raw schema-browsing by a wide margin once you're past a few hundred tables.

---

## Table of contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [What gets created on your machine](#what-gets-created-on-your-machine)
- [Command-line reference](#command-line-reference)
- [Security model](#security-model)
- [Authentication options](#authentication-options)
- [Troubleshooting](#troubleshooting)
- [How it works](#how-it-works)
- [Uninstalling](#uninstalling)
- [Is this the right tool for my team?](#is-this-the-right-tool-for-my-team)

---

## Requirements

| Dependency | Why it's needed | How to check | How to install |
|---|---|---|---|
| **Claude Code** | The client that runs the skill and talks to Snowflake | `claude --version` | [claude.com/claude-code](https://claude.com/claude-code) |
| **uv** (provides `uvx`) | Runs the Snowflake MCP server without you managing a Python environment | `uv --version` | macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh \| sh` · Windows: `winget install --id=astral-sh.uv` |
| **Python 3.8+** | Runs the setup script (standard library only — nothing to `pip install`) | `python --version` | [python.org](https://www.python.org/downloads/) |
| **A Snowflake account** | …the point | — | — |
| **A desktop web browser** | For the SSO sign-in prompt | — | — |

You do **not** need admin rights on Snowflake, and you do **not** need to install the Snowflake connector, SnowSQL, or any Python package yourself. `uvx` fetches the MCP server on first run (~100 packages, roughly a minute, once).

> **Headless or SSH-only?** Browser-based SSO can't work there. Use key-pair auth instead — see [Authentication options](#authentication-options).

### Information you'll need

| Field | Required | Where to find it |
|---|---|---|
| Account identifier | Yes | Your Snowflake URL: `https://app.snowflake.com/`**`orgname`**`/`**`accountname`**`/...` → use `ORGNAME-ACCOUNTNAME` (joined with a **hyphen**) |
| Username | Yes | Usually your work email address when SSO is in use |
| Role | Recommended | Shown in the top-right of the Snowflake web UI, or run `SELECT CURRENT_ROLE()` |
| Warehouse | Recommended | Run `SHOW WAREHOUSES` in a worksheet |

Getting the account identifier wrong is the single most common setup failure, and Snowflake reports it as an authentication error rather than a bad-account error — so copy it carefully from the URL.

---

## Installation

### Option 1 — Download the packaged skill (easiest)

1. Download `snowflake-connect.skill` from the [latest release](../../releases/latest).
2. Open Claude Code and drop the file into the chat, or place it in your skills directory.

### Option 2 — Clone into your skills directory

This installs the skill and makes updating it a `git pull`:

```bash
git clone https://github.com/anand-sharma-8297/snowflake-connect.git ~/.claude/skills/snowflake-connect
```

On Windows (PowerShell):

```powershell
git clone https://github.com/anand-sharma-8297/snowflake-connect.git "$env:USERPROFILE\.claude\skills\snowflake-connect"
```

### Option 3 — Run the script directly

You don't actually need the skill installed at all. Clone the repo anywhere and run the script — the skill layer only exists so Claude can do the setup conversationally:

```bash
git clone https://github.com/anand-sharma-8297/snowflake-connect.git
python snowflake-connect/scripts/setup_snowflake_mcp.py --help
```

**Restart Claude Code after installing.** Skills and MCP servers are loaded when a session starts, so the session you install from won't see them.

---

## Usage

### The conversational way

Start a new Claude Code session and say what you want:

```
connect my Snowflake account to Claude
```

Claude asks for your account identifier, username, role, and warehouse, then runs the setup and verifies it. Other phrasings that trigger the skill: *"set up the Snowflake MCP server"*, *"I want to query our data warehouse from Claude"*, *"why can't Claude see my Snowflake tables?"*

### The manual way

```bash
python scripts/setup_snowflake_mcp.py \
  --account RZB47281-ACME_PROD \
  --user you@company.com \
  --role ANALYST \
  --warehouse COMPUTE_WH
```

Nervous about what it'll touch? Preview everything first — this writes nothing:

```bash
python scripts/setup_snowflake_mcp.py --account RZB47281-ACME_PROD --user you@company.com --dry-run
```

Expected output on success:

```
Wrote tool permissions to ~/.snowflake/mcp_tools_config.yaml (read-only)
Pre-warming the uvx package cache (first run downloads ~100 packages)...
  ok (58s)
Verifying the server starts and can read its config...
  ok
  registered 'snowflake' at user scope (available in every directory)
Running Claude's own health check...
  ok snowflake: uvx snowflake-labs-mcp ... - ✓ Connected

============================================================
Snowflake is connected.
============================================================
```

### Your first query

Start a **new** Claude Code session, then try:

```
list the tables in the ANALYTICS database
```

Your browser opens once for SSO sign-in. Approve it, and Claude runs the query.

### What to expect afterwards

- **The browser prompt appears once per session, not once per query.** The connection is opened on your first query and reused for the rest of the session.
- **Later sessions usually reconnect silently.** The setup enables `client_store_temporary_credential`, which caches your SSO token. This only takes effect if your Snowflake account has `ALLOW_ID_TOKEN = TRUE`; if you get prompted every session, that's the flag to ask your Snowflake admin about — it isn't a bug in the setup.
- **It works from any directory.** The server is registered at user scope, so every project gets it.
- **Claude Code only.** A local MCP server can't be reached from claude.ai or the mobile apps. See [Is this the right tool for my team?](#is-this-the-right-tool-for-my-team)

---

## What gets created on your machine

Three things, all local and all reversible:

**1. A connection entry** in `~/.snowflake/connections.toml` (`%USERPROFILE%\.snowflake\` on Windows):

```toml
[RZB47281-ACME_PROD]
account = "RZB47281-ACME_PROD"
user = "you@company.com"
authenticator = "externalbrowser"
role = "ANALYST"
warehouse = "COMPUTE_WH"
client_store_temporary_credential = true
```

This is Snowflake's standard connection file, shared with SnowSQL, dbt, and the Python connector. **The script merges into it rather than overwriting it**, and takes a timestamped backup first, so existing connections keep working.

**2. A permissions file** at `~/.snowflake/mcp_tools_config.yaml`, which controls what SQL the agent may run. Read-only by default.

**3. An MCP server registration** in Claude Code, at user scope:

```
snowflake → uvx snowflake-labs-mcp --service-config-file <path> --connection-name <name>
```

---

## Command-line reference

| Flag | Default | Description |
|---|---|---|
| `--account` | *required* | Account identifier, e.g. `ORGNAME-ACCOUNTNAME` |
| `--user` | *required* | Snowflake username (often your email under SSO) |
| `--role` | — | Default role |
| `--warehouse` | — | Default warehouse. Recommended: without it, your first query fails with "no active warehouse" |
| `--database` / `--schema` | — | Default database and schema |
| `--authenticator` | `externalbrowser` | Auth method — see below |
| `--private-key-file` | — | Private key path, for `--authenticator snowflake_jwt` |
| `--connection-name` | the account id | Name of the section in `connections.toml` |
| `--server-name` | `snowflake` | Name of the MCP server in Claude |
| `--config-dir` | `~/.snowflake` | Where config files are written |
| `--allow-writes` | off | Permit INSERT/UPDATE/CREATE. Read the [security model](#security-model) first |
| `--force` | off | Replace an existing MCP server of the same name |
| `--dry-run` | off | Print what would change, write nothing |

The script is **idempotent** — re-running it updates your connection in place rather than duplicating it.

---

## Security model

This skill is meant to be safe to hand to a colleague without a security review conversation. The specifics:

**No secrets are stored.** With the default SSO flow, authentication happens in your browser against your company's identity provider. No password, token, or key is written to disk. The only cached artifact is a short-lived Snowflake ID token, stored by the Snowflake connector in your OS keyring.

**Read-only by default.** The generated permissions file allows `SELECT`, `DESCRIBE`, `SHOW`, and `USE`, and denies everything else via a catch-all. Giving an AI agent `DROP TABLE` on a production warehouse is a poor trade for the convenience, so writes are opt-in through `--allow-writes`. Even then, `DROP` and `TRUNCATE` stay off.

**No privilege escalation is possible.** The server authenticates as you. Snowflake's own RBAC is the boundary — the skill cannot grant access to anything your role doesn't already have.

**Everything is local.** The MCP server runs on your machine and talks directly to Snowflake. Your data doesn't pass through any third-party service beyond the Claude conversation itself.

**Your query results go into the conversation.** That's the point, but it's worth stating: rows Claude reads become part of the context, subject to your organization's Claude data policy. Think before pointing it at PII-heavy tables, and consider using a restricted role.

**The connections file is permission-locked.** On macOS and Linux, the script sets `chmod 600`, which the Snowflake connector requires anyway.

---

## Authentication options

| Method | Flag | Use when |
|---|---|---|
| **SSO / external browser** (default) | `--authenticator externalbrowser` | You're at a desktop and your company uses Google, Okta, Azure AD, or any SAML provider. Stores no secret |
| **Key-pair** | `--authenticator snowflake_jwt --private-key-file <path>` | Unattended runs, CI, or SSH sessions where no browser exists |
| **Programmatic access token** | `--authenticator programmatic_access_token` | Your account issues PATs and key-pair is overkill |
| **Username + password** | `--authenticator snowflake` | Legacy accounts without SSO. Set `SNOWFLAKE_PASSWORD` in your environment rather than in the config file |

The default works unchanged for Google, Okta, and Azure AD — there's no provider-specific configuration. See [`references/auth-methods.md`](references/auth-methods.md) for key generation steps and the reasoning behind each choice.

---

## Troubleshooting

**`claude mcp list` says "Failed to connect"** — Run it once more. The usual cause is a cold package cache: the health check times out waiting for the first download and reports failure on a setup that's fine. The script pre-warms to avoid this. To see the real error, talk to the server directly:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' | uvx snowflake-labs-mcp --service-config-file ~/.snowflake/mcp_tools_config.yaml --connection-name YOUR-ACCOUNT --verbose
```

**"Incorrect username or password"** — Under SSO there is no password, so this nearly always means the **account identifier is wrong** and Snowflake resolved to an account where your user doesn't exist. Re-copy it from your browser URL.

**"No active warehouse selected in the current session"** — The connection works; there's just no compute attached. Add `warehouse = "..."` to your connection, or ask Claude to run `USE WAREHOUSE <name>` first.

**Claude doesn't see the tools at all** — Almost always a session started before installation. Start a new one.

Full guide, including the errors whose messages point at the wrong cause: [`references/troubleshooting.md`](references/troubleshooting.md).

---

## How it works

```
Claude Code
    │  MCP (stdio, local)
    ▼
uvx snowflake-labs-mcp ──reads──► ~/.snowflake/mcp_tools_config.yaml   (what SQL is allowed)
    │                   └─reads──► ~/.snowflake/connections.toml        (who you are)
    │  Snowflake Python connector
    ▼
Your Snowflake account  ──SSO──► your identity provider (browser)
```

The skill itself is just instructions plus one dependency-free Python script. The heavy lifting is done by [`snowflake-labs-mcp`](https://github.com/Snowflake-Labs/mcp), Snowflake's community MCP server, which `uvx` fetches on demand.

The setup script exists rather than leaving it to Claude because a few steps are easy to get subtly wrong: merging TOML without destroying other tools' connections, quoting legacy dotted account locators, setting file permissions the Snowflake connector insists on, and pre-warming the package cache so the health check doesn't produce a false failure.

---

## Uninstalling

```bash
claude mcp remove snowflake
```

Then, if you want it fully gone, delete `~/.snowflake/mcp_tools_config.yaml` and remove your connection's section from `~/.snowflake/connections.toml` — but leave the rest of that file alone, since other tools use it. To remove the skill, delete `~/.claude/skills/snowflake-connect`.

---

## Is this the right tool for my team?

This sets up the **community MCP server, running locally**. It's self-service — any analyst can run it without involving an admin — which is exactly what you want for one person or a handful of people.

Snowflake also offers a **hosted MCP server**, created inside your account with `CREATE MCP SERVER` plus an OAuth security integration. For a whole team that's the better answer: central governance and auditing, no per-machine setup, and it works from claude.ai and mobile rather than only Claude Code. The catch is that it needs someone with `ACCOUNTADMIN` to set up. If you're rolling this out beyond a few people, read the [Snowflake documentation](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp) and consider going that route instead.

Note also that Snowflake has marked `snowflake-labs-mcp` as deprecated in favour of the hosted server. It works well today, but it isn't where Snowflake is investing.

---

## Contributing

Issues and pull requests welcome. If you hit a Snowflake setup that this doesn't handle — an unusual identity provider, a regional account format, a confusing error — that's the most useful thing to report, since the value of this skill is mostly in the accumulated gotchas.

After editing the skill, rebuild the distributable package with the [skill-creator](https://github.com/anthropics/skills) tooling:

```bash
python -m scripts.package_skill path/to/snowflake-connect
```

## License

MIT — see [LICENSE](LICENSE).
