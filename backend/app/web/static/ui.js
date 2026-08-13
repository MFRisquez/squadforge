(() => {
  // Soft focus helper for flashes
  const flash = document.querySelector(".flash");
  if (flash) {
    flash.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // Mark drawer sheets for enter animation when opened (bottom slide-up)
  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      const el = m.target;
      if (!(el instanceof HTMLElement) || !el.classList.contains("drawer")) continue;
      if (el.hidden) continue;
      el.querySelectorAll(".drawer-sheet, .match-detail-sheet, .player-detail-sheet").forEach((sheet) => {
        sheet.classList.remove("sheet-out");
        sheet.classList.remove("sheet-in");
        void sheet.offsetWidth;
        sheet.classList.add("sheet-in");
      });
    }
  });
  observer.observe(document.body, { attributes: true, subtree: true, attributeFilter: ["hidden"] });

  window.__ffCloseDrawer = function closeDrawer(drawer) {
    if (!drawer) return Promise.resolve();
    const sheet = drawer.querySelector(
      ".drawer-sheet, .match-detail-sheet, .player-detail-sheet"
    );
    if (!sheet || drawer.hidden) {
      drawer.hidden = true;
      return Promise.resolve();
    }
    sheet.classList.remove("sheet-in");
    sheet.classList.add("sheet-out");
    return new Promise((resolve) => {
      window.setTimeout(() => {
        drawer.hidden = true;
        sheet.classList.remove("sheet-out");
        resolve();
      }, 280);
    });
  };

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
  document.addEventListener("click", (e) => {
    if (e.target.closest("#themeToggle, #themeToggleHome")) toggleTheme();
  });

  // Chip info tip: fixed positioning so it isn’t clipped by chip strip scroll
  function placeChipTip(wrap) {
    const tip = wrap.querySelector(".chip-tip");
    const btn = wrap.querySelector(".chip-info-btn");
    if (!tip || !btn) return;
    tip.classList.add("is-fixed");
    const rect = btn.getBoundingClientRect();
    const tipWidth = Math.min(220, Math.max(140, window.innerWidth - 24));
    tip.style.width = `${tipWidth}px`;
    tip.style.maxWidth = `${tipWidth}px`;
    let left = rect.left + rect.width / 2 - tipWidth / 2;
    left = Math.max(12, Math.min(left, window.innerWidth - tipWidth - 12));
    let top = rect.bottom + 8;
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
    tip.style.right = "auto";
    tip.style.bottom = "auto";
    // If it would go below viewport, flip above
    requestAnimationFrame(() => {
      const h = tip.offsetHeight || 80;
      if (top + h > window.innerHeight - 12) {
        tip.style.top = `${Math.max(12, rect.top - h - 8)}px`;
        tip.classList.add("is-above");
      } else {
        tip.classList.remove("is-above");
      }
    });
  }

  function closeAllChipTips(except) {
    document.querySelectorAll(".chip-info-wrap.is-open").forEach((wrap) => {
      if (except && wrap === except) return;
      wrap.classList.remove("is-open");
      const btn = wrap.querySelector(".chip-info-btn");
      const tip = wrap.querySelector(".chip-tip");
      if (btn) btn.setAttribute("aria-expanded", "false");
      if (tip) {
        tip.classList.remove("is-fixed", "is-above");
        tip.style.left = "";
        tip.style.top = "";
        tip.style.width = "";
        tip.style.maxWidth = "";
      }
    });
  }
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".chip-info-btn");
    if (btn) {
      e.preventDefault();
      e.stopPropagation();
      const wrap = btn.closest(".chip-info-wrap");
      const willOpen = !wrap.classList.contains("is-open");
      closeAllChipTips(willOpen ? wrap : null);
      wrap.classList.toggle("is-open", willOpen);
      btn.setAttribute("aria-expanded", willOpen ? "true" : "false");
      if (willOpen) placeChipTip(wrap);
      return;
    }
    if (!e.target.closest(".chip-info-wrap") && !e.target.closest(".chip-tip")) {
      closeAllChipTips();
    }
  });
  window.addEventListener("scroll", () => closeAllChipTips(), true);
  window.addEventListener("resize", () => closeAllChipTips());

  // Desktop hover for chip tips (still uses fixed placement)
  if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    document.addEventListener("mouseover", (e) => {
      const wrap = e.target.closest(".chip-info-wrap");
      if (!wrap || wrap.classList.contains("is-open")) return;
      closeAllChipTips();
      wrap.classList.add("is-open");
      const btn = wrap.querySelector(".chip-info-btn");
      if (btn) btn.setAttribute("aria-expanded", "true");
      placeChipTip(wrap);
    });
    document.addEventListener("mouseout", (e) => {
      const wrap = e.target.closest(".chip-info-wrap");
      if (!wrap) return;
      const to = e.relatedTarget;
      if (to && wrap.contains(to)) return;
      if (to && to.closest && to.closest(".chip-tip")) return;
      closeAllChipTips();
    });
  }
})();
