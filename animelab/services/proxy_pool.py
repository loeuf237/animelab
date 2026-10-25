"""Public proxy catalogue and bounded HTTPS checks, independent of source sessions."""
import asyncio
import ipaddress
import json
import random
import threading
import time
from urllib.parse import urlsplit, urlunsplit

import httpx
from curl_cffi.requests import Session

from animelab.services.proxy_service import proxy_service

PROVIDERS = (
    {"id": "proxyscrape", "name": "ProxyScrape", "website": "https://github.com/proxyscrape/free-proxy-list",
     "url": "https://raw.githubusercontent.com/proxyscrape/free-proxy-list/main/proxies/protocols/https/data.json"},
    {"id": "proxifly", "name": "Proxifly", "website": "https://github.com/proxifly/free-proxy-list",
     "url": "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/https/data.json"},
    {"id": "geonode", "name": "Geonode", "website": "https://geonode.com/free-proxy-list",
     "url": "https://proxylist.geonode.com/api/proxy-list?limit=100&page=1&sort_by=lastChecked&sort_type=desc&protocols=http"},
)
MAX_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 3000
HEALTH_TTL = 30 * 60


def normalize_proxy(value, *, credentials=False):
    """Lists accept public IPs only. Named/local proxies belong in manual settings."""
    if isinstance(value, dict):
        url = value.get("proxy") or value.get("url")
        if not url:
            protocol = value.get("protocol") or value.get("protocols", ["http"])[0]
            # Provider 'https' flags describe CONNECT support, not TLS to the proxy.
            protocol = "http" if protocol == "https" else protocol
            ip = str(value.get("ip") or value.get("host") or "")
            host = f"[{ip}]" if ":" in ip else ip
            url = f"{protocol}://{host}:{value.get('port', '')}"
    else:
        url = value
    if not isinstance(url, str) or len(url) > 512 or any(c.isspace() for c in url):
        raise ValueError("Adresse de proxy invalide")
    parts = urlsplit(url if "://" in url else "http://" + url)
    if parts.scheme not in ("http", "https", "socks4", "socks4a", "socks5", "socks5h"):
        raise ValueError("Protocole de proxy invalide")
    address = ipaddress.ip_address(parts.hostname or "")
    if not address.is_global or address.is_multicast or address.is_unspecified:
        raise ValueError("Les listes de proxys acceptent uniquement des adresses IP publiques")
    if not parts.port or not 1 <= parts.port <= 65535 or parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("Port ou URL de proxy invalide")
    if not credentials and (parts.username or parts.password):
        raise ValueError("Identifiants interdits dans une liste publique")
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def parse_list(payload, *, credentials=False, strict=False):
    if isinstance(payload, dict):
        payload = payload.get("proxies", payload.get("data"))
    if isinstance(payload, str):
        payload = payload.splitlines()
    if not isinstance(payload, list) or len(payload) > 50000:
        raise ValueError("Format attendu : tableau JSON ou objet contenant proxies/data")
    if strict and len(payload) > 1000:
        raise ValueError("Limite de 1 000 proxys par import")
    result, rejected = {}, 0
    for item in payload:
        try:
            url = normalize_proxy(item, credentials=credentials)
            result[url] = {"url": url, "country": str(item.get("country_code") or item.get("country") or "")[:40] if isinstance(item, dict) else ""}
        except (ValueError, TypeError, KeyError, IndexError):
            rejected += 1
        if len(result) >= MAX_ENTRIES:
            break
    if strict and (rejected or not result):
        raise ValueError(f"Import refusé : {rejected} adresse(s) invalide(s). Utilisez des IP publiques avec un port ; les proxys locaux se configurent dans Manuel.")
    return list(result.values()), rejected


