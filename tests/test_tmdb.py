import pytest
from unittest.mock import patch, AsyncMock
from animelab.models.anime import AnimeDetail, Episode
from animelab.services.tmdb_service import tmdb_service

def test_tmdb_sanitize_title():
    assert tmdb_service.sanitize_title("One Piece (VF)") == "One Piece"
    assert tmdb_service.sanitize_title("Attack on Titan Saison 4 (VOSTFR)") == "Attack on Titan"
    assert tmdb_service.sanitize_title("Demon Slayer: Kimetsu no Yaiba - Le train de l'infini") == "Demon Slayer: Kimetsu no Yaiba"
    assert tmdb_service.sanitize_title("Naruto Shippuden (TV)") == "Naruto Shippuden"
    assert tmdb_service.sanitize_title("Jujutsu Kaisen 2") == "Jujutsu Kaisen"

def test_tmdb_extract_season_number():
    assert tmdb_service.extract_season_number("Bleach Saison 2") == 2
    assert tmdb_service.extract_season_number("Dr. Stone Season 3: New World") == 3
    assert tmdb_service.extract_season_number("Solo Leveling") == 1

def test_tmdb_similarity_calculation():
    assert tmdb_service.calculate_similarity("Solo Leveling", "Solo Leveling") == 100
    assert tmdb_service.calculate_similarity("Solo Leveling", "Solo Leveling Season 2") >= 60
    assert tmdb_service.calculate_similarity("One Piece", "Dragon Ball Z") < 30

@pytest.mark.asyncio
async def test_tmdb_enrich_anime_detail():
    ep1 = Episode(number=1, title="Épisode 1", playerUrl="http://example.com/ep1", version="VOSTFR")
    ep2 = Episode(number=2, title="Épisode 2", playerUrl="http://example.com/ep2", version="VOSTFR")
    detail = AnimeDetail(
        title="Solo Leveling (VOSTFR)",
        synopsis="Court synopsis.",
        imageUrl="",
        version="VOSTFR",
        url="https://w16.french-manga.net/1-solo.html",
        episodes=[ep1, ep2],
        source="french-manga"
    )

    mock_search = {
        "id": 12345,
        "name": "Solo Leveling",
        "media_type": "tv",
        "overview": "Synopsis officiel TMDB beaucoup plus complet et riche.",
        "backdrop_path": "/backdrop.jpg",
        "poster_path": "/poster.jpg",
        "first_air_date": "2024-01-07"
    }

    mock_episodes = {
        1: {
            "title": "Je suis habitué",
            "synopsis": "Résumé officiel de l'épisode 1 par TMDB.",
            "thumbnail": "https://image.tmdb.org/t/p/w500/ep1_thumb.jpg"
        },
        2: {
            "title": "Si j'avais une autre chance",
            "synopsis": "Résumé officiel de l'épisode 2 par TMDB.",
            "thumbnail": "https://image.tmdb.org/t/p/w500/ep2_thumb.jpg"
        }
    }

    with patch.object(tmdb_service, "search_anime", new_callable=AsyncMock) as mock_s, \
         patch.object(tmdb_service, "get_season_episodes", new_callable=AsyncMock) as mock_e:
        mock_s.return_value = mock_search
        mock_e.return_value = mock_episodes

        enriched = await tmdb_service.enrich_anime_detail(detail)

        assert enriched.tmdbId == 12345
        assert enriched.synopsis == "Synopsis officiel TMDB beaucoup plus complet et riche."
        assert enriched.bannerUrl == "https://image.tmdb.org/t/p/original/backdrop.jpg"
        assert enriched.imageUrl == "https://image.tmdb.org/t/p/w500/poster.jpg"
        assert enriched.releaseDate == "2024-01-07"

        assert enriched.episodes[0].title == "Épisode 1 - Je suis habitué"
        assert enriched.episodes[0].synopsis == "Résumé officiel de l'épisode 1 par TMDB."
        assert enriched.episodes[0].thumbnailUrl == "https://image.tmdb.org/t/p/w500/ep1_thumb.jpg"

        assert enriched.episodes[1].title == "Épisode 2 - Si j'avais une autre chance"
        assert enriched.episodes[1].thumbnailUrl == "https://image.tmdb.org/t/p/w500/ep2_thumb.jpg"

@pytest.mark.asyncio
async def test_tmdb_enrich_graceful_failure():
    detail = AnimeDetail(
        title="Unknown Nonexistent Anime 9999",
        synopsis="Synopsis original.",
        url="https://w16.french-manga.net/99-unknown.html",
        episodes=[],
        source="french-manga"
    )

    with patch.object(tmdb_service, "search_anime", new_callable=AsyncMock) as mock_s:
        mock_s.side_effect = Exception("Network timeout")

        # Ne doit pas lever d'erreur et retourner le détail d'origine intact
        result = await tmdb_service.enrich_anime_detail(detail)
        assert result.title == "Unknown Nonexistent Anime 9999"
        assert result.synopsis == "Synopsis original."
