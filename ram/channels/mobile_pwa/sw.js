// Squire PWA Service Worker — enables offline access and caching
const CACHE_NAME = 'squire-v1';
const OFFLINE_URLS = ['/pwa/', '/pwa/index.html', '/pwa/manifest.json'];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(OFFLINE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  // Network-first for API calls, cache-first for assets
  const url = new URL(event.request.url);
  if (url.pathname.startsWith('/chat') || url.pathname.startsWith('/voice')) {
    event.respondWith(fetch(event.request).catch(() =>
      new Response(JSON.stringify({ reply: "Squire is offline. Please reconnect." }),
                   { headers: { 'Content-Type': 'application/json' } })
    ));
  } else {
    event.respondWith(
      caches.match(event.request).then(cached =>
        cached || fetch(event.request).catch(() => caches.match('/pwa/'))
      )
    );
  }
});

// Push notifications
self.addEventListener('push', event => {
  const data = event.data ? event.data.json() : { title: 'Squire', body: 'You have a message.' };
  event.waitUntil(
    self.registration.showNotification(data.title || 'Squire', {
      body: data.body,
      icon: '/pwa/icon-192.png',
      badge: '/pwa/icon-192.png',
      data: data,
    })
  );
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(clients.openWindow('/pwa/'));
});
