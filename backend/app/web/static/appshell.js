(() => {
  const CATALOG_KEY = "ff_players_catalog_v2";
  const CATALOG_META = "ff_players_catalog_meta_v2";
  const WARM_KEY = "ff_shell_warmed_v1";
  const SHELL_PATHS = new Set(["/", "/lineup", "/team", "/fixtures", "/rules", "/leagues", "/onboard"]);
  const pageCache = new Map(); // full path+search -> { html, at }
  const CACHE_TTL_MS = 45_000;
  const DESK_MQ = window.matchMedia("(min-width: 900px)");
  let navigating = false;
  let pendingNav = null; // latest path queued while a soft-nav is in flight

  function syncDeskCookie() {
    try {
      const desk = DESK_MQ && DESK_MQ.matches ? "1" : "0";
      document.cookie = `ff_desk=${desk}; Path=/; Max-Age=31536000; SameSite=Lax`;
    } catch (_) {}
  }
  syncDeskCookie();
  if (DESK_MQ && typeof DESK_MQ.addEventListener === "function") {
    DESK_MQ.addEventListener("change", syncDeskCookie);
  }

  function softNavHeaders() {
    // Same ≥900px breakpoint as lineup isDesktop — server skips desk-side work on phone.
    syncDeskCookie();
    return {
      Accept: "text/html",
      "X-Requested-With": "ff-shell",
      "X-FF-Desktop": DESK_MQ && DESK_MQ.matches ? "1" : "0",
    };
  }

  function isAuthPage() {
    return document.body.classList.contains("page-auth");
  }

  function hasAppNav() {
    return Boolean(document.querySelector("nav.nav"));
  }

  function sameOriginPath(href) {
    try {
      const u = new URL(href, window.location.origin);
      if (u.origin !== window.location.origin) return null;
      return u.pathname + u.search;
    } catch (_) {
      return null;
    }
  }

  function isShellPath(pathWithSearch) {
    if (!pathWithSearch) return false;
    const path = pathWithSearch.split("?")[0];
    if (SHELL_PATHS.has(path)) return true;
    if (path.startsWith("/standings/")) return true;
    if (path.startsWith("/league")) return true;
    return false;
  }

  async function warmCatalog() {
    try {
      const cached = JSON.parse(sessionStorage.getItem(CATALOG_KEY) || "null");
      if (Array.isArray(cached) && cached.length) return cached;
    } catch (_) {}
    const res = await fetch("/api/players/catalog", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) throw new Error("catalog");
    const data = await res.json();
    const players = Array.isArray(data.players) ? data.players : [];
    try {
      sessionStorage.setItem(CATALOG_KEY, JSON.stringify(players));
      sessionStorage.setItem(
        CATALOG_META,
        JSON.stringify({ version: data.version || "", at: Date.now() })
      );
    } catch (_) {}
    return players;
  }

  function prefetch(url) {
    return fetch(url, {
      credentials: "same-origin",
      headers: { ...softNavHeaders(), Purpose: "prefetch" },
    })
      .then(async (res) => {
        if (!res.ok) return;
        const html = await res.text();
        // Keep query string (e.g. ?gw=) so GW arrows don't reuse the wrong page.
        pageCache.set(url, { html, at: Date.now(), serverPerf: readServerPerfHeader(res) });
      })
      .catch(() => {});
  }

  function leagueWarmUrl() {
    // Mirror base.html nav: one league → /standings/{id}; else hub /leagues.
    const nav = document.querySelector("nav.nav");
    if (!nav) return "/leagues";
    for (const a of nav.querySelectorAll("a[href]")) {
      const href = (a.getAttribute("href") || "").split("?")[0];
      if (href === "/leagues" || /^\/standings\/\d+$/.test(href)) return href;
    }
    return "/leagues";
  }

  async function warmShellData() {
    await Promise.allSettled([
      warmCatalog(),
      prefetch("/"),
      prefetch("/lineup"),
      prefetch("/team"),
      prefetch("/fixtures"),
      prefetch(leagueWarmUrl()),
      prefetch("/rules"),
    ]);
    try {
      sessionStorage.setItem(WARM_KEY, String(Date.now()));
    } catch (_) {}
  }

  function hideSplash() {
    const splash = document.getElementById("appSplash");
    if (!splash) return;
    splash.setAttribute("aria-busy", "false");
    splash.classList.add("is-done");
    document.documentElement.classList.remove("ff-splash-lock");
    window.setTimeout(() => splash.remove(), 340);
  }

  async function runColdStartSplash() {
    if (isAuthPage() || !hasAppNav()) {
      hideSplash();
      return;
    }
    const splash = document.getElementById("appSplash");
    if (!splash) {
      warmShellData();
      return;
    }

    // Full-screen brand hold for 2s; warm catalog/pages in parallel, then enter.
    document.documentElement.classList.add("ff-splash-lock");
    const warm = warmShellData().catch(() => {});
    await new Promise((r) => setTimeout(r, 2000));
    hideSplash();
    // Finish warming in background if still going.
    void warm;
  }

  function updateNavActive(path) {
    const nav = document.querySelector("nav.nav");
    if (!nav) return;
    const clean = path.split("?")[0];
    nav.querySelectorAll("a[href]").forEach((a) => {
      const href = sameOriginPath(a.getAttribute("href") || "");
      if (!href) return;
      const aPath = href.split("?")[0];
      let active = aPath === clean;
      if (aPath === "/lineup" && (clean.startsWith("/lineup") || clean.startsWith("/points") || clean.startsWith("/score"))) {
        active = true;
      }
      if (aPath === "/team" && (clean === "/team" || clean.startsWith("/transfers"))) {
        active = true;
      }
      if (aPath === "/fixtures" && clean.startsWith("/fixtures")) active = true;
      if (aPath === "/rules" && clean.startsWith("/rules")) active = true;
      if (
        (aPath === "/leagues" || aPath.startsWith("/standings/")) &&
        (clean.startsWith("/standings") || clean.startsWith("/league"))
      ) {
        active = true;
      }
      if (aPath === "/" && clean === "/") active = true;
      a.classList.toggle("is-active", active);
    });
  }

  function teardownPage() {
    if (typeof window.__ffTeardown === "function") {
      try {
        window.__ffTeardown();
      } catch (_) {}
    }
    window.__ffTeardown = null;
    document.querySelectorAll("body > .drawer, body > .picker-modal").forEach((el) => el.remove());
    document.body.classList.remove("picker-open");
    document.body.style.top = "";
  }

  async function runScripts(root) {
    const scripts = Array.from(root.querySelectorAll("script"));
    for (const old of scripts) {
      const type = (old.getAttribute("type") || "").toLowerCase();
      if (type && type !== "text/javascript" && type !== "module" && type !== "application/javascript") {
        // keep JSON / other data scripts in place
        continue;
      }
      const s = document.createElement("script");
      for (const attr of old.attributes) {
        s.setAttribute(attr.name, attr.value);
      }
      if (old.src) {
        await new Promise((resolve, reject) => {
          s.onload = () => resolve();
          s.onerror = () => resolve(); // don't block nav
          old.parentNode.replaceChild(s, old);
        });
      } else {
        s.textContent = old.textContent || "";
        old.parentNode.replaceChild(s, old);
      }
    }
  }

  /** Soft-nav timing (kept on for real-device measurement). */
  function reportSoftNavTiming({ url, fetchMs, scriptsMs, totalMs, fromCache, serverPerf }) {
    const fetchR = Math.round(fetchMs);
    const scriptsR = Math.round(scriptsMs);
    const totalR = Math.round(totalMs);
    const cacheTag = fromCache ? " cache" : "";
    const serverTag =
      serverPerf && serverPerf.server_ms != null ? ` server=${Math.round(serverPerf.server_ms)}ms` : "";
    console.log(
      `nav ${url}: fetch=${fetchR}ms, scripts=${scriptsR}ms, total=${totalR}ms${cacheTag}${serverTag}`
    );
    if (serverPerf && Array.isArray(serverPerf.spans)) {
      console.log(
        `nav ${url} server spans:`,
        serverPerf.spans.map((s) => `${s.name}=${s.ms}ms`).join(", ")
      );
    }
    try {
      fetch("/api/client-perf", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        credentials: "same-origin",
        keepalive: true,
        body: JSON.stringify({
          url: String(url || ""),
          fetch_ms: Math.round(fetchMs * 10) / 10,
          scripts_ms: Math.round(scriptsMs * 10) / 10,
          total_ms: Math.round(totalMs * 10) / 10,
          from_cache: Boolean(fromCache),
          server_perf: serverPerf || null,
        }),
      }).catch(() => {});
    } catch (_) {}
  }

  function readServerPerfHeader(res) {
    try {
      const raw = res.headers.get("X-FF-Server-Perf");
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (_) {
      return null;
    }
  }

  async function fetchPageHtml(path) {
    // Never reuse in-memory HTML for ?gw= — first tap must show the new gameweek.
    const key = path;
    const hasGw = /[?&]gw=/.test(path);
    if (!hasGw) {
      const hit = pageCache.get(key);
      if (hit && Date.now() - hit.at < CACHE_TTL_MS) {
        fetch(path, {
          credentials: "same-origin",
          cache: "no-store",
          headers: softNavHeaders(),
        })
          .then(async (res) => {
            if (!res.ok) return;
            pageCache.set(key, {
              html: await res.text(),
              at: Date.now(),
              serverPerf: readServerPerfHeader(res),
            });
          })
          .catch(() => {});
        return { html: hit.html, fromCache: true, serverPerf: hit.serverPerf || null };
      }
    }
    const res = await fetch(path, {
      credentials: "same-origin",
      cache: "no-store",
      headers: softNavHeaders(),
    });
    if (!res.ok) throw new Error("nav");
    if (res.redirected && res.url) {
      const dest = sameOriginPath(res.url);
      if (dest && dest.startsWith("/login")) {
        window.location.href = dest;
        return null;
      }
    }
    const serverPerf = readServerPerfHeader(res);
    const html = await res.text();
    pageCache.set(key, { html, at: Date.now(), serverPerf });
    return { html, fromCache: false, serverPerf };
  }

  async function softNavigate(path, { push = true } = {}) {
    if (navigating) {
      // Keep only the latest click (rapid GW arrow taps).
      pendingNav = { path, push };
      return;
    }
    if (!isShellPath(path)) {
      window.location.href = path;
      return;
    }
    navigating = true;
    const main = document.querySelector("main.shell");
    try {
      const t1 = performance.now();
      const fetched = await fetchPageHtml(path);
      const t2 = performance.now();
      if (fetched == null) return;
      const html = fetched.html;
      if (html == null) return;
      const doc = new DOMParser().parseFromString(html, "text/html");
      const nextMain = doc.querySelector("main.shell");
      if (!nextMain || !main) {
        window.location.href = path;
        return;
      }
      nextMain.classList.add("shell-pending");
      teardownPage();
      document.body.className = doc.body.className || "";
      document.title = doc.title || document.title;
      main.replaceWith(nextMain);
      updateNavActive(path.split("?")[0]);
      // Keep header GW pill in sync when soft-navigating ?gw=
      const nextPill = doc.querySelector(".gw-bar[data-view-gw]");
      const topPill = document.querySelector("header.top .pill");
      if (nextPill && topPill) {
        const n = nextPill.getAttribute("data-view-gw");
        if (n) topPill.textContent = `GW ${n}`;
      }
      if (push) history.pushState({ ffShell: true }, "", path);
      await runScripts(nextMain);
      const t3 = performance.now();
      reportSoftNavTiming({
        url: path,
        fetchMs: t2 - t1,
        scriptsMs: t3 - t2,
        totalMs: t3 - t1,
        fromCache: Boolean(fetched.fromCache),
        serverPerf: fetched.serverPerf || null,
      });
      bindGwPicker(nextMain);
      window.scrollTo(0, 0);
      requestAnimationFrame(() => {
        nextMain.classList.remove("shell-pending");
      });
    } catch (_) {
      window.location.href = path;
    } finally {
      navigating = false;
      if (pendingNav) {
        const next = pendingNav;
        pendingNav = null;
        softNavigate(next.path, { push: next.push });
      }
    }
  }

  function bindGwPicker(root) {
    const scope = root || document;
    scope.querySelectorAll(".gw-picker").forEach((sel) => {
      if (sel.dataset.gwBound === "1") return;
      sel.dataset.gwBound = "1";
      sel.addEventListener("change", () => {
        const base = sel.getAttribute("data-base-path") || window.location.pathname;
        const n = sel.value;
        if (!n) return;
        const url = `${base}${base.includes("?") ? "&" : "?"}gw=${encodeURIComponent(n)}`;
        const path = sameOriginPath(url) || url;
        // Soft-nav only — never full reload/splash when switching gameweeks.
        if (path === window.location.pathname + window.location.search) return;
        softNavigate(path, { push: true });
      });
    });
  }

  function onDocumentClick(e) {
    if (e.defaultPrevented) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (e.button !== 0) return;
    const a = e.target.closest("a[href]");
    if (!a) return;
    if (a.target && a.target !== "_self") return;
    if (a.hasAttribute("download")) return;
    // Legacy GW arrows (if any remain): full page load.
    if (a.classList.contains("gw-arrow")) return;
    const path = sameOriginPath(a.getAttribute("href") || "");
    if (!path || !isShellPath(path)) return;
    // allow hash-only on same page
    if (path.split("?")[0] === window.location.pathname && path.includes("#")) return;
    e.preventDefault();
    softNavigate(path);
  }

  window.addEventListener("popstate", () => {
    softNavigate(window.location.pathname + window.location.search, { push: false });
  });

  document.addEventListener("click", onDocumentClick);
  document.addEventListener("change", (e) => {
    if (e.target && e.target.classList && e.target.classList.contains("gw-picker")) {
      // bound via bindGwPicker; no-op safety
    }
  });

  // Expose for other modules (e.g. after save redirect)
  window.__ffNavigate = (url) => {
    const path = sameOriginPath(url);
    if (path && isShellPath(path)) softNavigate(path);
    else window.location.href = url;
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      bindGwPicker(document);
      runColdStartSplash();
    });
  } else {
    bindGwPicker(document);
    runColdStartSplash();
  }
})();
