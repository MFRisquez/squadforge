(() => {
  // Soft focus helper for flashes
  const flash = document.querySelector(".flash");
  if (flash) {
    flash.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // Mark drawer sheets for enter animation when opened
  const observer = new MutationObserver(() => {
    document.querySelectorAll(".drawer:not([hidden]) .drawer-sheet").forEach((el) => {
      el.classList.add("sheet-in");
    });
  });
  observer.observe(document.body, { attributes: true, subtree: true, attributeFilter: ["hidden"] });

  // Phone install prompt (Chrome/Edge/Android + Home Install button)
  let deferredInstall = null;
  const installBtn = document.getElementById("installAppBtn");
  const banner = document.getElementById("installBanner");
  const bannerInstall = document.getElementById("installBannerBtn");
  const bannerDismiss = document.getElementById("installBannerDismiss");
  const dismissedKey = "sf_install_dismissed";

  function showInstallUi(show) {
    if (installBtn) installBtn.hidden = !show;
    if (banner) {
      const dismissed = localStorage.getItem(dismissedKey) === "1";
      banner.hidden = !show || dismissed;
    }
  }

  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredInstall = e;
    showInstallUi(true);
  });

  window.addEventListener("appinstalled", () => {
    deferredInstall = null;
    showInstallUi(false);
    localStorage.setItem(dismissedKey, "1");
  });

  async function promptInstall() {
    if (!deferredInstall) return;
    deferredInstall.prompt();
    try {
      await deferredInstall.userChoice;
    } catch (_) {
      /* ignore */
    }
    deferredInstall = null;
    showInstallUi(false);
  }

  if (installBtn) installBtn.addEventListener("click", promptInstall);
  if (bannerInstall) bannerInstall.addEventListener("click", promptInstall);
  if (bannerDismiss) {
    bannerDismiss.addEventListener("click", () => {
      localStorage.setItem(dismissedKey, "1");
      if (banner) banner.hidden = true;
    });
  }

  // iOS tip: show banner with Add to Home Screen hint when standalone is unavailable
  const isStandalone =
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true;
  const isIos = /iphone|ipad|ipod/i.test(window.navigator.userAgent || "");
  if (isIos && !isStandalone && banner && localStorage.getItem(dismissedKey) !== "1") {
    banner.hidden = false;
    const tip = banner.querySelector(".install-banner-tip");
    if (tip) tip.hidden = false;
    if (bannerInstall) bannerInstall.hidden = true;
  }
  if (isStandalone) showInstallUi(false);

  // Theme: dark by default; toggle persists
  function applyTheme(theme) {
    const next = theme === "light" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("ff_theme", next);
    } catch (_) {}
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", next === "dark" ? "#121212" : "#FFFFFF");
  }
  function toggleTheme() {
    const cur = document.documentElement.getAttribute("data-theme") || "dark";
    applyTheme(cur === "dark" ? "light" : "dark");
  }
  document.querySelectorAll("#themeToggle, #themeToggleHome").forEach((btn) => {
    btn.addEventListener("click", toggleTheme);
  });

  // Prefetch nav targets so Home ↔ XI ↔ Transfers feel instant
  const prefetched = new Set();
  function prefetchHref(href) {
    if (!href || prefetched.has(href)) return;
    try {
      const u = new URL(href, window.location.origin);
      if (u.origin !== window.location.origin) return;
      prefetched.add(href);
      const link = document.createElement("link");
      link.rel = "prefetch";
      link.href = u.pathname + u.search;
      link.as = "document";
      document.head.appendChild(link);
    } catch (_) {}
  }
  document.querySelectorAll(".nav a[href]").forEach((a) => {
    const run = () => prefetchHref(a.href);
    a.addEventListener("pointerenter", run, { once: true });
    a.addEventListener("touchstart", run, { once: true, passive: true });
  });

  // Chip info: hover on desktop (CSS), tap toggle on phone
  function closeAllChipTips(except) {
    document.querySelectorAll(".chip-info-wrap.is-open").forEach((wrap) => {
      if (except && wrap === except) return;
      wrap.classList.remove("is-open");
      const btn = wrap.querySelector(".chip-info-btn");
      if (btn) btn.setAttribute("aria-expanded", "false");
    });
  }
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".chip-info-btn");
    if (btn) {
      e.preventDefault();
      e.stopPropagation();
      const wrap = btn.closest(".chip-info-wrap");
      const open = wrap.classList.toggle("is-open");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) closeAllChipTips(wrap);
      return;
    }
    if (!e.target.closest(".chip-info-wrap")) closeAllChipTips();
  });
})();
