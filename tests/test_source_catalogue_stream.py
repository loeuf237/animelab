import json
from types import SimpleNamespace
import httpx
import pytest
from fastapi import FastAPI
from animelab.models.anime import AnimeResult
from animelab.routers.sources import router as sources_router
from animelab.services.recipe_plans import section_listing_plan
from animelab.services.recipe_runtime import RecipeRuntime
from animelab.services.source_catalogue import source_catalogue
from animelab.services.source_http import VerificationRequired


@pytest.mark.asyncio
async def test_recipe_runtime_expand_listing_stream_streams_and_isolates_failures():
    pages = {
        'https://anime-sama.to/catalogue/frieren/': """
            <h1 id="titreOeuvre">Frieren</h1>
            <img id="coverOeuvre" src="/img/frieren.jpg" />
            <div id="synopsisText">Fantasy</div>
            <script>
              panneauAnime("Saison 1", "saison1/vostfr");
              panneauAnime("Saison 1 VF", "saison1/vf");
            </script>
        """,
        'https://anime-sama.to/catalogue/dandadan/': """
            <h1 id="titreOeuvre">Dandadan</h1>
            <img id="coverOeuvre" src="/img/dandadan.jpg" />
            <div id="synopsisText">Action</div>
            <script>
              panneauAnime("Saison 1", "saison1/vostfr");
            </script>
        """,
    }

    async def fetch_html(url):
        if url not in pages:
            raise RuntimeError('temporary upstream timeout')
        return pages[url]

    container = SimpleNamespace(
        base_url='https://anime-sama.to',
        pkg='eu.kanade.tachiyomi.animeextension.fr.animesama',
        recipe=SimpleNamespace(runtime={'listing_expansion': section_listing_plan()}),
        _fetch_html=fetch_html,
    )
    runtime = RecipeRuntime(container)
    items = [
        AnimeResult(id='1', title='Frieren', url='https://anime-sama.to/catalogue/frieren/', imageUrl=''),
        AnimeResult(id='2', title='Broken Series', url='https://anime-sama.to/catalogue/broken/', imageUrl=''),
        AnimeResult(id='3', title='Dandadan', url='https://anime-sama.to/catalogue/dandadan/', imageUrl=''),
    ]

    batches = []
    async for batch in runtime.expand_listing_stream(items):
        batches.append(batch)

    assert len(batches) == 3
    all_urls = {entry.url for batch in batches for entry in batch}
    assert 'https://anime-sama.to/catalogue/frieren/saison1/vostfr' in all_urls
    assert 'https://anime-sama.to/catalogue/frieren/saison1/vf' in all_urls
    assert 'https://anime-sama.to/catalogue/dandadan/saison1/vostfr' in all_urls
    assert 'https://anime-sama.to/catalogue/broken/' in all_urls


@pytest.mark.asyncio
async def test_stream_catalogue_route_emits_ndjson_and_handles_challenges(monkeypatch):
    app = FastAPI()
    app.include_router(sources_router)

    async def fake_stream(source_id, mode='latest', query='', tags=(), order='source', cursor=None, native_filters=None):
        if query == 'blocked':
            raise VerificationRequired('https://voiranime.cx/challenge')
        yield {'type': 'meta', 'totalEstimate': 2}
        yield {'type': 'items', 'items': [{'id': '1', 'title': 'Frieren', 'url': 'https://voiranime.cx/anime/frieren/', 'imageUrl': '', 'source': source_id}]}
        yield {'type': 'items', 'items': [{'id': '2', 'title': 'Solo Leveling', 'url': 'https://voiranime.cx/anime/solo-leveling/', 'imageUrl': '', 'source': source_id}]}
        yield {'type': 'done', 'source': source_id, 'nextCursor': 'next-2', 'queryScope': 'catalogue'}

    monkeypatch.setattr(source_catalogue, 'browse_stream', fake_stream)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/api/sources/voir-anime/catalogue/stream?mode=popular')
        assert response.status_code == 200
        assert 'application/x-ndjson' in response.headers['content-type']
        events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        assert [e['type'] for e in events] == ['meta', 'items', 'items', 'done']
        assert events[1]['items'][0]['title'] == 'Frieren'
        assert events[3]['nextCursor'] == 'next-2'

        blocked = await client.get('/api/sources/voir-anime/catalogue/stream?mode=search&q=blocked')
        assert blocked.status_code == 200
        blocked_events = [json.loads(line) for line in blocked.text.splitlines() if line.strip()]
        assert blocked_events[0]['type'] == 'error'
        assert blocked_events[0]['status'] == 409
        assert blocked_events[0]['code'] == 'verification_required'
