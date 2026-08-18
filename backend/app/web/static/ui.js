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
      el.querySelectorAll(".drawer-sheet, .match-detail-sheet, .player-detail-sheet, .club-picker-sheet").forEach((sheet) => {
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
      ".drawer-sheet, .match-detail-sheet, .player-detail-sheet, .club-picker-sheet"
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
  if (isStandalone) {
    document.documentElement.classList.add("is-standalone");
  }
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

  // Chip info tip: park on document.body so page-fit/transform ancestors
  // can't offset position:fixed far below the i icon.
  function ensureTipId(wrap) {
    if (!wrap.dataset.tipId) {
      wrap.dataset.tipId = `chip-tip-${Math.random().toString(36).slice(2, 9)}`;
    }
    return wrap.dataset.tipId;
  }

  function restoreChipTip(tip) {
    if (!tip) return;
    const homeId = tip.dataset.tipFor;
    const home = homeId ? document.querySelector(`.chip-info-wrap[data-tip-id="${homeId}"]`) : null;
    tip.classList.remove("is-fixed", "is-above", "is-open-tip");
    tip.style.cssText = "";
    tip.removeAttribute("data-tip-for");
    if (home && tip.parentElement !== home) home.appendChild(tip);
  }

  function placeChipTip(wrap) {
    const btn = wrap.querySelector(".chip-info-btn");
    let tip = wrap.querySelector(".chip-tip");
    if (!tip || !btn) return;
    const tipId = ensureTipId(wrap);
    tip.dataset.tipFor = tipId;
    // Escape overflow/transform ancestors
    if (tip.parentElement !== document.body) {
      document.body.appendChild(tip);
    }
    tip.classList.add("is-fixed", "is-open-tip");
    const rect = btn.getBoundingClientRect();
    const tipWidth = Math.min(148, Math.max(108, Math.min(window.innerWidth - 16, 148)));
    tip.style.position = "fixed";
    tip.style.width = `${tipWidth}px`;
    tip.style.maxWidth = `${tipWidth}px`;
    tip.style.right = "auto";
    tip.style.bottom = "auto";
    tip.style.margin = "0";
    tip.style.zIndex = "4000";
    // Center under the i button, tight gap
    let left = rect.left + rect.width / 2 - tipWidth / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - tipWidth - 8));
    let top = rect.bottom + 4;
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
    // Measure after paint; flip above if needed, keep glued to the icon
    requestAnimationFrame(() => {
      const h = tip.offsetHeight || 64;
      const spaceBelow = window.innerHeight - rect.bottom - 8;
      if (h > spaceBelow && rect.top > h + 8) {
        tip.style.top = `${Math.max(8, rect.top - h - 4)}px`;
        tip.classList.add("is-above");
      } else {
        tip.style.top = `${rect.bottom + 4}px`;
        tip.classList.remove("is-above");
      }
      // Re-clamp horizontally in case width changed with content
      const w = tip.offsetWidth || tipWidth;
      let nextLeft = rect.left + rect.width / 2 - w / 2;
      nextLeft = Math.max(8, Math.min(nextLeft, window.innerWidth - w - 8));
      tip.style.left = `${nextLeft}px`;
    });
  }

  function closeAllChipTips(except) {
    document.querySelectorAll(".chip-info-wrap.is-open").forEach((wrap) => {
      if (except && wrap === except) return;
      wrap.classList.remove("is-open");
      const btn = wrap.querySelector(".chip-info-btn");
      if (btn) btn.setAttribute("aria-expanded", "false");
      const tip =
        document.querySelector(`.chip-tip[data-tip-for="${wrap.dataset.tipId || ""}"]`) ||
        wrap.querySelector(".chip-tip");
      restoreChipTip(tip);
    });
    // Orphan tips left on body
    document.querySelectorAll("body > .chip-tip.is-open-tip").forEach((tip) => {
      const homeId = tip.dataset.tipFor;
      const wrap = homeId ? document.querySelector(`.chip-info-wrap[data-tip-id="${homeId}"]`) : null;
      if (except && wrap === except) return;
      restoreChipTip(tip);
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
      else {
        const tip =
          document.querySelector(`.chip-tip[data-tip-for="${wrap.dataset.tipId || ""}"]`) ||
          wrap.querySelector(".chip-tip");
        restoreChipTip(tip);
      }
      return;
    }
    if (!e.target.closest(".chip-info-wrap") && !e.target.closest(".chip-tip")) {
      closeAllChipTips();
    }
  });
  window.addEventListener("scroll", () => closeAllChipTips(), true);
  window.addEventListener("resize", () => closeAllChipTips());

  // Desktop hover for chip tips
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
      const to = e.relatedTarget;
      if (to && to.closest && to.closest(".chip-tip")) return;
      if (wrap) {
        if (to && wrap.contains(to)) return;
        closeAllChipTips();
        return;
      }
      // Leaving a body-parked tip
      if (e.target.closest && e.target.closest(".chip-tip")) {
        if (to && to.closest && to.closest(".chip-info-wrap")) return;
        closeAllChipTips();
      }
    });
  }

  function formatCountdown(ms) {
    if (ms <= 0) return "Locked";
    const totalSec = Math.floor(ms / 1000);
    const d = Math.floor(totalSec / 86400);
    const h = Math.floor((totalSec % 86400) / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = totalSec % 60;
    if (d > 0) return `${d}d ${h}h ${m}m`;
    if (h > 0) return `${h}h ${m}m ${String(s).padStart(2, "0")}s`;
    return `${m}m ${String(s).padStart(2, "0")}s`;
  }

  function tickCountdowns() {
    document.querySelectorAll(".gw-countdown[data-deadline]").forEach((el) => {
      const raw = el.getAttribute("data-deadline");
      if (!raw) return;
      const end = new Date(raw);
      if (Number.isNaN(end.getTime())) return;
      const left = end.getTime() - Date.now();
      el.textContent = formatCountdown(left);
      el.classList.toggle("is-urgent", left > 0 && left < 3 * 60 * 60 * 1000);
      el.classList.toggle("is-locked", left <= 0);
    });
  }

  tickCountdowns();
  window.setInterval(tickCountdowns, 1000);

  // Show / hide password fields on auth screens
  document.querySelectorAll(".auth-password-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const wrap = btn.closest(".auth-password-wrap");
      const input = wrap && wrap.querySelector("input");
      if (!input) return;
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.setAttribute("aria-pressed", show ? "true" : "false");
      btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
      btn.setAttribute("title", show ? "Hide password" : "Show password");
      btn.textContent = show ? "🙈" : "👁";
    });
  });

  // Leave-league confirm — name from <script type="application/json" id="leaveLeagueName">
  document.querySelectorAll("form.js-leave-league").forEach((form) => {
    form.addEventListener("submit", (e) => {
      const nameEl = document.getElementById("leaveLeagueName");
      let name = "";
      try {
        name = JSON.parse(nameEl.textContent);
      } catch (_) {
        name = "this league";
      }
      if (!window.confirm(`Leave ${name}?`)) {
        e.preventDefault();
      }
    });
  });
})();
