import io
import logging
import re
import struct
import zipfile
from animelab.services.recipe_plans import source_key, compile_operations
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

logger = logging.getLogger("animelab.dex_parser")


class RecipeVersionError(ValueError):
    pass


@dataclass
class SourceRecipe:
    """Recette de scraping extraite depuis le bytecode Dalvik d'une extension Aniyomi."""
    schema_version: int = 1
    name: str = ""
    pkg: str = ""
    base_url: str = ""
    lang: str = "all"
    supports_latest: bool = True
    multi_tags: bool = False
    multisrc_theme: str = ""

    # Sélecteurs CSS
    popular_selector: str = ""
    popular_next_selector: str = ""
    latest_selector: str = ""
    latest_next_selector: str = ""
    search_selector: str = ""
    search_next_selector: str = ""
    episode_list_selector: str = ""

    # Routes & Requêtes
    popular_request_path: str = ""
    latest_request_path: str = ""
    search_request_path: str = ""
    search_query_param: str = "s"  # ex: 's', 'keyword', 'story', 'q'
    search_method: str = "GET"     # 'GET' ou 'POST'
    search_post_params: Dict[str, str] = field(default_factory=dict)

    # Filtres, Tags, Tris & Recettes propres à la source (AnimeFilterList)
    tag_request_path: str = ""
    tag_param: str = ""
    order_param: str = ""
    filter_tags: Dict[str, str] = field(default_factory=dict)
    filter_orders: Dict[str, str] = field(default_factory=dict)
    filter_groups: List[Dict[str, Any]] = field(default_factory=list)
    custom_feeds: List[Dict[str, str]] = field(default_factory=list)

    # Extraction d'éléments
    item_title_selector: str = ""
    item_link_selector: str = ""
    item_thumb_selector: str = ""

    # Détails & streaming
    details_title_selector: str = ""
    details_synopsis_selector: str = ""
    details_genre_selector: str = ""
    details_status_selector: str = ""
    details_thumb_selector: str = ""

    # Épisodes & Lecteurs
    episode_link_selector: str = ""
    episode_name_selector: str = ""
    video_iframe_regex: str = r'<iframe[^>]*\ssrc=["\']([^"\']+)["\']'
    raw_strings: List[str] = field(default_factory=list)
    runtime: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourceRecipe":
        if not isinstance(data, dict) or type(data.get("schema_version", 1)) is not int or data.get("schema_version", 1) not in (1, 2):
            raise RecipeVersionError("Unsupported recipe schema version")
        cleaned = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        cleaned["schema_version"] = 1
        return cls(**cleaned)


def _is_valid_base_url(candidate: str) -> bool:
    if not candidate or not (candidate.startswith("https://") or candidate.startswith("http://")):
        return False
    stripped = candidate.rstrip("/")
    if stripped in ("https:", "http:", "https", "http"):
        return False
    skip_markers = (
        "schemas.android.com",
        "w3.org",
        "github.com",
        "google.com",
        "googleapis.com",
        "auth.hanime.tv",
        "htv-services.com",
        "freeanimehentai.net",
        "vidmoly.",
        "sibnet.",
        "sendvid.",
        "streamtape.",
        "uqload.",
        "voe.sx",
        "dood",
        "filemoon.",
        "mp4upload.",
        "mail.ru",
        "ok.ru",
        "vk.com",
        "dailymotion.",
        "yourupload.",
        "127.0.0.1",
        "localhost",
    )
    if any(m in stripped.lower() for m in skip_markers):
        return False
    host_part = stripped.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    parts = host_part.split(".")
    return len(parts) >= 2 and all(len(p) >= 2 and not p.startswith("-") for p in parts)


def _has_balanced_braces(text: str) -> bool:
    return text.count("{") == text.count("}")


def _is_usable_path_fragment(candidate: str) -> bool:
    s = candidate.strip()
    if not s or s in ("&", "?", "/#", "/"):
        return False
    if "://" in s or "{{" in s or not _has_balanced_braces(s):
        return False
    if any(ch.isspace() for ch in s):
        return False
    return True


def _reconstruct_request_path(m_strs: List[str]) -> str:
    """Reconstruit fidèlement le chemin HTTP à partir des constantes de popularAnimeRequest / latestUpdatesRequest."""
    raw_paths = [
        s.strip() for s in m_strs
        if isinstance(s, str) and (
            s.startswith("/") or s.startswith("?") or s.startswith("&")
            or "page=" in s or "m_orderby=" in s or "status=" in s
        )
    ]
    if not raw_paths:
        return ""
    paths = [p for p in raw_paths if (p == "/" or _is_usable_path_fragment(p)) and not p.startswith("&")]
    amp_extras = [p for p in raw_paths if p.startswith("&") and len(p) > 1 and _is_usable_path_fragment(p) and not p.endswith("=")]
    if not paths:
        return ""

    # Cas multi-fragments avec numéro de page intercalé : ex ['/filter-advance/page/', '/'] ou ['/page/', '/?m_orderby=views']
    if len(paths) >= 2 and paths[0].endswith("/page/"):
        suffix = paths[1]
        if suffix == "/":
            return f"{paths[0]}1/"
        if suffix.startswith("/?") or suffix.startswith("?"):
            q = suffix.lstrip("/")
            return f"{paths[0]}1/{q}"
        if suffix.startswith("/"):
            return f"{paths[0]}1{suffix}"

    for p in paths:
        if p.endswith(("?page=", "&page=")):
            res = p + "1"
            for extra in amp_extras:
                if extra not in res:
                    res += extra
            return res

    # Choisir le fragment le plus informatif (jamais un fragment commençant par '&' ni un '/' nu)
    non_root = [p for p in paths if p not in ("/", "/#", "?")]
    if non_root:
        best = non_root[0]
        if best.endswith("/page/"):
            best = best + "1/"
        elif best.endswith(("?page=", "&page=")):
            best = best + "1"
        if "?" in best:
            for extra in amp_extras:
                if extra not in best:
                    best += extra
        return best
    return "/"


def _reconstruct_search_path(m_strs: List[str], existing_param: str = "") -> tuple[str, str]:
    """Reconstruit le chemin de recherche et le paramètre requête depuis searchAnimeRequest."""
    query_param = existing_param
    candidates: List[str] = []
    has_page_prefix = False
    for raw in m_strs:
        if not isinstance(raw, str):
            continue
        s = raw.strip()
        if s in ("s", "keyword", "story", "q", "query", "search", "title", "k", "term"):
            query_param = s
            continue
        if s.endswith("/page/") and not any(ch.isspace() for ch in s):
            has_page_prefix = True
        if (s.startswith("/") or ("?" in s and not s.startswith("&") and "://" not in s)) and _is_usable_path_fragment(s):
            candidates.append(s)

    if not candidates:
        return "", query_param

    # Préférer les chemins qui contiennent un paramètre GET ou un segment /search/, plutôt qu'un préfixe nu /page/
    scored = sorted(
        candidates,
        key=lambda p: (
            "?" in p and "=" in p,
            "?" in p,
            "search" in p.lower() or "filter" in p.lower(),
            not p.endswith("/page/"),
            len(p),
        ),
        reverse=True,
    )
    chosen = scored[0]
    if chosen.startswith("/?") and has_page_prefix and "/page/" not in chosen:
        chosen = f"/page/1/{chosen.lstrip('/')}"
    elif chosen.endswith("/page/"):
        chosen = chosen + "1/"
    if chosen.endswith("="):
        chosen = chosen + "{query}"
    elif (
        "?" not in chosen
        and "{query}" not in chosen
        and not query_param
        and (chosen.endswith("/search/") or chosen.endswith("/search/title/") or ("/search/" in chosen and chosen.endswith("/")))
    ):
        chosen = chosen + "{query}"

    if not query_param:
        m_param = re.search(r"[?&]([a-zA-Z0-9_-]+)=\{query\}", chosen)
        if m_param:
            query_param = m_param.group(1)

    return chosen, query_param


