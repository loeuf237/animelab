// Vue SPA only. Changing the namespace also removes cached Jinja pages on upgrade.
const CACHE_NAME = "animelab-cache-v0.1.0-spa-only-1";
const PRECACHE_ASSETS = [
  "/offline.html",
  "/manifest.json",
  "/img/icon-192.png",
  "/img/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_ASSETS))
      .then(() => self.skipWaiting()),
  );
});
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  // Auth/API responses, SSE, HLS and media ranges always go to the server.
  if (
    request.method !== "GET" ||
    url.origin !== self.location.origin ||
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/auth/") ||
    request.headers.has("range") ||
    /\.(m3u8|ts|mp4|mkv|webm|key)$/i.test(url.pathname)
  )
    return;

  const branding =
    url.pathname === "/manifest.json" ||
    url.pathname === "/favicon.ico" ||
    /^\/(?:static\/)?img\//.test(url.pathname);
  if (branding) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE_NAME);
        try {
          const response = await fetch(request, { cache: "no-cache" });
          if (
            response.ok &&
            !response.headers.get("cache-control")?.includes("no-store")
          ) {
            await cache.put(request, response.clone());
          }
          return response;
        } catch {
          return (await cache.match(request)) || Response.error();
        }
      })(),
    );
    return;
  }
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(
        async () =>
          (await caches.match("/offline.html")) ||
          new Response("AnimeLab - Offline", { status: 503 }),
      ),
    );
    return;
  }
  // Vite-generated names contain a content fingerprint. Legacy unversioned JS
  // and HTML are never read from old caches or precached as a fallback.
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE_NAME);
        const cached = await cache.match(request);
        if (cached) return cached;
        const response = await fetch(request);
        if (
          response.ok &&
          !response.headers.get("cache-control")?.includes("no-store")
        ) {
          await cache.put(request, response.clone());
        }
        return response;
      })(),
    );
  }
});
