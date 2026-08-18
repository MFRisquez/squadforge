(() => {
  /** Shared DT / club profile bottom sheet (transfers + XI). */
  function closeDrawer(el) {
    if (!el) return Promise.resolve();
    if (typeof window.__ffCloseDrawer === "function") {
      return window.__ffCloseDrawer(el);
    }
    el.hidden = true;
    return Promise.resolve();
  }

  function paintClubDetail(data, { canChoose, onChoose } = {}) {
    const clubDetail = document.getElementById("clubDetail");
    const clubDetailBody = document.getElementById("clubDetailBody");
    const clubDetailActions = document.getElementById("clubDetailActions");
    const clubDetailBadge = document.getElementById("clubDetailBadge");
    const clubDetailName = document.getElementById("clubDetailName");
    const clubDetailSub = document.getElementById("clubDetailSub");
    const clubPicker = document.getElementById("clubPicker");

    if (clubDetailName) clubDetailName.textContent = data.name || data.code;
    if (clubDetailSub) clubDetailSub.textContent = data.code || "";
    if (clubDetailBadge) {
      if (data.badge) {
        clubDetailBadge.hidden = false;
        clubDetailBadge.src = data.badge;
        clubDetailBadge.alt = `${data.code} badge`;
      } else {
        clubDetailBadge.hidden = true;
      }
    }
    const t = data.table || {};
    const top = data.top_players || [];
    const fixtures = data.fixtures || [];
    const tableHtml = `
      <div class="kpi-block">
        <div class="player-fdr-head"><strong>Season table</strong></div>
        <div class="club-table-grid" role="table">
          <div class="club-table-row is-head" role="row">
            <span>P</span><span>Pts</span><span>W</span><span>D</span><span>L</span><span>GF</span><span>GA</span><span>GD</span>
          </div>
          <div class="club-table-row" role="row">
            <strong>${t.played ?? 0}</strong>
            <strong>${t.points ?? 0}</strong>
            <strong>${t.wins ?? 0}</strong>
            <strong>${t.draws ?? 0}</strong>
            <strong>${t.losses ?? 0}</strong>
            <strong>${t.gf ?? 0}</strong>
            <strong>${t.ga ?? 0}</strong>
            <strong>${(t.gd ?? 0) > 0 ? "+" : ""}${t.gd ?? 0}</strong>
          </div>
        </div>
      </div>`;
    const topHtml = `
      <div class="kpi-block">
        <div class="player-fdr-head"><strong>Top scorers</strong></div>
        <ul class="club-top-list">
          ${
            top.length
              ? top
                  .map(
                    (p) => `
            <li class="club-top-row avail-${p.availability || "ok"}">
              <span class="club-top-name">${p.name} <em class="muted">${p.position}</em></span>
              <span class="club-top-pts">${Math.round(Number(p.points) || 0)}</span>
              <span class="avail-text-${p.availability === "ok" ? "ok" : p.availability}">${p.status_label || "Available"}</span>
            </li>`
                  )
                  .join("")
              : `<li class="muted tiny">No player stats yet.</li>`
          }
        </ul>
      </div>`;
    const fxHtml = `
      <div class="player-fdr">
        <div class="player-fdr-head"><strong>Next 3 fixtures</strong></div>
        <div class="player-fdr-row">
          ${
            fixtures.length
              ? fixtures
                  .map(
                    (fx) => `
            <div class="fdr-chip fdr-pro fdr-${fx.difficulty}" title="${fx.opponent_name} (${fx.venue}) · FDR ${fx.difficulty}">
              <span class="fdr-opp">${fx.opponent} <em>${fx.venue}</em></span>
              <span class="fdr-gw">GW${fx.gw}</span>
            </div>`
                  )
                  .join("")
              : `<span class="muted tiny">No fixtures yet.</span>`
          }
        </div>
      </div>`;
    if (clubDetailBody) clubDetailBody.innerHTML = tableHtml + topHtml + fxHtml;
    if (clubDetailActions) {
      clubDetailActions.innerHTML = "";
      if (canChoose && typeof onChoose === "function") {
        const choose = document.createElement("button");
        choose.type = "button";
        choose.className = "btn";
        choose.textContent = "Choose club";
        choose.addEventListener("click", () => {
          onChoose(data);
          closeDrawer(clubDetail).then(() => closeDrawer(clubPicker));
        });
        clubDetailActions.appendChild(choose);
      }
    }
  }

  let activeCode = null;

  function openClubDetail(code, opts = {}) {
    const clubDetail = document.getElementById("clubDetail");
    if (!clubDetail || !code) return;
    const clubDetailBody = document.getElementById("clubDetailBody");
    const clubDetailActions = document.getElementById("clubDetailActions");
    const clubDetailBadge = document.getElementById("clubDetailBadge");
    const clubDetailName = document.getElementById("clubDetailName");
    const clubDetailSub = document.getElementById("clubDetailSub");
    const clubDetailEyebrow = document.getElementById("clubDetailEyebrow");

    activeCode = code;
    if (clubDetailEyebrow) clubDetailEyebrow.textContent = "Technical Director";
    if (clubDetailName) clubDetailName.textContent = code;
    if (clubDetailSub) clubDetailSub.textContent = "Loading…";
    if (clubDetailBadge) {
      clubDetailBadge.hidden = true;
      clubDetailBadge.removeAttribute("src");
    }
    if (clubDetailBody) {
      clubDetailBody.innerHTML = `<p class="muted tiny">Loading club profile…</p>`;
    }
    if (clubDetailActions) clubDetailActions.innerHTML = "";
    if (clubDetail.parentElement !== document.body) {
      document.body.appendChild(clubDetail);
    }
    clubDetail.hidden = false;
    fetch(`/api/clubs/${encodeURIComponent(code)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((data) => {
        if (activeCode !== code) return;
        if (data.error) throw new Error(data.error);
        paintClubDetail(data, opts);
      })
      .catch(() => {
        if (activeCode !== code) return;
        if (clubDetailBody) {
          clubDetailBody.innerHTML = `<p class="muted tiny">Couldn’t load this club.</p>`;
        }
      });
  }

  function bindClubDetailChrome() {
    const clubDetail = document.getElementById("clubDetail");
    const closeClubDetailBtn = document.getElementById("closeClubDetail");
    if (closeClubDetailBtn && !closeClubDetailBtn.dataset.ffBound) {
      closeClubDetailBtn.dataset.ffBound = "1";
      closeClubDetailBtn.addEventListener("click", () => closeDrawer(clubDetail));
    }
    if (clubDetail && !clubDetail.dataset.ffBound) {
      clubDetail.dataset.ffBound = "1";
      clubDetail.addEventListener("click", (e) => {
        if (e.target === clubDetail) closeDrawer(clubDetail);
      });
    }
  }

  window.__ffOpenClubDetail = openClubDetail;
  window.__ffBindClubDetail = bindClubDetailChrome;
  window.__ffCloseClubDrawer = closeDrawer;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindClubDetailChrome);
  } else {
    bindClubDetailChrome();
  }
})();
