/* SquadForge phone app shell */
const CACHE = "squadforge-v58";
const PRECACHE = [
  "/",
  "/login",
  "/static/styles.css",
  "/static/ui.js",
  "/static/lineup.js",
  "/static/squadboard.js",
  "/static/fixtures.js",
  "/static/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
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
  const isStatic = url.pathname.startsWith("/static/");
  const isShell =
    url.pathname === "/" ||
    url.pathname === "/login" ||
    url.pathname === "/team" ||
    url.pathname === "/lineup" ||
    url.pathname === "/fixtures" ||
    url.pathname === "/rules" ||
    url.pathname === "/leagues";

  if (!isStatic && !isShell) return;

  event.respondWith(
    caches.match(req).then((cached) => {
      const fetched = fetch(req)
        .then((res) => {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((cache) => cache.put(req, copy));
          }
          return res;
        })
        .catch(() => cached);
      // Shell pages: network first so live GW data stays fresh; static: cache first
      if (isShell) return fetched.then((res) => res || cached);
      return cached || fetched;
    })
  );
});
