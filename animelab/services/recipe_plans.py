"""Declarative compatibility plans compiled into recipes, never runtime adapters.

DEX string extraction cannot execute arbitrary Kotlin. These plans describe the
data operations our interpreter supports; unknown APIs remain unsupported.
"""
from urllib.parse import urlparse


def source_key(pkg, base_url=''):
    """A package identifier is authoritative; never match fragments of its name."""
    if pkg:
        return pkg.lower().rsplit('.', 1)[-1]
    host = (urlparse(base_url).hostname or '').lower().removeprefix('www.')
    return {
        'french-anime.com': 'frenchanime', 'franime.fr': 'franime',
        'hanime.tv': 'hanime', 'aniworld.to': 'aniworld',
        'anime-sama.to': 'animesama', 'anime-sama.fr': 'animesama',
        'anime-sama.me': 'animesama', 'v1.animesz.xyz': 'anisama',
    }.get(host, '')


def compile_operations(recipe):
    """Store all runtime decisions in the serializable recipe itself."""
    key = source_key(recipe.pkg, recipe.base_url)
    if recipe.runtime:
        return
    if key == 'franime':
        recipe.runtime = {
            'catalogue': {'url': '{api_base}/api/animes/', 'kind': 'series', 'ttl': 300,
                'aliases': {'originalTitle': ['titleO', 'originalTitle'], 'titlesAlt': ['titles', 'titlesAlt'],
                    'poster': ['affiche', 'poster'], 'genres': ['themes', 'genres'],
                    'seasons': ['saisons', 'seasons'], 'languages': ['lang', 'languages'],
                    'players': ['lecteurs', 'players']},
                'search_fields': ['title', 'originalTitle', 'titlesAlt'], 'slug_field': 'originalTitle', 'languages': {'vo': 'VOSTFR', 'vf': 'VF'},
                'entry_url': '{base}/anime/{slug}?lang={language}&s={season}',
                'popular_order': 'note', 'latest_order': 'latest'},
            'players': {'url': '{api_base}/api/anime/{id}/{season_index}/{episode_index}/{language}/{player_index}',
                        'response': 'url'},
        }
    elif key == 'hanime':
        recipe.runtime = {
            'catalogue': {'url': 'https://guest.freeanimehentai.net/api/v11/search_hvs',
                'root': 'data', 'allow_root_list': True, 'kind': 'flat', 'ttl': 3600,
                'aliases': {'title': ['name'], 'poster': ['poster_url', 'cover_url'], 'genres': ['tags']},
                'entry_url': '{base}/videos/hentai/{slug}', 'version': 'EN',
                'search_fields': ['title', 'name', 'slug', 'search_titles', 'genres'],
                'popular_order': 'likes', 'latest_order': 'created_at_unix'},
            'players': {'url': '{base}/api/v8/video?id={slug}', 'response': 'streams',
                'servers': 'videos_manifest.servers', 'streams': 'streams', 'quality': 'height'},
        }
    elif key == 'aniworld':
        recipe.runtime = {
            'search': {'response': 'json', 'title': 'name', 'link': 'link', 'image': 'cover',
                'relative_prefix': '/anime/stream/', 'version': 'DE', 'image_replace': ['150x225', '220x330']},
            'episodes': {'kind': 'pages', 'pages': '#stream > ul:first-child > li > a[href]',
                'selector': 'table.seasonEpisodesList tbody tr', 'link': 'td.seasonEpisodeTitle a[href]',
                'number': 'td meta[content]', 'number_attr': 'content', 'version': 'DE'},
            'players': {'response': 'redirects', 'selector': 'ul.row li[data-lang-key]',
                'link': 'a.watchEpisode[href]', 'name': 'h4', 'language_attr': 'data-lang-key',
                'languages': {'1': 'DE', '2': 'EN-SUB', '3': 'DE-SUB'}},
        }
        recipe.search_request_path = recipe.search_request_path or '/ajax/seriesSearch?keyword={query}'
        recipe.details_title_selector = recipe.details_title_selector or '.series-title h1 span, h1'
        recipe.details_thumb_selector = recipe.details_thumb_selector or '.seriesCoverBox img'
        recipe.details_synopsis_selector = recipe.details_synopsis_selector or 'p.seri_des'
    elif key == 'animesama':
        recipe.runtime = {'exclude_urls': ['/scan/'], 'episodes': {'kind': 'js_arrays',
            'array_pattern': r'(?:var|let|const)\s+(eps\w*)\s*=\s*\[([^\]]*)\]',
            'pages_pattern': r'panneauAnime\([^,]+,\s*["\x27]([^"\x27]+)["\x27]\)',
            'script_path': 'episodes.js'}}
        recipe.details_title_selector = recipe.details_title_selector or '#titreAnime, h1'
        recipe.details_thumb_selector = recipe.details_thumb_selector or '#coverAnime, .poster img'
        recipe.details_synopsis_selector = recipe.details_synopsis_selector or '#synopsis, .synopsis'
    elif key == 'anisama':
        recipe.runtime = {
            'episodes': {'kind': 'json_html', 'url': '/ajax/episode/list/{page_id}', 'root': 'html',
                'selector': '.ep-item', 'number_attr': 'data-number',
                'entry_url': '/ajax/episode/servers?episodeId={episode_id}'},
            'players': {'response': 'json_html', 'root': 'html', 'selector': '.server-item[data-id]',
                'url': '/ajax/episode/sources?id={server_id}&epid={episode_id}', 'link_field': 'link'},
        }
        recipe.details_title_selector = recipe.details_title_selector or '.anime-detail .dynamic-name, h1'
        recipe.details_thumb_selector = recipe.details_thumb_selector or '.film-poster-img'
        recipe.details_synopsis_selector = recipe.details_synopsis_selector or '.shorting'


def repair_legacy_recipe(recipe):
    """Discard only the demonstrably wrong Hanime profile on French Anime."""
    if source_key(recipe.pkg, recipe.base_url) != 'frenchanime':
        return False
    polluted = any(getattr(recipe, k).startswith('api:hanime') for k in (
        'popular_selector', 'latest_selector', 'search_selector', 'episode_list_selector'))
    if not polluted:
        return False
    from animelab.services.aniyomi_dex_parser import AniyomiDexParser, SourceRecipe
    clean = SourceRecipe(name=recipe.name, pkg=recipe.pkg, lang=recipe.lang,
                         base_url=recipe.base_url if source_key('', recipe.base_url) == 'frenchanime' else 'https://french-anime.com')
    AniyomiDexParser._fill_heuristics(clean)
    recipe.__dict__.update(clean.__dict__)
    return True
