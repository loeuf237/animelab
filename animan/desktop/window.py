"""Native UI entry point and a release probe that actually creates the window."""
from pathlib import Path
import sys
import threading
import webbrowser


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
    return str(root / 'animan/static/img/icon-512.png')


def open_window(url=None, control_url=None, workdir=None, probe=False):
    import webview
    from webview.menu import Menu, MenuAction
    from animan.services.source_http import USER_AGENT

    marker = threading.Event()
    window = webview.create_window('AnimeLab — Window check' if probe else 'AnimeLab',
        url, html='<html><body><p id="probe">AnimeLab window OK</p></body></html>' if probe else None,
        width=640 if probe else 1280, height=480 if probe else 820,
        min_size=(320, 240) if probe else (800, 600))

    def shown():
        marker.set()
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

    menu = [Menu('AnimeLab', [MenuAction('Administration', lambda: webbrowser.open(control_url)),
                             MenuAction('Quit / Quitter', window.destroy)])] if control_url else []
    from animan.services.browser_verification import browser_verification
    if not probe:
        browser_verification.webview_opener = lambda target: webview.create_window(
            'AnimeLab — Site verification', target, width=900, height=700)
    try:
        webview.start(user_agent=USER_AGENT, icon=window_icon(), menu=menu,
                      gui='edgechromium' if sys.platform == 'win32' else None)
    finally:
        browser_verification.webview_opener = None
    if probe and (not marker.is_set() or not (workdir / 'loaded').exists()):
        raise RuntimeError('Native window did not render the release probe')
