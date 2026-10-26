# Shared server (A09)

AnimeLab can run as a personal application or as an explicitly enabled shared
server. Desktop, Android and `python run.py` keep their existing personal mode.
Shared-server mode runs from source or Docker for network deployment. Desktop
packages expose the same account system through the launcher's **Authentication**
tab on loopback, including initial administrator setup and session policy.
See [desktop authentication](desktop-distribution.md#authentication-tab).
Source installation requires Python, the built web interface and FFmpeg.

## Start locally

From the repository root, after `uv sync --locked` and the frontend build:

```bash
uv run --locked python -m animelab.shared --data-dir ./shared-data create-admin administrator
uv run --locked python -m animelab.shared --data-dir ./shared-data serve --public-url http://127.0.0.1:8080
```

The first command prompts for a password of 12–256 characters and its confirmation.
There is no default administrator password, unattended public bootstrap route or
open registration. Open http://127.0.0.1:8080/app/ to sign in. Use the account icon
in the top bar, or `/auth/account`, to manage your account.

The application never imports or modifies your personal database. Use an empty,
private `--data-dir` outside the Git checkout for a persistent installation.
Do not put this directory under a public web server's static root.

## Accounts and permissions

An administrator can:

- Create an account and choose its permissions, or generate a single-use
  invitation valid for seven days. The recipient enters the code and chooses
  their own username and password on the login page.
- Grant the `download` permission (individual/batch/scheduled/automatic
  downloads) and the `extensions` permission (install, enable, update, edit
  recipes and change extension stores). New users receive only `download`.
- Grant administrator status, deactivate accounts, revoke unused codes and
  stop an account's engine. The last enabled administrator cannot be disabled
  or demoted.
- Issue a recovery code valid for 24 hours. It replaces an earlier recovery
  code for that account. The administrator does not need to know the new password.

Users can change their own password with the current password. Password changes,
recovery, deactivation and permission changes revoke existing sessions. Permission
changes/deactivation also stop the account engine, preserving partial downloads.
A subsequent login with no download permission keeps automatic/scheduled work
stopped. A normal logout revokes that browser session; existing downloads continue.
Users without download permission can still browse, watch and save ordinary favorites.
Proxy connection configuration remains restricted to administrators.

Only hashes of passwords, sessions and invitation/recovery codes are stored.
Passwords use salted scrypt with N=2^17, r=8, p=1. New hashes store their algorithm
and work factors (`scrypt$n$r$p$salt$key`). Historical `salt:key` records remain
readable with their original parameters and are upgraded after a successful login;
passwords do not need to be reset. A concurrent administrator reset takes precedence
over a login or hash upgrade. Sessions use random opaque
identifiers in HttpOnly, SameSite=Strict cookies (Secure for HTTPS). Sessions have
an absolute lifetime of 12 hours and a 30-minute idle timeout by default, with at most ten
sessions per account. Active media delivery refreshes activity; an idle SSE stream
does not. Only failed authentications count toward the ten-failure, fifteen-minute
budget per (username, peer address). Success clears that pair's failures. Invitations
and recovery have a separate budget per peer and chosen username or code digest,
so a bad code cannot block existing accounts or unrelated recovery codes. The map
is bounded to 10,000 active identities. No server-wide authentication quota is used.
Password computations run one at a time without an unbounded waiting queue; a busy
server returns HTTP 503 with `Retry-After: 1`, without recording a password failure.
An exhausted failure budget returns HTTP 429 with its remaining retry delay.
See the [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
and [session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
guidance used for these choices.

The source CLI supports `--session-hours` (1–168) and `--idle-minutes` (1–1440,
no longer than the absolute lifetime). Existing session records are migrated
without losing accounts. Each issued session records its absolute expiry;
extending the configured lifetime cannot resurrect an expired token.

## Network deployment and Docker

Use a dedicated origin and an HTTPS reverse proxy for network access. The public
URL must contain the exact scheme, host and optional port, with no subpath. HTTP
is accepted only for loopback development. Unsafe requests must send JSON and an
`Origin` header matching that URL. The gateway does not trust client-supplied
identity headers. Forwarding headers are ignored unless their immediate sender is
explicitly trusted. Keep the backend port reachable only by your proxy.
Configure its streaming timeouts for long media requests and disable buffering on
`/api/download/stream` (SSE). Seek requests, `HEAD`, `Range` and `Content-Range`
are preserved by the gateway. No WebSocket tunnel is exposed; download updates
currently use SSE.

Declare each actual proxy IP or CIDR explicitly (repeat `--trusted-proxy` as needed):

```bash
uv run --locked python -m animelab.shared --data-dir ./shared-data serve \
  --public-url https://anime.example.org --trusted-proxy 127.0.0.1
```

This enables `X-Forwarded-For`/`X-Forwarded-Proto` handling only for connections
from the declared proxies. Wildcards and hostnames are rejected. Use the proxy's
actual address as seen by the gateway, especially across a Docker network; avoid
trusting a broad network containing untrusted clients. Configure the edge proxy
to overwrite client-supplied forwarding headers. For example, for a single Nginx
proxy terminating HTTPS:

```nginx
proxy_set_header Host $host;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
```

`ANIMELAB_TRUSTED_PROXIES` is the comma-separated equivalent for source/Docker
deployment. It is empty by default. The shared Compose override passes it through.
Without this setting users behind a proxy still have separate per-username failure
budgets, but attempts at the same username share the proxy address.

The gateway adds a Content-Security-Policy to Vue pages and assets as well as auth
pages. Vue scripts must come from the same origin; inline scripts, plugins and
framing are blocked. HLS blob workers/media, remote HTTPS images/media and Google
font stylesheets remain supported. Auth pages keep their more restrictive policy.

Example using the existing image and volumes:

```bash
docker compose build
# Use only the base compose file for bootstrap; the override requires the URL.
docker compose run --rm animelab python -m animelab.shared --data-dir /data/shared create-admin administrator
export ANIMELAB_PUBLIC_URL=https://anime.example.org
export ANIMELAB_MAX_ENGINES=4
docker compose -f compose.yaml -f compose.shared.yaml up -d
```

The image includes the shared-server package. The override's health check probes
`/healthz`, which exposes only readiness/mode, not users or private data. All
shared account files, including downloads, are persisted under `/data/shared`
in the existing **data** volume. The personal-mode `/downloads` volume is not used
by shared accounts. Do not switch the same origin between personal and shared modes:
older personal service workers may have cached data there. Shared mode disables
offline caching and clears account-specific browser preferences on account switches.

## Isolation, resources and administration

A single gateway owns `accounts.sqlite3`. Account IDs are generated internally;
request headers, usernames and URL parameters cannot select another workspace.
Each activated account starts one private engine under `users/<id>/`, with its own
SQLite database, downloads, source cookie jars, cache, proxy and source settings.
Workers bind random loopback ports and require a private capability header for
all requests, including media/static routes. Browser session cookies alone cannot
access a worker directly. The gateway never forwards its session cookie or the
operator's proxy/source credentials to engines or external websites.

The engine count defaults to four (`--max-engines` / `ANIMELAB_MAX_ENGINES`, range
1–32). Engines remain active for background downloads until stopped by the admin
or server shutdown; exceeding the limit returns HTTP 503. Accounts and outstanding
codes each have a limit of 100. One OS lock protects each workspace and the gateway;
multiple gateway replicas sharing a directory are unsupported. Worker stdin is a
lifetime channel: loss of the gateway triggers graceful shutdown. Partial transfers
and library state survive an ordinary restart.

Host-device actions (opening the server's browser, native cookie capture, Android
storage dialogs) are unavailable in shared mode. Users may open the website link
on their own device; doing so does not transfer cookies automatically. A shared
engine only serves media inside its own download root, including resolved symlink
checks, rather than accepting files from the machine-wide temporary directory.

Remote image, subtitle, stream and HLS proxies enforce a domain allowlist in shared
mode for every account, including administrators. The list includes known source
domains, complete domains from the built-in extractors and enabled extensions.
Each destination must also pass public-IP/DNS checks. Redirect targets, HLS
segments and AES keys are checked too; cached data cannot bypass the domain policy.
Watching and cover display remain available without the `download` permission.
An operator may explicitly approve additional CDN domains using the comma-separated
`ANIMELAB_MEDIA_DOMAINS` environment variable (for example `cdn.example.org`).
Subdomains of approved domains are accepted; wildcard/URL entries are not. The
shared Compose override passes this setting to isolated engines. Restart active
engines after changing it. Only approve domains you intend to relay; new extension
CDNs may need approval. Personal desktop/Android mode keeps its existing URL policy.

This provides application-level separation, not an OS sandbox against arbitrary
code execution. Operators and server administrators are trusted. Do not grant
extension management to untrusted users; installed recipes and external sites are
still subject to the existing interpreter's limitations. Media files are currently
stored separately per account; cross-account physical deduplication is not included.
CPU/disk quotas, clustered deployment and external identity providers are not included.
Back up the entire private shared directory while the server is stopped.

Local operator password recovery (also revokes sessions):

```bash
uv run --locked python -m animelab.shared --data-dir ./shared-data reset-password administrator
```

## Verification

The normal Python CI suite includes `tests/test_shared_server.py`:

```bash
uv run --locked python scripts/check.py python -k shared_server
```

The integration test starts actual independent Python engines in temporary storage,
checks different users' libraries/settings, direct-port refusal, cross-user media
and task-action refusal, byte-range/HEAD delivery, persistence and worker cleanup.
Unit tests cover hashing, expiration, role/permission changes, invitations/recovery,
CSRF/origin/Host enforcement, body limits and session revocation. No personal
library or external anime site is needed.

Manual checks:

1. Create the administrator; open `/app/` signed out and confirm the login page.
2. Create Alice and Bob, using separate browser profiles; add a favorite and
   change a setting as Alice. Bob must not see those changes.
3. Generate/redeem an invitation. Reusing or revoking the code must prevent reuse.
4. Download an episode as Alice. Copy its media URL to Bob's profile: access must
   fail. Verify playback and seeking in Alice's profile after a server restart.
5. Remove download permission while a transfer runs: Alice is signed out, the
   engine stops, and a new login cannot resume or start automatic transfers.
6. Change a password or redeem a recovery code; other sessions must lose access.
7. Test `/auth/account` at a narrow mobile viewport and in French and English.
