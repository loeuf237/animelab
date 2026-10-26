"""Old bookmarks survive removal of Jinja, without rendering or source requests."""
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from run import app
from animelab.routers.web import DESTINATIONS


@pytest.mark.parametrize('path,target', DESTINATIONS.items())
def test_bookmarks_redirect_without_contacting_sources(path, target, monkeypatch):
    from animelab.services.scraping_service import scraping_service
    source = AsyncMock(side_effect=AssertionError('A bookmark must not contact a source'))
    monkeypatch.setattr(scraping_service, 'get_latest_releases', source)
    with TestClient(app, follow_redirects=False) as client:
        response = client.get(path)
    assert response.status_code == 303
    assert response.headers['location'].split('?')[0] == '/app/' + target
    assert response.headers['cache-control'] == 'no-store'
    source.assert_not_awaited()


def test_detail_and_search_links_preserve_encoded_query_parameters():
    with TestClient(app, follow_redirects=False) as client:
        url = 'https://source.example/anime?title=été&language=VF#episodes'
        detail = client.get('/voiranime', params={'url': url, 'source': 'wrong', 'lang': 'en'})
        parsed = urlsplit(detail.headers['location'])
        assert parsed.path == '/app/anime'
        assert parse_qs(parsed.query) == {'url': [url], 'source': ['voir-anime'], 'lang': ['en']}
        search = client.get('/search', params={'q': 'été & héros', 'source': 'all', 'next': 'https://evil.example'})
        parsed = urlsplit(search.headers['location'])
        assert not parsed.netloc and parsed.path == '/app/'
        assert parse_qs(parsed.query)['q'] == ['été & héros']
        assert parse_qs(parsed.query)['search'] == ['1']


def test_templates_and_legacy_scripts_are_not_shipped():
    root = Path(__file__).resolve().parents[1]
    for name in ('animelab/templates', 'animelab/templates_config.py',
                 'animelab/static/js/app.js', 'animelab/static/js/pwa.js', 'animelab/static/css/style.css'):
        assert not (root / name).exists()
    assert 'jinja2' not in (root / 'requirements.txt').read_text().lower()
    assert 'TEMPLATES_DIR' not in (root / 'animelab/config.py').read_text()


def test_missing_spa_build_is_explicit_instead_of_falling_back_to_jinja(monkeypatch, tmp_path):
    import run
    monkeypatch.setattr(run, 'frontend_dist', tmp_path)
    with TestClient(app) as client:
        response = client.get('/settings')
    assert response.status_code == 404
    assert 'npm run build' in response.json()['error']
