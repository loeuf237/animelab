import pytest
from bs4 import BeautifulSoup
from animelab.services.voiranime_service import voiranime_service

SAMPLE_MADARA_CARD_HTML = """
<div class="page-item-detail video">
  <div class="item-thumb c-image-hover" data-post-id="114035">
    <a href="https://voir-anime.to/anime/kaiju-girl-caramelise/" title="Kaiju Girl Caramelise">
      <img src="https://voir-anime.to/wp-content/uploads/thumb.png" alt="thumb" class="img-responsive"/>
    </a>
  </div>
  <div class="item-summary">
    <div class="post-title">
      <h3 class="h4">
        <a href="https://voir-anime.to/anime/kaiju-girl-caramelise/">Kaiju Girl Caramelise</a>
      </h3>
    </div>
    <div class="list-chapter">
      <div class="chapter-item">
        <span class="btn-link">11</span>
      </div>
    </div>
  </div>
</div>
"""

SAMPLE_SEARCH_CARD_HTML = """
<div class="row c-tabs-item__content">
  <div class="col-4">
    <div class="tab-thumb c-image-hover">
      <a href="https://voir-anime.to/anime/boruto-naruto-next-generations-vf/" title="Boruto: Naruto Next Generations (VF)">
        <img src="https://voir-anime.to/wp-content/uploads/boruto.jpg" class="img-responsive"/>
        <div class="manga-vf-flag">VF</div>
      </a>
    </div>
  </div>
  <div class="col-8">
    <div class="tab-summary">
      <div class="post-title">
        <h3 class="h4">
          <a href="https://voir-anime.to/anime/boruto-naruto-next-generations-vf/">Boruto: Naruto Next Generations (VF)</a>
        </h3>
      </div>
    </div>
  </div>
</div>
"""

SAMPLE_CHAPTERS_HTML = """
<div class="listing-chapters_wrap">
  <ul class="main version-chap">
    <li class="wp-manga-chapter">
      <a href="https://voir-anime.to/anime/test-anime/test-anime-03-vostfr/">Test Anime - 03 VOSTFR - 03</a>
    </li>
    <li class="wp-manga-chapter">
      <a href="https://voir-anime.to/anime/test-anime/test-anime-02-vostfr/">Test Anime - 02 VOSTFR - 02</a>
    </li>
    <li class="wp-manga-chapter">
      <a href="https://voir-anime.to/anime/test-anime/test-anime-01-vostfr/">Test Anime - 01 VOSTFR - 01</a>
    </li>
  </ul>
</div>
"""

SAMPLE_MASTER_M3U8 = """#EXTM3U
#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=3326401,RESOLUTION=1920x1080,FRAME-RATE=23.974
https://cdn.example.com/hls/index-1080p.m3u8?token=xyz
#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=516133,RESOLUTION=852x480,FRAME-RATE=23.974
https://cdn.example.com/hls/index-480p.m3u8?token=xyz
"""

def test_voiranime_parse_cards():
    results = voiranime_service.parse_cards(SAMPLE_MADARA_CARD_HTML)
    assert len(results) == 1
    r = results[0]
    assert r.title == "Kaiju Girl Caramelise"
    assert r.url == "https://voir-anime.to/anime/kaiju-girl-caramelise/"
    assert r.imageUrl == "https://voir-anime.to/wp-content/uploads/thumb.png"
    assert r.version == "VOSTFR"
    assert "11" in r.episodeInfo

def test_voiranime_parse_search_cards_with_vf():
    results = voiranime_service.parse_cards(SAMPLE_SEARCH_CARD_HTML)
    assert len(results) == 1
    r = results[0]
    assert "Boruto" in r.title
    assert r.version == "VF"
    assert r.url == "https://voir-anime.to/anime/boruto-naruto-next-generations-vf/"

def test_voiranime_episode_number_parsing():
    cases = [
        ("Kaiju Girl Caramelise - 11 VOSTFR - 11", "https://voir-anime.to/anime/kaiju/ep-11-vostfr/", 11),
        ("Boruto Naruto Next Generations - 293 VF - 293", "https://voir-anime.to/anime/boruto/ep-293-vf/", 293),
        ("(FILM VF) Kimetsu no Yaiba Movie 1", "https://voir-anime.to/anime/kimetsu/film-vf-1/", 1),
        ("(OAV VOSTFR) Naruto x UT", "https://voir-anime.to/anime/naruto/oav-vostfr/", 1),
        ("Solo Leveling 2 - 13 VOSTFR - 13", "https://voir-anime.to/anime/solo-2/ep-13/", 13),
        ("One Piece Episode 1050 VOSTFR", "https://voir-anime.to/anime/op/1050/", 1050),
    ]
    for title, url, expected in cases:
        parsed = voiranime_service._parse_episode_number(title, url, fallback=1)
        assert parsed == expected, f"Failed for {title}: expected {expected}, got {parsed}"

