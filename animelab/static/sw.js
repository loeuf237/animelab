// AnimeLab Service Worker - PWA Offline & Caching Engine
const CACHE_NAME = 'animelab-cache-v0.1.0-brand2';

const PRECACHE_ASSETS = [
  '/',
  '/offline.html',
  '/manifest.json',
  '/css/style.css?v=2.8',
  '/js/app.js?v=2.8',
  '/js/pwa.js',
  '/img/favicon.png',
  '/img/icon-192.png',
  '/img/icon-512.png',
  '/img/icon-maskable.png',
  '/img/logo.jpg'
];

// Installation: Pre-cache shell assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_ASSETS).catch((err) => {
        console.warn('[AnimeLab SW] Pre-caching partial error:', err);
      });
    }).then(() => self.skipWaiting())
  );
});

// Activation: Clean up previous caches and take control
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch Interception
self.addEventListener('fetch', (event) => {
  const request = event.request;

  // 1. Only handle GET requests
  if (request.method !== 'GET') {
    return;
  }

  const url = new URL(request.url);

  // 2. IMPORTANT: Never intercept or cache video streaming, SSE, or Range requests
  const isVideoOrStream = 
    url.pathname.startsWith('/api/media/stream') ||
    url.pathname.startsWith('/api/downloads/stream') ||
    url.pathname.includes('/stream') ||
    request.headers.get('accept')?.includes('text/event-stream') ||
    request.headers.has('range') ||
    /\.(m3u8|ts|mp4|mkv|webm|key)$/i.test(url.pathname);

  if (isVideoOrStream) {
    return; // Pass through directly to browser network
  }

  // Branding may be replaced at a stable URL on upgraded installations. Use
  // cached artwork only when offline, rather than showing the previous logo
  // for a whole page visit while background revalidation runs.
  const isBranding = url.pathname === '/manifest.json' || url.pathname === '/favicon.ico' ||
    /^\/(?:static\/)?img\/(?:icon-(?:192|512|maskable)|favicon|apple-touch-icon)\.png$/.test(url.pathname) ||
    /^\/(?:static\/)?img\/logo\.jpg$/.test(url.pathname);
  if (isBranding) {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE_NAME);
      try {
        const response = await fetch(request, { cache: 'no-cache' });
        if (response.ok) await cache.put(request, response.clone());
        return response;
      } catch {
        return (await cache.match(request)) || Response.error();
      }
    })());
    return;
  }

  // 3. Navigation requests (HTML pages)
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(async () => {
          const cachedResponse = await caches.match(request);
          if (cachedResponse) {
            return cachedResponse;
          }
          const offlinePage = await caches.match('/offline.html');
          if (offlinePage) {
            return offlinePage;
          }
          return new Response('AnimeLab - Hors ligne', {
            status: 503,
            statusText: 'Service Unavailable',
            headers: { 'Content-Type': 'text/plain; charset=utf-8' }
          });
        })
    );
    return;
  }

  // 4. API Endpoints: Network-first
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request).catch(() => {
        return caches.match(request);
      })
    );
    return;
  }

  // 5. Static Assets (CSS, JS, Images, Fonts): Cache-first with background revalidation
  if (
    url.pathname.startsWith('/css/') ||
    url.pathname.startsWith('/js/') ||
    url.pathname.startsWith('/img/') ||
    url.pathname.startsWith('/static/')
  ) {
    event.respondWith(
      caches.match(request).then((cachedResponse) => {
        const fetchPromise = fetch(request).then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const clone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return networkResponse;
        }).catch(() => null);

        return cachedResponse || fetchPromise;
      })
    );
    return;
  }

  // Default: Network with cache fallback
  event.respondWith(
    fetch(request).catch(() => caches.match(request))
  );
});
