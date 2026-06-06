// Minimal SW so the PWA is installable. No offline caching of API responses.
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => self.clients.claim());
self.addEventListener('fetch', () => {});
