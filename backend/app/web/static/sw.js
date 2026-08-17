/* FutFantasy phone app shell */
const CACHE = "futfantasy-v96";
const PRECACHE = [
  "/static/styles.css",
  "/static/ui.js",
  "/static/chips.js",
  "/static/appshell.js",
  "/static/lineup.js",
  "/static/squadboard.js",
  "/static/fixtures.js",
  "/static/fonts/Vielma_Grotesk_Bold.woff2",
  "/static/fonts/Vielma_Grotesk_Bold.otf",
  "/static/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/icon-512-maskable.png",
  "/static/icons/apple-touch-icon.png",
  "/static/icons/favicon-32.png",
  "/static/icons/logo.svg",
  "/favicon.ico",
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
  const isCatalog = url.pathname === "/api/players/catalog";
  const isShell =
    url.pathname === "/" ||
    url.pathname === "/login" ||
    url.pathname === "/team" ||
    url.pathname === "/lineup" ||
    url.pathname === "/fixtures" ||
    url.pathname === "/rules" ||
    url.pathname === "/leagues" ||
    url.pathname === "/onboard" ||
    url.pathname.startsWith("/standings/") ||
    url.pathname.startsWith("/league");

  if (!isStatic && !isShell && !isCatalog) return;

  event.respondWith(
    caches.match(req).then((cached) => {
      const fetched = fetch(req)
        .then((res) => {
          if (res && res.ok && (isStatic || isCatalog)) {
            const copy = res.clone();
            caches.open(CACHE).then((cache) => cache.put(req, copy));
          }
          return res;
        })
        .catch(() => cached);

      // Static + player catalog: cache-first
      if (isStatic || isCatalog) return cached || fetched;

      // Shell HTML: always network-first so GW / standings / fixtures never paint stale.
      // Do not put HTML into Cache Storage (query params like ?gw= must stay live).
      return fetched.then((res) => res || cached);
    })
  );
});
