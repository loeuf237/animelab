from animelab.services.source_http import VerificationRequired
import logging
import re
from typing import Optional

from animelab.services.extractors.base import BaseVideoExtractor, ExtractorResult
from animelab.services.unpacking import try_unpack

logger = logging.getLogger(__name__)

class Mp4uploadExtractor(BaseVideoExtractor):
    name = "Mp4upload"
    domains = ["mp4upload.com"]

    def get_default_referer(self, url: str) -> Optional[str]:
        return "https://www.mp4upload.com/"

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
                unpacked = try_unpack(raw_html)
                search_text = f"{raw_html}\n{unpacked}"

                m = (
                    re.search(r'player\.src\(\s*["\'](https?://[^"\']+\.mp4[^"\']*)["\']', search_text)
                    or re.search(r'src:\s*["\'](https?://[^"\']+\.mp4[^"\']*)["\']', search_text)
                    or re.search(r'<source[^>]*src=["\'](https?://[^"\']+\.mp4[^"\']*)["\']', search_text)
                )

                if not m:
                    return None

                direct_mp4 = m.group(1)
                file_size = -1
                try:
                    head_resp = await client.head(direct_mp4, headers={"Referer": "https://www.mp4upload.com/"}, timeout=5.0)
                    cl = head_resp.headers.get("Content-Length")
                    if cl and cl.isdigit():
                        file_size = int(cl)
                except VerificationRequired:
                    raise
                except Exception:
                    pass

                return ExtractorResult(
                    video_url=direct_mp4,
                    server_name="Mp4upload",
                    quality="HD",
                    qualities={"HD": direct_mp4},
                    headers={"Referer": "https://www.mp4upload.com/"},
                    size=file_size,
                )
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("Erreur extraction Mp4upload pour %s: %s", url, e)
            return None
