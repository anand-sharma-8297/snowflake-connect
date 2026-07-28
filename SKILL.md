---
name: snowflake-connect
description: Connect a user's Snowflake account to Claude Code by setting up the Snowflake MCP server, with SSO (Google/Okta/Azure via externalbrowser), key-pair, or token authentication. Use this skill whenever someone wants to connect Snowflake to Claude, query their Snowflake data warehouse or tables from Claude, set up snowflake-labs-mcp, fix a Snowflake MCP server showing "Failed to connect", or asks why Claude can't see their Snowflake data — even if they never say the words "MCP" or "connector".
---

# Connect Snowflake to Claude Code

This sets up a local MCP server that lets Claude browse schemas and run queries against the user's own Snowflake account. It runs on their machine under their own Snowflake identity, so it inherits exactly the permissions their role already has — nothing more.

Two defaults are deliberate, and worth keeping unless the user asks otherwise:

- **SSO (`externalbrowser`) authentication.** Snowflake opens the user's browser for their normal corporate sign-in (Google, Okta, Azure AD — all the same to Snowflake). No password, key, or token is ever written to disk, which is what makes this safe to hand to a colleague.
- **Read-only SQL.** Only `SELECT`, `DESCRIBE`, `SHOW`, and `USE` are permitted. An agent that can `DROP TABLE` on a production warehouse is a bad trade for the small convenience of writes. Users who genuinely need writes can opt in, but make them ask.

## Step 1 — Collect connection details

Ask for these in one message rather than one at a time. Most people know their username and not much else, so lead with how to find the account identifier — it's the field that actually blocks people.

**Account identifier (required).** Tell them to open Snowflake in a browser and look at the URL:

```
https://app.snowflake.com/ORGNAME/ACCOUNTNAME/...   →   use  ORGNAME-ACCOUNTNAME
```

So `https://app.snowflake.com/rzb47281/acme_prod/worksheets` means the identifier is `RZB47281-ACME_PROD`. Note the **hyphen** joining the two parts — a common mistake is using a dot or leaving it out. Older accounts sometimes use a locator like `xy12345.us-east-1` instead; that works too, pass it as-is.

**Username (required).** With SSO this is usually their full corporate email address.

**Role, warehouse, database, schema (optional but recommended).** Setting a default warehouse is worth pushing for: without one, the first query fails with "No active warehouse selected in the current session", which reads like a broken setup but isn't. If they don't know their warehouse, proceed anyway and mention they can add it later.

**Authentication method.** Default to SSO. Only reach for something else if the user says they don't use SSO, or they need unattended/scheduled runs where nobody is present to click a browser prompt — read `references/auth-methods.md` before setting up key-pair or token auth.

## Step 2 — Check prerequisites

The server runs via `uvx`, which ships with `uv`:

```bash
uv --version
```

If that fails, install `uv` — on macOS/Linux `curl -LsSf https://astral.sh/uv/install.sh | sh`, on Windows `winget install --id=astral-sh.uv`. Confirm the `claude` CLI is on PATH too (`claude --version`), since registration goes through it.

## Step 3 — Run the setup script

The script writes the config files, registers the MCP server, and verifies it — all idempotently, so it's safe to re-run:

```bash
python scripts/setup_snowflake_mcp.py --account ORGNAME-ACCOUNTNAME --user someone@company.com --role SOME_ROLE --warehouse SOME_WH
```

Useful flags:

- `--dry-run` — print exactly what would change without touching anything. Good for cautious users, and good for you when the user already has a config you don't want to disturb.
- `--connection-name NAME` — names the entry in `connections.toml`. Defaults to the account identifier.
- `--allow-writes` — permits INSERT/UPDATE/CREATE/etc. Only pass this if the user explicitly asked.
- `--authenticator` — for non-SSO setups; see `references/auth-methods.md`.
- `--force` — re-register a server whose name is already taken.

The script merges into an existing `connections.toml` rather than overwriting it, and backs the file up first, so other Snowflake connections the user already has (SnowSQL, the Python connector, dbt) keep working.

**Expect the first run to take a minute or two.** It pre-warms the `uvx` cache by downloading ~100 Python packages. This step exists because of a real failure mode: if you skip it and register first, Claude's health check times out against the cold download and reports `Failed to connect` on a setup that is actually fine. Don't debug that phantom — let the script pre-warm.

## Step 4 — Verify

The script runs both checks itself and prints the results, but if you're diagnosing by hand:

```bash
claude mcp list
```

A healthy setup shows `snowflake: uvx snowflake-labs-mcp ... - ✓ Connected`. If it doesn't, work through `references/troubleshooting.md` — it maps each error message to its actual cause, which is frequently not what the message suggests.

## Step 5 — Set expectations before handing back

Three things reliably confuse people afterward, so say them explicitly:

1. **The tools appear in the next session, not this one.** MCP servers load at session start, so the session that ran the setup can't use them. Have them start a new Claude Code session and ask something like "list the tables in <database>".
2. **The browser prompt is once per session, not once per query.** The connection is opened on the first query and reused. The script also enables `client_store_temporary_credential`, which caches the SSO token so later sessions reconnect silently — though this only works if the Snowflake account has `ALLOW_ID_TOKEN = TRUE`. If they get a prompt every single session, that's the flag to ask their admin about, not a bug in the setup.
3. **It's read-only.** Claude can explore and query but not modify. If they later want writes, re-run with `--allow-writes`.

## When this approach isn't the right one

This skill sets up the community `snowflake-labs-mcp` server running locally. Snowflake also offers a **hosted** MCP server, created inside the account with `CREATE MCP SERVER` plus an OAuth security integration. That version is better for teams — central governance, no per-machine setup, works from claude.ai and mobile rather than only Claude Code — but it requires a Snowflake admin with `ACCOUNTADMIN` to set up, so it isn't self-service. If the user is an admin, or is asking on behalf of a whole team rather than themselves, mention it as the more durable option: https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp
