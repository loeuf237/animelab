from animelab.services.source_http import source_http, VerificationRequired, USER_AGENT
import asyncio
import io
import logging
from typing import Optional

from animelab.services.extractors.base import BaseVideoExtractor, ExtractorResult

logger = logging.getLogger(__name__)

class _YtdlQuietLogger:
    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass

class YtDlpFallbackExtractor(BaseVideoExtractor):
    name = "yt-dlp"
    domains = []

    def matches(self, url: str) -> bool:
        # Utilisé explicitement comme repli par le registre
        return False

    async def extract(
        self,
        url: str,
        referer: Optional[str] = None,
        preferred_quality: Optional[str] = None,
    ) -> Optional[ExtractorResult]:
        try:
            import yt_dlp
            from yt_dlp.networking.common import Response as YtdlResponse
            from yt_dlp.networking.exceptions import HTTPError

            def shared_urlopen(request):
                target = request if isinstance(request, str) else getattr(request, "url", None) or request.full_url
                method = getattr(request, "method", None) or (
                    request.get_method() if hasattr(request, "get_method") else "GET")
                headers = dict(getattr(request, "headers", {}) or {})
                if referer:
                    headers.setdefault("Referer", referer)
                response = source_http.request(method, target, headers=headers,
                                               data=getattr(request, "data", None))
                result = YtdlResponse(io.BytesIO(response.content), str(response.url),
                                      dict(response.headers), status=response.status_code)
                if response.status_code >= 400:
                    raise HTTPError(result)
                return result

            def _extract_sync():
                ydl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "skip_download": True,
                    "logger": _YtdlQuietLogger(),
                }
                if referer:
                    ydl_opts["http_headers"] = {"Referer": referer}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    # Override this instance only; all fallback extractor HTTP
                    # requests retain the same source sessions and challenge checks.
                    ydl.urlopen = shared_urlopen
                    return ydl.extract_info(url, download=False)

            info = await asyncio.to_thread(_extract_sync)
            if not info:
                return None

            direct = info.get("url")
            if not direct and info.get("formats"):
                valid_fmts = [f for f in info["formats"] if f.get("url")]
                if valid_fmts:
                    direct = valid_fmts[-1]["url"]

            if not direct:
                return None

            sz = info.get("filesize") or info.get("filesize_approx") or -1
            extractor_name = info.get("extractor", "yt-dlp")
            headers = {"User-Agent": USER_AGENT}
            if referer:
                headers["Referer"] = referer

            return ExtractorResult(
                video_url=direct,
                server_name=extractor_name,
                quality="HD",
                qualities={"HD": direct},
                headers=headers,
                size=sz if sz and sz > 0 else -1,
            )
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("Extraction yt-dlp échouée pour %s: %s", url, e)
            return None
