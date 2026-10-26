"""Scoped three-way cookie exchange; unrelated domains never cross the bridge."""
import copy
import math
import time
from urllib.parse import urlparse


def record(cookie):
    return {'name': cookie.name, 'value': cookie.value, 'domain': cookie.domain,
            'path': cookie.path, 'secure': cookie.secure, 'expires': cookie.expires,
            'httpOnly': cookie.has_nonstandard_attr('HttpOnly'),
            'sameSite': cookie.get_nonstandard_attr('SameSite')}


def scoped(url, cookies):
    host = (urlparse(url).hostname or '').lower()
    result = {}
    for item in cookies:
        domain = str(item.get('domain') or host).lower()
        name, value, path = item.get('name'), item.get('value'), item.get('path', '/')
        if (domain != host and not (domain.startswith('.') and (host == domain[1:] or host.endswith(domain)))):
            continue
        if (not isinstance(name, str) or not name or not isinstance(value, str) or not isinstance(path, str) or
                any(c in name + value + path for c in '\x00\r\n') or not path.startswith('/')):
            continue
        expiry = item.get('expires')
        if expiry is not None and (not isinstance(expiry, (float, int)) or not math.isfinite(expiry) or expiry > 0 and expiry <= time.time()):
            continue
        result[(domain, path, name)] = {'name': name, 'value': value, 'domain': domain, 'path': path,
            'secure': bool(item.get('secure', True)), 'httpOnly': bool(item.get('httpOnly', False)),
            'expires': expiry if expiry and expiry > 0 else None,
            'sameSite': item.get('sameSite') if item.get('sameSite') in ('Strict', 'Lax', 'None') else None}
    return result


def visible(url, cookies):
    path = urlparse(url).path or '/'
    return {key: item for key, item in cookies.items()
            if path == item['path'] or path.startswith(item['path'].rstrip('/') + '/')}


def snapshot(transport, url, visible_only=False):
    state = transport.state(url)
    with state.condition:
        state.cookies.clear_expired_cookies()
        values = scoped(url, [record(cookie) for cookie in state.cookies])
        return visible(url, values) if visible_only else values


def merge(transport, url, browser, previous_browser, previous_engine, expected_route, visible_only=False):
    """Only browser changes are imported; concurrent engine updates take priority."""
    state = transport.state(url)
    browser = scoped(url, browser)
    if visible_only: browser = visible(url, browser)
    with state.condition:
        if (state.proxy, state.generation) != expected_route:
            from animelab.api_errors import APIProblem
            raise APIProblem('verification_route_changed', status=409, category='protection', action='verify')
        current = snapshot(transport, url, visible_only)
        changes = {key for key in previous_browser.keys() | browser.keys()
                   if previous_browser.get(key) != browser.get(key)}
        for key in changes:
            if current.get(key) != previous_engine.get(key):
                continue
            item = browser.get(key)
            if item is None:
                if key in current:
                    state.cookies.clear(*key)
            else:
                cookie = transport.cookie(item['domain'], item['name'], item['value'], item['path'],
                                          item['secure'], int(item['expires']) if item['expires'] else None)
                if item['httpOnly']: cookie.set_nonstandard_attr('HttpOnly', None)
                if item['sameSite']: cookie.set_nonstandard_attr('SameSite', item['sameSite'])
                state.cookies.set_cookie(cookie)
        if changes:
            transport._save(state)
        return copy.deepcopy(browser), snapshot(transport, url, visible_only), bool(changes)
