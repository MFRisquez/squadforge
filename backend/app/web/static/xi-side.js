/* XI left-rail KPIs: load after paint, render scorers + position chart. */
(function () {
  const root = document.getElementById("xiPositionBlock");
  if (!root) return;

  const scorersSlot = document.getElementById("xiScorersSlot");
  const positionSlot = document.getElementById("xiPositionSlot");
  const drawer = document.getElementById("rankHistoryDrawer");
  const drawerTitle = document.getElementById("rankHistoryTitle");
  const drawerBody = document.getElementById("rankHistoryBody");
  const url = root.getAttribute("data-kpi-url") || "/api/xi/side-kpis";

  let chartsCache = [];
  let activeChart = 0;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtPts(n) {
    const v = Number(n);
    if (!Number.isFinite(v)) return "—";
    return String(Math.round(v));
  }

  function renderScorers(rows) {
    if (!scorersSlot) return;
    scorersSlot.classList.remove("is-loading");
    scorersSlot.removeAttribute("aria-busy");
    if (!rows || !rows.length) {
      scorersSlot.innerHTML =
        '<p class="muted tiny">Points while you owned them show up after scored gameweeks.</p>';
      return;
    }
    const head =
      '<li class="desk-side-scorer-head" aria-hidden="true">' +
      '<span></span><span></span>' +
      "<span>Pts</span><span>APP</span><span>G</span><span>A</span><span>CS</span>" +
      "</li>";
    const body = rows
      .map((row, i) => {
        return (
          "<li>" +
          `<span class="desk-side-scorer-rank">${i + 1}</span>` +
          `<strong title="${esc(row.name)}">${esc(row.name)}</strong>` +
          `<span class="sc-pts">${fmtPts(row.points)}</span>` +
          `<span class="sc-app">${row.app ?? 0}</span>` +
          `<span class="sc-g">${row.goals ?? 0}</span>` +
          `<span class="sc-a">${row.assists ?? 0}</span>` +
          `<span class="sc-cs">${row.cs ?? 0}</span>` +
          "</li>"
        );
      })
      .join("");
    scorersSlot.innerHTML = `<ol class="desk-side-scorer-list">${head}${body}</ol>`;
  }

  function chartGeom(view) {
    const w = Number(view.chart_width) || 400;
    const h = Number(view.chart_height) || 280;
    const left = Number(view.plot_left != null ? view.plot_left : 78);
    const right = Number(view.plot_right != null ? view.plot_right : w - 22);
    const top = Number(view.plot_top != null ? view.plot_top : 16);
    const bottom = Number(view.plot_bottom != null ? view.plot_bottom : h - 24);
    return { w, h, left, right, top, bottom };
  }

  function renderSvg(view, opts) {
    opts = opts || {};
    const g = chartGeom(view);
    const showNames = opts.showNames !== false;
    const interactive = !!opts.interactive;
    const parts = [];
    parts.push(
      `<svg class="desk-side-rank-spark-svg" viewBox="0 0 ${g.w} ${g.h}" preserveAspectRatio="none" role="img">`
    );
    parts.push(
      `<rect class="rank-plot-bg" x="${g.left}" y="${g.top}" width="${Math.max(
        0,
        g.right - g.left
      )}" height="${Math.max(0, g.bottom - g.top)}" rx="4"></rect>`
    );
    (view.grid || []).forEach((row) => {
      parts.push(
        `<line class="rank-grid" x1="${g.left}" y1="${row.y}" x2="${g.right}" y2="${row.y}"></line>`
      );
      if (!showNames) {
        parts.push(
          `<text class="rank-axis rank-axis-y" x="${g.left - 6}" y="${
            Number(row.y) + 3.5
          }">${esc(row.rank)}</text>`
        );
      }
    });
    if (showNames) {
      (view.name_labels || []).forEach((lab) => {
        parts.push(
          `<text class="rank-name-label${
            lab.is_me ? " is-me" : ""
          }" x="${g.left - 8}" y="${Number(lab.y) + 3.5}" text-anchor="end">` +
            `<title>${esc(lab.full || lab.text)}</title>${esc(lab.text)}</text>`
        );
      });
    }
    (view.gw_labels || []).forEach((lab) => {
      parts.push(
        `<text class="rank-axis gw" x="${lab.x}" y="${g.h - 6}">GW${esc(
          lab.number
        )}</text>`
      );
    });
    (view.series || []).forEach((s) => {
      if (s.area_path && s.is_me) {
        parts.push(`<path class="rank-area is-me" d="${esc(s.area_path)}"></path>`);
      }
    });
    (view.series || []).forEach((s) => {
      if (!s.polyline) return;
      parts.push(
        `<polyline class="rank-line${s.is_me ? " is-me" : ""}" fill="none" stroke="${esc(
          s.color || "#888"
        )}" stroke-width="${s.is_me ? 3 : 1.35}" stroke-linecap="round" stroke-linejoin="round" points="${esc(
          s.polyline
        )}"><title>${esc(s.team_name)}</title></polyline>`
      );
      (s.points || []).forEach((p) => {
        parts.push(
          `<circle class="rank-dot${s.is_me ? " is-me" : ""}" cx="${p.x}" cy="${
            p.y
          }" r="${s.is_me ? 3.6 : 2.1}" fill="${esc(
            s.color || "#888"
          )}" stroke="#fff" stroke-width="0.85"><title>${esc(p.title)}</title></circle>`
        );
      });
    });
    parts.push("</svg>");
    const wrapClass = interactive
      ? "desk-side-rank-spark-chart is-clickable"
      : "desk-side-rank-spark-chart";
    return `<div class="${wrapClass}" ${
      interactive ? 'role="button" tabindex="0" data-rank-open' : ""
    }>${parts.join("")}</div>`;
  }

  function bindSwitch(rootEl) {
    const btns = rootEl.querySelectorAll("[data-rank-chart]");
    const panels = rootEl.querySelectorAll("[data-rank-panel]");
    if (!btns.length || panels.length < 2) return;
    btns.forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = btn.getAttribute("data-rank-chart");
        activeChart = Number(idx) || 0;
        btns.forEach((b) => {
          const on = b.getAttribute("data-rank-chart") === idx;
          b.classList.toggle("is-active", on);
          b.setAttribute("aria-selected", on ? "true" : "false");
        });
        panels.forEach((p) => {
          const on = p.getAttribute("data-rank-panel") === idx;
          p.classList.toggle("is-active", on);
          if (on) p.removeAttribute("hidden");
          else p.setAttribute("hidden", "");
        });
        rootEl.classList.toggle(
          "is-preview",
          !!(rootEl.querySelector(".desk-side-rank-panel.is-active .desk-side-preview-mark"))
        );
      });
    });
  }

  function openHistory(chart) {
    if (!drawer || !drawerBody || !chart) return;
    const full = chart.full || chart;
    if (drawerTitle) {
      drawerTitle.textContent = chart.league_name
        ? `${chart.league_name} · all GWs`
        : "Full season";
    }
    drawerBody.innerHTML = renderSvg(full, { showNames: true, interactive: false });
    drawer.hidden = false;
    document.body.classList.add("drawer-open");
  }

  function closeHistory() {
    if (!drawer) return;
    drawer.hidden = true;
    document.body.classList.remove("drawer-open");
  }

  function bindHistory(rootEl) {
    rootEl.querySelectorAll("[data-rank-open]").forEach((el) => {
      const open = () => {
        const panel = el.closest("[data-rank-panel]");
        const idx = panel ? Number(panel.getAttribute("data-rank-panel") || 0) : activeChart;
        openHistory(chartsCache[idx]);
      };
      el.addEventListener("click", open);
      el.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          open();
        }
      });
    });
  }

  if (drawer) {
    drawer.addEventListener("click", (ev) => {
      if (ev.target === drawer) closeHistory();
    });
    drawer.querySelectorAll("[data-rank-close]").forEach((el) => {
      el.addEventListener("click", closeHistory);
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && drawer && !drawer.hidden) closeHistory();
    });
  }

  function renderPosition(spark) {
    if (!positionSlot) return;
    positionSlot.classList.remove("is-loading");
    positionSlot.removeAttribute("aria-busy");
    chartsCache = (spark && spark.charts) || [];
    if (!chartsCache.length) {
      positionSlot.innerHTML =
        '<header class="desk-rail-head"><p class="eyebrow">Position</p><h2>League trend</h2></header>' +
        '<p class="muted tiny">Join a league to track your rank here.</p>';
      return;
    }
    const multi = chartsCache.length > 1;
    let html = `<div class="desk-side-rank-spark${
      chartsCache[0].preview ? " is-preview" : ""
    }" id="deskRankSpark" aria-label="Position trend">`;
    html += '<header class="desk-side-rank-spark-head"><p class="eyebrow">Position</p>';
    if (multi) {
      html += '<div class="desk-side-rank-switch" role="tablist" aria-label="League chart">';
      chartsCache.forEach((c, i) => {
        html += `<button type="button" class="desk-side-rank-switch-btn${
          i === 0 ? " is-active" : ""
        }" role="tab" aria-selected="${i === 0 ? "true" : "false"}" data-rank-chart="${i}">${esc(
          c.league_name
        )}</button>`;
      });
      html += "</div>";
    }
    html += "</header>";
    chartsCache.forEach((c, i) => {
      const view = c.window || c;
      html += `<div class="desk-side-rank-panel${
        i === 0 ? " is-active" : ""
      }" data-rank-panel="${i}" role="tabpanel"${i === 0 ? "" : " hidden"}>`;
      html += '<div class="desk-side-rank-meta">';
      html += `<strong>${esc(c.league_name)}${
        c.current_rank && !c.preview ? ` · #${esc(c.current_rank)}` : ""
      }</strong>`;
      if (c.preview && c.watermark) {
        html += `<p class="desk-side-preview-mark">${esc(c.watermark)}</p>`;
      } else if (c.has_more_gws) {
        html += '<p class="muted tiny desk-side-rank-hint">Last 5 GWs · tap chart for full season</p>';
      }
      html += "</div>";
      html += renderSvg(view, { showNames: true, interactive: true });
      html += "</div>";
    });
    html += "</div>";
    positionSlot.innerHTML = html;
    const sparkRoot = document.getElementById("deskRankSpark");
    if (sparkRoot) {
      bindSwitch(sparkRoot);
      bindHistory(sparkRoot);
    }
  }

  function fail(msg) {
    if (scorersSlot) {
      scorersSlot.classList.remove("is-loading");
      scorersSlot.innerHTML = `<p class="muted tiny">${esc(msg || "Stats unavailable.")}</p>`;
    }
    if (positionSlot) {
      positionSlot.classList.remove("is-loading");
      positionSlot.innerHTML =
        '<header class="desk-rail-head"><p class="eyebrow">Position</p><h2>League trend</h2></header>' +
        `<p class="muted tiny">${esc(msg || "Chart unavailable.")}</p>`;
    }
  }

  const run = () => {
    fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error("bad status"))))
      .then((data) => {
        if (!data || !data.ok) {
          fail("Stats unavailable.");
          return;
        }
        renderScorers(data.top_scorers || []);
        renderPosition(data.rank_spark);
      })
      .catch(() => fail("Stats unavailable."));
  };

  if (typeof requestIdleCallback === "function") {
    requestIdleCallback(run, { timeout: 1200 });
  } else {
    setTimeout(run, 0);
  }
})();
