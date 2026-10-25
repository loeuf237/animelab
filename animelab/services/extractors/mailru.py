from animelab.services.source_http import VerificationRequired
import logging
import re
from typing import Dict, Optional

from animelab.services.extractors.base import BaseVideoExtractor, ExtractorResult

logger = logging.getLogger(__name__)

class MailRuExtractor(BaseVideoExtractor):
    name = "MailRu"
    domains = ["my.mail.ru", "mail.ru"]

    def get_default_referer(self, url: str) -> Optional[str]:
        return "https://my.mail.ru/"

    async def extract(
        self,
        url: str,
        referer: Optional[str] = None,
        preferred_quality: Optional[str] = None,
    ) -> Optional[ExtractorResult]:
        try:
            m_id = re.search(r"/video/embed/(\d+)", url) or re.search(r"/video/([a-zA-Z0-9_/]+)", url)
            if not m_id:
                return None

            vid_id = m_id.group(1)
            meta_url = f"https://my.mail.ru/+/video/meta/{vid_id}"

            ref = referer or self.get_default_referer(url)
            headers = self.get_headers(url)
            if ref:
                headers["Referer"] = ref

            async with self.create_async_client(headers=headers, timeout=10.0) as client:
                resp = await client.get(meta_url)
                if resp.status_code != 200:
                    return None

                data = resp.json()
                videos = data.get("videos", [])
                qualities: Dict[str, str] = {}
                for v in videos:
                    key = str(v.get("key", "HD"))
                    label = f"{key}p" if key.isdigit() else key
                    u = v.get("url")
                    if u:
                        if u.startswith("//"):
                            u = "https:" + u
                        qualities[label] = u

                if not qualities:
                    return None

                chosen_quality = preferred_quality or "1080p"
                chosen_url = qualities.get(chosen_quality)
                if not chosen_url:
                    for k in ["1080p", "720p", "480p", "360p", "HD"]:
                        if k in qualities:
                            chosen_quality = k
                            chosen_url = qualities[k]
                            break
                if not chosen_url:
                    chosen_quality, chosen_url = next(iter(qualities.items()))

                return ExtractorResult(
                    video_url=chosen_url,
                    server_name="MailRu",
                    quality=chosen_quality,
                    qualities=qualities,
                    headers={"Referer": "https://my.mail.ru/"},
                )
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("Erreur extraction MailRu pour %s: %s", url, e)
            return None