class AniyomiDexParser:
    """Analyseur pur-Python pour décompiler et convertir les règles de scraping d'un APK Aniyomi."""

    @staticmethod
    def parse_apk(apk_bytes: bytes, pkg_name: str = "", default_base_url: str = "", *, strict: bool = False) -> SourceRecipe:
        """Extrait classes.dex depuis un APK et analyse les méthodes de scraping."""
        clean_default = default_base_url.rstrip("/") if _is_valid_base_url(default_base_url) else ""
        recipe = SourceRecipe(pkg=pkg_name, base_url=clean_default)
        try:
            with zipfile.ZipFile(io.BytesIO(apk_bytes)) as z:
                dex_names = [n for n in z.namelist() if n.endswith(".dex")]
                all_dex_data = [z.read(n) for n in dex_names]
        except Exception as e:
            logger.error("[dex_parser] Erreur ouverture ZIP de l'APK: %s", e)
            if strict:
                raise ValueError('Impossible de lire les fichiers DEX de l’APK.') from e
            AniyomiDexParser._fill_heuristics(recipe)
            return recipe

        for dex in all_dex_data:
            try:
                AniyomiDexParser._parse_dex_data(dex, recipe)
            except Exception as e:
                logger.warning("[dex_parser] Erreur analyse DEX: %s", e)
                if strict:
                    raise ValueError('Impossible d’analyser les fichiers DEX de l’APK.') from e

        # Complétion heuristique et profils Aniyomi/Anikku
        AniyomiDexParser._fill_heuristics(recipe)
        return recipe

    @staticmethod
    def _read_uleb128(data: bytes, pos: int):
        val = 0
        shift = 0
        while True:
            b = data[pos]
            pos += 1
            val |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                break
            shift += 7
        return val, pos

    @staticmethod
    def _parse_dex_data(dex: bytes, recipe: SourceRecipe):
        if len(dex) < 0x70 or dex[:4] != b"dex\n":
            return

        # 1. String IDs
        string_ids_size, string_ids_off = struct.unpack_from("<II", dex, 0x38)
        strings: List[str] = []
        for i in range(string_ids_size):
            off, = struct.unpack_from("<I", dex, string_ids_off + i * 4)
            pos = off
            while dex[pos] & 0x80:
                pos += 1
            pos += 1
            end = dex.find(b"\x00", pos)
            strings.append(dex[pos:end].decode("utf-8", errors="replace"))

        recipe.raw_strings = [
            s for s in strings
            if 1 < len(s) < 120 and any(c in s for c in [".", "/", "http", "div", "span", "a", "img", "search", "genre", "page"])
        ]

        # 2. Type IDs
        type_ids_size, type_ids_off = struct.unpack_from("<II", dex, 0x40)
        types = [strings[struct.unpack_from("<I", dex, type_ids_off + i * 4)[0]] for i in range(type_ids_size)]

        # 3. Method IDs
        method_ids_size, method_ids_off = struct.unpack_from("<II", dex, 0x58)
        methods = []
        for i in range(method_ids_size):
            c_idx, p_idx, n_idx = struct.unpack_from("<HHI", dex, method_ids_off + i * 8)
            methods.append((types[c_idx], strings[n_idx]))

        # 4. Class Defs & Méthodes (avec hiérarchie d'héritage)
        class_defs_size, class_defs_off = struct.unpack_from("<II", dex, 0x60)
        class_Hierarchy: Dict[str, str] = {}
        class_methods: Dict[str, Dict[str, List[str]]] = {}

        for c in range(class_defs_size):
            class_idx, access_flags, superclass_idx, interfaces_off, source_file_idx, annotations_off, class_data_off, static_values_off = struct.unpack_from(
                "<IIIIIIII", dex, class_defs_off + c * 32
            )
            c_type = types[class_idx] if class_idx < len(types) else ""
            s_type = types[superclass_idx] if superclass_idx != 0xFFFFFFFF and superclass_idx < len(types) else ""
            if c_type:
                class_Hierarchy[c_type] = s_type
                class_methods.setdefault(c_type, {})

            if class_data_off == 0 or not c_type:
                continue

            pos = class_data_off
            num_static_fields, pos = AniyomiDexParser._read_uleb128(dex, pos)
            num_instance_fields, pos = AniyomiDexParser._read_uleb128(dex, pos)
            num_direct_methods, pos = AniyomiDexParser._read_uleb128(dex, pos)
            num_virtual_methods, pos = AniyomiDexParser._read_uleb128(dex, pos)

            for _ in range(num_static_fields + num_instance_fields):
                _, pos = AniyomiDexParser._read_uleb128(dex, pos)
                _, pos = AniyomiDexParser._read_uleb128(dex, pos)

            for m_count in (num_direct_methods, num_virtual_methods):
                method_idx = 0
                for _ in range(m_count):
                    diff, pos = AniyomiDexParser._read_uleb128(dex, pos)
                    method_idx += diff
                    m_flags, pos = AniyomiDexParser._read_uleb128(dex, pos)
                    code_off, pos = AniyomiDexParser._read_uleb128(dex, pos)
                    if code_off > 0 and method_idx < len(methods):
                        m_class, m_name = methods[method_idx]
                        registers_size, ins_size, outs_size, tries_size, debug_info_off, insns_size = struct.unpack_from("<HHHHII", dex, code_off)
                        insns_off = code_off + 16
                        insns = dex[insns_off:insns_off + insns_size * 2]

                        m_strings: List[str] = []
                        ip = 0
                        while ip < len(insns) - 1:
                            op = insns[ip]
                            if op == 0x1A and ip + 3 < len(insns):
                                str_idx, = struct.unpack_from("<H", insns, ip + 2)
                                if str_idx < len(strings):
                                    m_strings.append(strings[str_idx])
                                ip += 4
                            elif op == 0x1B and ip + 5 < len(insns):
                                str_idx, = struct.unpack_from("<I", insns, ip + 2)
                                if str_idx < len(strings):
                                    m_strings.append(strings[str_idx])
                                ip += 6
                            else:
                                ip += 2

                        if m_strings:
                            existing = class_methods[c_type].get(m_name, [])
                            class_methods[c_type][m_name] = existing + m_strings

        # Détection du thème Multisrc éventuel
        for c_type, s_type in class_Hierarchy.items():
            combined = f"{c_type} {s_type}".lower()
            if "datalifeengine" in combined:
                recipe.multisrc_theme = "datalifeengine"
            elif "dooplay" in combined:
                recipe.multisrc_theme = "dooplay"
            elif "wpanime" in combined:
                recipe.multisrc_theme = "wpanime"
            elif "madara" in combined:
                recipe.multisrc_theme = "madara"
            elif "zoro" in combined:
                recipe.multisrc_theme = "zoro"

        # Identification des classes sources principales (AnimeHttpSource / ParsedAnimeHttpSource / Multisrc)
        source_base_markers = (
            "AnimeHttpSource",
            "ParsedAnimeHttpSource",
            "ConfigurableAnimeSource",
            "multisrc/dooplay",
            "multisrc/wpanime",
            "multisrc/madara",
            "multisrc/zoro",
            "multisrc/datalifeengine",
        )
        source_classes: List[str] = []
        extends_parsed_source = False
        for c_type in class_Hierarchy:
            cur = c_type
            visited = set()
            while cur and cur not in visited:
                visited.add(cur)
                parent = class_Hierarchy.get(cur, "")
                if "ParsedAnimeHttpSource" in parent or "multisrc/" in parent:
                    extends_parsed_source = True
                if any(marker in parent for marker in source_base_markers):
                    source_classes.append(c_type)
                    break
                cur = parent

        # Construire method_strings_map en priorisant la hiérarchie de la classe source principale
        method_strings_map: Dict[str, List[str]] = {}
        ordered_classes: List[str] = []
        for sc in source_classes:
            cur = sc
            while cur and cur in class_methods and cur not in ordered_classes:
                ordered_classes.append(cur)
                cur = class_Hierarchy.get(cur, "")
        if not ordered_classes:
            ordered_classes = [c for c in class_methods if recipe.pkg.replace(".", "/") in c]

        # On parcourt en ordre inverse pour que les classes principales (en tête) gagnent
        for c_type in reversed(ordered_classes):
            for m_name, m_strs in class_methods.get(c_type, {}).items():
                method_strings_map[m_name] = m_strs

        # Extraction de base_url depuis la classe source principale (constructeur <init> ou getBaseUrl)
        if not _is_valid_base_url(recipe.base_url):
            recipe.base_url = ""
            for sc in source_classes:
                for m_name in ("getBaseUrl", "<init>", "<clinit>"):
                    for s in class_methods.get(sc, {}).get(m_name, []):
                        if _is_valid_base_url(s):
                            recipe.base_url = s.rstrip("/")
                            break
                    if recipe.base_url:
                        break
                if recipe.base_url:
                    break
        if not _is_valid_base_url(recipe.base_url):
            for s in strings:
                if _is_valid_base_url(s):
                    recipe.base_url = s.rstrip("/")
                    break

        # 5. Mapping des chaînes extraites vers la recette
        for m_name, m_strs in method_strings_map.items():
            if "popularAnimeSelector" in m_name and m_strs:
                recipe.popular_selector = m_strs[0]
            elif "popularAnimeNextPageSelector" in m_name and m_strs:
                recipe.popular_next_selector = m_strs[0]
            elif "latestUpdatesSelector" in m_name and m_strs:
                recipe.latest_selector = m_strs[0]
            elif "latestUpdatesNextPageSelector" in m_name and m_strs:
                recipe.latest_next_selector = m_strs[0]
            elif "searchAnimeSelector" in m_name and m_strs:
                recipe.search_selector = m_strs[0]
            elif "searchAnimeNextPageSelector" in m_name and m_strs:
                recipe.search_next_selector = m_strs[0]
            elif "episodeListSelector" in m_name and m_strs:
                recipe.episode_list_selector = m_strs[0]
            elif "popularAnimeRequest" in m_name:
                reconstructed = _reconstruct_request_path(m_strs)
                if reconstructed:
                    recipe.popular_request_path = reconstructed
            elif "latestUpdatesRequest" in m_name:
                reconstructed = _reconstruct_request_path(m_strs)
                if reconstructed:
                    recipe.latest_request_path = reconstructed
            elif "searchAnimeRequest" in m_name:
                search_path, detected_param = _reconstruct_search_path(m_strs)
                if search_path and (not recipe.search_request_path or len(search_path) >= len(recipe.search_request_path)):
                    recipe.search_request_path = search_path
                if detected_param:
                    recipe.search_query_param = detected_param
                if "POST" in m_strs or "FormBody" in m_strs or "do=search" in "".join(m_strs):
                    recipe.search_method = "POST"

        # Extraction des sélecteurs depuis *AnimeParse si *AnimeSelector n'est pas utilisé
        def _is_non_card_selector(sc: str) -> bool:
            low = sc.lower()
            if sc.startswith(("link[", "meta[", "head", "script", "style")):
                return True
            if re.search(
                r"(?:^|[.#\s>])(?:next|prev|previous|pagination|pager|page-numbers|wp-pagenavi|breadcrumb|nav-links)(?:$|[\s.#:\[])",
                low,
            ):
                return True
            if re.fullmatch(r"(?:a|li|span|div)[.#](?:next|prev|footer|header|menu|nav)", low):
                return True
            return False

        def _extract_css_from_parse(m_strs: List[str]) -> str:
            cands = []
            for s in m_strs:
                sc = s.strip()
                if not sc or _is_non_card_selector(sc):
                    continue
                if any(sc.startswith(p) for p in ("div.", "ul.", "li.", "article", "#", ".")):
                    if " " in sc or "." in sc or "#" in sc or ">" in sc:
                        cands.append(sc)
            return ", ".join(dict.fromkeys(cands[:3]))

        if not recipe.popular_selector and "popularAnimeParse" in method_strings_map:
            sel = _extract_css_from_parse(method_strings_map["popularAnimeParse"])
            if sel:
                recipe.popular_selector = sel
        if not recipe.latest_selector and "latestUpdatesParse" in method_strings_map:
            sel = _extract_css_from_parse(method_strings_map["latestUpdatesParse"])
            if sel:
                recipe.latest_selector = sel
        if not recipe.search_selector and "searchAnimeParse" in method_strings_map:
            sel = _extract_css_from_parse(method_strings_map["searchAnimeParse"])
            if sel:
                recipe.search_selector = sel

        # Element functions expose selectors independently of page-level selectors.
        for method in ("popularAnimeFromElement", "latestUpdatesFromElement", "searchAnimeFromElement"):
            values = method_strings_map.get(method, [])
            for value in values:
                low = value.lower()
                if (
                    not value.startswith(("http", "//", "(", "[", "/"))
                    and "href" not in low
                    and len(value) <= 60
                    and re.search(r"(?:title|\bh[1-4]\b|\.name\b|\.tt\b|anime-title|film-name|serie-title|entry-title)", low)
                ):
                    recipe.item_title_selector = recipe.item_title_selector or value
                elif "img" in low and not value.startswith(("http", "//")):
                    recipe.item_thumb_selector = recipe.item_thumb_selector or value

        dex_has_selectors = any(
            bool(getattr(recipe, f))
            for f in ("popular_selector", "latest_selector", "search_selector", "episode_list_selector")
        )
        if source_classes and not extends_parsed_source and not dex_has_selectors:
            method_tokens = " ".join(
                s.lower() for m_strs in method_strings_map.values() for s in m_strs if isinstance(s, str)
            )
            has_api_marker = any(
                tok in method_tokens
                for tok in ("graphql", "application/json", "/api/", "query {", "mutation ", "bearer ")
            ) or any(
                s == "parseAs" or s.startswith(("Lkotlinx/serialization/", "Lcom/google/gson/"))
                for s in strings
            )
            if has_api_marker:
                recipe.runtime["_dex_direct_api"] = True

        # Literal label/path pairs in source constructors (e.g. DLE genres).
        # Restrict extraction to the source hierarchy, never bundled extractors.
        for values in method_strings_map.values():
            for label, path in zip(values, values[1:]):
                if path.startswith('/genre/') and path.endswith('/') and 1 < len(label) < 50 and not label.startswith(('/', 'http')):
                    recipe.filter_tags.setdefault(label, path.strip('/').split('/')[-1])

        # Extraction des filtres AnimeFilter depuis les classes du DEX (uniquement les sous-classes d'AnimeFilter)
        for c_type, s_type in class_Hierarchy.items():
            if "AnimeFilter" in s_type:
                init_strs = class_methods.get(c_type, {}).get("<init>", []) + class_methods.get(c_type, {}).get("<clinit>", [])
                clean_tokens = [
                    t for t in init_strs
                    if 1 <= len(t) <= 40 and not t.startswith(("http", "L", "[L", "(", "kotlin", "java", "_"))
                ]
                # Ignorer le titre initial du filtre si le nombre d'éléments est impair
                if len(clean_tokens) >= 7 and len(clean_tokens) % 2 == 1:
                    clean_tokens = clean_tokens[1:]
                if len(clean_tokens) >= 6 and len(clean_tokens) % 2 == 0:
                    pairs = list(zip(clean_tokens[0::2], clean_tokens[1::2]))
                    if any(v in ("latest", "views", "rating", "trending", "alphabet", "new-manga", "created_at_unix", "likes") for _, v in pairs):
                        for label, val in pairs:
                            if val and label:
                                recipe.filter_orders.setdefault(label, val)
                    elif len(pairs) >= 5 and all(" " not in v or "+" in v or v == "" for _, v in pairs[:5]):
                        for label, val in pairs:
                            if val and not val.startswith("/") and label.lower() not in ("tous", "all", "<select>", "select", "tout", "-----"):
                                recipe.filter_tags.setdefault(label, val)

        # Expressions régulières vidéo
        for s in strings:
            if "<iframe" in s:
                recipe.video_iframe_regex = s
                break

    @staticmethod
    def _fill_heuristics(recipe: SourceRecipe):
        """Remplit les sélecteurs, routes populaires, filtres/tags et recettes spécifiques par profil."""
        pkg_lower = (recipe.pkg or "").lower()
        base_lower = (recipe.base_url or "").lower()
        identity = source_key(recipe.pkg, recipe.base_url)

        if not _is_valid_base_url(recipe.base_url):
            if "jetanime" in pkg_lower:
                recipe.base_url = "https://ssl.jetanimes.com"
            elif identity == "frenchanime":
                recipe.base_url = "https://french-anime.com"
            elif identity == "hanime":
                recipe.base_url = "https://hanime.tv"
            elif "animesama" in pkg_lower:
                recipe.base_url = "https://anime-sama.to"
            elif "animevostfr" in pkg_lower:
                recipe.base_url = "https://animevostfr.tv"
            elif "anisama" in pkg_lower:
                recipe.base_url = "https://v1.animesz.xyz"
            elif "franime" in pkg_lower:
                recipe.base_url = "https://franime.fr"
            elif "voiranime" in pkg_lower:
                recipe.base_url = "https://voiranime.cx"
            elif "vostfree" in pkg_lower:
                recipe.base_url = "https://vostfree.ws"
            elif "aniworld" in pkg_lower:
                recipe.base_url = "https://aniworld.to"
            elif "hentaihaven" in pkg_lower:
                recipe.base_url = "https://hentaihaven.xxx"
            base_lower = (recipe.base_url or "").lower()

        # Profils spécialisés pour les extensions Aniyomi / Anikku
        if "animesama" in pkg_lower or "anime-sama" in base_lower:
            recipe.multi_tags = True
            recipe.search_selector = recipe.search_selector or "#list_catalog > div, #list_catalog > div a, .catalog-card, #containerAjoutsAnimes > div"
            recipe.popular_selector = "#containerPepites > div a, #containerClassiques > div a, #list_catalog > div"
            recipe.latest_selector = "#containerSorties .as-carte-anime, #containerAjoutsAnimes .as-carte-anime, #containerAjoutsAnimes > div"
            recipe.popular_request_path = recipe.popular_request_path or "/"
            recipe.latest_request_path = recipe.latest_request_path or "/"
            recipe.search_request_path = recipe.search_request_path or "/catalogue/?search={query}"
            recipe.tag_request_path = "/catalogue/?genre[]={tag}&page={page}"
            recipe.tag_param = "genre[]"
            recipe.search_query_param = "search"
            recipe.item_title_selector = ".card-title, .as-carte-titre, h2, h3, img[alt]"
            recipe.item_thumb_selector = "img.card-image, img[src], img[data-src]"
            recipe.item_link_selector = "a[href]"
            genres = [
                "Action", "Adolescence", "Aliens", "Amitié", "Amour", "Apocalypse", "Art",
                "Arts martiaux", "Assassins", "Autre monde", "Aventure", "Combats", "Comédie",
                "Comédie romantique", "Cuisine", "Cyberpunk", "Danse", "Démons", "Détective",
                "Dieux / Déesses", "Drame", "Ecchi", "École", "Énigme", "Enquête", "Espace",
                "Exorcistes", "Famille", "Fantaisie", "Fantômes", "Football", "Futur", "Gastronomie",
                "Guerre", "Harem", "Harem inversé", "Histoire", "Historique", "Horreur", "Idols",
                "Isekai", "Jeunesse", "Jeux", "Jeux vidéo", "Josei", "Chevaliers", "Mafia", "Magie",
                "Maladie", "Mariage", "Mature", "Mecha", "Médiéval", "Militaire", "Monde virtuel",
                "Monstres", "Musique", "Mystère", "Mythologie", "Ninjas", "Nostalgie", "Paranormal",
                "Philosophie", "Pirates", "Police", "Politique", "Post-apocalyptique", "Pouvoirs",
                "Psychologique", "Quotidien", "Réincarnation", "Religion", "Romance", "Samouraïs",
                "School Life", "Science-Fiction", "Seinen", "Shojo", "Shonen", "Shonen Ai",
                "Slice of Life", "Société", "Sport", "Super-héros", "Surnaturel", "Survie",
                "Suspense", "Technologie", "Tournois", "Tragédie", "Tranche de vie", "Vampires",
                "Vengeance", "Voyage", "Voyage temporel", "Yakuza", "Yaoi", "Yuri",
            ]
            recipe.filter_tags = {g.strip(): g.strip() for g in genres}
            if not recipe.filter_groups:
                recipe.filter_groups = [
                    {
                        "key": "type",
                        "label": "Type",
                        "param": "type[]",
                        "multi": True,
                        "options": [
                            {"label": "Anime", "value": "Anime"},
                            {"label": "Film", "value": "Film"},
                            {"label": "Autres", "value": "Autres"},
                        ],
                    },
                    {
                        "key": "langue",
                        "label": "Langue",
                        "param": "langue[]",
                        "multi": True,
                        "options": [
                            {"label": "VOSTFR", "value": "VOSTFR"},
                            {"label": "VF", "value": "VF"},
                            {"label": "VASTFR", "value": "VASTFR"},
                        ],
                    },
                ]
            if not recipe.custom_feeds:
                recipe.custom_feeds = [
                    {"id": "pepites", "label": "Pépites", "path": "/", "selector": "#containerPepites > div, #containerPepites a"},
                    {"id": "classiques", "label": "Classiques", "path": "/", "selector": "#containerClassiques > div, #containerClassiques a"},
                    {"id": "films", "label": "Films", "path": "/catalogue/?type[]=Film", "selector": "#list_catalog > div"},
                    {"id": "vf", "label": "Animes VF", "path": "/catalogue/?type[]=Anime&langue[]=VF", "selector": "#list_catalog > div"},
                ]

        elif "animevostfr" in pkg_lower or "animevostfr" in base_lower:
            recipe.search_selector = "div.ml-item, .film_list article"
            recipe.popular_selector = "div.ml-item"
            recipe.latest_selector = "div.ml-item"
            recipe.popular_request_path = "/filter-advance/page/1/"
            recipe.popular_next_selector = "ul.pagination li:not(.active):last-child a"
            recipe.latest_request_path = "/filter-advance/page/1/?status=ongoing"
            recipe.latest_next_selector = "ul.pagination li:not(.active):last-child a"
            recipe.search_request_path = "/?s={query}"
            recipe.tag_request_path = "/filter-advance/page/{page}/?genre={tag}"
            recipe.tag_param = "genre"
            recipe.episode_list_selector = "div#seasonss > div.les-title > a, .les-content a"
            recipe.item_title_selector = "span.mli-info > h2, h3, h2, .title"
            recipe.item_thumb_selector = "div.thumb > img, img[src], img[data-src]"
            recipe.filter_tags = {
                g.replace("-", " ").title(): g
                for g in [
                    "action", "adventure", "animation", "biography", "comedy", "crime", "documentary",
                    "drama", "ecchi", "family", "fantasy", "fantastique", "foreign", "gore", "harem",
                    "historical", "history", "horror", "isekai", "jeux-video", "josei", "kids", "magic",
                    "martial-arts", "mecha", "military", "music", "mystery", "parody", "police",
                    "psychological", "romance", "samurai", "school", "sci-fi", "science-fiction",
                    "seinen", "shoujo", "shounen", "slice-of-life", "space", "sports", "super-power",
                    "supernatural", "thriller", "vampire", "war", "western",
                ]
            }
            if not recipe.filter_groups:
                recipe.filter_groups = [
                    {
                        "key": "typesub",
                        "label": "Langue",
                        "param": "typesub",
                        "multi": False,
                        "options": [
                            {"label": "VOSTFR", "value": "vostfr"},
                            {"label": "VF", "value": "vf"},
                            {"label": "VO", "value": "vo"},
                        ],
                    },
                    {
                        "key": "status",
                        "label": "Statut",
                        "param": "status",
                        "multi": False,
                        "options": [
                            {"label": "En cours", "value": "ongoing"},
                            {"label": "Terminé", "value": "completed"},
                        ],
                    },
                    {
                        "key": "topic",
                        "label": "Type",
                        "param": "topic",
                        "multi": False,
                        "options": [
                            {"label": "Anime", "value": "anime"},
                            {"label": "Film", "value": "movie"},
                            {"label": "Série", "value": "series"},
                            {"label": "Cartoon", "value": "cartoon"},
                        ],
                    },
                ]
            if not recipe.custom_feeds:
                recipe.custom_feeds = [
                    {"id": "vf", "label": "Animes VF", "path": "/filter-advance/page/1/?typesub=vf", "selector": "div.ml-item"},
                    {"id": "vostfr", "label": "Animes VOSTFR", "path": "/filter-advance/page/1/?typesub=vostfr", "selector": "div.ml-item"},
                    {"id": "movies", "label": "Films", "path": "/filter-advance/page/1/?topic=movie", "selector": "div.ml-item"},
                ]

        elif "vostfree" in pkg_lower or "vostfree" in base_lower:
            recipe.multisrc_theme = "dle"
            recipe.search_method = "POST"
            if not recipe.search_request_path or recipe.search_request_path == "/animes-vostfr/page/":
                recipe.search_request_path = "/index.php?do=search"
            recipe.search_query_param = "story"
            recipe.search_post_params = {
                "do": "search",
                "subaction": "search",
                "search_start": "1",
                "full_search": "0",
                "result_from": "1",
            }
            recipe.search_selector = "#dle-content .search-result, #dle-content .movie-poster"
            recipe.popular_request_path = "/films-vf-vostfr/page/1/"
            recipe.popular_selector = "#dle-content .movie-poster, #dle-content .search-result"
            recipe.popular_next_selector = "span.next-page a, .navigation a"
            recipe.latest_request_path = "/animes-vostfr/page/1/"
            recipe.latest_selector = "#dle-content .movie-poster, #dle-content .search-result"
            recipe.latest_next_selector = "span.next-page a, .navigation a"
            recipe.tag_request_path = "/genre/{tag}/page/{page}/"
            recipe.item_link_selector = ".play a[href], .info-ems .title a[href], a[href]"
            recipe.item_title_selector = ".info-ems .title, .title, h2, h3"
            recipe.item_thumb_selector = ".image img, img[src], img[data-src]"
            recipe.episode_list_selector = "select.new_player_selector option"
            recipe.details_thumb_selector = "div.slide-poster img"
            recipe.filter_tags = {
                "Action": "Action",
                "Comédie": "Comédie",
                "Drame": "Drame",
                "Surnaturel": "Surnaturel",
                "Shonen": "Shonen",
                "Romance": "Romance",
                "Tranche de vie": "Tranche+de+vie",
                "Fantasy": "Fantasy",
                "Mystère": "Mystère",
                "Psychologique": "Psychologique",
                "Sci-Fi": "Sci-Fi",
            }
            if not recipe.custom_feeds:
                recipe.custom_feeds = [
                    {"id": "animes_vf", "label": "Animes VF", "path": "/animes-vf/page/1/", "selector": "#dle-content .movie-poster"},
                    {"id": "animes_vostfr", "label": "Animes VOSTFR", "path": "/animes-vostfr/page/1/", "selector": "#dle-content .movie-poster"},
                    {"id": "films", "label": "Films VF/VOSTFR", "path": "/films-vf-vostfr/page/1/", "selector": "#dle-content .movie-poster"},
                ]

        elif "anisama" in pkg_lower or "animesz" in base_lower:
            recipe.multisrc_theme = "wpanime"
            recipe.search_selector = ".film_list article, .film_list .film-item"
            recipe.popular_selector = ".film_list article, .film_list .film-item"
            recipe.latest_selector = ".film_list article, .film_list .film-item"
            recipe.popular_request_path = "/most-popular/?page=1"
            recipe.popular_next_selector = ".ap__-btn-next a:not(.disabled)"
            if not recipe.latest_request_path or recipe.latest_request_path.endswith("?page="):
                recipe.latest_request_path = "/recently-added/?page=1"
            recipe.latest_next_selector = ".ap__-btn-next a:not(.disabled)"
            recipe.search_request_path = "/filter?keyword={query}"
            recipe.tag_request_path = "/filter?genre={tag}&page={page}"
            recipe.tag_param = "genre"
            recipe.order_param = "sort"
            recipe.item_title_selector = ".dynamic-name, h3, h2, .title"
            recipe.item_thumb_selector = ".film-poster-img, img[src], img[data-src]"
            recipe.filter_tags = {
                "Action": "action",
                "Aventure": "adventure",
                "Comédie": "comedy",
                "Drame": "drama",
                "Fantaisie": "fantasy",
                "Horreur": "horror",
                "Isekai": "isekai",
                "Magie": "magic",
                "Mecha": "mecha",
                "Mystère": "mystery",
                "Psychologique": "psychological",
                "Romance": "romance",
                "Sci-Fi": "sci-fi",
                "Seinen": "seinen",
                "Shoujo": "shoujo",
                "Shounen": "shounen",
                "Slice of Life": "slice-of-life",
                "Sports": "sports",
                "Surnaturel": "supernatural",
                "Thriller": "thriller",
            }
            recipe.filter_orders = {
                "Populaires": "most-popular",
                "Récents": "recently-added",
                "Dernières sorties": "recently-updated",
                "Score": "score",
                "Titre A-Z": "name-az",
            }
            if not recipe.custom_feeds:
                recipe.custom_feeds = [
                    {"id": "popular", "label": "Plus populaires", "path": "/most-popular/?page=1", "selector": ".film_list article"},
                    {"id": "recent", "label": "Récemment ajoutés", "path": "/recently-added/?page=1", "selector": ".film_list article"},
                ]

        elif "jetanime" in pkg_lower or "jetanime" in base_lower:
            recipe.multisrc_theme = "dooplay"
            recipe.search_selector = "div#archive-content > article, div.search-page > div.result-item, div.content article, article"
            recipe.popular_selector = "aside#dtw_content_views-2 div.dtw_content > article, div.content article, article"
            if not recipe.latest_selector or recipe.latest_selector == "div.content article > div.poster":
                recipe.latest_selector = "div.content article"
            recipe.popular_request_path = recipe.popular_request_path or "/"
            if not recipe.latest_request_path or recipe.latest_request_path == "/page/":
                recipe.latest_request_path = "/page/1/"
            recipe.latest_next_selector = "div.pagination > span.current + a, .pagination a.next"
            recipe.search_request_path = "/?s={query}"
            recipe.tag_request_path = "/genre/{tag}/page/{page}/"
            recipe.item_link_selector = "div.poster a[href], div.image a[href], .data h3 a[href], a[href]"
            recipe.item_title_selector = ".data h3, h3, .title, img[alt]"
            recipe.item_thumb_selector = "div.poster img, div.image img, img[data-src], img[src]"
            recipe.episode_list_selector = "ul.episodios > li, #seasons .episodiotitle a, .episodiotitle a"
            recipe.filter_tags = {
                "Action": "action",
                "Aventure": "aventure",
                "Comédie": "comedie",
                "Drame": "drame",
                "Fantastique": "fantastique",
                "Animation": "animation",
                "Science-Fiction": "science-fiction",
                "Romance": "romance",
                "Mystère": "mystere",
            }
            if not recipe.custom_feeds:
                recipe.custom_feeds = [
                    {"id": "series", "label": "Séries Animes", "path": "/serie/", "selector": "div.content article"},
                    {"id": "films", "label": "Films Animes", "path": "/films/", "selector": "div.content article"},
                ]

        elif "voiranime" in pkg_lower or "voir-anime" in base_lower or "voiranime" in base_lower:
            recipe.multisrc_theme = "madara"
            recipe.multi_tags = True
            current_cards = ".page-item-detail.video, .page-item-detail, .c-tabs-item__content"
            recipe.search_selector = recipe.search_selector or current_cards
            recipe.latest_selector = recipe.latest_selector or current_cards
            recipe.popular_selector = recipe.popular_selector or current_cards
            recipe.popular_request_path = "/page/1/?s&post_type=wp-manga&m_orderby=trending"
            recipe.popular_next_selector = "a.nextpostslink, .wp-pagenavi a.next"
            recipe.latest_request_path = recipe.latest_request_path or "/page/1/?s&post_type=wp-manga&m_orderby=new-manga"
            recipe.latest_next_selector = "a.nextpostslink, .wp-pagenavi a.next"
            recipe.search_request_path = "/?s={query}&post_type=wp-manga"
            recipe.tag_request_path = "/?s=&post_type=wp-manga&genre[]={tag}&op=AND"
            recipe.tag_param = "genre[]"
            recipe.order_param = "m_orderby"
            recipe.item_link_selector = ".post-title a[href], .item-thumb a[href], .tab-thumb a[href]"
            recipe.item_title_selector = ".post-title a, h3.h5 a, h3 a"
            recipe.item_thumb_selector = ".item-thumb img, .tab-thumb img"
            recipe.episode_list_selector = "li.wp-manga-chapter, .listing-chapters .chapter-item"
            recipe.filter_orders = {
                "Date de mise à jour": "latest",
                "Nouveautés": "new-manga",
                "Populaires": "trending",
                "Plus vues": "views",
                "Note": "rating",
                "Titre A → Z": "alphabet",
            }
            recipe.filter_tags = {
                label: slug
                for label, slug in [
                    ("Action", "action"), ("Aventure", "adventure"), ("Comédie", "comedy"),
                    ("Drame", "drama"), ("Ecchi", "ecchi"), ("Fantaisie", "fantasy"),
                    ("Horreur", "horror"), ("Mecha", "mecha"), ("Mystère", "mystery"),
                    ("Psychologique", "psychological"), ("Romance", "romance"),
                    ("Sci-Fi", "sci-fi"), ("Slice of Life", "slice-of-life"),
                    ("Sports", "sports"), ("Surnaturel", "supernatural"), ("Thriller", "thriller"),
                ]
            }
            if not recipe.custom_feeds:
                recipe.custom_feeds = [
                    {"id": "trending", "label": "Tendances", "path": "/page/1/?s&post_type=wp-manga&m_orderby=trending", "selector": current_cards},
                    {"id": "views", "label": "Plus vus", "path": "/page/1/?s&post_type=wp-manga&m_orderby=views", "selector": current_cards},
                    {"id": "rating", "label": "Mieux notés", "path": "/page/1/?s&post_type=wp-manga&m_orderby=rating", "selector": current_cards},
                ]

        elif identity == "frenchanime":
            # DataLifeEngine constants from the upstream extension, never Hanime.
            recipe.multisrc_theme = "datalifeengine"
            recipe.popular_request_path = recipe.popular_request_path or "/animes-vostfr/page/1/"
            recipe.latest_request_path = recipe.latest_request_path or "/"
            recipe.search_request_path = "/index.php?do=search"
            recipe.search_method = "POST"
            recipe.search_query_param = "story"
            recipe.search_post_params = {"do": "search", "subaction": "search", "full_search": "0"}
            recipe.popular_selector = recipe.popular_selector or "div#dle-content > div.mov"
            recipe.latest_selector = recipe.latest_selector or recipe.popular_selector
            recipe.search_selector = recipe.search_selector or recipe.popular_selector
            recipe.item_title_selector = recipe.item_title_selector or ".short-title a, .shortstory-title a, h2 a, h3 a"
            recipe.details_thumb_selector = recipe.details_thumb_selector or ".full-poster img, .fposter img, .poster img"
            recipe.popular_next_selector = recipe.popular_next_selector or "span.navigation > span:not(.nav_ext) + a"
            recipe.search_next_selector = recipe.search_next_selector or recipe.popular_next_selector
            recipe.details_synopsis_selector = recipe.details_synopsis_selector or "div.mov-desc span[itemprop=description]"
            recipe.details_genre_selector = recipe.details_genre_selector or "div.mov-desc span[itemprop=genre] a"
            recipe.episode_list_selector = "div.eps"
            recipe.runtime = {"episodes": {"kind": "text_pairs", "selector": "div.eps", "separator": "!"}}
            recipe.filter_tags = dict(recipe.filter_tags)
            recipe.tag_request_path = "/genre/{tag}/page/{page}/"
            recipe.custom_feeds = [
                {"id": "vf", "label": "Animes VF", "path": "/animes-vf/page/1/", "selector": recipe.popular_selector},
                {"id": "vostfr", "label": "Animes VOSTFR", "path": "/animes-vostfr/page/1/", "selector": recipe.popular_selector},
                {"id": "films", "label": "Films", "path": "/films-vf-vostfr/page/1/", "selector": recipe.popular_selector},
            ]

        elif "franime" in pkg_lower or "franime" in base_lower:
            recipe.multi_tags = True
            recipe.popular_request_path = "/api/animes/?order=note"
            recipe.popular_selector = "api:franime"
            recipe.latest_request_path = "/api/animes/?order=latest"
            recipe.latest_selector = "api:franime"
            recipe.search_request_path = "/api/animes/?q={query}"
            recipe.search_selector = "api:franime"
            recipe.episode_list_selector = "api:franime"
            recipe.filter_tags = {
                g: g
                for g in [
                    "Action", "Aventure", "Comédie", "Drame", "Ecchi", "Fantaisie",
                    "Horreur", "Isekai", "Magie", "Mecha", "Militaire", "Musique",
                    "Mystère", "Psychologique", "Romance", "School Life", "Sci-Fi",
                    "Seinen", "Shôjo", "Shônen", "Slice of Life", "Sports",
                    "Surnaturel", "Thriller",
                ]
            }
            recipe.filter_orders = {
                "Mieux notés": "note",
                "Récents": "latest",
                "Titre A → Z": "title",
                "Titre Z → A": "title_desc",
            }
            if not recipe.filter_groups:
                recipe.filter_groups = [
                    {
                        "key": "lang",
                        "label": "Langue",
                        "param": "lang",
                        "multi": False,
                        "options": [
                            {"label": "VOSTFR", "value": "VOSTFR"},
                            {"label": "VF", "value": "VF"},
                        ],
                    },
                    {
                        "key": "format",
                        "label": "Format",
                        "param": "format",
                        "multi": False,
                        "options": [
                            {"label": "Série TV", "value": "TV"},
                            {"label": "Film", "value": "FILM"},
                            {"label": "OVA", "value": "OVA"},
                        ],
                    },
                    {
                        "key": "status",
                        "label": "Statut",
                        "param": "status",
                        "multi": False,
                        "options": [
                            {"label": "En cours", "value": "EN COURS"},
                            {"label": "Terminé", "value": "TERMINÉ"},
                        ],
                    },
                ]
            if not recipe.custom_feeds:
                recipe.custom_feeds = [
                    {"id": "top_rated", "label": "Mieux notés", "path": "/api/animes/?order=note", "selector": "api:franime"},
                    {"id": "vf", "label": "Catalogue VF", "path": "/api/animes/?lang=VF", "selector": "api:franime"},
                ]

        elif "aniworld" in pkg_lower or "aniworld" in base_lower:
            recipe.popular_request_path = "/beliebte-animes"
            recipe.popular_selector = "div.seriesListContainer div"
            recipe.latest_request_path = "/neu"
            recipe.latest_selector = "div.seriesListContainer div"
            recipe.search_request_path = "/ajax/seriesSearch?keyword={query}"
            recipe.search_selector = "div.seriesListContainer div"
            recipe.item_link_selector = "a[href]"
            recipe.item_title_selector = "h3"
            recipe.item_thumb_selector = "img[data-src], img[src]"
            recipe.episode_list_selector = "table.seasonEpisodesList tbody tr"
            recipe.filter_tags = {
                g: g.lower()
                for g in [
                    "Action", "Abenteuer", "Komödie", "Drama", "Fantasy", "Romantik",
                    "Sci-Fi", "Mystery", "Horror", "Psychodrama", "Sport", "Alltagsleben", "Ecchi", "Isekai",
                ]
            }
            if not recipe.custom_feeds:
                recipe.custom_feeds = [
                    {"id": "beliebte", "label": "Beliebte Animes", "path": "/beliebte-animes", "selector": "div.seriesListContainer div"},
                    {"id": "neu", "label": "Neue Animes", "path": "/neu", "selector": "div.seriesListContainer div"},
                ]

        elif identity == "hanime":
            recipe.multi_tags = True
            recipe.popular_request_path = "/search?order_by=likes"
            recipe.popular_selector = "api:hanime"
            recipe.latest_request_path = "/search?order_by=created_at_unix"
            recipe.latest_selector = "api:hanime"
            recipe.search_request_path = "/search?q={query}"
            recipe.search_selector = "api:hanime"
            recipe.episode_list_selector = "api:hanime"
            recipe.filter_tags = {
                t.title(): t.lower()
                for t in [
                    "3d", "ahegao", "anal", "bdsm", "big boobs", "blow job", "bondage", "boob job",
                    "censored", "comedy", "cosplay", "creampie", "dark skin", "demon", "elf", "facial",
                    "fantasy", "femdom", "foot job", "futanari", "gangbang", "glasses", "hand job",
                    "harem", "hd", "horror", "incest", "inflation", "lactation", "loli", "maid",
                    "masturbation", "milf", "mind break", "mind control", "monster", "nekomimi",
                    "ntr", "nurse", "orgy", "plot", "pov", "pregnant", "public sex", "rape",
                    "reverse rape", "rimjob", "romance", "school girl", "shota", "softcore",
                    "swimsuit", "teacher", "tentacle", "threesome", "toys", "trap", "tsundere",
                    "ugly bastard", "uncensored", "vanilla", "virgin", "watersports", "x-ray", "yuri",
                ]
            }
            recipe.filter_orders = {
                "Récents": "created_at_unix",
                "Plus vus": "views",
                "Plus aimés": "likes",
                "Date de sortie": "released_at_unix",
                "Titre A → Z": "title_sortable",
            }
            if not recipe.custom_feeds:
                recipe.custom_feeds = [
                    {"id": "likes", "label": "Plus aimés", "path": "/search?order_by=likes", "selector": "api:hanime"},
                    {"id": "views", "label": "Plus vus", "path": "/search?order_by=views", "selector": "api:hanime"},
                ]

        elif "hentaihaven" in pkg_lower or "hentaihaven" in base_lower:
            recipe.multisrc_theme = "madara"
            cards_sel = "div.page-item-detail.video, div.page-item-detail, div.c-tabs-item__content, div.c-tabs-item"
            recipe.popular_request_path = "/page/1/?m_orderby=views"
            recipe.popular_selector = cards_sel
            recipe.popular_next_selector = "a.nextpostslink, div.wp-pagenavi a.next"
            recipe.latest_request_path = "/page/1/?m_orderby=latest"
            recipe.latest_selector = cards_sel
            recipe.latest_next_selector = "a.nextpostslink, div.wp-pagenavi a.next"
            recipe.search_request_path = "/page/1/?s={query}&post_type=wp-manga"
            recipe.search_selector = cards_sel
            recipe.tag_request_path = "/series/{tag}/page/{page}/"
            recipe.order_param = "m_orderby"
            recipe.item_link_selector = ".post-title a[href], .item-thumb a[href], a[href]"
            recipe.item_title_selector = ".post-title a, h3 a, .h5 a"
            recipe.item_thumb_selector = ".item-thumb img, img[data-src], img[src]"
            recipe.episode_list_selector = "li.wp-manga-chapter a"
            recipe.filter_orders = {
                "Récents": "latest",
                "Nouveautés": "new-manga",
                "Plus vus": "views",
                "Note": "rating",
                "A-Z": "alphabet",
            }
            recipe.filter_tags = {
                label: slug
                for label, slug in [
                    ("Uncensored", "uncensored"), ("Romance", "romance"), ("Fantasy", "fantasy"),
                    ("Comedy", "comedy"), ("Action", "action"), ("School", "school"),
                    ("Harem", "harem"), ("Big Boobs", "big-boobs"), ("Vanilla", "vanilla"),
                    ("Milf", "milf"), ("NTR", "ntr"), ("Yuri", "yuri"), ("3D", "3d"),
                ]
            }
            if not recipe.custom_feeds:
                recipe.custom_feeds = [
                    {"id": "views", "label": "Plus vus", "path": "/page/1/?m_orderby=views", "selector": cards_sel},
                    {"id": "rating", "label": "Mieux notés", "path": "/page/1/?m_orderby=rating", "selector": cards_sel},
                ]

        compile_operations(recipe)

        dex_direct_api = bool(recipe.runtime.pop("_dex_direct_api", False))
        has_runtime_handler = any(
            k in recipe.runtime for k in ("catalogue", "search", "listing_expansion", "episodes", "players")
        )
        has_selectors = any(
            bool(getattr(recipe, f))
            for f in ("popular_selector", "latest_selector", "search_selector", "episode_list_selector")
        )
        if dex_direct_api and not recipe.multisrc_theme and not has_runtime_handler and not has_selectors:
            recipe.runtime["api_only_apk"] = True
            return

        # Détection générique depuis raw_strings si encore incomplet
        if not recipe.search_selector or not recipe.popular_selector:
            container_candidates = []
            for s in recipe.raw_strings:
                s_clean = s.strip()
                if not s_clean or len(s_clean) < 3 or len(s_clean) > 80:
                    continue
                if s_clean.startswith(('http', '//', '(', 'L', '[L', '#EXT', '"', '%.', 'data:', 'android.')):
                    continue
                if re.search(r'[\(\)\{\}\*\+\?\$\\\^]', s_clean):
                    continue
                if any(k in s_clean for k in ['#list_catalog', 'containerAjouts', 'catalog-card', 'ml-item', 'film_list', 'archive-content', 'c-tabs-item', 'result-item', 'movie-poster']):
                    container_candidates.append(s_clean)
                elif s_clean.startswith(('#', '.', 'div', 'article')) and any(c in s_clean for c in ['#', '.', '>', ' ']):
                    if any(w in s_clean for w in ['poster', 'card', 'item', 'content', 'article', 'thumb', 'entry']):
                        container_candidates.append(s_clean)

            if container_candidates:
                chosen_selector = ", ".join(dict.fromkeys(container_candidates))
                if not recipe.search_selector:
                    recipe.search_selector = chosen_selector
                if not recipe.popular_selector:
                    recipe.popular_selector = chosen_selector

        if not recipe.search_selector and recipe.popular_selector:
            recipe.search_selector = recipe.popular_selector
        if not recipe.latest_selector and recipe.popular_selector:
            recipe.latest_selector = recipe.popular_selector

        # Format de recherche
        if not recipe.search_request_path:
            if "search" in recipe.raw_strings and "/catalogue/" in recipe.raw_strings:
                recipe.search_request_path = "/catalogue/?search={query}"
                recipe.search_query_param = "search"
            elif recipe.search_query_param:
                recipe.search_request_path = f"/?{recipe.search_query_param}={{query}}"
            else:
                recipe.search_request_path = "/?s={query}"

        # Éléments enfants par défaut
        if not recipe.item_title_selector:
            recipe.item_title_selector = "h3, h2, .title, .post-title, a.title, .entry-title, .card-title, img[alt]"
        if not recipe.item_link_selector:
            recipe.item_link_selector = "a[href]"
        if not recipe.item_thumb_selector:
            recipe.item_thumb_selector = "img[src], img[data-src], img[loading], .poster img"
        if not recipe.episode_link_selector:
            recipe.episode_link_selector = "a[href], option"
        if not recipe.episode_name_selector:
            recipe.episode_name_selector = "a, span, option"
