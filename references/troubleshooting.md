# Troubleshooting the Snowflake MCP connection

Errors here are often reported by a layer far from the actual cause, so match on the message and check the stated cause before changing anything.

## `claude mcp list` shows "Failed to connect"

**First, re-run it once.** The most common cause by far is a cold `uvx` cache: the health check has to wait for ~100 packages to download and gives up first. The setup script pre-warms to prevent this, but if the package was updated since, you'll hit it again. Confirm by running the server by hand — it should print a FastMCP banner within a few seconds:

```bash
uvx snowflake-labs-mcp --help
```

If it's still failing after the cache is warm, run the server directly and read the actual error. This is the highest-value diagnostic step, because the health check hides stderr:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' | uvx snowflake-labs-mcp --service-config-file <path-to-tools-config> --connection-name <name> --verbose
```

A working server prints `Using external authentication`, then a JSON result line. Anything else is the real error.

## "250001 (08001): Failed to connect to DB: ... Incorrect username or password"

With SSO this almost never means the password is wrong — there is no password. It usually means the **account identifier is wrong**, and Snowflake resolved to an account where that user doesn't exist. Re-derive it from the browser URL (`ORGNAME-ACCOUNTNAME`, joined with a hyphen).

## "No active warehouse selected in the current session"

The connection works; there's just no compute attached to run the query. Either add `warehouse = "..."` to the connection's section in `connections.toml`, or have Claude run `USE WAREHOUSE <name>` first. If the user doesn't know what warehouses exist, `SHOW WAREHOUSES` works without one.

## The browser opens on every single query

It shouldn't — one connection is reused for the whole session. If it truly opens per query, the server is likely crashing and restarting between calls; run the manual handshake above to see why.

Once per *session* is expected behavior. To reduce that, `client_store_temporary_credential = true` must be in the connection config **and** the Snowflake account must have `ALLOW_ID_TOKEN = TRUE`, which only an admin can set. Without the account flag, the client-side setting silently does nothing.

## The browser never opens, or it hangs

`externalbrowser` needs a real desktop browser session. It cannot work over plain SSH, in a container, or in CI. Those environments need key-pair or token auth — see `auth-methods.md`.

## Claude doesn't see the Snowflake tools at all

Almost always one of:

1. **The session predates the setup.** MCP servers are loaded at session start. Start a new session.
2. **Registered to the wrong scope.** `claude mcp add --scope user` makes it available in every directory; `--scope local` (the default) ties it to one project. Check with `claude mcp list` from a *different* folder.
3. **Expecting it outside Claude Code.** A local stdio MCP server only works in Claude Code on that machine — not on claude.ai, not on mobile. That needs the hosted Snowflake MCP server instead.

## "Statement type not permitted" / Claude refuses to write data

Working as intended — the default config is read-only. Re-run the setup script with `--allow-writes` if the user actually wants this, and make sure they understand the agent can then modify data under their role's permissions.

## Permission warnings about connections.toml on macOS/Linux

The Snowflake connector refuses or warns on a `connections.toml` readable by other users. Fix:

```bash
chmod 600 ~/.snowflake/connections.toml
```

The setup script does this automatically, but a file restored from backup or copied from another machine can lose it.

## Starting over

Remove the registration and re-run setup. Config files in `~/.snowflake` can stay — other tools may be using them.

```bash
claude mcp remove snowflake
```
