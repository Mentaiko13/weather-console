// sw.js (v3) - simple PWA cache for Weather Console
const CACHE_NAME = "weather-console-v3";
const APP_SHELL = [
  "/ui",
  "/static/manifest.json",
  "/static/sw.js",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await cache.addAll(APP_SHELL);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => (k !== CACHE_NAME ? caches.delete(k) : Promise.resolve())));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Never cache webhook/API (POST will not be here, but keep safe)
  if (url.pathname === "/webhook") return;

  // Navigation: try network first, fallback to cache
  if (req.mode === "navigate") {
    event.respondWith((async () => {
      try {
        const fresh = await fetch(req);
        const cache = await caches.open(CACHE_NAME);
        cache.put("/ui", fresh.clone());
        return fresh;
      } catch (e) {
        const cached = await caches.match("/ui");
        return cached || new Response("Offline", { status: 503 });
      }
    })());
    return;
  }

  // Static assets: cache-first
  if (url.pathname.startsWith("/static/")) {
    event.respondWith((async () => {
      const cached = await caches.match(req);
      if (cached) return cached;
      const res = await fetch(req);
      const cache = await caches.open(CACHE_NAME);
      cache.put(req, res.clone());
      return res;
    })());
  }
});
