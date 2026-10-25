import json
from pathlib import Path
from animelab.services.unpacking import unpack, try_unpack
from animelab.services.scraping_service import scraping_service

def test_dean_edwards_unpacker():
    # Simple packed string test
    packed_html = "eval(function(p,a,c,k,e,d){return p;}('0 1 2',3,3,'hello|world|test'.split('|')))"
    result = try_unpack(packed_html)
    assert "hello world test" in result

def test_parse_episodes_from_json():
    sample_json_path = Path("/home/paulin/Projets/Animan/manga_episodes_api_response.json")
    if sample_json_path.exists():
        with open(sample_json_path, "r", encoding="utf-8") as f:
            content = f.read()
        episodes = scraping_service.parse_episodes_from_json(content)
        assert len(episodes) > 0
        ep1 = episodes[0]
        assert ep1.number >= 1
        assert ep1.version in ["VF", "VOSTFR"]
        assert ep1.playerUrl != ""
        assert ep1.downloadPageUrl != ""

def test_parse_search_results():
    sample_html_path = Path("/home/paulin/Projets/Animan/ajax_search_result.html")
    if sample_html_path.exists():
        with open(sample_html_path, "r", encoding="utf-8") as f:
            html = f.read()
        results = scraping_service.parse_search_results(html)
        assert len(results) > 0
        for r in results:
            assert r.title != ""
            assert r.url != ""
