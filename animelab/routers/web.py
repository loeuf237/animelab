"""Compatibility bookmarks lead to the single Vue frontend, without source I/O."""
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

router = APIRouter(include_in_schema=False)
DESTINATIONS = {
    '/': '', '/downloads': 'downloads', '/settings': 'settings',
    '/library': 'library', '/favorites': 'library', '/history': 'history',
    '/extensions': 'extensions', '/sources': 'sources',
    '/search': '', '/anime': 'anime', '/voiranime': 'anime',
}


async def legacy_page(request: Request):
    path = request.url.path
    query = list(request.query_params.multi_items())
    if path == '/search':
        query = [(key, value) for key, value in query if key != 'search'] + [('search', '1')]
    if path == '/voiranime':
        query = [(key, value) for key, value in query if key != 'source'] + [('source', 'voir-anime')]
    target = '/app/' + DESTINATIONS[path]
    if query:
        target += '?' + urlencode(query)
    return RedirectResponse(target, status_code=303, headers={'Cache-Control': 'no-store'})


for path in DESTINATIONS:
    router.add_api_route(path, legacy_page, methods=['GET', 'HEAD'])
