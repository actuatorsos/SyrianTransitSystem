// Damascus Transit — Driver PWA Service Worker v1.1.0
const CACHE_NAME = 'driver-v1.1.0';

// Core assets to cache for offline use
const PRECACHE_URLS = [
  '/driver/',
  '/driver/index.html',
  '/driver/manifest.json',
  // MapLibre GL JS (CDN — cached on first load)
  'https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.js',
  'https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.css',
];

// ─── Install: precache shell ───
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(PRECACHE_URLS).catch(err => {
        // CDN assets may fail on first offline install — that's OK
        console.warn('[SW] Precache partial:', err);
      });
    })
  );
  // Activate immediately without waiting for old SW to finish
  self.skipWaiting();
});

// ─── Activate: clean old caches ───
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      )
    )
  );
  // Take control of all open tabs immediately
  self.clients.claim();
});

// ─── Fetch: network-first for API, cache-first for assets ───
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // API calls: always go to network (positions are handled by the queue in-page)
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request).catch(() => {
        return new Response(
          JSON.stringify({ detail: 'Offline — request queued' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }
        );
      })
    );
    return;
  }

  // Map tiles: cache with network fallback (stale-while-revalidate)
  if (url.hostname.includes('carto') || url.hostname.includes('tile')) {
    event.respondWith(
      caches.open(CACHE_NAME).then(cache =>
        cache.match(event.request).then(cached => {
          const fetchPromise = fetch(event.request).then(response => {
            if (response.ok) cache.put(event.request, response.clone());
            return response;
          }).catch(() => cached);

          return cached || fetchPromise;
        })
      )
    );
    return;
  }

  // All other assets: cache-first, fallback to network
  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;

      return fetch(event.request).then(response => {
        // Cache successful GET responses
        if (response.ok && event.request.method === 'GET') {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      });
    })
  );
});
