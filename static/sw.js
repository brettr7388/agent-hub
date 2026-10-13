const SHELL_CACHE = 'agent-hub-shell-v35';
const SHELL = ['/', '/index.html', '/static/style.css', '/static/onboarding.css', '/static/markdown.js', '/static/emoji.js', '/static/onboarding.js', '/static/app.js', '/static/phone.js', '/static/qr.js', '/manifest.json', '/static/logo.svg', '/static/favicon.svg', '/static/mascot.svg', '/static/pips.js', '/static/inter-latin.woff2', '/static/inter-latin-ext.woff2'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then(async (cache) => {
    await Promise.all(SHELL.map(async (path) => {
      try {
        const response = await fetch(path, { cache: 'reload' });
        if (response.ok && response.type === 'basic' && (response.headers.get('content-type') || '').includes((path.endsWith('.png') || path.endsWith('.svg')) ? 'image/' : path.endsWith('.js') ? 'javascript' : path.endsWith('.css') ? 'text/css' : path.endsWith('.json') ? 'json' : 'html')) await cache.put(path, response);
      } catch { /* shell remains available only for assets that loaded */ }
    }));
    await self.skipWaiting();
  }));
});
self.addEventListener('activate', (event) => {
  event.waitUntil(Promise.all([
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== SHELL_CACHE).map((key) => caches.delete(key)))),
    self.clients.claim()
  ]));
});
self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.search || !SHELL.includes(url.pathname)) return;
  event.respondWith(fetch(request).then((response) => {
    if (response.ok && response.type === 'basic') {
      const copy = response.clone();
      event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy)));
    }
    return response;
  }).catch(async () => (await caches.match(request)) || Response.error()));
});
