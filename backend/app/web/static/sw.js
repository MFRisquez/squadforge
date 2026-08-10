/* SquadForge offline shell — cache static assets only */
const CACHE = "squadforge-v23";
const PRECACHE = [
  "/static/styles.css",
  "/static/ui.js",
  "/static/manifest.webmanifest",
  "/static/icons/icon-192.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(req).then((cached) => {
        const fetched = fetch(req)
          .then((res) => {
            const copy = res.clone();
            caches.open(CACHE).then((cache) => cache.put(req, copy));
            return res;
          })
          .catch(() => cached);
        return cached || fetched;
      })
    );
  }
});
