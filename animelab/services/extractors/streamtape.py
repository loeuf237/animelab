from animelab.services.source_http import VerificationRequired
import logging
import re
from typing import Optional
from urllib.parse import urlparse

from animelab.services.extractors.base import BaseVideoExtractor, ExtractorResult

logger = logging.getLogger(__name__)

class StreamtapeExtractor(BaseVideoExtractor):
    name = "Streamtape"
    domains = ["streamtape.com", "tapecontent.net", "streamta.pe", "stape"]

    def get_default_referer(self, url: str) -> Optional[str]:
        return "https://streamtape.com/"

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

            vid_m = re.search(r"/[ev]/([a-zA-Z0-9]+)", url)
            video_id = vid_m.group(1) if vid_m else ""

            async with self.create_async_client(headers=headers, timeout=12.0) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return None

                st_html = resp.text
                if not st_html or "Video not found" in st_html or "deleted by the creator" in st_html or "has been removed" in st_html:
                    return None

                candidates = []

                # Extraction via obfuscation substring chain
                pattern = r"innerHTML\s*=\s*['\"]([^'\"]+)['\"]\s*\+\s*(?:''\s*\+\s*)?\(\s*['\"]([^'\"]+)['\"]\s*\)((?:\s*\.substring\(\s*\d+\s*\))+)"
                for m in re.finditer(pattern, st_html):
                    prefix = m.group(1)
                    raw_str = m.group(2)
                    sub_ops = re.findall(r"\.substring\((\d+)\)", m.group(3))
                    s = raw_str
                    for op in sub_ops:
                        s = s[int(op):]
                    cand = prefix + s
                    candidates.append(cand)

                # Fallback videolink (JS assignment ou balise HTML)
                m_tape = re.search(r"document\.getElementById\(['\"]videolink['\"]\)\.innerHTML\s*=\s*['\"]([^'\"]+)['\"]", st_html)
                if m_tape:
                    candidates.append(m_tape.group(1))
                else:
                    m_div = re.search(r'<[a-zA-Z0-9]+[^>]*id=["\']videolink["\'][^>]*>(.*?)</[a-zA-Z0-9]+>', st_html, re.DOTALL)
                    if m_div:
                        candidates.append(m_div.group(1))

                direct_url = None
                for cand in candidates:
                    cand = cand.strip()
                    if cand.startswith("//"):
                        cand = "https:" + cand
                    elif not cand.startswith("http"):
                        cand = "https://streamtape.com/" + cand.lstrip("/")

                    # Normalisation des chemins et pièges
                    cand = re.sub(r"https?://[^/]*tape[^/]*/(?:streamtape\.com/)+", "https://streamtape.com/", cand)
                    cand = re.sub(r"https?://[^/]*tape[^/]*/", "https://streamtape.com/", cand)
                    cand = cand.replace("/bget_video", "/get_video").replace("/get_videbo", "/get_video").replace("/get_vidbo", "/get_video")
                    if video_id:
                        cand = re.sub(r"([?&])(?:b?id=)[^&]+", r"\1id=" + video_id, cand)

                    if "streamtape.com/get_video?" in cand:
                        try:
                            # Test de redirection 302 vers tapecontent.net
                            r_redir = await client.get(
                                cand,
                                headers={"Referer": "https://streamtape.com/"},
                                follow_redirects=False,
                            )
                            if r_redir.status_code in [301, 302, 303, 307, 308]:
                                direct_url = r_redir.headers.get("location")
                                if direct_url:
                                    break
                            elif r_redir.status_code == 200 and "text/html" not in (r_redir.headers.get("content-type") or ""):
                                direct_url = cand
                                break
                        except VerificationRequired:
                            raise
                        except Exception as e:
                            logger.debug("Test redirection Streamtape échoué: %s", e)

                    if not direct_url and ("tapecontent.net" in cand or "get_video" in cand):
                        direct_url = cand

                if not direct_url:
                    return None

                file_size = -1
                try:
                    head_resp = await client.head(direct_url, headers={"Referer": "https://streamtape.com/"}, timeout=5.0)
                    cl = head_resp.headers.get("Content-Length")
                    if cl and cl.isdigit():
                        file_size = int(cl)
                except VerificationRequired:
                    raise
                except Exception:
                    pass

                return ExtractorResult(
                    video_url=direct_url,
                    server_name="Streamtape",
                    quality="HD",
                    qualities={"HD": direct_url},
                    headers={"Referer": "https://streamtape.com/"},
                    size=file_size,
                )
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("Erreur extraction Streamtape pour %s: %s", url, e)
            return None
