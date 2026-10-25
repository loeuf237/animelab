from animelab.services.source_http import VerificationRequired
import logging
import re
from typing import Dict, Optional

from animelab.services.extractors.base import BaseVideoExtractor, ExtractorResult
from animelab.services.unpacking import try_unpack

logger = logging.getLogger(__name__)

class FilemoonExtractor(BaseVideoExtractor):
    name = "Filemoon"
    domains = [
        "filemoon.sx",
        "filemoon.to",
        "filemoon.in",
        "moonplayer",
        "byse",
        "gn1r5n",
        "weneverbeenfree",
    ]

    def get_default_referer(self, url: str) -> Optional[str]:
        u = url.lower()
        if "gn1r5n" in u or "byse" in u or "weneverbeenfree" in u:
            return "https://gn1r5n.org/"
        return "https://filemoon.sx/"

    def get_headers(self, url: str) -> Dict[str, str]:
        headers = super().get_headers(url)
        u = url.lower()
        if "gn1r5n" in u or "byse" in u or "weneverbeenfree" in u:
            headers["X-Embed-Origin"] = "voir-anime.to"
            headers["X-Embed-Referer"] = "https://voir-anime.to/"
        return headers

    async def extract(
        self,
        url: str,
        referer: Optional[str] = None,
        preferred_quality: Optional[str] = None,
    ) -> Optional[ExtractorResult]:
        try:
            ref = referer or self.get_default_referer(url)
            headers = self.get_headers(url)
            if ref:
                headers["Referer"] = ref

            async with self.create_async_client(headers=headers, timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return None

                raw_html = resp.text
                # Dépaqueter le JavaScript si présent
                unpacked_js = try_unpack(raw_html)
                search_text = f"{raw_html}\n{unpacked_js}"

                # Recherche du flux m3u8
                m = re.search(r'file:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', search_text)
                if not m:
                    m = re.search(r'sources:\s*\[\s*\{\s*file:\s*["\']([^"\']+)["\']', search_text)
                if not m:
                    m = re.search(r'["\'](https?://[^"\'\s>]+\.m3u8[^"\'\s>]*)["\']', search_text)

                if not m:
                    return None

                video_url = m.group(1)
                return ExtractorResult(
                    video_url=video_url,
                    server_name="Filemoon",
                    quality="HD",
                    qualities={"HD": video_url},
                    headers={"Referer": url},
                )
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("Erreur extraction Filemoon pour %s: %s", url, e)
            return None
