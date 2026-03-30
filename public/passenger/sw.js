// Damascus Transit — Passenger PWA Service Worker v1.1.0
const CACHE_NAME = 'passenger-v1.1.0';

const PRECACHE_URLS = [
  '/passenger/',
  '/passenger/index.html',
  '/passenger/manifest.json',
  'https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.js',
  'https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.css',
];

// ─── Install ───
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache =>
      cache.addAll(PRECACHE_URLS).catch(err =>
        console.warn('[SW] Precache partial:', err)
      )
    )
  );
  self.skipWaiting();
});

// ─── Activate: clean old caches ───
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// ─── Fetch strategy ───
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // API: network-only with offline fallback
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request).catch(() =>
        new Response(
          JSON.stringify({ detail: 'Offline — data may be stale' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }
        )
      )
    );
    return;
  }

  // Map tiles: stale-while-revalidate
  if (url.hostname.includes('carto') || url.hostname.includes('tile')) {
    event.respondWith(
      caches.open(CACHE_NAME).then(cache =>
        cache.match(event.request).then(cached => {
          const networkFetch = fetch(event.request).then(res => {
            if (res.ok) cache.put(event.request, res.clone());
            return res;
          }).catch(() => cached);
          return cached || networkFetch;
        })
      )
    );
    return;
  }

  // Assets: cache-first
  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;
      return fetch(event.request).then(response => {
        if (response.ok && event.request.method === 'GET') {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      });
    })
  );
});
