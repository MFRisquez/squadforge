/* FutFantasy News magazine — filters + detail sheet */
(function () {
  const bootEl = document.getElementById("newsFeedBoot");
  let cards = [];
  try {
    cards = (bootEl && JSON.parse(bootEl.textContent || "{}").cards) || [];
  } catch (_) {
    cards = [];
  }
  const byId = {};
  cards.forEach((c) => {
    if (c && c.id) byId[c.id] = c;
  });

  const drawer = document.getElementById("newsDetail");
  const body = document.getElementById("newsDetailBody");
  const titleEl = document.getElementById("newsDetailTitle");
  const eyebrow = document.getElementById("newsDetailEyebrow");
  const closeBtn = document.getElementById("closeNewsDetail");

  function openDetail(card) {
    if (!drawer || !body || !card) return;
    if (eyebrow) {
      eyebrow.textContent =
        (card.label || "News") +
        (card.gameweek_number ? " · GW" + card.gameweek_number : "");
    }
    if (titleEl) titleEl.textContent = card.headline || "News";
    const parts = [];
    if (card.photo) {
      parts.push(
        '<div class="news-detail-hero">' +
          '<img class="news-detail-photo" src="' +
          card.photo +
          '"' +
          (card.photo_fallback
            ? ' data-fallback="' + card.photo_fallback + '"'
            : "") +
          ' alt="' +
          (card.player_name || "") +
          '" onerror="if(this.dataset.fallback&&this.src!==this.dataset.fallback){this.src=this.dataset.fallback;}else{this.parentElement.remove();}" />' +
          "</div>"
      );
    }
    if (card.player_name) {
      parts.push('<p class="news-detail-player">' + escapeHtml(card.player_name) + "</p>");
    }
    const stats = card.stats || [];
    if (stats.length) {
      parts.push('<div class="news-detail-stats">');
      stats.forEach((s) => {
        parts.push(
          '<span class="news-stat-chip"><span class="news-stat-label">' +
            escapeHtml(s.label) +
            '</span><strong>' +
            escapeHtml(String(s.value)) +
            "</strong></span>"
        );
      });
      parts.push("</div>");
    }
    const paras = String(card.body || "")
      .split(/\n\n+/)
      .map((p) => p.trim())
      .filter(Boolean);
    if (paras.length) {
      parts.push('<div class="news-detail-copy">');
      paras.forEach((p) => {
        parts.push("<p>" + escapeHtml(p) + "</p>");
      });
      parts.push("</div>");
    } else if (card.summary) {
      parts.push('<p class="news-detail-copy">' + escapeHtml(card.summary) + "</p>");
    }
    body.innerHTML = parts.join("");
    drawer.hidden = false;
    document.body.classList.add("drawer-open");
  }

  function closeDetail() {
    if (!drawer) return;
    drawer.hidden = true;
    document.body.classList.remove("drawer-open");
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  document.querySelectorAll("[data-news-card]").forEach((el) => {
    el.addEventListener("click", () => {
      const id = el.getAttribute("data-card-id");
      openDetail(byId[id]);
    });
  });

  if (closeBtn) closeBtn.addEventListener("click", closeDetail);
  if (drawer) {
    drawer.addEventListener("click", (e) => {
      if (e.target === drawer) closeDetail();
    });
  }

  const filters = document.querySelector("[data-news-filters]");
  if (filters) {
    filters.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-filter]");
      if (!btn || !filters.contains(btn)) return;
      const key = btn.getAttribute("data-filter") || "all";
      filters.querySelectorAll(".news-filter").forEach((b) => {
        b.classList.toggle("is-active", b === btn);
      });
      document.querySelectorAll("[data-news-card]").forEach((card) => {
        const f = card.getAttribute("data-filter") || "";
        const show = key === "all" || f === key;
        card.hidden = !show;
        card.classList.toggle("is-filtered-out", !show);
      });
    });
  }

  window.__ffTeardown = function () {
    closeDetail();
  };
})();
