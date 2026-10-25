import base64
import pytest
from animelab.services.voiranime_service import voiranime_service

def test_decode_base64_mirror_iframe():
    raw_iframe = '<iframe src="https://vidmoly.to/embed-xyz123.html" width="100%" height="100%" frameborder="0"></iframe>'
    b64_val = base64.b64encode(raw_iframe.encode("utf-8")).decode("utf-8")

    decoded = voiranime_service._decode_base64_mirror(b64_val)
    assert decoded == "https://vidmoly.to/embed-xyz123.html"

def test_decode_base64_mirror_protocol_relative():
    raw_iframe = '<iframe src="//streamtape.com/e/abc456" frameborder="0"></iframe>'
    b64_val = base64.b64encode(raw_iframe.encode("utf-8")).decode("utf-8")

    decoded = voiranime_service._decode_base64_mirror(b64_val)
    assert decoded == "https://streamtape.com/e/abc456"

def test_decode_base64_mirror_invalid():
    assert voiranime_service._decode_base64_mirror("") is None
    assert voiranime_service._decode_base64_mirror("short") is None
    assert voiranime_service._decode_base64_mirror("not_base64!@#$%^") is None

def test_parse_episode_sources_from_mirror_select():
    # Simule une page de voiranime.io avec select.mirror et options encodées en base64
    iframe1 = '<iframe src="https://vidmoly.to/embed-111.html"></iframe>'
    iframe2 = '<iframe src="https://streamtape.com/e/222"></iframe>'
    b64_1 = base64.b64encode(iframe1.encode("utf-8")).decode("utf-8")
    b64_2 = base64.b64encode(iframe2.encode("utf-8")).decode("utf-8")

    html = f"""
    <div class="player-area">
      <select class="mirror" name="mirror">
        <option data-index="1" data-name="Vidmoly" value="{b64_1}">Lecteur Vidmoly</option>
        <option data-index="2" data-name="Streamtape" value="{b64_2}">Lecteur Streamtape</option>
      </select>
    </div>
    """

    sources = voiranime_service._parse_episode_sources(html)
    assert "myTV" in sources  # Vidmoly est normalisé en myTV
    assert sources["myTV"] == "https://vidmoly.to/embed-111.html"
    assert "stape" in sources  # Streamtape est normalisé en stape
    assert sources["stape"] == "https://streamtape.com/e/222"
