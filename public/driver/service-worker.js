// Damascus Transit Driver PWA - Service Worker
// Provides offline support and Web Push notifications for driver app.

const CACHE_NAME = 'damascus-driver-v1';
const APP_SHELL = [
  '/driver/',
  '/driver/index.html',
  '/driver/manifest.json',
];

// ─── Install: pre-cache app shell ───
self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return Promise.allSettled(
        APP_SHELL.map(url => cache.add(url).catch(() => {}))
      );
    })
  );
});

// ─── Activate: clear old caches ───
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ─── Fetch: app shell only, API is always network ───
self.addEventListener('fetch', event => {
  const { request } = event;
  if (request.method !== 'GET') return;
  if (request.headers.get('Accept') === 'text/event-stream') return;
  if (request.url.includes('/api/')) return;

  event.respondWith(
    caches.match(request).then(cached => {
      if (cached) return cached;
      return fetch(request).then(response => {
        if (response.ok) {
          caches.open(CACHE_NAME).then(cache => cache.put(request, response.clone()));
        }
        return response;
      }).catch(async () => {
        const fallback = await caches.match('/driver/index.html') || await caches.match('/driver/');
        return fallback || new Response('Offline', { status: 503 });
      });
    })
  );
});

// ─── Web Push: receive notification ───
self.addEventListener('push', event => {
  let payload = { title: 'Damascus Transit', body: '', data: {} };
  if (event.data) {
    try { Object.assign(payload, JSON.parse(event.data.text())); } catch {}
  }
  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: '/driver/icons/icon-192.png',
      badge: '/driver/icons/badge-72.png',
      data: payload.data,
      dir: 'auto',
      lang: 'ar',
      requireInteraction: true,
    })
  );
});

// ─── Web Push: notification click ───
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/driver/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      for (const client of windowClients) {
        if (client.url.includes('/driver/') && 'focus' in client) {
          if (event.notification.data) {
            client.postMessage({ type: 'PUSH_DATA', data: event.notification.data });
          }
          return client.focus();
        }
      }
      return clients.openWindow(url);
    })
  );
});
