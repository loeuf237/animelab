from animelab.services.source_http import VerificationRequired
import logging
import re
from typing import Optional

from animelab.services.extractors.base import BaseVideoExtractor, ExtractorResult

logger = logging.getLogger(__name__)

class SibnetExtractor(BaseVideoExtractor):
    name = "Sibnet"
    domains = ["sibnet.ru", "video.sibnet.ru", "dv.sibnet.ru"]

    def get_default_referer(self, url: str) -> Optional[str]:
        return "https://video.sibnet.ru/"

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

                m = re.search(r'src:\s*["\'](/v/[^"\']+\.mp4[^"\']*)["\']', resp.text)
                if not m:
                    return None

                direct_mp4 = "https://video.sibnet.ru" + m.group(1)

                # Résolution de la taille avec Range: bytes=0-0 pour contourner le rejet du HEAD
                file_size = -1
                try:
                    range_headers = {"Referer": "https://video.sibnet.ru/", "Range": "bytes=0-0"}
                    range_resp = await client.get(direct_mp4, headers=range_headers, timeout=5.0)
                    cr = range_resp.headers.get("Content-Range")
                    if cr and "/" in cr:
                        total_str = cr.split("/")[-1].strip()
                        if total_str.isdigit():
                            file_size = int(total_str)
                    if file_size <= 0:
                        cl = range_resp.headers.get("Content-Length")
                        if cl and cl.isdigit() and range_resp.status_code == 200:
                            file_size = int(cl)
                except VerificationRequired:
                    raise
                except Exception as e:
                    logger.debug("Impossible d'obtenir la taille Sibnet: %s", e)

                return ExtractorResult(
                    video_url=direct_mp4,
                    server_name="Sibnet",
                    quality="HD",
                    qualities={"HD": direct_mp4},
                    headers={"Referer": "https://video.sibnet.ru/"},
                    size=file_size,
                )
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("Erreur extraction Sibnet pour %s: %s", url, e)
            return None
