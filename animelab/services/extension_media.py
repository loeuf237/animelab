"""Short-lived media capabilities keep extension credentials out of player URLs.

HLS stays encrypted where applicable: rewrite resources, including keys/maps,
without decrypting or discarding playlist attributes. Every hop uses the normal
media destination policy. Capabilities contain no client-controlled destination.
"""
from collections import OrderedDict
from dataclasses import dataclass
import re
import secrets
import time
from urllib.parse import urljoin, urlsplit

from animelab.media_policy import validate_media_url


@dataclass(frozen=True)
class Resource:
    url: str
    headers: dict
    expires: float
    kind: str = 'auto'


class ExtensionMedia:
    def __init__(self, limit=2048, lifetime=3600, clock=time.monotonic):
        self.limit, self.lifetime, self.clock = limit, lifetime, clock
        self.resources = OrderedDict()

    def issue(self, url, headers=None, *, kind='auto', expires=None):
        validate_media_url(url)
        values = dict(headers or {})
        if len(values) > 64 or any(not isinstance(k, str) or not isinstance(v, str) or
                                   any(c in k + v for c in '\r\n\x00') or len(k + v) > 16384
                                   for k, v in values.items()):
            raise ValueError('En-têtes de média invalides.')
        blocked = {'host', 'connection', 'content-length', 'transfer-encoding', 'proxy-authorization'}
        values = {k: v for k, v in values.items() if k.lower() not in blocked}
        now = self.clock()
        self.resources = OrderedDict((k, v) for k, v in self.resources.items() if v.expires > now)
        if expires is not None:
            for token, resource in self.resources.items():
                if resource.url==url and resource.headers==values and resource.expires==expires and resource.kind==kind:
                    return '/api/media/extension-resource/' + token
        while len(self.resources) >= self.limit:
            self.resources.popitem(last=False)
        token = secrets.token_urlsafe(24)
        self.resources[token] = Resource(url, values, expires if expires is not None else now + self.lifetime, kind)
        return '/api/media/extension-resource/' + token

    def get(self, token):
        value = self.resources.get(token)
        if value is None or value.expires <= self.clock():
            self.resources.pop(token, None)
            raise ValueError('La session de lecture a expiré ; résolvez à nouveau cet épisode.')
        self.resources.move_to_end(token)
        return value

    @staticmethod
    def origin(url):
        parsed = urlsplit(url)
        return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)

    def playlist(self, text, resource, final_url):
        if not text.lstrip().startswith('#EXTM3U'):
            raise ValueError('Playlist HLS invalide.')
        if '#EXT-X-CONTENT-STEERING:' in text:
            raise ValueError('Le pilotage externe HLS n’est pas encore pris en charge.')
        def child(relative):
            absolute = urljoin(final_url, relative)
            headers = resource.headers
            if self.origin(absolute) != self.origin(resource.url):
                headers = {k: v for k, v in headers.items() if k.lower() not in ('authorization', 'cookie', 'origin')}
            return self.issue(absolute, headers, expires=resource.expires)
        lines = []
        for line in text.splitlines():
            if line.startswith('#'):
                line = re.sub(r'(?<![\w-])URI="([^"\r\n]+)"', lambda m: 'URI="' + child(m[1]) + '"', line)
            elif line.strip():
                line = child(line.strip())
            lines.append(line)
        return '\n'.join(lines) + '\n'


extension_media = ExtensionMedia()
