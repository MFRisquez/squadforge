(() => {
  const bootEl = document.getElementById("h2hFixturesBoot");
  const drawer = document.getElementById("h2hMatchDetail");
  const body = document.getElementById("h2hMatchBody");
  const title = document.getElementById("h2hMatchTitle");
  const closeBtn = document.getElementById("closeH2hMatch");
  if (!bootEl || !drawer || !body) return;

  let cards = [];
  try {
    cards = JSON.parse(bootEl.textContent || "[]");
  } catch (_) {
    cards = [];
  }
  const byId = Object.fromEntries(cards.map((c) => [String(c.id), c]));

  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function sideHtml(side, showScores) {
    const top = showScores ? side.top_player : null;
    const chips = Array.isArray(side.chips_left) ? side.chips_left : [];
    const pts = showScores ? `${Math.round(Number(side.points) || 0)} pts` : "Preview";
    const topLine = showScores
      ? top
        ? `<p class="h2h-sheet-top"><span class="muted">Top XI</span> <strong>${escapeHtml(top.name)}</strong> · ${Math.round(Number(top.points) || 0)} pts</p>`
        : `<p class="h2h-sheet-top muted">Top XI · —</p>`
      : `<p class="h2h-sheet-top muted">Top XI · reveals after deadline</p>`;
    const chipLine = chips.length
      ? `<p class="h2h-sheet-chips"><span class="muted">Chips left</span> ${chips.map(escapeHtml).join(" · ")}</p>`
      : `<p class="h2h-sheet-chips muted">Chips left · none</p>`;
    return `
      <article class="h2h-sheet-side">
        <header class="h2h-sheet-side-head">
          <div>
            <strong class="h2h-sheet-team">${escapeHtml(side.team_name)}</strong>
            <p class="muted tiny">${escapeHtml(side.display_name)}</p>
          </div>
          <span class="h2h-sheet-pts">${escapeHtml(pts)}</span>
        </header>
        ${topLine}
        ${chipLine}
      </article>
    `;
  }

  function openMatch(id) {
    const fx = byId[String(id)];
    if (!fx) return;
    if (title) {
      title.textContent = `${fx.home.team_name} vs ${fx.away.team_name}`;
    }
    const show = !!fx.show_scores;
    body.innerHTML = `
      <div class="h2h-sheet-scoreline">
        ${sideHtml(fx.home, show)}
        <div class="h2h-sheet-vs muted">${show ? (fx.result === "pending" ? "LIVE" : fx.result === "draw" ? "DRAW" : "FT") : "Preview"}</div>
        ${sideHtml(fx.away, show)}
      </div>
    `;
    drawer.hidden = false;
  }

  function closeMatch() {
    if (typeof window.__ffCloseDrawer === "function") {
      window.__ffCloseDrawer(drawer);
    } else {
      drawer.hidden = true;
    }
  }

  document.querySelectorAll("[data-h2h-match]").forEach((btn) => {
    btn.addEventListener("click", () => openMatch(btn.getAttribute("data-h2h-match")));
  });
  if (closeBtn) closeBtn.addEventListener("click", closeMatch);
  drawer.addEventListener("click", (e) => {
    if (e.target === drawer) closeMatch();
  });
})();
