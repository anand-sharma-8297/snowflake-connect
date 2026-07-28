#!/usr/bin/env python3
"""Set up the Snowflake MCP server for Claude Code.

Writes a Snowflake connection entry, a read-only tool permission config, and
registers the MCP server with Claude Code. Safe to re-run: the connections file
is merged and backed up rather than overwritten, so other tools that share it
(SnowSQL, dbt, the Python connector) keep working.

Requires only the standard library.
"""

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

READ_ONLY_PERMISSIONS = """# Snowflake MCP tool permissions (read-only).
# Regenerate with the snowflake-connect skill; edit freely if you know what you want.
agent_services: []
search_services: []
analyst_services: []

other_services:
  object_manager: False
  query_manager: True
  semantic_manager: False

# Allow reads and metadata; deny everything else. "All: False" is the catch-all
# that keeps a future statement type from being permitted by omission.
sql_statement_permissions:
  - Select: True
  - Describe: True
  - Use: True
  - Command: True
  - All: False
"""

WRITE_ENABLED_PERMISSIONS = """# Snowflake MCP tool permissions (writes ENABLED).
# This agent can modify data under your role's permissions. Regenerate without
# --allow-writes to return to read-only.
agent_services: []
search_services: []
analyst_services: []

other_services:
  object_manager: True
  query_manager: True
  semantic_manager: True

sql_statement_permissions:
  - Select: True
  - Describe: True
  - Use: True
  - Command: True
  - Insert: True
  - Update: True
  - Delete: True
  - Merge: True
  - Create: True
  - Alter: True
  - Drop: False
  - TruncateTable: False
  - Unknown: False
"""

# TOML bare keys allow letters, digits, underscores and dashes. Anything else
# (notably the dots in legacy account locators) has to be quoted or TOML reads
# it as a nested table.
BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def log(msg=""):
    print(msg, flush=True)


def toml_section_header(name):
    return f"[{name}]" if BARE_KEY.match(name) else f'["{name}"]'


def toml_escape(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def build_section(name, fields):
    lines = [toml_section_header(name)]
    for key, value in fields.items():
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            lines.append(f"{key} = {str(value).lower()}")
        else:
            lines.append(f'{key} = "{toml_escape(value)}"')
    return "\n".join(lines) + "\n"


def merge_connection(existing_text, name, section_text):
    """Replace this connection's section, or append it, leaving others intact."""
    if not existing_text.strip():
        return section_text, "created"

    # Match either the bare or quoted spelling of the header, since a file
    # written by another tool may differ from what we would emit.
    header = re.compile(
        r"^[ \t]*\[[ \t]*\"?" + re.escape(name) + r"\"?[ \t]*\][ \t]*$",
        re.MULTILINE,
    )
    match = header.search(existing_text)
    if not match:
        joiner = "" if existing_text.endswith("\n\n") else (
            "\n" if existing_text.endswith("\n") else "\n\n"
        )
        return existing_text + joiner + section_text, "appended"

    next_header = re.compile(r"^[ \t]*\[", re.MULTILINE)
    following = next_header.search(existing_text, match.end())
    if following:
        end = following.start()
        section_text += "\n"  # keep the blank line that separated the sections
    else:
        end = len(existing_text)
    updated = existing_text[: match.start()] + section_text + existing_text[end:]
    return updated, "updated"


def secure(path):
    """Snowflake refuses a connections.toml other users can read."""
    if os.name != "nt":
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError as exc:
            log(f"  ! could not tighten permissions on {path}: {exc}")


def run(cmd, **kwargs):
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kwargs
    )


def require_tools():
    missing = []
    for tool, hint in (("uv", "https://astral.sh/uv"), ("claude", "the Claude Code CLI")):
        if shutil.which(tool) is None:
            missing.append(f"  - {tool} not found on PATH (install: {hint})")
    if missing:
        log("Missing prerequisites:")
        log("\n".join(missing))
        return False
    return True


def prewarm():
    """Download the server package before registering.

    Claude's health check has a short timeout. Against a cold cache the first
    launch spends a minute pulling ~100 packages, the check gives up, and a
    perfectly good setup is reported as "Failed to connect".
    """
    log("Pre-warming the uvx package cache (first run downloads ~100 packages)...")
    started = time.time()
    result = run(["uvx", "snowflake-labs-mcp", "--help"])
    if result.returncode != 0:
        log("  ! could not pre-fetch snowflake-labs-mcp:")
        log(result.stderr.strip()[:2000])
        return False
    log(f"  ok ({time.time() - started:.0f}s)")
    return True


