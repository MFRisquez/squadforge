/* FutFantasy phone app shell */
const CACHE = "futfantasy-v186";
const PRECACHE = [
  "/static/styles.css?v=186",
  "/static/ui.js",
  "/static/chips.js",
  "/static/appshell.js?v=186",
  "/static/lineup.js?v=186",
  "/static/xi-side.js?v=186",
  "/static/squadboard.js?v=186",
  "/static/club-sheet.js?v=186",
  "/static/fixtures.js?v=186",
  "/static/league_h2h.js?v=186",
  "/static/news.js?v=186",
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
/* Club badges (+ player photos) from FPL CDN — same host as BADGE_CDN in kits.py */
const BADGE_CDN_HOST = "resources.premierleague.com";

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
  const isCss = isStatic && url.pathname.endsWith(".css");
  const isJs = isStatic && url.pathname.endsWith(".js");
  const isCatalog = url.pathname === "/api/players/catalog";
  const isBadgeCdn = url.hostname === BADGE_CDN_HOST;
  const isShell =
    url.pathname === "/" ||
    url.pathname === "/login" ||
    url.pathname === "/team" ||
    url.pathname === "/lineup" ||
    url.pathname === "/fixtures" ||
    url.pathname === "/rules" ||
    url.pathname === "/leagues" ||
    url.pathname === "/onboard" ||
    url.pathname === "/xi" ||
    url.pathname.startsWith("/standings/") ||
    url.pathname.startsWith("/league");

  if (!isStatic && !isShell && !isCatalog && !isBadgeCdn) return;

  event.respondWith(
    caches.match(req).then((cached) => {
      const fetched = fetch(req)
        .then((res) => {
          // Opaque cross-origin (no-cors <img>) has ok=false / status 0 — still cacheable.
          const okToCache =
            res && (res.ok || (isBadgeCdn && res.type === "opaque"));
          if (okToCache && (isStatic || isCatalog || isBadgeCdn)) {
            const copy = res.clone();
            caches.open(CACHE).then((cache) => cache.put(req, copy));
          }
          return res;
        })
        .catch(() => cached);

      // All static CSS/JS: cache-first. Soft-nav re-injects page scripts every
      // tab; appshell also keeps an in-memory source cache. Live GW data lives
      // in HTML/API, not these assets. Catalog stays network-first.
      if (isCss || isJs) {
        return cached || fetched;
      }

      // Shell HTML + catalog: network-first.
      if (isCatalog || isShell) {
        return fetched.then((res) => res || cached);
      }

      // Badge CDN (and other static): cache-first.
      if (isStatic || isBadgeCdn) return cached || fetched;

      return fetched.then((res) => res || cached);
    })
  );
});
