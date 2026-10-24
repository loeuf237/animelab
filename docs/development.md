# Reproducible development and checks

## Fresh clone

Install Git, Node.js 22 LTS (22.13+) with npm, uv **0.13.1**, and FFmpeg/ffprobe on PATH.
On Debian/Ubuntu, media and native-binary tests need:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg build-essential llvm
```

On Windows/macOS install equivalent media tools; C/LLVM-specific tests may skip
when their tools are absent. A Chrome-family browser is optional for the installed-
browser detection test. CI installs Chromium through Playwright for UI tests.
Python 3.12 and 3.13 are supported and tested by CI. uv uses Python 3.13 by default.

```bash
git clone https://github.com/loeuf237/animelab.git
cd animelab
uv sync --locked
cd frontend
npm ci
npx playwright install --with-deps chromium
cd ..
uv run --locked python scripts/check.py all
```

The checkout does not need an existing database, local configuration, API key,
Android SDK, release credentials or frontend build output. The `all` command
builds the interface before Python tests. Installation needs Internet; browser
packages and system prerequisites are not bundled in the repository. Tests use
mocks/local servers where appropriate; these checks do not prove that every
external anime source is currently online or accessible.

The Python test runner creates a temporary HOME/USERPROFILE, database, downloads,
cache and a separate TMPDIR/TEMP/TMP, removes inherited ANIMAN settings, disables startup refresh and cleans
up afterwards. It never starts the personal server. Test reports are written to
the checkout when requested. Tests involving FFmpeg use tiny generated media.

## Individual checks

Run from the repository root after `uv sync --locked` and `npm ci` in `frontend/`:

```bash
uv run --locked python scripts/check.py quality
uv run --locked python scripts/check.py frontend
uv run --locked python scripts/check.py python
uv run --locked python scripts/check.py ui
```

`python` requires a frontend build; `frontend` creates it. Pass pytest arguments
after `python`, for example:

```bash
uv run --locked python scripts/check.py python -k subtitle
uv run --locked python scripts/check.py python --junitxml=test-results/python.xml
```

CI uses the last command on Python 3.12 and 3.13. The underlying test command is
`python -m pytest tests -q`; the wrapper sets isolated storage before any engine
imports. Do not use the underlying command with a personal library environment.

`tests/conftest.py` mocks DNS centrally for offline fixture domains and isolates
the DNS cache between tests. Numeric addresses and loopback sockets remain
usable for local HTTP server tests. Override `socket.getaddrinfo` in a security
test to simulate a private address or a failed lookup; URL safety checks remain
enabled. The test environment permits `testserver` and `test` as HTTP hosts;
production defaults permit only `localhost` and `127.0.0.1`.

With the underlying pytest command, the SPA serving test uses `skipif` when
`frontend/dist/index.html` is absent. The wrapper and CI still require this
build and fail if it is missing; the skip only supports backend-only test runs.

To apply frontend formatting or ESLint's safe automatic fixes:

```bash
cd frontend
npm run format
npm run lint:fix
```

Review the diff and rerun checks after any automatic changes.

## Checks and progressive adoption

- **Ruff** checks Python correctness rules (`E9`, `F`) throughout `animan/`,
  `scripts/`, `tests/` and the three application entry points. Unused imports and
  local variables (`F401`, `F841`) are deferred; Python style formatting is not
  enforced yet. Three fixture-importing test files allow intentional fixture-name
  shadowing (`F811`). Undefined names and other enabled violations fail CI.
- **mypy** checks typed episode/anime schemas, Android request authentication,
  download resume helpers, subtitle parsing, subtitle errors and the check runner.
  These modules require typed function signatures and parameterized generics.
  Imported engine modules are followed silently; the rest of the engine is not
  claimed to be fully type-checked. Extend `tool.mypy.files` as modules are typed.
- **ESLint** checks frontend JavaScript/TypeScript and essential Vue rules.
  Existing explicit `any` values and single-word route component names remain
  allowed during migration. **vue-tsc** independently checks frontend types.
- **Prettier** enforces one frontend format. Generated output, dependencies,
  public assets and the npm lockfile are excluded.

These checks complement behavior and browser tests; they do not replace them.
Quality tools belong to the development dependency group, outside the generated
runtime requirements used by Docker and application packaging.

## Dependency changes

`pyproject.toml` declares direct Python dependencies; **`uv.lock`** records the
complete resolution, versions, platform markers and artifact hashes. Commit both.
`uv sync --locked` refuses a stale lock instead of silently selecting new versions.
Do not edit `requirements.txt` manually; regenerate its runtime-only export:

```bash
uv lock
uv export --locked --no-dev --no-hashes --no-emit-project --output-file requirements.txt
uv sync --locked
```

Use `uv lock --upgrade-package NAME` for a deliberate package update. Rerun the
full checks and commit the generated export. CI verifies that it matches the lock.
For a runtime-only environment, use `uv sync --locked --no-dev` and start the server
with `uv run --locked --no-dev python run.py`.

Frontend dependencies use `npm ci` and the committed package lock. Desktop release
and Android native builds keep their separate dependency lists/toolchains; the
server lock does not claim to reproduce their complete platform environments.

## Required GitHub checks

The CI workflow produces `Python quality`, `Interface tests and build`,
`Python 3.12 tests` and `Python 3.13 tests` checks. A repository owner must mark
these as required in branch protection/rulesets for `main`; a failing workflow
alone does not prevent merging. Existing Docker and Android resource checks can
also be required. Review repository settings for administrator bypass policy.
