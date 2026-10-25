from animelab.services.source_http import VerificationRequired
import logging
from typing import Optional

from animelab.services.extractors.base import BaseVideoExtractor, ExtractorResult
from animelab.services.animepahe_service import animepahe_service

logger = logging.getLogger(__name__)

class KwikExtractor(BaseVideoExtractor):
    name = "Kwik"
    domains = ["kwik.cx", "kwik.si", "kwik.sh", "pahe.win", "animepahe.org"]

    def get_default_referer(self, url: str) -> Optional[str]:
        return "https://kwik.cx/"

    async def extract(
        self,
        url: str,
        referer: Optional[str] = None,
        preferred_quality: Optional[str] = None,
    ) -> Optional[ExtractorResult]:
        try:
            direct_stream = await animepahe_service.extract_kwik_stream(url)
            if not direct_stream:
                return None

            return ExtractorResult(
                video_url=direct_stream,
                server_name="Kwik",
                quality=preferred_quality or "HD",
                qualities={"HD": direct_stream},
                headers={"Referer": "https://kwik.cx/"},
            )
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("Erreur extraction Kwik pour %s: %s", url, e)
            return None
