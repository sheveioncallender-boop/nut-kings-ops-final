'use strict';
const CACHE = 'nut-kings-ops-v1.4.2';
const WORKSPACE_PATHS = ['/nutkings/', '/nutkings/admin', '/nutkings/raw-materials/receiving', '/nutkings/raw-materials/issuing', '/nutkings/finished-goods/receiving', '/nutkings/finished-goods/issued'];
const SHELL = [
  '/nut_kings_ops/static/workspace/index.html?v=1.4.2',
  '/nut_kings_ops/static/workspace/app-v1.4.1.css',
  '/nut_kings_ops/static/workspace/app-v1.4.1.js?v=1.4.2',
  '/nut_kings_ops/static/img/nut_kings_logo.png',
  '/nut_kings_ops/static/description/icon-192.png',
  '/nut_kings_ops/static/description/icon-512.png',
  '/nutkings/manifest.webmanifest'
];
self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key.startsWith('nut-kings-ops-') && key !== CACHE).map((key) => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/nutkings/api/') || url.pathname.startsWith('/web/')) return;
  if (WORKSPACE_PATHS.includes(url.pathname)) {
    event.respondWith(fetch(request).then((response) => {
      if (response.ok && !response.redirected) caches.open(CACHE).then((cache) => cache.put(request, response.clone()));
      return response;
    }).catch(async () => (await caches.match(request)) || (await caches.match('/nut_kings_ops/static/workspace/index.html?v=1.4.2')) || new Response('Open this workspace while online before using it offline.', { status: 503, headers: { 'Content-Type': 'text/plain' } })));
    return;
  }
  if (url.pathname.startsWith('/nut_kings_ops/static/')) {
    event.respondWith(caches.match(request).then((cached) => cached || fetch(request).then((response) => {
      if (response.ok) caches.open(CACHE).then((cache) => cache.put(request, response.clone()));
      return response;
    }).catch(() => caches.match('/nutkings/'))));
  }
});
