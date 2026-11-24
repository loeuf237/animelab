"""Self-contained GTK3 + WebKit2GTK isolated verification WebView host for Linux.

Uses an ephemeral WebKit2 WebContext so cookies, storage and cache stay isolated
from both the user's browser and AnimeLab's main desktop window while capturing
HttpOnly clearance cookies via WebKit2.CookieManager + libsoup.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

_DARK_BG = '#0f172a'
_LIGHT_BG = '#f8fafc'
_CLEARANCE_NAMES = frozenset({'cf_clearance', 'ddg_clearance', '__ddg2_', 'sucuri_cloudproxy'})
_CHALLENGE_TITLES = (
    'just a moment',
    'attention required',
    'checking your browser',
    'ddos-guard',
    'un instant',
    'vérification',
    'cloudflare',
    'please wait',
    'access denied',
    'one more step',
)


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def _apex_url(target_url: str) -> str | None:
    parsed = urlsplit(target_url or '')
    host = (parsed.hostname or '').lower()
    labels = [p for p in host.split('.') if p]
    if len(labels) < 2 or not parsed.scheme:
        return None
    return f'{parsed.scheme}://{".".join(labels[-2:])}/'


def _same_or_subdomain(base_url: str, candidate_url: str | None) -> bool:
    base_host = (urlsplit(base_url or '').hostname or '').lower()
    cand_host = (urlsplit(candidate_url or '').hostname or '').lower()
    if not base_host or not cand_host:
        return False
    base_apex = '.'.join(base_host.split('.')[-2:])
    return cand_host == base_host or cand_host == base_apex or cand_host.endswith('.' + base_apex)


def _is_challenge_title(title: str | None) -> bool:
    low = (title or '').strip().lower()
    if not low:
        return True
    return any(marker in low for marker in _CHALLENGE_TITLES)


def _cookie_expires_timestamp(cookie) -> float | None:
    try:
        exp = cookie.get_expires()
    except Exception:
        return None
    if exp is None:
        return None
    if hasattr(exp, 'to_unix'):
        val = float(exp.to_unix())
        return val if val > 0 else None
    if hasattr(exp, 'to_time_t'):
        val = float(exp.to_time_t())
        return val if val > 0 else None
    return None


def _serialize_soup_cookie(cookie, default_domain: str) -> dict | None:
    try:
        name = str(cookie.get_name() or '')
        value = str(cookie.get_value() or '')
        domain = str(cookie.get_domain() or default_domain or '')
        path = str(cookie.get_path() or '/')
        secure = bool(cookie.get_secure()) if hasattr(cookie, 'get_secure') else True
        http_only = bool(cookie.get_http_only()) if hasattr(cookie, 'get_http_only') else False
    except Exception:
        return None
    if not name:
        return None
    same_site = None
    if hasattr(cookie, 'get_same_site_policy'):
        try:
            raw_ss = str(cookie.get_same_site_policy().value_nick or '').capitalize()
            if raw_ss in ('Strict', 'Lax', 'None'):
                same_site = raw_ss
        except Exception:
            pass
    return {
        'name': name,
        'value': value,
        'domain': domain,
        'path': path,
        'secure': secure,
        'httpOnly': http_only,
        'expires': _cookie_expires_timestamp(cookie),
        'sameSite': same_site,
    }


def run_verification_webview(config: dict) -> None:
    import gi

    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    webkit_ver = '4.1'
    try:
        gi.require_version('WebKit2', '4.1')
    except ValueError:
        webkit_ver = '4.0'
        gi.require_version('WebKit2', '4.0')
    gi.require_version('Soup', '3.0' if webkit_ver == '4.1' else '2.4')
    from gi.repository import Gdk, GLib, Gtk, Soup, WebKit2

    GLib.set_prgname('animelab')
    GLib.set_application_name('AnimeLab — Verification')

    target_url = str(config.get('url') or '').strip()
    if not target_url:
        raise SystemExit(1)
    parsed_target = urlsplit(target_url)
    target_host = parsed_target.hostname or 'Verification'
    initial_cookies_cfg = list(config.get('cookies') or [])
    initial_dark = bool(config.get('initial_dark', True))
    auto_close = bool(config.get('auto_close', True))
    width = int(config.get('width') or 920)
    height = int(config.get('height') or 740)
    icon_path = config.get('icon')

    gtk_settings = Gtk.Settings.get_default()
    if gtk_settings is not None:
        try:
            gtk_settings.set_property('gtk-application-prefer-dark-theme', initial_dark)
        except Exception:
            pass

    context = WebKit2.WebContext.new_ephemeral()
    cookie_manager = context.get_cookie_manager()
    try:
        cookie_manager.set_accept_policy(WebKit2.CookieAcceptPolicy.ALWAYS)
    except Exception:
        pass

    wv = WebKit2.WebView.new_with_context(context)
    wv_settings = wv.get_settings()
    for prop, value in (
        ('enable_javascript', True),
        ('enable_dom_storage', True),
        ('enable_html5_local_storage', True),
        ('enable_mediasource', True),
        ('enable_webgl', True),
        ('enable_developer_extras', False),
    ):
        setter = f'set_{prop}'
        if hasattr(wv_settings, setter):
            try:
                getattr(wv_settings, setter)(value)
            except Exception:
                pass
    rgba = Gdk.RGBA()
    if rgba.parse(_DARK_BG if initial_dark else _LIGHT_BG):
        try:
            wv.set_background_color(rgba)
        except Exception:
            pass

    win = Gtk.Window(title=f'AnimeLab — {target_host}')
    win.set_default_size(width, height)
    if icon_path and Path(icon_path).is_file():
        try:
            win.set_icon_from_file(str(icon_path))
        except Exception:
            pass

    header = Gtk.HeaderBar()
    header.set_show_close_button(True)
    header.props.title = target_host
    header.props.subtitle = target_url

    back_btn = Gtk.Button.new_from_icon_name('go-previous-symbolic', Gtk.IconSize.BUTTON)
    forward_btn = Gtk.Button.new_from_icon_name('go-next-symbolic', Gtk.IconSize.BUTTON)
    reload_btn = Gtk.Button.new_from_icon_name('view-refresh-symbolic', Gtk.IconSize.BUTTON)
    done_btn = Gtk.Button(label='Terminer')
    done_btn.get_style_context().add_class('suggested-action')

    back_btn.set_sensitive(False)
    forward_btn.set_sensitive(False)
    header.pack_start(back_btn)
    header.pack_start(forward_btn)
    header.pack_start(reload_btn)
    header.pack_end(done_btn)
    win.set_titlebar(header)

    progress_bar = Gtk.ProgressBar()
    progress_bar.set_no_show_all(True)

    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    vbox.pack_start(progress_bar, False, False, 0)
    vbox.pack_start(wv, True, True, 0)
    win.add(vbox)

    closing = False
    auto_close_timer = None
    initial_cookie_keys = {
        (str(item.get('domain') or '').lower(), str(item.get('path') or '/'), str(item.get('name') or ''))
        for item in initial_cookies_cfg
        if item.get('name')
    }

    def update_nav() -> None:
        if closing:
            return
        back_btn.set_sensitive(wv.can_go_back())
        forward_btn.set_sensitive(wv.can_go_forward())
        cur_uri = wv.get_uri() or target_url
        cur_title = wv.get_title() or target_host
        header.props.title = ' '.join(cur_title.split())[:80] or target_host
        header.props.subtitle = cur_uri

    back_btn.connect('clicked', lambda *_: wv.go_back() if wv.can_go_back() else None)
    forward_btn.connect('clicked', lambda *_: wv.go_forward() if wv.can_go_forward() else None)
    reload_btn.connect('clicked', lambda *_: wv.reload())

    def collect_cookies(callback, req_id: str | None = None) -> None:
        uris = []
        for candidate in (_apex_url(target_url), wv.get_uri(), target_url):
            if candidate and candidate.startswith(('http://', 'https://')) and candidate not in uris:
                uris.append(candidate)
        if not uris:
            callback([], req_id)
            return

        collected: dict[tuple[str, str, str], dict] = {}
        pending = len(uris)

        def on_uri_cookies(manager, res, _data) -> None:
            nonlocal pending
            try:
                cookies_list = manager.get_cookies_finish(res) or []
                for c in cookies_list:
                    rec = _serialize_soup_cookie(c, target_host)
                    if rec:
                        collected[(rec['domain'].lower(), rec['path'], rec['name'])] = rec
            except Exception:
                pass
            pending -= 1
            if pending == 0:
                callback(list(collected.values()), req_id)

        for uri in uris:
            cookie_manager.get_cookies(uri, None, on_uri_cookies, None)

    def apply_seed_cookies(items: list[dict], done_cb=None) -> None:
        if not items:
            if done_cb:
                done_cb()
            return
        pending = len(items)

        def one_done(manager, res, _data) -> None:
            nonlocal pending
            try:
                if hasattr(manager, 'add_cookie_finish'):
                    manager.add_cookie_finish(res)
            except Exception:
                pass
            pending -= 1
            if pending == 0 and done_cb:
                done_cb()

        def one_deleted(manager, res, _data) -> None:
            nonlocal pending
            try:
                if hasattr(manager, 'delete_cookie_finish'):
                    manager.delete_cookie_finish(res)
            except Exception:
                pass
            pending -= 1
            if pending == 0 and done_cb:
                done_cb()

        now = time.time()
        for item in items:
            name = str(item.get('name') or '')
            value = str(item.get('value') or '')
            domain = str(item.get('domain') or target_host)
            path = str(item.get('path') or '/')
            exp = item.get('expires')
            if exp is not None and exp <= now:
                sc = Soup.Cookie.new(name, '', domain, path, 0)
                cookie_manager.delete_cookie(sc, None, one_deleted, None)
                continue
            max_age = max(1, int(exp - now)) if exp is not None else -1
            sc = Soup.Cookie.new(name, value, domain, path, max_age)
            sc.set_secure(bool(item.get('secure', parsed_target.scheme == 'https')))
            sc.set_http_only(bool(item.get('httpOnly', False)))
            cookie_manager.add_cookie(sc, None, one_done, None)

    def finish_and_close() -> None:
        nonlocal closing
        if closing:
            return
        closing = True
        if auto_close_timer is not None:
            try:
                GLib.source_remove(auto_close_timer)
            except Exception:
                pass

        def after_flush(records: list[dict], _req_id: str | None) -> None:
            _emit({'event': 'cookies', 'cookies': records, 'url': wv.get_uri() or target_url, 'title': wv.get_title() or ''})
            _emit({'event': 'closed'})
            win.destroy()

        collect_cookies(after_flush)

    done_btn.connect('clicked', lambda *_: finish_and_close())

    def on_delete_event(_win, _event) -> bool:
        if closing:
            return False
        finish_and_close()
        return True

    win.connect('delete-event', on_delete_event)
    win.connect('destroy', lambda *_: Gtk.main_quit() if Gtk.main_level() > 0 else None)

    def on_progress(_wv, _pspec) -> None:
        prog = float(wv.get_estimated_load_progress() or 0.0)
        if 0.0 < prog < 1.0:
            progress_bar.set_fraction(prog)
            progress_bar.show()
        else:
            progress_bar.hide()

    wv.connect('notify::estimated-load-progress', on_progress)
    wv.connect('notify::title', lambda *_: update_nav())

    def on_create(_wv, navigation_action):
        req = navigation_action.get_request() if hasattr(navigation_action, 'get_request') else None
        uri = str(req.get_uri() or '') if req is not None else ''
        if uri.startswith('https://') or (parsed_target.scheme == 'http' and uri.startswith('http://')):
            wv.load_uri(uri)
        return None

    wv.connect('create', on_create)

    def on_load_changed(_wv, event) -> None:
        nonlocal auto_close_timer
        update_nav()
        if event != WebKit2.LoadEvent.FINISHED or closing:
            return

        cur_url = wv.get_uri() or target_url
        cur_title = wv.get_title() or ''

        def after_collect(records: list[dict], _req_id: str | None) -> None:
            nonlocal auto_close_timer
            if closing:
                return
            _emit({'event': 'cookies', 'cookies': records, 'url': cur_url, 'title': cur_title})
            if not auto_close or not _same_or_subdomain(target_url, cur_url) or _is_challenge_title(cur_title):
                return
            has_clearance = any(r['name'] in _CLEARANCE_NAMES for r in records)
            cur_keys = {(r['domain'].lower(), r['path'], r['name']) for r in records}
            changed = bool(records) and cur_keys != initial_cookie_keys
            if not has_clearance and not changed:
                return
            if auto_close_timer is not None:
                try:
                    GLib.source_remove(auto_close_timer)
                except Exception:
                    pass

            def delayed_close() -> bool:
                nonlocal auto_close_timer
                auto_close_timer = None
                if not closing and _same_or_subdomain(target_url, wv.get_uri() or cur_url) and not _is_challenge_title(wv.get_title() or cur_title):
                    finish_and_close()
                return False

            auto_close_timer = GLib.timeout_add(1200, delayed_close)

        collect_cookies(after_collect)

    wv.connect('load-changed', on_load_changed)

    stdin_buf = ''

    def handle_command(raw: str) -> None:
        try:
            cmd_obj = json.loads(raw)
        except Exception:
            return
        if not isinstance(cmd_obj, dict):
            return
        cmd = cmd_obj.get('cmd')
        if cmd == 'get_cookies':
            collect_cookies(
                lambda records, rid: _emit({'event': 'cookies', 'req_id': rid, 'cookies': records}),
                cmd_obj.get('req_id'),
            )
        elif cmd == 'set_cookies':
            apply_seed_cookies(list(cmd_obj.get('cookies') or []))
        elif cmd == 'close':
            finish_and_close()

    try:
        fd = sys.stdin.fileno()

        def on_stdin_ready(_src, cond) -> bool:
            nonlocal stdin_buf
            if cond & (GLib.IO_HUP | GLib.IO_ERR):
                finish_and_close()
                return False
            try:
                data = os.read(fd, 4096)
            except Exception:
                data = b''
            if not data:
                finish_and_close()
                return False
            stdin_buf += data.decode('utf-8', errors='replace')
            while '\n' in stdin_buf:
                line, stdin_buf = stdin_buf.split('\n', 1)
                if line.strip():
                    handle_command(line)
            return True

        GLib.io_add_watch(fd, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, on_stdin_ready)
    except Exception:
        pass

    ua = ''
    try:
        if hasattr(wv_settings, 'get_user_agent'):
            ua = str(wv_settings.get_user_agent() or '')
    except Exception:
        pass
    _emit({'event': 'ready', 'userAgent': ua})

    apply_seed_cookies(initial_cookies_cfg, lambda: wv.load_uri(target_url))
    win.show_all()
    progress_bar.hide()
    Gtk.main()


if __name__ == '__main__':
    first_line = sys.stdin.readline()
    if not first_line.strip():
        raise SystemExit(1)
    run_verification_webview(json.loads(first_line))
