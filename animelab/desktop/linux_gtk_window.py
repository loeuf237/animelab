"""Self-contained GTK3 + WebKit2GTK native window host executed under system Python on Linux.

This module uses only Python standard library modules at import time and imports
``gi`` (GTK 3 / WebKit2GTK) lazily inside :func:`run_window` so virtual environments
that lack compiled PyGObject wheels can spawn the system Python interpreter.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit
import webbrowser

_DARK_BG = '#0b1517'
_LIGHT_BG = '#f5fafb'


def get_local_origin(url: str | None) -> tuple[str, str, int | None] | None:
    """Return ``(scheme, hostname, port)`` only for local HTTP origins."""
    parsed = urlsplit(str(url or ''))
    if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        return None
    return parsed.scheme, parsed.hostname, parsed.port


def format_origin(origin: tuple[str, str, int | None] | None) -> str | None:
    """Format a validated local origin tuple as ``window.location.origin``."""
    if origin is None:
        return None
    scheme, host, port = origin
    host_part = f'[{host}]' if ':' in host else host
    if port is None or port == 80:
        return f'{scheme}://{host_part}'
    return f'{scheme}://{host_part}:{port}'


def sanitize_title(title: str | None) -> str:
    """Normalize whitespace and cap length of a native window title."""
    return ' '.join(str(title or 'AnimeLab').split())[:120] or 'AnimeLab'


def build_bridge_script(expected_origin: str) -> str:
    """Return the WebKit UserScript exposing ``window.pywebview.api`` for a trusted local origin."""
    origin_literal = json.dumps(expected_origin)
    return f"""(function () {{
  var expectedOrigin = {origin_literal};
  if (window.location.origin !== expectedOrigin) return;
  if (window.__animelabGtkBridgeInstalled) return;
  window.__animelabGtkBridgeInstalled = true;
  var nextId = 0;
  var pending = Object.create(null);

  window.__animelabBridgeResolve = function (id, ok, value) {{
    var entry = pending[id];
    if (!entry) return;
    delete pending[id];
    if (ok) entry.resolve(value);
    else entry.reject(new Error(typeof value === 'string' ? value : 'Native bridge error'));
  }};

  function invoke(method) {{
    var args = Array.prototype.slice.call(arguments, 1);
    if (window.location.origin !== expectedOrigin) {{
      return Promise.reject(new Error('Desktop native actions are available only in the local AnimeLab window'));
    }}
    var handlers = window.webkit && window.webkit.messageHandlers;
    var bridge = handlers && handlers.animelabBridge;
    if (!bridge || typeof bridge.postMessage !== 'function') {{
      return Promise.reject(new Error('AnimeLab native bridge unavailable'));
    }}
    var id = ++nextId;
    return new Promise(function (resolve, reject) {{
      pending[id] = {{ resolve: resolve, reject: reject }};
      try {{
        bridge.postMessage(JSON.stringify({{ id: id, method: method, args: args }}));
      }} catch (err) {{
        delete pending[id];
        reject(err);
      }}
    }});
  }}

  window.pywebview = {{
    api: {{
      platform_info: function () {{ return invoke('platform_info'); }},
      set_title: function (title) {{ return invoke('set_title', title); }},
      set_theme: function (theme) {{ return invoke('set_theme', theme); }},
      choose_download_directory: function () {{ return invoke('choose_download_directory'); }},
      choose_external_player: function () {{ return invoke('choose_external_player'); }}
    }}
  }};

  function fireReady() {{
    window.dispatchEvent(new Event('pywebviewready'));
  }}
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', fireReady, {{ once: true }});
  }} else {{
    setTimeout(fireReady, 0);
  }}
}})();"""


def _extract_js_message(message: object) -> str:
    """Read string payload from WebKit2 JavascriptResult across WebKitGTK versions."""
    if hasattr(message, 'get_js_value'):
        val = message.get_js_value()  # type: ignore[attr-defined]
        return str(val.to_string()) if val is not None else ''
    if hasattr(message, 'to_string'):
        return str(message.to_string())  # type: ignore[attr-defined]
    if hasattr(message, 'get_value'):
        val = message.get_value()  # type: ignore[attr-defined]
        return str(val.to_string()) if val is not None else ''
    return ''


def _eval_js(webview: object, script: str, callback=None) -> None:
    """Evaluate JavaScript on a WebKit2.WebView handling 2.40+ and older APIs."""
    if hasattr(webview, 'evaluate_javascript'):
        webview.evaluate_javascript(script, -1, None, None, None, callback, None)  # type: ignore[attr-defined]
    else:
        webview.run_javascript(script, None, callback, None)  # type: ignore[attr-defined]


def _eval_js_text(webview: object, res: object) -> str | None:
    """Extract string result from evaluate_javascript / run_javascript finish."""
    if hasattr(webview, 'evaluate_javascript_finish'):
        val = webview.evaluate_javascript_finish(res)  # type: ignore[attr-defined]
        return str(val.to_string()) if val is not None else None
    result = webview.run_javascript_finish(res)  # type: ignore[attr-defined]
    if result is not None and hasattr(result, 'get_js_value'):
        val = result.get_js_value()
        return str(val.to_string()) if val is not None else None
    return None


def _open_launcher(launcher_cmd: list[str]) -> None:
    if not launcher_cmd:
        return
    subprocess.Popen(
        [*launcher_cmd, '--launcher'],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def run_window(config: dict) -> None:
    """Create and run the GTK3 + WebKit2GTK native window from JSON config."""
    import gi

    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    try:
        gi.require_version('WebKit2', '4.1')
    except ValueError:
        gi.require_version('WebKit2', '4.0')
    from gi.repository import Gdk, GLib, Gtk, WebKit2

    GLib.set_prgname('animelab')
    GLib.set_application_name('AnimeLab')

    probe = bool(config.get('probe'))
    url = config.get('url')
    workdir_raw = config.get('workdir')
    workdir = Path(workdir_raw) if workdir_raw else None
    initial_dark = bool(config.get('initial_dark', True))
    has_control = bool(config.get('has_control'))
    launcher_cmd = [str(item) for item in (config.get('launcher_cmd') or [])]
    width = int(config.get('width') or (640 if probe else 1280))
    height = int(config.get('height') or (480 if probe else 820))
    min_width = int(config.get('min_width') or (320 if probe else 800))
    min_height = int(config.get('min_height') or (240 if probe else 600))
    icon_path = config.get('icon')

    expected_origin = get_local_origin(url) if not probe else get_local_origin('http://127.0.0.1/')
    expected_origin_str = format_origin(expected_origin)

    win = Gtk.Window(title='AnimeLab — Window check' if probe else 'AnimeLab')
    win.set_default_size(width, height)
    geom = Gdk.Geometry()
    geom.min_width = min_width
    geom.min_height = min_height
    win.set_geometry_hints(None, geom, Gdk.WindowHints.MIN_SIZE)
    if icon_path and Path(icon_path).is_file():
        try:
            win.set_icon_from_file(str(icon_path))
        except Exception:
            pass

    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    win.add(vbox)

    if has_control and not probe:
        menubar = Gtk.MenuBar()
        root_item = Gtk.MenuItem(label='AnimeLab')
        submenu = Gtk.Menu()
        admin_item = Gtk.MenuItem(label='Administration')
        admin_item.connect('activate', lambda *_: _open_launcher(launcher_cmd))
        quit_item = Gtk.MenuItem(label='Quit / Quitter')
        quit_item.connect('activate', lambda *_: win.close())
        submenu.append(admin_item)
        submenu.append(quit_item)
        root_item.set_submenu(submenu)
        menubar.append(root_item)
        vbox.pack_start(menubar, False, False, 0)

    ucm = WebKit2.UserContentManager()
    wv = WebKit2.WebView.new_with_user_content_manager(ucm)

    wv_settings = wv.get_settings()
    for prop, value in (
        ('enable_javascript', True),
        ('enable_mediasource', True),
        ('enable_media_stream', True),
        ('enable_webgl', True),
        ('enable_developer_extras', False),
    ):
        setter = f'set_{prop}'
        if hasattr(wv_settings, setter):
            try:
                getattr(wv_settings, setter)(value)
            except Exception:
                pass

    def apply_theme(dark: bool) -> None:
        gtk_settings = Gtk.Settings.get_default()
        if gtk_settings is not None:
            try:
                gtk_settings.set_property('gtk-application-prefer-dark-theme', bool(dark))
            except Exception:
                pass
        rgba = Gdk.RGBA()
        if rgba.parse(_DARK_BG if dark else _LIGHT_BG):
            try:
                wv.set_background_color(rgba)
            except Exception:
                pass

    apply_theme(initial_dark)
    vbox.pack_start(wv, True, True, 0)

    def choose_download_directory() -> str | None:
        selected = None
        if hasattr(Gtk, 'FileChooserNative'):
            try:
                dialog = Gtk.FileChooserNative.new(
                    'AnimeLab',
                    win,
                    Gtk.FileChooserAction.SELECT_FOLDER,
                    '_Open',
                    '_Cancel',
                )
                if dialog.run() == Gtk.ResponseType.ACCEPT:
                    selected = dialog.get_filename()
                dialog.destroy()
                return selected
            except Exception:
                selected = None
        dialog = Gtk.FileChooserDialog(
            title='AnimeLab',
            parent=win,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN,
            Gtk.ResponseType.ACCEPT,
        )
        try:
            if dialog.run() == Gtk.ResponseType.ACCEPT:
                selected = dialog.get_filename()
        finally:
            dialog.destroy()
        return selected

    def choose_external_player() -> str | None:
        selected = None
        if hasattr(Gtk, 'FileChooserNative'):
            try:
                dialog = Gtk.FileChooserNative.new(
                    'AnimeLab',
                    win,
                    Gtk.FileChooserAction.OPEN,
                    '_Open',
                    '_Cancel',
                )
                if dialog.run() == Gtk.ResponseType.ACCEPT:
                    selected = dialog.get_filename()
                dialog.destroy()
                return selected
            except Exception:
                selected = None
        dialog = Gtk.FileChooserDialog(
            title='AnimeLab',
            parent=win,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN,
            Gtk.ResponseType.ACCEPT,
        )
        try:
            if dialog.run() == Gtk.ResponseType.ACCEPT:
                selected = dialog.get_filename()
        finally:
            dialog.destroy()
        return selected

    def resolve_bridge_call(req_id: int, ok: bool, value: object) -> None:
        script = (
            'window.__animelabBridgeResolve && '
            f'window.__animelabBridgeResolve({json.dumps(req_id)}, {json.dumps(ok)}, {json.dumps(value)});'
        )
        _eval_js(wv, script)

    if not probe and expected_origin_str is not None:
        ucm.register_script_message_handler('animelabBridge')
        user_script = WebKit2.UserScript(
            build_bridge_script(expected_origin_str),
            WebKit2.UserContentInjectedFrames.TOP_FRAME,
            WebKit2.UserScriptInjectionTime.START,
            None,
            None,
        )
        ucm.add_script(user_script)

        def on_bridge_message(_manager, message) -> None:
            raw = _extract_js_message(message)
            try:
                payload = json.loads(raw)
            except Exception:
                return
            if not isinstance(payload, dict) or 'id' not in payload:
                return
            req_id = payload['id']
            if expected_origin is None or get_local_origin(wv.get_uri()) != expected_origin:
                resolve_bridge_call(
                    req_id,
                    False,
                    'Desktop native actions are available only in the local AnimeLab window',
                )
                return
            method = payload.get('method')
            args = payload.get('args') if isinstance(payload.get('args'), list) else []
            try:
                if method == 'platform_info':
                    resolve_bridge_call(req_id, True, {'runtime': 'desktop', 'os': 'linux'})
                elif method == 'set_title':
                    clean = sanitize_title(args[0] if args else 'AnimeLab')
                    win.set_title(clean)
                    resolve_bridge_call(req_id, True, clean)
                elif method == 'set_theme':
                    dark = str(args[0] if args else 'dark').strip().lower() != 'light'
                    apply_theme(dark)
                    resolve_bridge_call(req_id, True, True)
                elif method == 'choose_download_directory':
                    resolve_bridge_call(req_id, True, choose_download_directory())
                elif method == 'choose_external_player':
                    resolve_bridge_call(req_id, True, choose_external_player())
                else:
                    resolve_bridge_call(req_id, False, f'Unsupported desktop action: {method}')
            except Exception as exc:
                resolve_bridge_call(req_id, False, str(exc))

        ucm.connect('script-message-received::animelabBridge', on_bridge_message)

    def on_create(_webview, navigation_action):
        req = navigation_action.get_request() if hasattr(navigation_action, 'get_request') else None
        uri = str(req.get_uri() or '') if req is not None else ''
        if uri.startswith(('http://', 'https://')):
            if expected_origin is not None and get_local_origin(uri) == expected_origin:
                wv.load_uri(uri)
            else:
                webbrowser.open(uri)
        return None

    wv.connect('create', on_create)

    shown_done = False

    def mark_shown() -> None:
        nonlocal shown_done
        if shown_done:
            return
        shown_done = True
        if workdir is not None:
            (workdir / 'shown').touch()

    def quit_gtk() -> None:
        if Gtk.main_level() > 0:
            Gtk.main_quit()

    win.connect('map-event', lambda *_: (mark_shown(), False)[1])
    win.connect('destroy', lambda *_: quit_gtk())

    if workdir is not None and not probe:
        def watch_stop() -> bool:
            if (workdir / 'stop').exists():
                win.destroy()
                return False
            return True

        GLib.timeout_add(200, watch_stop)

    try:
        fd = sys.stdin.fileno()

        def on_stdin_hup(_src, _cond) -> bool:
            win.destroy()
            return False

        GLib.io_add_watch(fd, GLib.IO_HUP | GLib.IO_ERR, on_stdin_hup)
    except Exception:
        pass

    if probe:
        probe_handled = False

        def on_probe_js(webview, res, _data) -> None:
            try:
                text = _eval_js_text(webview, res)
            except Exception:
                text = None
            if text == 'AnimeLab window OK':
                if workdir is not None:
                    (workdir / 'loaded').touch()
                GLib.timeout_add(300, lambda: (win.destroy(), False)[1])

        def on_probe_load_changed(webview, event) -> None:
            nonlocal probe_handled
            if event == WebKit2.LoadEvent.FINISHED and not probe_handled:
                probe_handled = True
                _eval_js(webview, 'document.getElementById("probe").textContent', on_probe_js)

        wv.connect('load-changed', on_probe_load_changed)
        wv.load_html('<html><body><p id="probe">AnimeLab window OK</p></body></html>', 'http://127.0.0.1/')
        GLib.timeout_add_seconds(15, lambda: (win.destroy(), False)[1])
    elif url:
        def on_app_load_changed(webview, event) -> None:
            if (
                event == WebKit2.LoadEvent.FINISHED
                and expected_origin is not None
                and get_local_origin(webview.get_uri()) == expected_origin
            ):
                _eval_js(webview, "window.dispatchEvent(new Event('pywebviewready'))")

        wv.connect('load-changed', on_app_load_changed)
        wv.load_uri(str(url))

    win.show_all()
    GLib.idle_add(lambda: (mark_shown(), False)[1])
    Gtk.main()


if __name__ == '__main__':
    line = sys.stdin.readline()
    if not line.strip():
        raise SystemExit(1)
    run_window(json.loads(line))