@pytest.mark.asyncio
async def test_voiranime_fetch_episodes_chronological_order():
    soup = BeautifulSoup(SAMPLE_CHAPTERS_HTML, "html.parser")
    episodes = await voiranime_service.fetch_episodes("https://voir-anime.to/anime/test-anime/", soup)
    assert len(episodes) == 3
    # Verify sorting is ascending: 1, 2, 3
    assert episodes[0].number == 1
    assert episodes[1].number == 2
    assert episodes[2].number == 3
    assert episodes[0].playerUrl == "https://voir-anime.to/anime/test-anime/test-anime-01-vostfr/"

def test_voiranime_extract_qualities_from_m3u8(monkeypatch):
    class MockResponse:
        status_code = 200
        text = SAMPLE_MASTER_M3U8

    class MockClient:
        def get(self, url, headers=None):
            return MockResponse()

    qualities = voiranime_service._extract_qualities_from_m3u8("https://cdn.example.com/hls/master.m3u8", MockClient())
    assert "1080p" in qualities
    assert "480p" in qualities
    assert "index-1080p.m3u8" in qualities["1080p"]
    assert "index-480p.m3u8" in qualities["480p"]

def test_voiranime_resolve_streamtape_modern_obfuscation():
    sample_streamtape_html = """
    <html>
      <body>
        <div id="robotlink" style="display:none;">decoy</div>
        <script>
          document.getElementById('robotlink').innerHTML = '//streamtape.com/get_video'+ ('xcd?id=testId123&expires=1789187309&ip=127.0.0.1&token=validToken').substring(2).substring(1);
          document.getElementById('ideoolink').innerHTML = '//streamtape.comb/get_video'+ ('fake').substring(1);
        </script>
      </body>
    </html>
    """
    class MockStreamtapeClient:
        def get(self, url, headers=None, follow_redirects=True, timeout=None):
            class Resp:
                def __init__(self, sc, text, headers=None):
                    self.status_code = sc
                    self.text = text
                    self.headers = headers or {}
            if "streamtape.com/e/" in url:
                return Resp(200, sample_streamtape_html)
            elif "streamtape.com/get_video?" in url:
                return Resp(302, "", {"location": "https://cdn.tapecontent.net/video.mp4"})
            return Resp(404, "")

    res = voiranime_service._resolve_streamtape("https://streamtape.com/e/testId123", "https://voir-anime.to/", MockStreamtapeClient())
    assert res == "https://cdn.tapecontent.net/video.mp4"

def test_voiranime_resolve_streamtape_deleted_video():
    deleted_html = """
    <div id="realcontent">
      <h1 class="white">Video not found!</h1>
      <p class="subheading white">Maybe it got deleted by the creator!</p>
    </div>
    """
    class MockDeletedClient:
        def get(self, url, headers=None, follow_redirects=True, timeout=None):
            class Resp:
                status_code = 200
                text = deleted_html
                headers = {}
            return Resp()

    res = voiranime_service._resolve_streamtape("https://streamtape.com/e/deleted", "https://voir-anime.to/", MockDeletedClient())
    assert res is None

def test_voiranime_parse_asp_html():
    sample_asp_html = """
    ___ASPSTART_HTML___<div id="asp-res-2188" class='item asp_r_pagepost asp_r_pagepost_2188 asp_r_wp-manga'>
        <div class='asp_content'>
            <a class='asp_res_image_url' href='https://voir-anime.to/anime/monster-vf/'>
                <div class='asp_image' data-src="https://voir-anime.to/wp-content/uploads/2020/01/thumb_5e10806794066.jpg">
                    <img loading="lazy" alt="Monster (VF)" src="https://voir-anime.to/wp-content/uploads/2020/01/thumb_5e10806794066.jpg">
                    <div class='void'></div>
                </div>
            </a>
            <h3><a class='asp_res_url' href='https://voir-anime.to/anime/monster-vf/'>Monster (VF)<span class='overlap'></span></a></h3>
            <div class='etc'></div>
            <div class='asp_res_text'>Kenzo Tenma est un medecin japonais...</div>
        </div>
        <div class='clear'></div>
    </div>___ASPEND_HTML___
    """
    items = voiranime_service.parse_asp_html(sample_asp_html, default_version="VF")
    assert len(items) == 1
    assert items[0].title == "Monster (VF)"
    assert items[0].url == "https://voir-anime.to/anime/monster-vf/"
    assert items[0].version == "VF"
    assert "thumb_5e10806794066.jpg" in items[0].imageUrl


