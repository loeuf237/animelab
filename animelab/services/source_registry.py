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
                'isEnabled': True, 'views': views, 'multiTags': self.capabilities.multi_tags,
                'capabilities': {key: getattr(self.capabilities, key) for key in self.capabilities.__dataclass_fields__}}


class SourceRegistry:
    def __init__(self, natives=None, extensions=None):
        self._natives = natives
        self._extensions = extensions

    def natives(self) -> dict[str, SourceProvider]:
        if self._natives is not None:
            return self._natives
        from animelab.services.scraping_service import scraping_service
        from animelab.services.voiranime_service import voiranime_service
        from animelab.services.animepahe_service import animepahe_service
        return {'french-manga': scraping_service, 'voir-anime': voiranime_service, 'animepahe': animepahe_service}

    def extensions(self):
        if self._extensions is not None:
            return self._extensions
        from animelab.services.extension_service import extension_service
        return extension_service

    def describe(self, source_id: str, service: SourceProvider) -> RegisteredSource:
        native_names = {'french-manga': 'French-Manga', 'voir-anime': 'VoirAnime', 'animepahe': 'AnimePahe'}
        imported = source_id not in self.natives()
        recipe = getattr(service, 'recipe', None)
        if imported and getattr(service, 'runtime', '') == 'android-apk':
            capabilities = SourceCapabilities(search=True, detail=True, latest=service.supports_latest,
                                              popular=True, catalogue=True, multi_tags=True)
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
                popular=source_id == 'voir-anime', catalogue=not imported,
                featured=source_id == 'french-manga', multi_tags=source_id == 'voir-anime')
        return RegisteredSource(source_id, native_names.get(source_id) or service.name,
                                getattr(service, 'lang', 'en' if source_id == 'animepahe' else 'fr'),
                                imported, service, capabilities)

    def all(self) -> list[RegisteredSource]:
        providers = dict(self.natives())
        providers.update({getattr(source,'source_id',source.pkg): source for source in self.extensions().get_enabled_container_sources()})
        return [self.describe(sid, service) for sid, service in providers.items()]

    def get(self, source_id: str) -> RegisteredSource:
        source_id = source_id.strip().lower()
        service = self.natives().get(source_id)
        if service is None:
            service = self.extensions().get_container_source_by_id(source_id)
        if service is None:
            raise APIProblem('source_not_found', status=404, category='not_found')
        return self.describe(source_id, service)

    def detect(self, url: str, fallback: str = 'french-manga') -> str:
        host = (urlparse(url).hostname or '').lower()
        if not host:
            return fallback
        aliases = {'animepahe': ('animepahe.com', 'animepahe.pw', 'animepahe.si', 'kwik.cx', 'kwik.si', 'pahe.win'),
                   'voir-anime': ('voir-anime.to', 'voiranime.to', 'voiranime.io', 'voiranime.homes'),
                   'french-manga': ('french-manga.net',)}
        for provider in self.all():
            domains = [urlparse(provider.base_url).hostname or ''] + list(aliases.get(provider.id, ()))
            if any(domain and (host == domain or host.endswith('.' + domain)) for domain in domains):
                return provider.id
        return fallback


source_registry = SourceRegistry()
