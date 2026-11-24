"""Typed source boundary shared by search, details, feeds, catalogue and tracking."""
from dataclasses import dataclass
import time
import asyncio
from pathlib import Path
from animelab.diagnostics import telemetry,domain
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

from animelab.api_errors import APIProblem
from animelab.models.anime import AnimeResult, AnimeDetail
from animelab.services.aniyomi_dex_parser import SourceRecipe


def source_identity(service, fallback):
    value=getattr(service,'source_id',None)
    return value if isinstance(value,str) and value else fallback


@runtime_checkable
class SourceProvider(Protocol):
    base_url: str
    async def search_anime(self, query: str) -> list[AnimeResult]: ...
    async def get_anime_detail(self, url: str) -> AnimeDetail | None: ...
    async def get_latest_releases(self) -> list[AnimeResult]: ...


@dataclass(frozen=True)
class SourceCapabilities:
    search: bool
    detail: bool
    latest: bool
    popular: bool = False
    catalogue: bool = False
    featured: bool = False
    multi_tags: bool = False

    def views(self) -> list[dict[str, str]]:
        labels = {'latest': 'Dernières sorties', 'popular': 'Populaires',
                  'featured': 'Coups de cœur', 'catalogue': 'Catalogue', 'search': 'Recherche'}
        return [{'id': mode, 'label': label} for mode, label in labels.items() if getattr(self, mode)]


@dataclass(frozen=True)
class RegisteredSource:
    id: str
    name: str
    language: str
    imported: bool
    service: SourceProvider
    capabilities: SourceCapabilities

    @property
    def base_url(self) -> str:
        return self.service.base_url

    def require(self, operation: str) -> None:
        if not getattr(self.capabilities, operation, False):
            raise APIProblem('source_operation_unsupported', status=400, category='validation')

    async def search_anime(self, query: str) -> list[AnimeResult]:
        self.require('search')
        return self._identify(await self.observe("search",self.service.search_anime(query)))

    async def get_latest_releases(self) -> list[AnimeResult]:
        self.require('latest')
        return self._identify(await self.observe("latest",self.service.get_latest_releases()))

    async def get_popular_anime(self, page: int = 1) -> list[AnimeResult]:
        self.require('popular')
        fn = getattr(self.service, 'get_popular_anime', None)
        if fn is None:
            raise APIProblem('source_operation_unsupported', status=400, category='validation')
        return self._identify(await self.observe("popular", fn(page=page)))

    async def get_anime_detail(self, url: str) -> AnimeDetail | None:
        self.require('detail')
        detail = await self.observe("detail",self.service.get_anime_detail(url))
        if detail is not None:
            detail = detail.model_copy(deep=True, update={'source': self.id})
        return detail

    async def observe(self,operation,work):
        from animelab.services.extension_observability import extension_observability
        started=time.monotonic()
        revision=getattr(self.service,'_diagnostics_recipe_revision',None)
        error=None;count=0
        try:
            result=await work
            count=(len(result.episodes) if isinstance(result,AnimeDetail) else len(result['results'])
                   if isinstance(result,dict) and isinstance(result.get('results'),list) else len(result) if result is not None else 0)
            return result
        except BaseException as exc:
            error=exc
            raise
        finally:
            duration=(time.monotonic()-started)*1000
            telemetry.event('source_request',source=self.id,domain=domain(self.base_url),operation=operation,
                            durationMs=duration,status='failed' if error else 'completed',count=count)
            if self.imported and not isinstance(error, asyncio.CancelledError):
                try:
                    path=getattr(self.service,'_diagnostics_db_path',None)
                    extension_observability.record(self.id,operation,count=count,error=error,duration_ms=duration,
                        db_path=path if isinstance(path,(str,Path)) else None,base_url=self.base_url,
                        recipe_revision=revision if isinstance(revision,int) else None)
                except Exception:
                    # A diagnostic failure must not replace the source result.
                    telemetry.event('extension_health_unavailable',source=self.id,operation=operation)

    def _identify(self, items: list[AnimeResult]) -> list[AnimeResult]:
        # Do not modify provider cache entries when annotating a response.
        return [item.model_copy(update={'source': self.id}) for item in items or []]

    def descriptor(self) -> dict:
        views = list(self.capabilities.views())
        recipe = getattr(self.service, 'recipe', None)
        if isinstance(recipe, SourceRecipe) and recipe.custom_feeds:
            existing_ids = {v['id'] for v in views}
            for feed in recipe.custom_feeds:
                fid = f"feed:{feed.get('id')}"
                if feed.get('id') and feed.get('label') and fid not in existing_ids:
                    views.append({'id': fid, 'label': feed['label']})
                    existing_ids.add(fid)
        return {'id': self.id, 'name': self.name, 'baseUrl': self.base_url,
                'lang': self.language, 'type': 'imported' if self.imported else 'native',
                'runtime': getattr(self.service, 'runtime', '') or ('native' if not self.imported else 'recipe'),
                'isEnabled': True, 'views': views, 'multiTags': self.capabilities.multi_tags,
                'capabilities': {key: getattr(self.capabilities, key) for key in self.capabilities.__dataclass_fields__}}


