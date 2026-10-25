# Native desktop launcher design

Reference: [Suwayomi/Suwayomi-Launcher](https://github.com/Suwayomi/Suwayomi-Launcher),
commit `12d5a0548d80e97a2f5d1b531e6b2ab5dc9124b9`.

## How the reference is built

- `build.gradle.kts`: Kotlin/JVM, Swing, Darklaf themes, MigLayout forms,
  coroutine state flows, and Typesafe Config/Config4k for settings.
- `Main.kt`: a 410×660 `JFrame`, settings in a `JTabbedPane`, and Launch/Electron
  buttons below the form.
- `LauncherViewModel.kt`: binds preferences to controls, checks the port, locates
  the JVM/server JAR and starts the independent server with `ProcessBuilder`.
  The configuration process exits after launch.
- `config/ConfigManager.kt`, `settings/LauncherSettings.kt` and `ui/*.kt`:
  persistent server/launcher settings, root-directory selection and native forms.

## AnimeLab's implementation

AnimeLab has an independently written Python/Qt Widgets (PySide6-Essentials) implementation. No
Suwayomi Kotlin code, JVM, Electron runtime or branding is bundled. The new code
uses AnimeLab's GPL-3.0-only license; the reference has its own MPL-2.0 license.

The window follows the compact configuration-first layout: two rows of five tabs,
labelled controls and launch buttons below the form. Its categories map to
AnimeLab: WebUI, Server, Downloader, Directories, Requests, Proxy, Extensions,
Diagnostics, Backup and About. Manga-specific OPDS/KOReader/CBZ controls have no
equivalent in AnimeLab.

Opening the launcher starts no engine. Launch saves preferences and starts the
supervised engine separately. The launcher stays available for monitoring and
shutdown; closing it leaves a running server active. Native window uses the
existing system WebView and cookie-verification integration; Browser uses the
installed default browser.

Preferences extend the existing `~/.animan/desktop/config.json` while preserving
port/browser-only files. Validated settings map to explicit startup overrides.
Existing download preferences seed the first profile. Proxy credentials remain
in the engine's SQLite table and are masked in the form, not exported as launcher
settings. SQLite backup includes committed WAL data without stopping the server.

PyInstaller collects Qt Widgets and its platform plugins; Qt WebEngine, QML and
Qt Quick are excluded. Linux packaging installs GTK/X11 prerequisites. On GNOME, the included GTK platform helper supplies the system chooser.
QFileDialog requests the native platform dialog, with Qt fallback if no native
helper exists on another desktop. A launcher probe renders every tab in Windows CI and
Windows/Linux package builds. macOS remains marked untested on real hardware.
Headless operation and the browser administration recovery page remain available.

## Installed reference and rendering correction (2026-10-25)

The installed `/usr/share/java/suwayomi-server/Suwayomi-Launcher.jar` has SHA-256
`3589306433210f7b2147c73fd5fd7f1531b7ee4ae7fa015fd4c945da0ca88f10`.
REA inventory `ev_ae6c9af2fb2813837c96d304dccacf468ffabb1cb8895f41d2dcf563db338bd7`
records the installed archive (static inspection, not an execution trace).
Its classes include Darklaf's `DarkCheckBoxUI` and `DarkFileChooserUI`, alongside
MigLayout and the Kotlin entry point. The corresponding source uses
`JTabbedPane.WRAP_TAB_LAYOUT` and `JFileChooser.DIRECTORIES_ONLY`: the reference's
chooser is a styled Swing dialog, rather than the GNOME chooser itself.

The previous UV Python Tk build on this Linux host exposed legacy bitmap fonts
and its built-in directory chooser. Qt now uses outline system fonts with Unicode
support, vector checkbox ticks, and fixed balanced tab rows. French text is kept
as UTF-8, without replacing punctuation to compensate for missing glyphs.
Qt is dynamically bundled; its third-party licenses and source references are
included with desktop distributions. The Android engine/UI does not depend on Qt.

Qt references: [native file dialog behavior](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QFileDialog.html)
and [font rendering and fallback](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QFont.html).
