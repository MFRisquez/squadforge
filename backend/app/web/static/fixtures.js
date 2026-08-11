(() => {
  const bootEl = document.getElementById("fixturesBoot");
  const BOOT = bootEl ? JSON.parse(bootEl.textContent) : { gw: 1, poll: false };
  const list = document.getElementById("fixtureList");
  const meta = document.getElementById("fixturesMeta");
  const matchDetail = document.getElementById("matchDetail");
  const matchEyebrow = document.getElementById("matchEyebrow");
  const matchTitle = document.getElementById("matchTitle");
  const matchBody = document.getElementById("matchBody");
  const closeMatch = document.getElementById("closeMatch");
  const deskPanel = document.getElementById("fixtureDetailPanel");
  const deskEyebrow = document.getElementById("deskMatchEyebrow");
  const deskTitle = document.getElementById("deskMatchTitle");
  const deskBody = document.getElementById("deskMatchBody");
  const DESK_MQ = window.matchMedia("(min-width: 900px)");
  let selectedId = null;

  function isDesktop() {
    return Boolean(DESK_MQ && DESK_MQ.matches);
  }

  function formatKickoff(iso) {
    if (!iso) return "TBC";
    const m = String(iso).match(/T(\d{2}:\d{2})/);
    return m ? m[1] : iso;
  }

  function sideLines(rows, label) {
    if (!rows || !rows.length) return "";
    return rows
      .map((r) => {
        const mult = r.value > 1 ? ` ×${r.value}` : "";
        return `<li><span class="muted">${label}</span> <strong>${r.name}</strong>${mult}</li>`;
      })
      .join("");
  }

  function sideBlock(title, html) {
    return `<div>
      <h3>${title}</h3>
      <ul class="event-list">${html || "<li class='muted tiny'>—</li>"}</ul>
    </div>`;
  }

  function playerNewsList(players) {
    const lines = (players || [])
      .map((p) => {
        const news = (p.news || "").trim();
        if (!news) return "";
        const avail = p.availability && p.availability !== "ok" ? ` · ${p.availability}` : "";
        return `<li><strong>${p.name}</strong>${avail}: ${news}</li>`;
      })
      .filter(Boolean);
    return lines.length ? `<ul class="fx-detail-news">${lines.join("")}</ul>` : "";
  }

  function myPlayersBlock(players, heading) {
    if (!players || !players.length) return "";
    const chips = players
      .map((p) => `<span class="fx-mine-chip avail-${p.availability || "ok"}">${p.name}</span>`)
      .join("");
    const news = playerNewsList(players);
    return `<div class="fx-detail-side">
      <h4>${heading}</h4>
      <div class="fx-detail-chips">${chips}</div>
      ${news || `<p class="muted tiny">No injury/suspension notes.</p>`}
    </div>`;
  }

  function detailHtml(data, score) {
    const homeCode = data.home?.code || "";
    const awayCode = data.away?.code || "";
    const homeMine = data.my_players?.home || MY_BY_CLUB[homeCode] || [];
    const awayMine = data.my_players?.away || MY_BY_CLUB[awayCode] || [];

    const goalsHome = sideLines(data.goals?.home, "⚽");
    const goalsAway = sideLines(data.goals?.away, "⚽");
    const assistsHome = sideLines(data.assists?.home, "ⓐ");
    const assistsAway = sideLines(data.assists?.away, "ⓐ");
    const ogHome = sideLines(data.own_goals?.home, "OG");
    const ogAway = sideLines(data.own_goals?.away, "OG");
    const ycHome = sideLines(data.yellow_cards?.home, "YC");
    const ycAway = sideLines(data.yellow_cards?.away, "YC");
    const rcHome = sideLines(data.red_cards?.home, "RC");
    const rcAway = sideLines(data.red_cards?.away, "RC");
    const psHome = sideLines(data.penalties_saved?.home, "PS");
    const psAway = sideLines(data.penalties_saved?.away, "PS");
    const pmHome = sideLines(data.penalties_missed?.home, "PM");
    const pmAway = sideLines(data.penalties_missed?.away, "PM");
    const svHome = sideLines(data.saves?.home, "Sv");
    const svAway = sideLines(data.saves?.away, "Sv");

    const homeHtml = goalsHome + assistsHome + ogHome + ycHome + rcHome + psHome + pmHome + svHome;
    const awayHtml = goalsAway + assistsAway + ogAway + ycAway + rcAway + psAway + pmAway + svAway;
    const hasEvents = Boolean(homeHtml || awayHtml);
    const homeBadge = data.home.badge
      ? `<img class="fx-badge fx-badge-detail" src="${data.home.badge}" alt="${data.home.name || ""}" width="96" height="96" loading="lazy" />`
      : `<span class="fx-badge-fallback">${homeCode}</span>`;
    const awayBadge = data.away.badge
      ? `<img class="fx-badge fx-badge-detail" src="${data.away.badge}" alt="${data.away.name || ""}" width="96" height="96" loading="lazy" />`
      : `<span class="fx-badge-fallback">${awayCode}</span>`;

    const status = data.status || "upcoming";
    const kick = formatKickoff(data.kickoff);
    const statusLine =
      status === "live"
        ? `<p class="fx-detail-status is-live">Live · kickoff ${kick} UTC · GW${data.gw}</p>`
        : status === "finished"
          ? `<p class="fx-detail-status">Full time · kicked off ${kick} UTC · GW${data.gw}</p>`
          : `<p class="fx-detail-status">Upcoming · ${kick} UTC · GW${data.gw}</p>`;

    const watchBlock =
      status === "upcoming"
        ? `<section class="fx-detail-section">
            <h3>What you’ll see</h3>
            <p class="muted tiny">When the match starts, this panel updates with goals, assists, cards, penalties and saves. Refresh live to pull the latest FPL feed.</p>
          </section>`
        : status === "live"
          ? `<section class="fx-detail-section">
            <h3>In play</h3>
            <p class="muted tiny">Live feed: goals, assists, own goals, yellow/red cards, pens and saves. Tap Refresh live on the list if something looks stale.</p>
          </section>`
          : "";

    const squadBlock =
      homeMine.length || awayMine.length
        ? `<section class="fx-detail-section">
            <h3>${status === "upcoming" ? "Your players & news" : "Your players"}</h3>
            <div class="fx-detail-squad">
              ${myPlayersBlock(homeMine, data.home.name || homeCode)}
              ${myPlayersBlock(awayMine, data.away.name || awayCode)}
            </div>
          </section>`
        : `<section class="fx-detail-section">
            <h3>Your players</h3>
            <p class="muted tiny">None of your squad are in this match.</p>
          </section>`;

    const actionBlock = hasEvents
      ? `<section class="fx-detail-section">
          <h3>${status === "finished" ? "Match action" : "Live action"}</h3>
          <div class="match-events">
            ${sideBlock(data.home.name || "Home", homeHtml)}
            ${sideBlock(data.away.name || "Away", awayHtml)}
          </div>
        </section>`
      : status === "upcoming"
        ? ""
        : `<section class="fx-detail-section">
            <h3>Match action</h3>
            <p class="muted tiny">No events yet — refresh while the match is live or after full time.</p>
          </section>`;

    return `
      <div class="match-scoreline match-scoreline-badges">
        <div class="match-club">
          ${homeBadge}
          <strong class="match-club-name">${data.home.name || homeCode}</strong>
        </div>
        <div class="match-score">${score}</div>
        <div class="match-club away">
          ${awayBadge}
          <strong class="match-club-name">${data.away.name || awayCode}</strong>
        </div>
      </div>
      ${statusLine}
      ${watchBlock}
      ${squadBlock}
      ${actionBlock}
    `;
  }

  function markSelected(id) {
    selectedId = id ? String(id) : null;
    if (!list) return;
    list.querySelectorAll(".fx-card").forEach((btn) => {
      btn.classList.toggle("is-selected", selectedId && btn.getAttribute("data-fixture-id") === selectedId);
    });
  }

  function renderMatchDetail(data) {
    const hs = data.home.score;
    const as_ = data.away.score;
    const score = hs != null && as_ != null ? `${hs}–${as_}` : "vs";
    const eyebrow =
      data.status === "live" ? "Live" : data.status === "finished" ? "Full time" : "Upcoming";
    const title =
      data.status === "live"
        ? "Match in play"
        : data.status === "finished"
          ? "Full time"
          : "Match preview";
    const body = detailHtml(data, score);

    if (isDesktop() && deskEyebrow && deskTitle && deskBody) {
      if (matchDetail) matchDetail.hidden = true;
      deskEyebrow.textContent = eyebrow;
      deskTitle.textContent = title;
      deskBody.innerHTML = body;
      return;
    }

    if (!matchEyebrow || !matchTitle || !matchBody || !matchDetail) return;
    matchEyebrow.textContent = eyebrow;
    matchTitle.textContent = title;
    matchBody.innerHTML = body;
    if (matchDetail.parentElement !== document.body) {
      document.body.appendChild(matchDetail);
    }
    matchDetail.hidden = false;
    matchDetail.scrollTop = 0;
  }

  function renderMatchError() {
    if (isDesktop() && deskEyebrow && deskTitle && deskBody) {
      if (matchDetail) matchDetail.hidden = true;
      deskEyebrow.textContent = "Match";
      deskTitle.textContent = "Unavailable";
      deskBody.innerHTML = `<p class="muted">Couldn’t load match detail.</p>`;
      return;
    }
    if (!matchEyebrow || !matchTitle || !matchBody || !matchDetail) return;
    matchEyebrow.textContent = "Match";
    matchTitle.textContent = "Unavailable";
    matchBody.innerHTML = `<p class="muted">Couldn’t load match detail.</p>`;
    if (matchDetail.parentElement !== document.body) {
      document.body.appendChild(matchDetail);
    }
    matchDetail.hidden = false;
  }

  function openMatch(id) {
    markSelected(id);
    fetch(`/api/fixtures/${id}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((data) => {
        if (data.error) throw new Error(data.error);
        renderMatchDetail(data);
      })
      .catch(() => renderMatchError());
  }

  function bindRows(root) {
    if (!root) return;
    root.querySelectorAll("[data-fixture-id]").forEach((btn) => {
      btn.addEventListener("click", () => openMatch(btn.getAttribute("data-fixture-id")));
    });
  }

  const MY_BY_CLUB = BOOT.myByClub || {};

  function attachSquad(fixtures) {
    return (fixtures || []).map((m) => {
      const homeCode = m.home?.code || "";
      const awayCode = m.away?.code || "";
      const homeMine = MY_BY_CLUB[homeCode] || m.my_players?.home || [];
      const awayMine = MY_BY_CLUB[awayCode] || m.my_players?.away || [];
      const news = [];
      [...homeMine, ...awayMine].forEach((p) => {
        const text = (p.news || "").trim();
        if (!text) return;
        const line = `${p.name}: ${text}`;
        if (!news.includes(line) && news.length < 3) news.push(line);
      });
      return {
        ...m,
        my_players: { home: homeMine, away: awayMine },
        news: m.news && m.news.length ? m.news : news,
      };
    });
  }

  function mineHtml(sideRows, _code, away) {
    if (!sideRows || !sideRows.length) return "";
    const chips = sideRows
      .map((p) => `<span class="fx-mine-chip avail-${p.availability || "ok"}">${p.name}</span>`)
      .join("");
    return `<p class="fx-mine-side${away ? " away" : ""}">${chips}</p>`;
  }

  function newsHtml(lines) {
    if (!lines || !lines.length) return "";
    return `<ul class="fx-news">${lines.map((l) => `<li>${l}</li>`).join("")}</ul>`;
  }

  function renderList(fixtures) {
    if (!list) return;
    const rows = attachSquad(fixtures);
    if (!rows.length) {
      list.innerHTML = `<li class="empty-pick">No fixtures for this GW.</li>`;
      return;
    }
    list.innerHTML = rows
      .map((m) => {
        const scored = m.home.score != null && m.away.score != null;
        const top =
          m.status === "live"
            ? `<em class="live-dot">LIVE</em>`
            : m.status === "finished"
              ? `<span class="fx-status">Full time</span>`
              : `<span class="fx-status">${formatKickoff(m.kickoff)} UTC</span>`;
        const scoreBlock = scored
          ? `<span class="fx-score-num">${m.home.score}</span><span class="fx-score-sep">–</span><span class="fx-score-num">${m.away.score}</span>`
          : `<span class="fx-vs">vs</span>`;
        const homeBadge = m.home.badge
          ? `<img class="fx-badge" src="${m.home.badge}" alt="" width="40" height="40" loading="lazy" />`
          : "";
        const awayBadge = m.away.badge
          ? `<img class="fx-badge" src="${m.away.badge}" alt="" width="40" height="40" loading="lazy" />`
          : "";
        const homeMine = m.my_players?.home || [];
        const awayMine = m.my_players?.away || [];
        const hasMine = homeMine.length || awayMine.length;
        const mineBlock = hasMine
          ? `<div class="fx-mine">${mineHtml(homeMine, m.home.code, false)}${mineHtml(awayMine, m.away.code, true)}</div>`
          : "";
        const selected = selectedId && String(m.id) === selectedId ? " is-selected" : "";
        return `<li>
          <button type="button" class="fx-card status-${m.status}${hasMine ? " has-mine" : ""}${selected}" data-fixture-id="${m.id}">
            <div class="fx-card-top">${top}</div>
            <div class="fx-card-match">
              <div class="fx-club">
                ${homeBadge}
                <strong>${m.home.code}</strong>
                <span class="fx-club-name">${m.home.name || ""}</span>
              </div>
              <div class="fx-score-block">${scoreBlock}</div>
              <div class="fx-club away">
                ${awayBadge}
                <strong>${m.away.code}</strong>
                <span class="fx-club-name">${m.away.name || ""}</span>
              </div>
            </div>
            ${mineBlock}
            ${newsHtml(m.news)}
          </button>
        </li>`;
      })
      .join("");
    bindRows(list);
    if (meta) meta.textContent = `${rows.length} matches · updated`;
  }

  function refreshQuiet() {
    fetch(`/api/fixtures/refresh?gw=${BOOT.gw}`, { method: "POST" })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((data) => renderList(data.fixtures || []))
      .catch(() => {});
  }

  bindRows(list);
  if (closeMatch) closeMatch.addEventListener("click", () => (matchDetail.hidden = true));
  if (matchDetail) {
    matchDetail.addEventListener("click", (e) => {
      if (e.target === matchDetail) matchDetail.hidden = true;
    });
  }
  if (DESK_MQ && typeof DESK_MQ.addEventListener === "function") {
    DESK_MQ.addEventListener("change", () => {
      if (isDesktop() && matchDetail) matchDetail.hidden = true;
    });
  }

  // Live poll while any match may be in progress
  if (BOOT.poll) {
    setInterval(refreshQuiet, 45000);
  }
})();
