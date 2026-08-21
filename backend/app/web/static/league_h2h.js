(() => {
  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function initMatchDrawer() {
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
  }

  function playerRowHtml(p, showScores) {
    const arm = p.is_captain
      ? '<em class="league-rival-arm">C</em>'
      : p.is_vice
        ? '<em class="league-rival-arm">V</em>'
        : "";
    let pts;
    if (p.points != null && Number.isFinite(Number(p.points))) {
      pts = String(Math.round(Number(p.points)));
    } else if (!showScores) {
      pts = "—";
    } else {
      pts = '<span class="muted">…</span>';
    }
    return (
      `<li class="league-rival-player${p.is_captain ? " is-cap" : ""}">` +
      `<span class="league-rival-pos">${escapeHtml(p.pos || "")}</span>` +
      `<span class="league-rival-name">${escapeHtml(p.name || "")}${arm}` +
      `<span class="muted">${escapeHtml(p.team || "")}</span></span>` +
      `<span class="league-rival-ppts">${pts}</span>` +
      `</li>`
    );
  }

  function renderXiList(slot, players, showScores, emptyMsg) {
    if (!slot) return;
    const list = Array.isArray(players) ? players : [];
    if (!list.length) {
      slot.outerHTML = `<p class="muted tiny">${escapeHtml(emptyMsg || "No locked XI yet.")}</p>`;
      return;
    }
    slot.classList.remove("is-skeleton");
    slot.removeAttribute("aria-hidden");
    slot.innerHTML = list.map((p) => playerRowHtml(p, showScores)).join("");
  }

  function setPts(el, value, showScores) {
    if (!el) return;
    if (!showScores) {
      el.textContent = "—";
      el.classList.add("is-muted");
      return;
    }
    el.classList.remove("is-muted");
    el.textContent = String(Math.round(Number(value) || 0));
  }

  function fillRivalCard(root, snap) {
    if (!root || !snap) return;
    if (snap.bye) {
      root.classList.remove("is-loading");
      root.removeAttribute("aria-busy");
      root.removeAttribute("data-h2h-rival-url");
      root.innerHTML = `<p class="muted">${escapeHtml(snap.message || "You have a bye this gameweek.")}</p>`;
      return;
    }
    if (snap.squad_unavailable) {
      root.classList.remove("is-loading");
      root.removeAttribute("aria-busy");
      root.removeAttribute("data-h2h-rival-url");
      const note = root.querySelector("[data-rival-note]");
      const xis = root.querySelector("[data-rival-xis]");
      if (note) {
        note.hidden = false;
        note.textContent = snap.message || "Squad locks at deadline — live points appear once the GW starts.";
      }
      if (xis) {
        xis.innerHTML = `<p class="muted">${escapeHtml(snap.message || "Squad not available yet.")}</p>`;
      }
      return;
    }

    const showScores = !!snap.show_scores;
    setPts(root.querySelector("[data-rival-me-pts]"), snap.me && snap.me.points, showScores);
    setPts(root.querySelector("[data-rival-them-pts]"), snap.rival && snap.rival.points, showScores);

    const note = root.querySelector("[data-rival-note]");
    if (note) {
      if (snap.message) {
        note.hidden = false;
        note.textContent = snap.message;
      } else {
        note.hidden = true;
        note.textContent = "";
      }
    }

    renderXiList(
      root.querySelector("[data-rival-me-xi]"),
      snap.me_players,
      showScores,
      "No locked XI yet."
    );
    renderXiList(
      root.querySelector("[data-rival-them-xi]"),
      snap.rival_players || snap.players,
      showScores,
      "No locked XI yet."
    );

    root.classList.remove("is-loading");
    root.removeAttribute("aria-busy");
    root.removeAttribute("data-h2h-rival-url");
  }

  function initRivalLazy() {
    const root = document.querySelector(".league-rival-card[data-h2h-rival-url]");
    if (!root) return;
    const url = root.getAttribute("data-h2h-rival-url");
    if (!url) return;

    fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then((r) => r.json())
      .then((data) => {
        if (!data || !data.ok || !data.rival) {
          root.classList.remove("is-loading");
          root.removeAttribute("aria-busy");
          const xis = root.querySelector("[data-rival-xis]");
          if (xis) {
            xis.innerHTML = '<p class="muted tiny">Could not load squad details.</p>';
          }
          return;
        }
        fillRivalCard(root, data.rival);
      })
      .catch(() => {
        root.classList.remove("is-loading");
        root.removeAttribute("aria-busy");
        const xis = root.querySelector("[data-rival-xis]");
        if (xis) {
          xis.innerHTML = '<p class="muted tiny">Could not load squad details.</p>';
        }
      });
  }

  initMatchDrawer();
  initRivalLazy();
})();
