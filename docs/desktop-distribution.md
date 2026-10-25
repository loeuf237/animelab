# AnimeLab desktop packages

These archives contain the Python engine, the compiled Vue interface, curl_cffi,
yt-dlp and FFmpeg/ffprobe. Python and Node.js are not required on the target machine.
Extract the entire archive: the executable requires its adjacent resources.

- Windows x64: launch `AnimeLab.exe`. The native window uses installed Microsoft
  Edge WebView2; the application can fall back to the installed browser.
- Linux x64: launch `./AnimeLab`. Built on Ubuntu 22.04; requires a compatible glibc
  (2.35 or newer). GTK/WebKit availability varies between distributions; an
  installed browser is the fallback. This is an archive, not a universal AppImage.
- macOS Apple Silicon / Intel: choose the matching archive and open `AnimeLab.app`.
  **UNTESTED ON REAL MAC HARDWARE.** Automated package checks do not certify
  interactive playback or window behavior. The app is not Developer-ID signed
  or notarized; macOS may block opening it. Do not disable system security globally.

The launcher opens `/spa/` on an IPv4 loopback server and pauses/persists active
transfers when closing normally. Paused transfers can be resumed from Downloads.
Data stays in the user's existing `.animan` data directory and `Downloads/Animan`,
outside the archive. These are portable archives, not system installers.

## Desktop administration

The native window's **AnimeLab → Administration** menu opens a local control
panel in your browser. You can also open the shortcut beside the executable:

| Platform | Administration | Browser mode | Stop the running application |
| --- | --- | --- | --- |
| Windows | `Administration.cmd` | `Browser.cmd` | `Stop.cmd` |
| Linux | `./Administration.sh` | `./Browser.sh` | `./Stop.sh` |
| macOS | `Administration.command` | `Browser.command` | `Stop.command` |

On macOS the archive contains an `AnimeLab` folder with `AnimeLab.app` and these
shortcuts. The macOS hardware test warning above still applies.

The panel provides:

- The actual application address and whether the requested port was occupied.
  A free local port is selected in that case; other programs are never stopped.
- A port setting (1–65535) and a preference for using the installed browser.
  Save settings, then use **Restart the server** to apply them. The port refers
  to the application, not the separate, automatically allocated administration port.
- Local checks for the compiled interface, SQLite integrity, write access to the
  download folder, FFmpeg/ffprobe and the local HTTP server. Checks do not contact
  anime sources. A JSON report can be downloaded for support.
- Graceful restart and shutdown of the launcher-owned engine. Closing an
  administration/browser tab leaves the server running; **Quit AnimeLab** stops it.
  Closing the main native window also stops the desktop application.

The panel stays alive when the engine or native window fails. A native-window
crash triggers a fresh engine in browser mode, and the panel explains the fallback.
A second launcher invocation reuses the running desktop instance rather than
starting another engine against the same library.
A private engine lock and a supervisor heartbeat also prevent an orphaned child
from continuing after the launcher crashes. Normal termination requests are
handled gracefully; a hung orphan exits after its shutdown deadline.

Desktop settings and bounded rotating logs live in `~/.animan/desktop/`
(`%USERPROFILE%\.animan\desktop\` on Windows):

- `config.json`: port and browser preference, outside the installation folder.
- `desktop.log`: launcher events; `engine.log`: engine/native-window errors.
- `engine-console.log` and `.1`: bounded child console output, including native errors.
- `runtime.json`: transient, private administration capability. **Do not share it.**

Diagnostic reports deliberately exclude raw logs, source URLs, cookies, task names
and proxy credentials. Do not post the whole data directory in an issue.

The control server binds to `127.0.0.1` only, rejects other Host/Origin values,
requires a fresh per-launch capability for every API call, and permits no CORS.
The capability is passed in a URL fragment, removed from the address bar and kept
only in that tab's session storage. Another local process running under your user
account can read your files; this is not an isolation boundary against that user.
These tools are desktop-only; `run.py`, Docker and Android do not expose them.

## Command line and recovery

Use `AnimeLab.exe` on Windows, `./AnimeLab` on Linux, or
`./AnimeLab.app/Contents/MacOS/AnimeLab` on macOS:

```sh
./AnimeLab --admin                  # Start/reuse the engine and open administration
./AnimeLab --browser                # Use the installed browser for this launch
./AnimeLab --headless --port 8090    # Save this port, start without opening a window
./AnimeLab --status                 # JSON status of the active desktop instance
./AnimeLab --diagnose               # Export checks to ~/.animan/desktop/diagnostics.json
./AnimeLab --diagnose --report-file /path/to/report.json
./AnimeLab --stop                   # Wait for the running desktop instance to stop
```

Windowed Windows builds have no console: use the panel or `--report-file` for JSON
output (`--status --report-file status.json` also works). `--stop` controls only
the desktop launcher instance, not an independently started `python run.py` server.
`--port` takes precedence over `ANIMAN_PORT`, which otherwise overrides the saved
port for that launch. A saved port is restored after updates. If the configuration
is invalid, `--admin --port 8080` repairs it without modifying your library.

`--self-test` checks the packaged interface, curl library, temporary SQLite storage
and media tools without contacting anime sources. `--gui-self-test` actually
creates a native window, verifies rendered JavaScript content, then closes it.
CI runs this Windows GUI probe on pushes/PRs, and the release workflow additionally
tests the packaged executable, administration panel and shutdown. These automated
checks do not certify real-hardware playback. `--version` reports the app version.

The Windows v0.1.2 native startup failure was caused by passing a PNG to WinForms'
`System.Drawing.Icon`. The launcher now supplies a packaged ICO, while Cocoa uses
its bundle icon and Linux uses PNG. Old v0.1.2 binaries are unaffected by source
changes: use their `--headless` workaround until a new package is built.
Before testing an updated package, stop any engine started by the old launcher
or `.bat`. Older releases do not participate in the new instance lock and cannot
be stopped through the new administration panel.

`release-metadata` contains the build commit, dependency versions, media versions
and license notices. The GitHub release supplies `SHA256SUMS.txt` for all assets.
