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

  function renderMatchDetail(data) {
    matchEyebrow.textContent =
      data.status === "live" ? "Live" : data.status === "finished" ? "Full time" : "Upcoming";
    const hs = data.home.score;
    const as_ = data.away.score;
    const score =
      hs != null && as_ != null ? `${hs}–${as_}` : "vs";
    matchTitle.textContent = `${data.home.code} ${score} ${data.away.code}`;

    const goalsHome = sideLines(data.goals?.home, "⚽");
    const goalsAway = sideLines(data.goals?.away, "⚽");
    const assistsHome = sideLines(data.assists?.home, "ⓐ");
    const assistsAway = sideLines(data.assists?.away, "ⓐ");
    const ogHome = sideLines(data.own_goals?.home, "OG");
    const ogAway = sideLines(data.own_goals?.away, "OG");
    const homeHtml = goalsHome + assistsHome + ogHome;
    const awayHtml = goalsAway + assistsAway + ogAway;
    const hasEvents = Boolean(homeHtml || awayHtml);

    matchBody.innerHTML = `
      <div class="match-scoreline">
        <div>
          <strong>${data.home.name}</strong>
          <span class="muted">${data.home.code}</span>
        </div>
        <div class="match-score">${score}</div>
        <div class="away">
          <strong>${data.away.name}</strong>
          <span class="muted">${data.away.code}</span>
        </div>
      </div>
      ${
        hasEvents
          ? `<div class="match-events">
              <div>
                <h3>Home</h3>
                <ul class="event-list">${homeHtml || "<li class='muted tiny'>—</li>"}</ul>
              </div>
              <div>
                <h3>Away</h3>
                <ul class="event-list">${awayHtml || "<li class='muted tiny'>—</li>"}</ul>
              </div>
            </div>`
          : `<p class="muted">No goal or assist data yet — refresh while the match is live or finished.</p>`
      }
      <p class="muted tiny">Kickoff ${formatKickoff(data.kickoff)} · GW${data.gw}</p>
    `;
    if (matchDetail.parentElement !== document.body) {
      document.body.appendChild(matchDetail);
    }
    matchDetail.hidden = false;
    matchDetail.scrollTop = 0;
  }

  function openMatch(id) {
    fetch(`/api/fixtures/${id}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((data) => {
        if (data.error) throw new Error(data.error);
        renderMatchDetail(data);
      })
      .catch(() => {
        matchEyebrow.textContent = "Match";
        matchTitle.textContent = "Unavailable";
        matchBody.innerHTML = `<p class="muted">Couldn’t load match detail.</p>`;
        if (matchDetail.parentElement !== document.body) {
          document.body.appendChild(matchDetail);
        }
        matchDetail.hidden = false;
      });
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

  function mineHtml(sideRows, code, away) {
    if (!sideRows || !sideRows.length) return "";
    const chips = sideRows
      .map((p) => `<span class="fx-mine-chip avail-${p.availability || "ok"}">${p.name}</span>`)
      .join("");
    return `<p class="fx-mine-side${away ? " away" : ""}"><span class="fx-mine-label">${code}</span>${chips}</p>`;
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
        return `<li>
          <button type="button" class="fx-card status-${m.status}${hasMine ? " has-mine" : ""}" data-fixture-id="${m.id}">
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

  // Live poll while any match may be in progress
  if (BOOT.poll) {
    setInterval(refreshQuiet, 45000);
  }
})();
