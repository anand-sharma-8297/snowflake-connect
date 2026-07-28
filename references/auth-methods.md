# Authentication methods other than SSO

Prefer `externalbrowser` (the default) whenever a human is present at a desktop: it stores no secret on disk, and it inherits whatever MFA the company already enforces. Reach for these alternatives only when that isn't possible.

## Key-pair — the right choice for unattended runs

Use when queries must run with nobody there to click a browser prompt (scheduled jobs, CI, a headless server), or when the user is working over SSH where `externalbrowser` simply cannot work.

Generate an encrypted key pair, register the public half, then point the connection at the private half:

```bash
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out ~/.snowflake/rsa_key.p8
openssl rsa -in ~/.snowflake/rsa_key.p8 -pubout -out ~/.snowflake/rsa_key.pub
chmod 600 ~/.snowflake/rsa_key.p8
```

The user (or an admin) then registers the public key, pasting the body of the `.pub` file without its header and footer lines:

```sql
ALTER USER someone SET RSA_PUBLIC_KEY='MIIBIjANBg...';
```

Set it up with:

```bash
python scripts/setup_snowflake_mcp.py --account ORG-ACCT --user someone \
  --authenticator snowflake_jwt --private-key-file ~/.snowflake/rsa_key.p8
```

If the key is encrypted with a passphrase, the connector reads it from the `PRIVATE_KEY_PASSPHRASE` environment variable. Set that in the shell profile rather than writing it into `connections.toml` — the whole point of an encrypted key is defeated if the passphrase sits next to it in plaintext.

## Programmatic access token (PAT)

A reasonable middle ground where key-pair is overkill, if the account has PATs enabled. The token is a bearer credential with an expiry, so treat it like a password: never commit it, and re-run setup when it expires.

```bash
python scripts/setup_snowflake_mcp.py --account ORG-ACCT --user someone --authenticator programmatic_access_token
```

The script will not accept the token on the command line, because shell history is a bad place for credentials. Put it in `~/.snowflake/connections.toml` under `password = "<token>"` in that connection's section, or export `SNOWFLAKE_PASSWORD`.

## Plain username + password

Only viable on accounts without SSO or MFA enforcement, which is increasingly rare and generally being phased out. If it's the only option, set `SNOWFLAKE_PASSWORD` in the environment rather than storing it in the config file, and prefer moving to key-pair when possible.

Never accept a password as a command-line argument, and never write one into a file the user might later share or sync.

## Okta native (rarely needed)

Some Okta tenants support passing the Okta URL directly as the authenticator (`https://company.okta.com`), avoiding the browser round-trip. This bypasses parts of the browser-based flow and often breaks under MFA policies, so try `externalbrowser` first — it already works with Okta, and with Google and Azure AD, without special configuration.
