from animelab.services.source_http import VerificationRequired
import base64
import html
import json
import logging
import re
from typing import Dict, Optional
from urllib.parse import urlparse

from animelab.services.extractors.base import BaseVideoExtractor, ExtractorResult

logger = logging.getLogger(__name__)

class VoeExtractor(BaseVideoExtractor):
    name = "VOE"
    domains = [
        "voe.sx",
        "johnfullwonder",
        "voe-un-block",
        "repackers",
        "roberttranspiration",
        "audaciousdefaulthouse",
        "maxfinishsubsequent",
    ]

    def get_default_referer(self, url: str) -> Optional[str]:
        return "https://voe.sx/"

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

            async with self.create_async_client(headers=headers, timeout=12.0) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return None

                html_text = resp.text
                curr_url = str(resp.url)

                # Suivi de redirection JavaScript window.location.href
                redir_m = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", html_text)
                if redir_m:
                    curr_url = redir_m.group(1)
                    redir_resp = await client.get(curr_url, headers={"Referer": url})
                    if redir_resp.status_code == 200:
                        html_text = redir_resp.text
                        curr_url = str(redir_resp.url)

                qualities: Dict[str, str] = {}

                # 1. Tenter la page /download de VOE (direct MP4 multi-qualités)
                vid_m = re.search(r"/[ed]/([a-zA-Z0-9]+)", curr_url) or re.search(r"/[ed]/([a-zA-Z0-9]+)", url)
                if vid_m:
                    vid = vid_m.group(1)
                    parsed_u = urlparse(curr_url)
                    host = parsed_u.netloc or "voe.sx"
                    dl_page_url = f"https://{host}/{vid}/download"
                    try:
                        r_dl = await client.get(dl_page_url, headers={"Referer": curr_url}, timeout=8.0)
                        if r_dl.status_code == 200:
                            dl_html = r_dl.text
                            for a_m in re.finditer(
                                r"<a[^>]+href=[\x27\x22](https?://[^\x27\x22]+)[\x27\x22][^>]*>(.*?)</a>",
                                dl_html,
                                re.DOTALL,
                            ):
                                href = html.unescape(a_m.group(1))
                                text = a_m.group(2).strip()
                                if ".mp4" in href or "download" in href:
                                    q_m = re.search(r"(\d{3,4}p)", text, re.IGNORECASE)
                                    q_label = f"{q_m.group(1)}" if q_m else "720p"
                                    qualities[q_label] = href
                    except VerificationRequired:
                        raise
                    except Exception as e:
                        logger.debug("Erreur page download VOE: %s", e)

                # 2. Recherche de payload base64 / sources json
                if not qualities:
                    # Recherche sources JSON explicites
                    m_src = re.search(r"sources\s*=\s*(\{.+?\});", html_text, re.DOTALL)
                    if m_src:
                        try:
                            s_data = json.loads(m_src.group(1))
                            hls = s_data.get("hls") or s_data.get("mp4")
                            if hls:
                                qualities["HD"] = html.unescape(hls)
                        except VerificationRequired:
                            raise
                        except Exception:
                            pass

                # 3. Recherche de base64 atob() souvent utilisé par VOE
                if not qualities:
                    b64_matches = re.findall(r"atob\(['\"]([A-Za-z0-9+/=]{20,})['\"]\)", html_text)
                    for b64_str in b64_matches:
                        try:
                            decoded = base64.b64decode(b64_str).decode("utf-8", errors="ignore")
                            if ".m3u8" in decoded or ".mp4" in decoded:
                                m_url = re.search(r'https?://[^\s\'"<>]+', decoded)
                                if m_url:
                                    qualities["HD"] = m_url.group(0)
                                    break
                        except VerificationRequired:
                            raise
                        except Exception:
                            continue

                # 4. Fallback Regex m3u8 et mp4
                if not qualities:
                    m3u8_matches = re.findall(r"['\"](https?://[^\s'\"<>]+\.m3u8[^\s'\"<>]*)['\"]", html_text)
                    mp4_matches = re.findall(r"['\"](https?://[^\s'\"<>]+\.mp4[^\s'\"<>]*)['\"]", html_text)

                    valid_m3u8 = [html.unescape(u) for u in m3u8_matches if "google" not in u]
                    valid_mp4 = [html.unescape(u) for u in mp4_matches if "test-videos" not in u and "google" not in u]

                    if valid_m3u8:
                        qualities["HD"] = valid_m3u8[0]
                    elif valid_mp4:
                        qualities["HD"] = valid_mp4[0]

                if not qualities:
                    return None

                chosen_quality = preferred_quality or "1080p"
                chosen_url = qualities.get(chosen_quality)
                if not chosen_url:
                    for k in ["1080p", "720p", "480p", "HD"]:
                        if k in qualities:
                            chosen_quality = k
                            chosen_url = qualities[k]
                            break
                if not chosen_url:
                    chosen_quality, chosen_url = next(iter(qualities.items()))

                return ExtractorResult(
                    video_url=chosen_url,
                    server_name="VOE",
                    quality=chosen_quality,
                    qualities=qualities,
                    headers={"Referer": "https://voe.sx/"},
                )
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("Erreur extraction VOE pour %s: %s", url, e)
            return None