class ProxyPool:
    def __init__(self, config=proxy_service):
        self.config = config
        self.lock = threading.RLock()
        self.entries = {}
        self.provider_status = {}
        self.options = {"automatic": False}
        self.last_refresh = None
        self.refreshing = False
        self._refresh_task = None
        self._checking = False
        self.last_check = 0
        self._domain_attempts = {}
        with config._get_conn() as conn:
            row = conn.execute("SELECT payload FROM public_proxy_pool WHERE id=1").fetchone()
        if row:
            try:
                data = json.loads(row[0])
                self.options.update({"automatic": bool(data.get("automatic", False))})
                self.last_refresh = data.get("lastRefresh")
                self.provider_status = data.get("providers", {})
                for entry in data.get("entries", [])[:MAX_ENTRIES]:
                    normalize_proxy(entry["url"], credentials=entry.get("provider") == "import")
                    self.entries[entry["url"]] = entry
            except (ValueError, KeyError, TypeError):
                self.entries = {}

    def _save(self):
        # Caller holds the lock; credentials stay in SQLite and are masked in API output.
        payload = json.dumps({**self.options, "lastRefresh": self.last_refresh,
                              "providers": self.provider_status, "entries": list(self.entries.values())})
        with self.config._get_conn() as conn:
            conn.execute("INSERT INTO public_proxy_pool VALUES(1, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (payload,))

    def snapshot(self):
        with self.lock:
            now = time.time()
            rows = sorted(self.entries.values(), key=lambda e: (not self.healthy(e, now), e.get("latencyMs") or 99999, e["url"]))
            return {**self.options, "refreshing": self.refreshing, "checking": self._checking,
                    "lastRefresh": self.last_refresh, "total": len(rows),
                    "importedCount": sum(e.get("provider") == "import" for e in rows),
                    "healthy": sum(self.healthy(e, now) for e in rows),
                    "healthyExits": len({e.get("exitIp") or urlsplit(e["url"]).hostname for e in rows if self.healthy(e, now)}),
                    "providers": [{"id": p["id"], "name": p["name"], "website": p["website"], **self.provider_status.get(p["id"], {})} for p in PROVIDERS],
                    "entries": [{**e, "url": self.config.mask_url(e["url"]), "usable": self.healthy(e, now)} for e in rows[:100]]}

    @staticmethod
    def healthy(entry, now=None):
        now = now or time.time()
        return entry.get("status") == "ok" and now - entry.get("checkedAt", 0) < HEALTH_TTL

    def set_options(self, data):
        if not isinstance(data.get("automatic"), bool):
            raise ValueError("Le réglage de rotation doit être un booléen")
        with self.lock:
            self.options["automatic"] = data["automatic"]
            self._save()
        return self.snapshot()

    def import_json(self, payload):
        rows, _ = parse_list(payload, credentials=True, strict=True)
        with self.lock:
            if len(set(self.entries) | {e["url"] for e in rows}) > MAX_ENTRIES:
                raise ValueError("Catalogue plein ; retirez la liste importée avant cet import")
            for entry in rows:
                old = self.entries.get(entry["url"], {})
                self.entries[entry["url"]] = {**entry, "provider": "import", "status": old.get("status", "untested"),
                                              "checkedAt": old.get("checkedAt", 0), "latencyMs": old.get("latencyMs"), "exitIp": old.get("exitIp")}
            self._save()
        return {"imported": len(rows), "pool": self.snapshot()}

    def clear_imported(self):
        with self.lock:
            self.entries = {u: e for u, e in self.entries.items() if e.get("provider") != "import"}
            self._save()
        return self.snapshot()

    async def _fetch_provider(self, provider):
        # Fixed HTTPS endpoints, no source cookies/proxies and no redirect to unknown hosts.
        async with asyncio.timeout(20):
            async with httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False) as client:
                async with client.stream("GET", provider["url"]) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise ValueError("Liste trop volumineuse")
        return parse_list(json.loads(body))

    async def refresh(self):
        if self._refresh_task and not self._refresh_task.done():
            return await asyncio.shield(self._refresh_task)
        self._refresh_task = asyncio.create_task(self._refresh())
        return await asyncio.shield(self._refresh_task)

    async def _refresh(self):
        self.refreshing = True
        try:
            results = await asyncio.gather(*(self._fetch_provider(p) for p in PROVIDERS), return_exceptions=True)
            with self.lock:
                for provider, result in zip(PROVIDERS, results):
                    key = provider["id"]
                    if isinstance(result, BaseException):
                        self.provider_status[key] = {"status": "error", "error": "Liste indisponible ; copie précédente conservée", "count": sum(e.get("provider") == key for e in self.entries.values())}
                        continue
                    rows, rejected = result
                    if not rows:
                        self.provider_status[key] = {"status": "error", "error": "Liste vide ou invalide ; copie précédente conservée"}
                        continue
                    previous = self.entries
                    kept = {u: e for u, e in previous.items() if e.get("provider") != key}
                    # Keep imports and other providers; take a representative, bounded sample.
                    random.shuffle(rows)
                    for entry in rows[:750]:
                        u = entry["url"]
                        if u in kept or len(kept) >= MAX_ENTRIES:
                            continue
                        kept[u] = {**entry, "provider": key, **{k: v for k, v in previous.get(u, {}).items() if k in ("status", "checkedAt", "latencyMs", "exitIp")}}
                    self.entries = kept
                    self.provider_status[key] = {"status": "ok", "count": len(rows), "rejected": rejected, "updatedAt": time.time()}
                self.last_refresh = time.time()
                self._save()
            await self.check(24)
            return self.snapshot()
        finally:
            self.refreshing = False

    @staticmethod
    def probe(url):
        start = time.monotonic()
        try:
            # Strict TLS, fixed public endpoint, no cookies or authentication from sources.
            with Session(proxy=url, trust_env=False, verify=True, impersonate="chrome") as client:
                response = client.get("https://api.ipify.org?format=json", timeout=6, allow_redirects=False)
                response.raise_for_status()
                ip = ipaddress.ip_address(response.json()["ip"])
                if not ip.is_global:
                    raise ValueError("Réponse de test invalide")
            return {"status": "ok", "checkedAt": time.time(), "latencyMs": round((time.monotonic() - start) * 1000), "exitIp": str(ip)}
        except Exception:
            return {"status": "failed", "checkedAt": time.time(), "latencyMs": None}

    async def check(self, limit=24):
        if self._checking:
            return self.snapshot()
        self._checking = True
        self.last_check = time.monotonic()
        try:
            with self.lock:
                # Spread tests among providers; retry expired successes before old failures.
                now = time.time()
                rows = list(self.entries.values())
                random.shuffle(rows)
                def priority(entry):
                    if entry.get("status") == "ok":
                        return (3 if self.healthy(entry, now) else 0, entry.get("checkedAt", 0))
                    return (2 if entry.get("status") == "failed" else 1, entry.get("checkedAt", 0))
                rows.sort(key=priority)
                groups = {}
                for entry in rows:
                    groups.setdefault(entry["provider"], []).append(entry["url"])
                selected = []
                while groups and len(selected) < min(limit, 48):
                    for key in list(groups):
                        selected.append(groups[key].pop(0))
                        if not groups[key]: del groups[key]
                        if len(selected) >= min(limit, 48): break
            semaphore = asyncio.Semaphore(6)
            async def test(url):
                async with semaphore:
                    result = await asyncio.to_thread(self.probe, url)
                    with self.lock:
                        if url in self.entries:
                            self.entries[url].update(result)
            await asyncio.gather(*(test(u) for u in selected))
            with self.lock: self._save()
            return self.snapshot()
        finally:
            self._checking = False

    async def watch(self):
        """Opt-in rotation needs fresh candidates during long application sessions."""
        while True:
            await asyncio.sleep(30)
            if self.options["automatic"] and not self.refreshing and not self._checking:
                if (not self.last_check or time.monotonic() - self.last_check >= 300) and self.snapshot()["healthyExits"] < 3:
                    await self.check()

    def choose(self, domain, current, *, automatic=False):
        with self.lock:
            if automatic and not self.options["automatic"]:
                return None
            now = time.time()
            attempts = self._domain_attempts.get(domain, [])
            attempts = [(t, u) for t, u in attempts if now - t < 300]
            # At most two automatic changes per domain in five minutes. Manual choice remains available.
            if automatic and len(attempts) >= 2:
                return None
            tried = {u for _, u in attempts} | {current}
            hosts = {urlsplit(u).hostname for u in tried if u}
            exit_ips = {self.entries[u].get("exitIp") for u in tried if u in self.entries} - {None}
            usable = sorted((e for e in self.entries.values() if e["url"] not in tried and self.healthy(e, now)
                             and urlsplit(e["url"]).hostname not in hosts and e.get("exitIp") not in exit_ips),
                            key=lambda e: e.get("latencyMs") or 99999)
            if not usable:
                return None
            url = usable[0]["url"]
            self._domain_attempts[domain] = attempts + [(now, url)]
            return url

    async def close(self):
        task, self._refresh_task = self._refresh_task, None
        if task and not task.done():
            owner = task.get_loop()
            if owner.is_closed():
                self.refreshing = False
                return
            if owner is asyncio.get_running_loop():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            else:
                owner.call_soon_threadsafe(task.cancel)


proxy_pool = ProxyPool()
