"""Native UI entry point and a release probe that actually creates the window."""
import ctypes
from pathlib import Path
import sys
import threading
import subprocess
from urllib.parse import urlsplit


def _apply_native_window_theme(window, dark: bool) -> None:
    """Synchronize native window decorations (Windows DWM / Linux GTK) with the app theme."""
    if window is None:
        return
    if sys.platform == 'win32':
        try:
            native = getattr(window, 'native', None)
            handle = getattr(native, 'Handle', None)
            hwnd = int(handle.ToInt64()) if hasattr(handle, 'ToInt64') else int(handle or 0)
            if not hwnd:
                hwnd = ctypes.windll.user32.GetActiveWindow()
            if hwnd:
                value = ctypes.c_int(1 if dark else 0)
                dwmapi = ctypes.windll.dwmapi
                for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (Win11 / Win10)
                    dwmapi.DwmSetWindowAttribute(
                        ctypes.c_void_p(hwnd),
                        ctypes.c_uint(attribute),
                        ctypes.byref(value),
                        ctypes.sizeof(value),
                    )
        except Exception:
            pass
    elif sys.platform.startswith('linux'):
        try:
            import gi

            gi.require_version('Gtk', '3.0')
            from gi.repository import Gtk

            gtk_settings = Gtk.Settings.get_default()
            if gtk_settings is not None:
                gtk_settings.set_property('gtk-application-prefer-dark-theme', bool(dark))
        except Exception:
            pass


def _initial_theme_dark() -> bool:
    try:
        from animelab.services import app_preferences

        prefs = app_preferences.load()
        return prefs.get('theme') != 'light'
    except Exception:
        return True


class DesktopBridge:
    """Only the trusted local application may invoke native desktop actions."""

    def __init__(self, url):
        self._origin = self._get_origin(url)
        self._window = None

    @staticmethod
    def _get_origin(url):
        parsed = urlsplit(url or '')
        if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            return None
        return parsed.scheme, parsed.hostname, parsed.port

    def _require_local_origin(self):
        if (
            self._window is None
            or self._origin is None
            or self._get_origin(self._window.get_current_url()) != self._origin
        ):
            raise PermissionError('Desktop native actions are available only in the local AnimeLab window')

    def choose_download_directory(self):
        self._require_local_origin()
        import webview

        selected = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return selected[0] if selected else None

    def platform_info(self):
        self._require_local_origin()
        os_name = 'windows' if sys.platform == 'win32' else 'macos' if sys.platform == 'darwin' else 'linux'
        return {'runtime': 'desktop', 'os': os_name}

    def set_title(self, title: str):
        self._require_local_origin()
        clean = ' '.join(str(title or 'AnimeLab').split())[:120] or 'AnimeLab'
        if hasattr(self._window, 'set_title'):
            self._window.set_title(clean)
        return clean

    def set_theme(self, theme: str):
        self._require_local_origin()
        dark = str(theme or 'dark').strip().lower() != 'light'
        _apply_native_window_theme(self._window, dark)
        return True


DirectoryPicker = DesktopBridge


def window_icon():
    root = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
    if sys.platform == 'win32':
        icon = root / ('desktop-assets/animelab.ico' if getattr(sys, 'frozen', False) else 'docs/branding/animelab.ico')
        data = icon.read_bytes()
        # WinForms System.Drawing.Icon rejects PNG, even when the file is named .ico.
        if len(data) < 22 or data[:4] != b'\x00\x00\x01\x00' or int.from_bytes(data[4:6], 'little') == 0:
            raise ValueError('The desktop window requires a valid Windows ICO resource')
        return str(icon)
    if sys.platform == 'darwin':
        return None  # Cocoa uses the .app bundle icon.
    return str(root / 'animelab/static/img/icon-512.png')


def open_window(url=None, control_url=None, workdir=None, probe=False):
    import webview
    from webview.menu import Menu, MenuAction

    marker = threading.Event()
    bridge = DesktopBridge(url) if not probe else None
    initial_dark = True if probe else _initial_theme_dark()
    bg_color = '#0b1517' if initial_dark else '#f5fafb'
    window = webview.create_window(
        'AnimeLab — Window check' if probe else 'AnimeLab',
        url,
        html='<html><body><p id="probe">AnimeLab window OK</p></body></html>' if probe else None,
        width=640 if probe else 1280,
        height=480 if probe else 820,
        min_size=(320, 240) if probe else (800, 600),
        background_color=bg_color,
        js_api=bridge,
    )
    if bridge:
        bridge._window = window

    def shown():
        marker.set()
        if not probe:
            _apply_native_window_theme(window, initial_dark)
        if workdir:
            (workdir / 'shown').touch()

    window.events.shown += shown
    if probe:
        def loaded():
            if window.evaluate_js('document.getElementById("probe").textContent') == 'AnimeLab window OK':
                marker.set()
                (workdir / 'loaded').touch()
            threading.Timer(.3, window.destroy).start()
        window.events.loaded += loaded
    elif workdir:
        def watch_stop():
            while not (workdir / 'stop').exists():
                if window.events.closed.wait(.2):
                    return
            window.destroy()
        threading.Thread(target=watch_stop, daemon=True).start()

    def administration():
        from .supervisor import launcher_command
        kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {'start_new_session': True}
        subprocess.Popen(
            launcher_command() + ['--launcher'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )

    menu = (
        [
            Menu(
                'AnimeLab',
                [
                    MenuAction('Administration', administration),
                    MenuAction('Quit / Quitter', window.destroy),
                ],
            )
        ]
        if control_url
        else []
    )
    from animelab.services.browser_verification import browser_verification
    if not probe:
        opener = lambda target: webview.create_window(
            'AnimeLab — Site verification', target, width=900, height=700)
        opener.user_agent = lambda: window.evaluate_js('navigator.userAgent')
        browser_verification.webview_opener = opener
    try:
        webview.start(
            icon=window_icon(),
            menu=menu,
            gui='edgechromium' if sys.platform == 'win32' else 'cocoa' if sys.platform == 'darwin' else 'gtk',
        )
    finally:
        browser_verification.webview_opener = None
    if probe and (not marker.is_set() or not (workdir / 'loaded').exists()):
        raise RuntimeError('Native window did not render the release probe')
