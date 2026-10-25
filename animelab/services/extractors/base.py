from animelab.services.source_http import source_http, VerificationRequired, USER_AGENT
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import logging
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

import httpx

from animelab.services.proxy_service import proxy_service

logger = logging.getLogger(__name__)

@dataclass
class ExtractorResult:
    video_url: str
    server_name: str
    quality: str = "HD"
    qualities: Dict[str, str] = field(default_factory=dict)
    qualities_sizes: Dict[str, str] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)
    size: int = -1
    subtitles: List[Dict[str, str]] = field(default_factory=list)
    audio_tracks: List[Dict[str, str]] = field(default_factory=list)

    def to_download_info(self) -> Dict[str, Any]:
        """Convertit le résultat au format attendu par le download_manager."""
        q_map = dict(self.qualities)
        if not q_map and self.video_url:
            q_map[self.quality or "HD"] = self.video_url
        elif self.quality and self.quality not in q_map and self.video_url:
            q_map[self.quality] = self.video_url

        return {
            "videoUrl": self.video_url,
            "serverType": self.server_name,
            "selectedQuality": self.quality or "HD",
            "videoQualities": json.dumps(q_map),
            "size": self.size,
            "headers": self.headers,
            "subtitles": self.subtitles,
            "audioTracks": self.audio_tracks,
        }

class BaseVideoExtractor(ABC):
    name: str = ""
    domains: List[str] = []

    def matches(self, url: str) -> bool:
        if not url:
            return False
        u = url.lower()
        return any(d in u for d in self.domains)

    def get_headers(self, url: str) -> Dict[str, str]:
        """Renvoie les en-têtes indispensables pour l'accès et le téléchargement."""
        ua = USER_AGENT
        headers = {"User-Agent": ua}
        ref = self.get_default_referer(url)
        if ref:
            headers["Referer"] = ref
        return headers

    def get_default_referer(self, url: str) -> Optional[str]:
        """Referer par défaut si aucun n'est fourni."""
        try:
            parsed = urlparse(url)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}/"
        except VerificationRequired:
            raise
        except Exception:
            pass
        return None

    def create_async_client(
        self,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 10.0,
        follow_redirects: bool = True,
    ) -> httpx.AsyncClient:
        return source_http.async_client(headers=headers, timeout=timeout, follow_redirects=follow_redirects)

    @abstractmethod
    async def extract(
        self,
        url: str,
        referer: Optional[str] = None,
        preferred_quality: Optional[str] = None,
    ) -> Optional[ExtractorResult]:
        """
        Extrait le flux vidéo direct à partir de l'URL du lecteur ou de la vidéo hébergée.
        """
        pass
