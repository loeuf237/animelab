from animelab.services.source_http import VerificationRequired
import logging
import re
from typing import Dict, Optional
from urllib.parse import urljoin

from animelab.services.extractors.base import BaseVideoExtractor, ExtractorResult

logger = logging.getLogger(__name__)

class VidmolyExtractor(BaseVideoExtractor):
    name = "Vidmoly"
    domains = ["ansembed", "vidmoly", "voembed", "vmeas", "vmpx"]

    def get_default_referer(self, url: str) -> Optional[str]:
        if "ansembed" in url.lower():
            return "https://ansembed.net/"
        return "https://voembed.net/"

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

                text = resp.text
                m = re.search(r'file:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', text)
                if not m:
                    m = re.search(r'sources:\s*\[\s*\{\s*file:\s*["\']([^"\']+)["\']', text)

                if not m:
                    return None

                master_m3u8 = m.group(1)
                qualities: Dict[str, str] = {"HD": master_m3u8}

                # Tenter de parser les variantes du master m3u8
                try:
                    m3u8_resp = await client.get(master_m3u8, headers={"Referer": url})
                    if m3u8_resp.status_code == 200 and "#EXT-X-STREAM-INF:" in m3u8_resp.text:
                        lines = m3u8_resp.text.strip().splitlines()
                        for i, line in enumerate(lines):
                            if line.strip().startswith("#EXT-X-STREAM-INF:"):
                                res_m = re.search(r"RESOLUTION=\d+x(\d+)", line)
                                q_label = f"{res_m.group(1)}p" if res_m else "HD"
                                if i + 1 < len(lines):
                                    cand = lines[i + 1].strip()
                                    if not cand.startswith("#"):
                                        full_cand = urljoin(master_m3u8, cand)
                                        qualities[q_label] = full_cand
                except VerificationRequired:
                    raise
                except Exception as e:
                    logger.debug("Erreur parsing variantes m3u8 Vidmoly: %s", e)

                chosen_quality = preferred_quality or "HD"
                chosen_url = qualities.get(chosen_quality) or master_m3u8
                if chosen_quality not in qualities:
                    # Trouver la meilleure qualité disponible
                    for k in ["1080p", "720p", "480p", "HD"]:
                        if k in qualities:
                            chosen_quality = k
                            chosen_url = qualities[k]
                            break

                return ExtractorResult(
                    video_url=chosen_url,
                    server_name="Vidmoly",
                    quality=chosen_quality,
                    qualities=qualities,
                    headers={"Referer": url},
                )
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("Erreur extraction Vidmoly pour %s: %s", url, e)
            return None
