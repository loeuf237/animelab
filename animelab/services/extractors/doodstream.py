from animelab.services.source_http import VerificationRequired
import logging
import random
import re
import string
import time
from typing import Optional
from urllib.parse import urlparse

from animelab.services.extractors.base import BaseVideoExtractor, ExtractorResult

logger = logging.getLogger(__name__)

class DoodstreamExtractor(BaseVideoExtractor):
    name = "Doodstream"
    domains = [
        "doodstream.com",
        "dood.to",
        "dood.so",
        "dood.cx",
        "dood.la",
        "dood.watch",
        "dood.ws",
        "dood.re",
        "dood.pm",
        "ds2play",
        "doods.pro",
    ]

    def get_default_referer(self, url: str) -> Optional[str]:
        try:
            parsed = urlparse(url)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}/"
        except VerificationRequired:
            raise
        except Exception:
            pass
        return "https://dood.to/"

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

            parsed = urlparse(url)
            host = parsed.netloc or "dood.to"

            async with self.create_async_client(headers=headers, timeout=12.0) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return None

                html = resp.text
                md5_match = re.search(r"/(pass_md5/[^\"'/\s]+)", html)
                if not md5_match:
                    return None

                pass_md5_path = md5_match.group(1)
                pass_md5_url = f"https://{host}/{pass_md5_path}"

                # Token makePlay
                token_match = re.search(r"makePlay.*?return\s*a\s*\+\s*\"([^\"]+)\"", html)
                token_suffix = token_match.group(1) if token_match else ""

                md5_headers = {"Referer": url, "User-Agent": headers.get("User-Agent", "")}
                md5_resp = await client.get(pass_md5_url, headers=md5_headers)
                if md5_resp.status_code != 200 or not md5_resp.text:
                    return None

                base_video_url = md5_resp.text.strip()
                rand_str = "".join(random.choices(string.ascii_letters + string.digits, k=10))
                now_ts = int(time.time() * 1000)

                direct_video_url = f"{base_video_url}{rand_str}?token={pass_md5_path.split('/')[-1]}&expiry={now_ts}"

                return ExtractorResult(
                    video_url=direct_video_url,
                    server_name="Doodstream",
                    quality="HD",
                    qualities={"HD": direct_video_url},
                    headers={"Referer": f"https://{host}/"},
                )
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("Erreur extraction Doodstream pour %s: %s", url, e)
            return None
