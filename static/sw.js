// sw.js (v4) - safe defaults for this app
// - Never intercept POST /webhook
// - Cache UI shell + static assets
// - Network-first for HTML, cache-first for icons/css/js

const VERSION = "v4-20251224";
const CACHE_NAME = `weather-console-${VERSION}`;

const PRECACHE_URLS = [
  "/ui",
  "/static/manifest.json",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/sw.js"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => (k !== CACHE_NAME ? caches.delete(k) : null)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Don't touch non-GET (especially POST /webhook)
  if (req.method !== "GET") return;

  // Never cache API-ish calls (keep it simple and safe)
  if (url.pathname === "/webhook") {
    event.respondWith(fetch(req));
    return;
  }

  // HTML: network-first (so UI updates are picked up), fallback to cache
  const accept = req.headers.get("accept") || "";
  const isHtml = accept.includes("text/html") || url.pathname === "/ui" || url.pathname === "/";
  if (isHtml) {
    event.respondWith((async () => {
      try {
        const fresh = await fetch(req, { cache: "no-store" });
        const cache = await caches.open(CACHE_NAME);
        cache.put(req, fresh.clone());
        return fresh;
      } catch (e) {
        const cached = await caches.match(req);
        return cached || new Response("オフラインです。接続後に再読み込みしてください。", { status: 503 });
      }
    })());
    return;
  }

  // Static assets: cache-first
  event.respondWith((async () => {
    const cached = await caches.match(req);
    if (cached) return cached;
    const fresh = await fetch(req);
    const cache = await caches.open(CACHE_NAME);
    cache.put(req, fresh.clone());
    return fresh;
  })());
});
