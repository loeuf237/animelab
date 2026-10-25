from animelab.services.source_http import VerificationRequired
import logging
from typing import Dict, List, Optional
from urllib.parse import urlparse

from animelab.services.extractors.base import BaseVideoExtractor, ExtractorResult
from animelab.services.extractors.vidmoly import VidmolyExtractor
from animelab.services.extractors.sibnet import SibnetExtractor
from animelab.services.extractors.sendvid import SendvidExtractor
from animelab.services.extractors.streamtape import StreamtapeExtractor
from animelab.services.extractors.voe import VoeExtractor
from animelab.services.extractors.uqload import UqloadExtractor
from animelab.services.extractors.filemoon import FilemoonExtractor
from animelab.services.extractors.doodstream import DoodstreamExtractor
from animelab.services.extractors.mp4upload import Mp4uploadExtractor
from animelab.services.extractors.mailru import MailRuExtractor
from animelab.services.extractors.kwik import KwikExtractor
from animelab.services.extractors.ytdlp_fallback import YtDlpFallbackExtractor
from animelab.services.proxy_service import proxy_service
from animelab.services.source_http import USER_AGENT

logger = logging.getLogger(__name__)

class ExtractorRegistry:
    def __init__(self):
        self._extractors: List[BaseVideoExtractor] = []
        self._fallback_extractor = YtDlpFallbackExtractor()
        self._register_defaults()

    def _register_defaults(self):
        self.register(VidmolyExtractor())
        self.register(SibnetExtractor())
        self.register(SendvidExtractor())
        self.register(StreamtapeExtractor())
        self.register(VoeExtractor())
        self.register(UqloadExtractor())
        self.register(FilemoonExtractor())
        self.register(DoodstreamExtractor())
        self.register(Mp4uploadExtractor())
        self.register(MailRuExtractor())
        self.register(KwikExtractor())

    def register(self, extractor: BaseVideoExtractor):
        self._extractors.append(extractor)

    def find_extractor(self, url: str) -> Optional[BaseVideoExtractor]:
        if not url:
            return None
        for ext in self._extractors:
            if ext.matches(url):
                return ext
        return None

    def is_known_embed(self, url: str) -> bool:
        if not url:
            return False
        return self.find_extractor(url) is not None

    def get_headers_for_url(self, url: str, server_type: Optional[str] = None) -> Dict[str, str]:
        """
        Génère les en-têtes HTTP requis pour une URL donnée en déléguant à l'extracteur correspondant.
        """
        ua = USER_AGENT
        headers = {"User-Agent": ua}
        u_lower = (url or "").lower()
        s_lower = (server_type or "").lower()

        # 1. Recherche par extracteur dédié
        extractor = self.find_extractor(url)
        if extractor:
            ext_headers = extractor.get_headers(url)
            headers.update(ext_headers)
            return headers

        # 2. Cas particuliers par server_type
        if s_lower in ["stape", "streamtape"]:
            headers["Referer"] = "https://streamtape.com/"
        elif s_lower in ["vidmoly", "mytv", "voembed", "ansembed"]:
            headers["Referer"] = "https://ansembed.net/" if "ansembed" in u_lower else "https://voembed.net/"
        elif s_lower == "sibnet":
            headers["Referer"] = "https://video.sibnet.ru/"
        elif s_lower == "sendvid":
            headers["Referer"] = "https://sendvid.com/"
        elif s_lower == "uqload":
            headers["Referer"] = "https://uqload.is/"
        elif s_lower in ["fhd1", "mailru"]:
            headers["Referer"] = "https://my.mail.ru/"
        elif s_lower == "voe":
            headers["Referer"] = "https://voe.sx/"
        elif s_lower == "moon":
            headers["Referer"] = "https://gn1r5n.org/"
            headers["X-Embed-Origin"] = "voir-anime.to"
            headers["X-Embed-Referer"] = "https://voir-anime.to/"
        elif s_lower == "kwik" or "owocdn" in u_lower:
            headers["Referer"] = "https://kwik.cx/"
        elif "vidzy" in u_lower or s_lower == "vidzy":
            headers["Referer"] = "https://vidzy.live/"
        else:
            try:
                parsed = urlparse(url)
                if parsed.scheme and parsed.netloc:
                    headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
                else:
                    headers["Referer"] = "https://vidzy.live/"
            except VerificationRequired:
                raise
            except Exception:
                headers["Referer"] = "https://vidzy.live/"

        return headers

    async def extract(
        self,
        url: str,
        referer: Optional[str] = None,
        preferred_quality: Optional[str] = None,
    ) -> Optional[ExtractorResult]:
        """
        Extrait la vidéo directe. Tente d'abord l'extracteur natif dédié, puis repli vers yt-dlp.
        """
        if not url:
            return None

        extractor = self.find_extractor(url)
        if extractor:
            logger.debug("Extraction via %s pour URL: %s", extractor.name, url)
            try:
                res = await extractor.extract(url, referer=referer, preferred_quality=preferred_quality)
                if res and res.video_url:
                    return res
            except VerificationRequired:
                raise
            except Exception as e:
                logger.debug("Échec de l'extracteur %s: %s", extractor.name, e)

        # Repli silencieux vers yt-dlp
        logger.debug("Tentative repli yt-dlp pour URL: %s", url)
        try:
            res_ytdl = await self._fallback_extractor.extract(url, referer=referer, preferred_quality=preferred_quality)
            if res_ytdl and res_ytdl.video_url:
                return res_ytdl
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("Échec du repli yt-dlp: %s", e)

        return None

extractor_registry = ExtractorRegistry()