class SourceRegistry:
    def __init__(self, natives=None, extensions=None, seanime=None):
        self._natives = natives
        self._extensions = extensions
        self._seanime = seanime

    def seanime(self):
        if self._seanime is not None:
            return self._seanime
        if self._extensions is not None:
            return None
        from animelab.services.seanime_service import seanime_service
        return seanime_service

    def natives(self) -> dict[str, SourceProvider]:
        if self._natives is not None:
            return self._natives
        from animelab.services.scraping_service import scraping_service
        from animelab.services.french_stream_service import french_stream_service
        from animelab.services.voiranime_service import voiranime_service
        from animelab.services.animepahe_service import animepahe_service
        return {
            'french-manga': scraping_service,
            'french-stream': french_stream_service,
            'voir-anime': voiranime_service,
            'animepahe': animepahe_service,
        }

    def extensions(self):
        if self._extensions is not None:
            return self._extensions
        from animelab.services.extension_service import extension_service
        return extension_service

    def describe(self, source_id: str, service: SourceProvider) -> RegisteredSource:
        native_names = {
            'french-manga': 'French-Manga',
            'french-stream': 'French-Stream',
            'voir-anime': 'VoirAnime',
            'animepahe': 'AnimePahe',
        }
        imported = source_id not in self.natives()
        recipe = getattr(service, 'recipe', None)
        if imported and getattr(service, 'runtime', '') == 'android-apk':
            capabilities = SourceCapabilities(search=True, detail=True, latest=service.supports_latest,
                                              popular=True, catalogue=True, multi_tags=True)
        elif imported and getattr(service, 'runtime', '') == 'seanime':
            capabilities = SourceCapabilities(search=True, detail=True, latest=False,
                                              popular=False, catalogue=False, multi_tags=False)
        elif imported and isinstance(recipe, SourceRecipe):
            api_catalogue = bool(recipe.runtime.get('catalogue'))
            popular = bool(
                (recipe.popular_request_path and recipe.popular_selector)
                or api_catalogue
            )
            has_filters = bool(recipe.filter_tags or recipe.filter_orders or recipe.filter_groups)
            capabilities = SourceCapabilities(
                search=bool(api_catalogue or recipe.runtime.get('search') or recipe.search_selector),
                detail=bool(api_catalogue or recipe.runtime.get('episodes') or recipe.episode_list_selector),
                latest=bool(recipe.supports_latest and (api_catalogue or recipe.latest_selector or recipe.popular_selector)),
                popular=popular,
                catalogue=bool(api_catalogue or popular or has_filters),
                featured=bool(recipe.custom_feeds),
                multi_tags=bool(api_catalogue or recipe.multi_tags),
            )
        else:
            capabilities = SourceCapabilities(search=True, detail=True, latest=True,
                popular=source_id in ('voir-anime', 'french-stream'), catalogue=not imported,
                featured=source_id in ('french-manga', 'french-stream'), multi_tags=source_id == 'voir-anime')
        return RegisteredSource(source_id, native_names.get(source_id) or service.name,
                                getattr(service, 'lang', 'en' if source_id == 'animepahe' else 'fr'),
                                imported, service, capabilities)

    def all(self) -> list[RegisteredSource]:
        providers = dict(self.natives())
        providers.update({source_identity(source,source.pkg): source for source in self.extensions().get_enabled_container_sources()})
        seanime_svc = self.seanime()
        if seanime_svc is not None:
            providers.update({source.source_id: source for source in seanime_svc.get_enabled_sources()})
        return [self.describe(sid, service) for sid, service in providers.items()]

    def get(self, source_id: str) -> RegisteredSource:
        source_id = source_id.strip().lower()
        service = self.natives().get(source_id)
        if service is None:
            service = self.extensions().get_container_source_by_id(source_id)
        if service is None:
            seanime_svc = self.seanime()
            if seanime_svc is not None:
                service = seanime_svc.get_source_by_id(source_id)
        if service is None:
            raise APIProblem('source_not_found', status=404, category='not_found')
        return self.describe(source_identity(service,source_id), service)

    def detect(self, url: str, fallback: str = 'french-manga') -> str:
        from animelab.services.french_stream_service import is_french_stream_host
        host = (urlparse(url).hostname or '').lower()
        if not host:
            return fallback
        aliases = {'animepahe': ('animepahe.com', 'animepahe.pw', 'animepahe.si', 'kwik.cx', 'kwik.si', 'pahe.win'),
                   'voir-anime': ('voiranime.cx', 'voir-anime.to', 'voiranime.to', 'voiranime.io', 'voiranime.homes'),
                   'french-manga': ('french-manga.net',),
                   'french-stream': ('fstream.net', 'fs016.lol', 'french-stream.net')}
        providers = self.all()
        preferred_id = fallback.strip().lower()
        if not any(provider.id == preferred_id for provider in providers):
            resolve_alias = getattr(self.extensions(), 'get_container_source_by_id', None)
            selected = resolve_alias(preferred_id) if resolve_alias is not None else None
            if selected is not None:
                preferred_id = source_identity(selected, preferred_id)
        # Several runtimes can serve the same site. Keep the selected source
        # when its origin matches, before considering automatic detection.
        providers.sort(key=lambda provider: provider.id != preferred_id)
        for provider in providers:
            domains = [urlparse(provider.base_url).hostname or ''] + list(aliases.get(provider.id, ()))
            if any(domain and (host == domain or host.endswith('.' + domain)) for domain in domains):
                return provider.id
            if provider.id == 'french-stream' and is_french_stream_host(host):
                return provider.id
        return fallback


source_registry = SourceRegistry()
