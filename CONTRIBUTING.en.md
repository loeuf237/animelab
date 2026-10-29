# Contributing to AnimeLab

[Français](CONTRIBUTING.md) | [English](CONTRIBUTING.en.md)

Thank you for contributing to AnimeLab! We welcome bug fixes, translations,
documentation, interface improvements and device testing. You do not need to
know how to code to participate.

Discussions can take place in French or English. Be respectful, describe
problems clearly and keep discussions focused on the proposed changes.

## Where to start

- Check the [open issues](https://github.com/loeuf237/animelab/issues) before
  starting work to avoid duplication.
- If issues have the `good first issue` or `help wanted` labels, they are a good
  place to start. Otherwise, suggest a small improvement or ask in an issue
  whether someone is already working on the topic.
- For a substantial change, first describe the problem, your proposed approach
  and the affected platforms in an issue.
- A small fix, translation or documentation clarification can be submitted
  directly as a pull request.

## Areas where we are looking for help

The [detailed call for contributors](docs/contribution-priorities.en.md)
describes the goals and validation criteria for each area:

- redesigning the Android loading screen;
- detecting new versions and offering configurable automatic downloads;
- fixing duplicate downloads/saved files in French-Manga and other affected
  sources;
- validating Aniyomi/Anikku extension APKs;
- adding a **Tools** tab and a complete subtitle workspace, including
  search, downloads and translation using personal API keys;
- downloading and editing audio from extensions, then creating multi-audio
  MKV files;
- improving the Extensions page’s usability and appearance, inspired by
  Mihon/Aniyomi;
- improving the README and documentation.

Feature and architecture proposals are welcome. You can contact the maintainer
on [Telegram — @loeuf237](https://t.me/loeuf237). Record useful decisions and
results in an issue or PR. Always state what you actually tested.

## Reporting a bug

[Open an issue](https://github.com/loeuf237/animelab/issues/new) with as much
of the following information as possible:

```text
AnimeLab version or commit:
Operating system, version and architecture:
Installation: release / source / Docker
Mode: launcher / browser / Android

Steps to reproduce:
1.
2.

Expected result:
Actual result:
How often the problem occurs:
Relevant logs or screenshots, with private data removed:
```

For an extension issue, include its name, package ID and version, the repository
used, the platform and the operation that fails: installation, search, catalogue,
episodes, playback or download. State whether verification was requested in the
WebView and whether you completed it.

Remove passwords, API keys, cookies, tokens, private or signed URLs and personal
information from logs and screenshots. Avoid attaching a complete personal
database or backup.

If you discover a vulnerability, do not publish exploitable details in an issue.
Use **Report a vulnerability** in the **Security** tab if that option is
available; otherwise, contact the maintainer privately on
[Telegram](https://t.me/loeuf237).

## Setting up your environment

To change the code, **fork** the repository on GitHub, clone your fork and open
a terminal at the project root, where `pyproject.toml` is located. Create a
dedicated branch for your change.

Prerequisites:

- Git;
- Python **3.12 or 3.13**; `uv` selects 3.13 by default;
- **uv 0.13.1**;
- Node.js **22.13 or a later 22.x version**, with npm;
- FFmpeg and ffprobe on your `PATH` for media processing and tests.

Install the dependencies and build the interface:

```bash
uv sync --locked
cd frontend
npm ci
npm run build
cd ..
```

These commands work on Linux and in PowerShell on Windows. See the
[development guide](docs/development.md) for additional system packages,
checks and dependency updates. Documentation-only contributions do not require
this setup.

### Starting the application

To open the launcher from source, run this from the project root:

```bash
uv run --locked --group desktop python desktop.py
```

To start only the server:

```bash
uv run --locked python run.py
```

Then open <http://localhost:8080/app/>. To work on the interface, keep the server
running and start Vite in a second terminal:

```bash
cd frontend
npm run dev
```

The development interface is available at <http://localhost:5173> and proxies API
requests to the server on port 8080. Native window prerequisites are described
in the [desktop guide](docs/desktop-distribution.md).

## Finding your way around the code

| Location | Contents |
| --- | --- |
| `animelab/` | Python engine, FastAPI API, services and data |
| `frontend/src/` | Vue 3 and TypeScript interface |
| `frontend/src/locales/` | Interface translations |
| `android/` | Android application, native bridges and APK extension runtime |
| `tests/` | Python tests and regression coverage |
| `frontend/tests/` | Frontend unit tests |
| `scripts/` | Checks, build tools and distribution tools |
| `docs/` | Guides, architecture, studies and validation results |
| `.github/workflows/` | CI, Android validation and releases |

See the [architecture documentation](docs/architecture/README.md) for interactions
between components. When translating, preserve existing message keys and
placeholders, and check the result in the interface.

## Checking your changes

Run the checks relevant to your contribution. For a bug fix, add a regression
test when the behavior can be tested automatically. For a visual change, include
a screenshot and state the screen sizes tested. For documentation-only changes,
check the relevant links, paths and commands.

From the project root, after installing dependencies:

```bash
uv run --locked python scripts/check.py quality
uv run --locked python scripts/check.py frontend
uv run --locked python scripts/check.py python
```

The `frontend` check builds the interface, which is required before running the
`python` check. The latter uses a temporary library, database and directories:
prefer this runner over invoking pytest directly with your personal environment.
To focus on a topic, such as subtitles:

```bash
uv run --locked python scripts/check.py python -k subtitle
```

To run all checks, including browser tests in Chromium, install the test browser
first:

```bash
cd frontend
npx playwright install --with-deps chromium
cd ..
uv run --locked python scripts/check.py all
```

Installing Chromium may download large files and require administrator
privileges for system dependencies. It is needed for browser tests; a simple
documentation correction does not require it.

The [development guide](docs/development.md) covers Ruff, mypy, ESLint, Prettier,
TypeScript and individual checks. If a test cannot run on your platform, state
that in the PR and explain why.

## Extensions and Android validation

AnimeLab uses Python recipes on desktop/server and an experimental runtime for
original APKs on Android. Success on one platform does not prove compatibility
on the other. Document the operations verified and remaining limitations; see
the [extension guide](docs/extension-recipes.md) and
[Android validation status](docs/studies/aniyomi-anikku/UTILISATION.md).

For contribution APK builds, use the validation workflows in GitHub Actions.
The [Android extension APK runtime](.github/workflows/android-extensions.yml)
workflow builds the runtime and runs its emulator tests. Validation builds do
not require the production signing key; do not request or attach that key.
Release publication is handled by the maintainer.

Testing on a phone is still useful: report the model, Android version,
architecture, AnimeLab version and scenario tested. Distinguish emulator results
from results obtained on physical devices.

A new external engine must remain experimental until its adoption criteria are
demonstrated and documented. Existing studies and decisions are collected in
the [study folders](docs/studies/).

## Submitting a pull request

Open your PR from the branch in your fork to `main` in the AnimeLab repository.
Draft PRs are welcome for work that is still in progress.

- Keep one clear objective per PR; avoid unrelated formatting changes.
- Explain the problem, the resulting behavior and any limitations.
- Link the relevant issue, for example with `Fixes #123` if the PR resolves it.
- List the check commands you ran and their results; state which checks you
  did not run.
- Update the documentation if usage or configuration changes.
- Keep lockfiles consistent with dependencies. `requirements.txt` is generated:
  follow the [dependency update guide](docs/development.md#dependency-changes).
- Do not commit secrets, personal data, virtual environments, downloaded
  dependencies or generated build files.

Use a clear title, such as `fix(launcher): preserve the running server` or
`docs: clarify Linux startup`. CI complements local checks. Review its results
and fix failures related to your change before requesting the final review.

## AI assistance and licensing

You may use a tool such as Codex to help with your work. If that assistance
played a significant role, briefly mention it in the PR description. Read,
understand and verify the code you submit; you remain responsible for your
contribution. Do not send secrets or private data to these tools.

AnimeLab is distributed under **GPL-3.0-only**: contributions must be compatible
with the [project license](LICENSE). Preserve third-party notices and identify
the source of any reused code or assets.
