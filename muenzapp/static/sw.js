// Offline ansehen: Seite, Dateien und GET-Daten werden beim Laden gemerkt.
// Ohne Internet zeigt die App den zuletzt geladenen Stand (nur ansehen).
const CACHE = 'muenzapp-v1';

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});

function shouldCache(url) {
  if (url.origin !== self.location.origin) return false;
  const p = url.pathname;
  if (p === '/login' || p === '/logout' || p.startsWith('/api/export')) return false;
  return true;
}

// Gemerkte Seite bekommt class="offline", damit der Offline-Hinweis erscheint
async function markOffline(res) {
  const text = (await res.text()).replace('<body>', '<body class="offline">');
  return new Response(text, { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname === '/logout') {
    e.waitUntil(caches.delete(CACHE));
    return;
  }
  if (req.method !== 'GET' || !shouldCache(url)) return;

  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const res = await fetch(req);
      // Weiterleitung (z.B. zum Anmelden) nicht merken
      if (res.ok && !res.redirected) cache.put(req, res.clone());
      return res;
    } catch (err) {
      const hit = (await cache.match(req)) || (await cache.match(req, { ignoreSearch: true }));
      if (req.mode === 'navigate') {
        const page = hit || (await cache.match('/', { ignoreSearch: true }));
        if (page) return markOffline(page);
        return new Response('<meta charset="utf-8"><p style="font-family:system-ui;padding:20px">Kein Internet, und die App wurde hier noch nie geladen.</p>',
          { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
      }
      if (hit) return hit;
      throw err;
    }
  })());
});