def verify_server(config_file, connection_name):
    """Speak MCP to the server directly, which surfaces errors the health check hides."""
    log("Verifying the server starts and can read its config...")
    handshake = (
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":'
        '"2024-11-05","capabilities":{},"clientInfo":{"name":"setup","version":"1"}}}\n'
    )
    try:
        result = subprocess.run(
            [
                "uvx", "snowflake-labs-mcp",
                "--service-config-file", str(config_file),
                "--connection-name", connection_name,
            ],
            input=handshake,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        log("  ! server did not respond within 3 minutes")
        return False

    if '"result"' in result.stdout and "serverInfo" in result.stdout:
        log("  ok")
        return True
    log("  ! server did not complete the handshake:")
    log((result.stderr or result.stdout).strip()[:2000])
    return False


def register(name, config_file, connection_name, force):
    existing = run(["claude", "mcp", "get", name])
    if existing.returncode == 0:
        if not force:
            log(f"  ! an MCP server named '{name}' is already registered; leaving it alone.")
            log("    Re-run with --force to replace it, or pass --server-name to use another name.")
            return False
        log(f"  replacing existing '{name}' registration")
        run(["claude", "mcp", "remove", name])

    result = run([
        "claude", "mcp", "add", "--scope", "user", name, "--",
        "uvx", "snowflake-labs-mcp",
        "--service-config-file", str(config_file),
        "--connection-name", connection_name,
    ])
    if result.returncode != 0:
        log("  ! registration failed:")
        log((result.stderr or result.stdout).strip()[:2000])
        return False
    log(f"  registered '{name}' at user scope (available in every directory)")
    return True


def health_check(name):
    log("Running Claude's own health check...")
    result = run(["claude", "mcp", "list"])
    for line in result.stdout.splitlines():
        if line.strip().startswith(f"{name}:"):
            healthy = "Connected" in line
            log(f"  {'ok' if healthy else '!'} {line.strip()[:160]}")
            return healthy
    log("  ! server did not appear in `claude mcp list`")
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Set up the Snowflake MCP server for Claude Code.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n"
               "  python setup_snowflake_mcp.py --account ORG-ACCOUNT \\\n"
               "      --user me@company.com --role ANALYST --warehouse COMPUTE_WH",
    )
    parser.add_argument("--account", required=True,
                        help="Account identifier, e.g. ORGNAME-ACCOUNTNAME (from the Snowflake URL)")
    parser.add_argument("--user", required=True, help="Snowflake username (often your email with SSO)")
    parser.add_argument("--role", help="Default role")
    parser.add_argument("--warehouse", help="Default warehouse (strongly recommended)")
    parser.add_argument("--database", help="Default database")
    parser.add_argument("--schema", help="Default schema")
    parser.add_argument("--authenticator", default="externalbrowser",
                        help="Auth method (default: externalbrowser for SSO)")
    parser.add_argument("--private-key-file", help="Path to private key, for --authenticator snowflake_jwt")
    parser.add_argument("--connection-name", help="Name for the connections.toml entry (default: the account)")
    parser.add_argument("--server-name", default="snowflake", help="MCP server name in Claude (default: snowflake)")
    parser.add_argument("--config-dir", default=str(Path.home() / ".snowflake"),
                        help="Snowflake config directory (default: ~/.snowflake)")
    parser.add_argument("--allow-writes", action="store_true",
                        help="Permit INSERT/UPDATE/CREATE. Off by default; only pass if explicitly requested.")
    parser.add_argument("--force", action="store_true", help="Replace an existing MCP server of the same name")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without changing it")
    args = parser.parse_args()

    if args.authenticator == "externalbrowser" and args.private_key_file:
        parser.error("--private-key-file needs --authenticator snowflake_jwt")

    connection_name = args.connection_name or args.account
    config_dir = Path(args.config_dir).expanduser()
    connections_path = config_dir / "connections.toml"
    tools_path = config_dir / "mcp_tools_config.yaml"

    section = build_section(connection_name, {
        "account": args.account,
        "user": args.user,
        "authenticator": args.authenticator,
        "role": args.role,
        "warehouse": args.warehouse,
        "database": args.database,
        "schema": args.schema,
        "private_key_file": args.private_key_file,
        # Caches the SSO token so later sessions reconnect without a browser
        # prompt. Requires ALLOW_ID_TOKEN=TRUE on the account to take effect.
        "client_store_temporary_credential": args.authenticator == "externalbrowser" or None,
    })

    existing = connections_path.read_text(encoding="utf-8") if connections_path.exists() else ""
    merged, action = merge_connection(existing, connection_name, section)
    permissions = WRITE_ENABLED_PERMISSIONS if args.allow_writes else READ_ONLY_PERMISSIONS

    if args.dry_run:
        log("DRY RUN — nothing will be written.\n")
        log(f"{connections_path}  ({action} section {toml_section_header(connection_name)})")
        log("-" * 60)
        log(section)
        log(f"{tools_path}  ({'writes enabled' if args.allow_writes else 'read-only'})")
        log("-" * 60)
        log(permissions)
        log("Would then register with Claude Code:")
        log(f"  claude mcp add --scope user {args.server_name} -- uvx snowflake-labs-mcp \\")
        log(f"      --service-config-file {tools_path} --connection-name {connection_name}")
        return 0

    if not require_tools():
        return 1

    config_dir.mkdir(parents=True, exist_ok=True)

    if existing:
        backup = connections_path.with_suffix(f".toml.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(connections_path, backup)
        log(f"Backed up existing connections to {backup}")

    connections_path.write_text(merged, encoding="utf-8")
    secure(connections_path)
    log(f"{action.capitalize()} connection '{connection_name}' in {connections_path}")

    tools_path.write_text(permissions, encoding="utf-8")
    log(f"Wrote tool permissions to {tools_path} "
        f"({'WRITES ENABLED' if args.allow_writes else 'read-only'})")

    if not prewarm():
        return 1
    if not verify_server(tools_path, connection_name):
        log("\nThe config was written but the server would not start. "
            "See references/troubleshooting.md.")
        return 1
    if not register(args.server_name, tools_path, connection_name, args.force):
        return 1

    healthy = health_check(args.server_name)

    log("\n" + "=" * 60)
    if healthy:
        log("Snowflake is connected.")
    else:
        log("Setup finished, but the health check did not report Connected.")
        log("Re-run `claude mcp list` once — a slow first launch can trip it.")
    log("=" * 60)
    log("\nWhat to expect:")
    log("  1. Start a NEW Claude Code session — MCP tools load at session start,")
    log("     so this session cannot see them yet.")
    log("  2. Ask something like: \"list the tables in <database>\"")
    if args.authenticator == "externalbrowser":
        log("  3. Your browser opens once per session for SSO sign-in, not once per query.")
    if not args.warehouse:
        log("  4. No default warehouse is set. If a query reports no active warehouse,")
        log(f"     add  warehouse = \"<name>\"  under [{connection_name}] in connections.toml.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
