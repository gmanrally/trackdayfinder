// Minimal service worker: qualifies the site for install and keeps the
// static shell cached. Pages always go to the network — event data is live
// and must never be served stale.
const CACHE = 'tdf-static-v1';
const PRECACHE = ['/static/logo-light.svg', '/static/favicon-192.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // Cache-first for our own static assets only; everything else untouched.
  if (url.origin === location.origin && url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.match(e.request).then((hit) =>
        hit || fetch(e.request).then((r) => {
          const copy = r.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
          return r;
        })
      )
    );
  }
});
