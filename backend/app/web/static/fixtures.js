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
  /** @type {Record<string, { homeBadge?: string, awayBadge?: string, homeName?: string, awayName?: string, homeCode?: string, awayCode?: string }>} */
  const FIXTURE_META = {};

  function isDesktop() {
    return Boolean(DESK_MQ && DESK_MQ.matches);
  }

  function rememberFixtureMeta(m) {
    if (!m || m.id == null) return;
    FIXTURE_META[String(m.id)] = {
      homeBadge: m.home?.badge || "",
      awayBadge: m.away?.badge || "",
      homeName: m.home?.name || "",
      awayName: m.away?.name || "",
      homeCode: m.home?.code || "",
      awayCode: m.away?.code || "",
    };
  }

  function mergeDetailBadges(data) {
    const meta = FIXTURE_META[String(data.id)] || {};
    const home = { ...(data.home || {}) };
    const away = { ...(data.away || {}) };
    if (!home.badge && meta.homeBadge) home.badge = meta.homeBadge;
    if (!away.badge && meta.awayBadge) away.badge = meta.awayBadge;
    if (!home.name && meta.homeName) home.name = meta.homeName;
    if (!away.name && meta.awayName) away.name = meta.awayName;
    if (!home.code && meta.homeCode) home.code = meta.homeCode;
    if (!away.code && meta.awayCode) away.code = meta.awayCode;
    // Last resort: pull badge URLs from the selected list card
    if ((!home.badge || !away.badge) && list) {
      const btn = list.querySelector(`[data-fixture-id="${data.id}"]`);
      if (btn) {
        const imgs = btn.querySelectorAll(".fx-badge");
        if (!home.badge) {
          home.badge = btn.getAttribute("data-home-badge") || imgs[0]?.src || "";
        }
        if (!away.badge) {
          away.badge = btn.getAttribute("data-away-badge") || imgs[1]?.src || "";
        }
      }
    }
    return { ...data, home, away };
  }

  /** Date + Mx / US (ET) / VZ local kickoff times for the group. */
  function kickoffParts(iso) {
    if (!iso) return null;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    const date = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Mexico_City",
      weekday: "short",
      month: "short",
      day: "numeric",
    })
      .format(d)
      .replace(",", "");
    const timeOpts = { hour: "2-digit", minute: "2-digit", hour12: false };
    const mx = new Intl.DateTimeFormat("en-GB", { timeZone: "America/Mexico_City", ...timeOpts }).format(d);
    const us = new Intl.DateTimeFormat("en-GB", { timeZone: "America/New_York", ...timeOpts }).format(d);
    const vz = new Intl.DateTimeFormat("en-GB", { timeZone: "America/Caracas", ...timeOpts }).format(d);
    return { date, mx, us, vz, text: `${date}  Mx ${mx} | US ${us} | VZ ${vz}` };
  }

  function formatKickoff(iso) {
    const p = kickoffParts(iso);
    return p ? p.text : iso ? String(iso) : "TBC";
  }

  function formatKickoffHtml(iso) {
    const p = kickoffParts(iso);
    if (!p) return `<span class="fx-status">TBC</span>`;
    return `<span class="fx-status">
      <span class="fx-ko-date">${p.date}</span>
      <span class="fx-ko-zones"><span class="fx-ko-z">Mx ${p.mx}</span><span class="fx-ko-bar" aria-hidden="true">|</span><span class="fx-ko-z">US ${p.us}</span><span class="fx-ko-bar" aria-hidden="true">|</span><span class="fx-ko-z">VZ ${p.vz}</span></span>
    </span>`;
  }

  function fixtureTopHtml(m) {
    const ko = formatKickoffHtml(m.kickoff);
    if (m.status === "live") {
      return `<span class="fx-status-row"><em class="live-dot">LIVE</em>${ko}</span>`;
    }
    if (m.status === "finished") {
      return `<span class="fx-status-row"><span class="fx-ft-label">Full time</span>${ko}</span>`;
    }
    return ko;
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

  function fmtMatchKpi(v) {
    if (v == null || v === "") return "—";
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return Number.isInteger(n) ? String(n) : n.toFixed(1);
  }

  function myPlayersBlock(players, heading) {
    if (!players || !players.length) return "";
    const rows = players
      .map((p) => {
        const avail = p.availability || "ok";
        return `<tr class="avail-${avail}">
          <td class="fx-xi-name"><span class="fx-xi-player">${p.name || "—"}</span><span class="fx-xi-pos">${p.position || ""}</span></td>
          <td>${fmtMatchKpi(p.goals)}</td>
          <td>${fmtMatchKpi(p.assists)}</td>
          <td>${fmtMatchKpi(p.clean_sheets)}</td>
          <td>${fmtMatchKpi(p.points)}</td>
        </tr>`;
      })
      .join("");
    return `<div class="fx-detail-side fx-xi-table-wrap">
      <h4>${heading}</h4>
      <div class="fx-xi-scroll">
        <table class="fx-xi-table">
          <thead>
            <tr>
              <th scope="col">Player</th>
              <th scope="col">G</th>
              <th scope="col">A</th>
              <th scope="col">CS</th>
              <th scope="col">Pts</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;
  }

  function newsCardHtml(card) {
    if (!card) return "";
    const photo = card.photo
      ? `<img class="fx-news-photo" src="${card.photo}" alt="" width="56" height="56" loading="lazy" decoding="async" />`
      : `<span class="fx-news-photo is-empty" aria-hidden="true"></span>`;
    return `<article class="fx-news-card avail-${card.availability || "ok"}">
      ${photo}
      <div class="fx-news-copy">
        <p class="fx-news-kind">${card.kind || "Team news"}</p>
        <h5 class="fx-news-title">${card.title || card.player || "Update"}</h5>
        <p class="fx-news-body">${card.body || ""}</p>
      </div>
    </article>`;
  }

  function teamNewsColumn(cards, heading) {
    const list = (cards || []).map(newsCardHtml).join("");
    return `<div class="fx-detail-side fx-news-side">
      <h4>${heading}</h4>
      ${list || `<p class="muted tiny">No fresh team news.</p>`}
    </div>`;
  }

  function previewBlock(data) {
    const preview = data.preview;
    if (!preview || !(preview.body || preview.title)) return "";
    const homeBadge = preview.image_home
      ? `<img src="${preview.image_home}" alt="" width="40" height="40" />`
      : "";
    const awayBadge = preview.image_away
      ? `<img src="${preview.image_away}" alt="" width="40" height="40" />`
      : "";
    return `<div class="fx-preview-card">
      <div class="fx-preview-media" aria-hidden="true">${homeBadge}<span>vs</span>${awayBadge}</div>
      <div class="fx-preview-copy">
        <h5>${preview.title || "Match preview"}</h5>
        <p>${preview.body || ""}</p>
      </div>
    </div>`;
  }

  function sumSide(rows) {
    return (rows || []).reduce((n, r) => n + Number(r.value || 0), 0);
  }

  function teamTotals(data, side) {
    return {
      goals: sumSide(data.goals?.[side]),
      assists: sumSide(data.assists?.[side]),
      yellow: sumSide(data.yellow_cards?.[side]),
      red: sumSide(data.red_cards?.[side]),
      saves: sumSide(data.saves?.[side]),
      penSaved: sumSide(data.penalties_saved?.[side]),
      penMissed: sumSide(data.penalties_missed?.[side]),
      ownGoals: sumSide(data.own_goals?.[side]),
    };
  }

  function matchStatsCompareHtml(data, status) {
    const home = teamTotals(data, "home");
    const away = teamTotals(data, "away");
    const homeName = data.home?.name || data.home?.code || "Home";
    const awayName = data.away?.name || data.away?.code || "Away";
    const team = data.team_stats || {};
    const rows = [
      ["Possession", team.possession?.home, team.possession?.away, true],
      ["Shots on target", team.shots_on_target?.home, team.shots_on_target?.away, true],
      ["Goal attempts", team.chances_created?.home, team.chances_created?.away, true],
      ["Passes completed", team.passes_accurate?.home, team.passes_accurate?.away, true],
      ["Duels won", team.duels_won?.home, team.duels_won?.away, true],
      ["Fouls", team.fouls?.home, team.fouls?.away, true],
      ["Goals", home.goals, away.goals, false],
      ["Assists", home.assists, away.assists, false],
      ["Yellow cards", home.yellow, away.yellow, false],
      ["Red cards", home.red, away.red, false],
      ["Saves", home.saves, away.saves, false],
    ];
    const upcoming = status === "upcoming";
    const body = rows
      .map(([label, h, a, isAdvanced]) => {
        // Advanced PulseLive rows: show values whenever present (don't hide
        // behind FPL "upcoming" if Opta already published possession/SOT).
        const hideH = isAdvanced ? h == null || h === "" : upcoming || h == null || h === "";
        const hideA = isAdvanced ? a == null || a === "" : upcoming || a == null || a === "";
        const hv = hideH ? "—" : h;
        const av = hideA ? "—" : a;
        const hn = Number(String(h).replace("%", ""));
        const an = Number(String(a).replace("%", ""));
        const numeric = Number.isFinite(hn) && Number.isFinite(an);
        const hWin = !hideH && !hideA && numeric && hn > an;
        const aWin = !hideH && !hideA && numeric && an > hn;
        return `<tr>
          <td class="fx-stat-home ${hWin ? "is-lead" : ""}">${hv}</td>
          <th scope="row">${label}</th>
          <td class="fx-stat-away ${aWin ? "is-lead" : ""}">${av}</td>
        </tr>`;
      })
      .join("");
    // Advanced rows (possession / SOT / passes) come from PulseLive stats/match
    // when the match has published Opta team stats; otherwise show a short note.
    const advancedNote = data.team_stats
      ? ""
      : `<p class="muted tiny fx-stats-note">Possession &amp; shots stats unavailable this season.</p>`;
    return `<section class="fx-detail-section fx-stats-section" data-fx-team-stats>
      <h3>${status === "live" ? "Live stats" : "Match stats"}</h3>
      ${advancedNote}
      <table class="fx-stat-table">
        <thead>
          <tr>
            <th class="fx-stat-home">${homeName}</th>
            <th scope="col"></th>
            <th class="fx-stat-away">${awayName}</th>
          </tr>
        </thead>
        <tbody>${body}</tbody>
      </table>
    </section>`;
  }

  function newsSectionHtml(data, { loading } = {}) {
    if (loading) {
      return `<section class="fx-detail-section fx-news-section" data-fx-news>
      <h3>News</h3>
      <p class="muted tiny fx-news-loading">Loading team news…</p>
    </section>`;
    }
    const homeCode = data.home?.code || "";
    const awayCode = data.away?.code || "";
    const homeNews = data.team_news?.home || [];
    const awayNews = data.team_news?.away || [];
    return `<section class="fx-detail-section fx-news-section" data-fx-news>
      <h3>News</h3>
      ${previewBlock(data)}
      <div class="fx-detail-squad fx-news-grid">
        ${teamNewsColumn(homeNews, data.home?.name || homeCode)}
        ${teamNewsColumn(awayNews, data.away?.name || awayCode)}
      </div>
    </section>`;
  }

  function detailHtml(data, score, { newsLoading } = {}) {
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
      ? `<img class="fx-badge fx-badge-detail" src="${data.home.badge}" alt="${data.home.name || homeCode}" width="96" height="96" decoding="async" />`
      : `<span class="fx-badge-fallback" aria-label="${homeCode}">${homeCode}</span>`;
    const awayBadge = data.away.badge
      ? `<img class="fx-badge fx-badge-detail" src="${data.away.badge}" alt="${data.away.name || awayCode}" width="96" height="96" decoding="async" />`
      : `<span class="fx-badge-fallback" aria-label="${awayCode}">${awayCode}</span>`;

    const status = data.status || "upcoming";
    const kick = formatKickoff(data.kickoff);
    const clockBit = data.clock ? ` · ${data.clock}` : "";
    const venueBit =
      data.preview?.venue
        ? ` · ${data.preview.venue}${data.preview.city ? `, ${data.preview.city}` : ""}`
        : "";
    const statusLine =
      status === "live"
        ? `<p class="fx-detail-status is-live" data-fx-status>Live${clockBit} · ${kick} · GW${data.gw}${venueBit}</p>`
        : status === "finished"
          ? `<p class="fx-detail-status" data-fx-status>Full time${clockBit} · ${kick} · GW${data.gw}${venueBit}</p>`
          : `<p class="fx-detail-status" data-fx-status>Upcoming · ${kick} · GW${data.gw}${venueBit}</p>`;

    const watchBlock = matchStatsCompareHtml(data, status);

    const squadBlock =
      homeMine.length || awayMine.length
        ? `<section class="fx-detail-section fx-xi-section">
            <h3>In your XI</h3>
            <div class="fx-detail-squad">
              ${myPlayersBlock(homeMine, data.home.name || homeCode)}
              ${myPlayersBlock(awayMine, data.away.name || awayCode)}
            </div>
          </section>`
        : `<section class="fx-detail-section fx-xi-section">
            <h3>In your XI</h3>
            <p class="muted tiny">None of your squad are in this match.</p>
          </section>`;

    const newsBlock = newsSectionHtml(data, { loading: Boolean(newsLoading) });

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
        <div class="match-side">
          ${homeBadge}
          <strong class="match-club-name">${data.home.name || homeCode}</strong>
        </div>
        <div class="match-score">
          <span class="match-score-nums">${score}</span>
          ${data.clock ? `<span class="fx-match-clock">${data.clock}</span>` : ""}
        </div>
        <div class="match-side">
          ${awayBadge}
          <strong class="match-club-name">${data.away.name || awayCode}</strong>
        </div>
      </div>
      ${statusLine}
      ${watchBlock}
      ${squadBlock}
      ${newsBlock}
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

  function activeDetailBody() {
    if (isDesktop() && deskBody && (!matchDetail || matchDetail.hidden)) return deskBody;
    return matchBody;
  }

  function renderMatchDetail(raw, { newsLoading } = {}) {
    const data = mergeDetailBadges(raw || {});
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
    const body = detailHtml(data, score, { newsLoading });

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

  function applyMatchPreview(base, enrich) {
    if (!enrich || enrich.error) return;
    const merged = mergeDetailBadges({
      ...base,
      team_news: enrich.team_news,
      preview: enrich.preview,
      pulse: enrich.pulse,
      team_stats: enrich.team_stats != null ? enrich.team_stats : base.team_stats,
      team_stats_status: enrich.team_stats_status || base.team_stats_status,
    });
    const root = activeDetailBody();
    if (!root) return;
    const news = root.querySelector("[data-fx-news]");
    if (news) news.outerHTML = newsSectionHtml(merged, { loading: false });
    const stats = root.querySelector("[data-fx-team-stats]");
    if (stats && (enrich.team_stats != null || enrich.team_stats_status)) {
      stats.outerHTML = matchStatsCompareHtml(merged, merged.status || "upcoming");
    }
    const statusEl = root.querySelector("[data-fx-status]");
    if (statusEl && merged.preview?.venue) {
      const kick = formatKickoff(merged.kickoff);
      const venueBit = ` · ${merged.preview.venue}${merged.preview.city ? `, ${merged.preview.city}` : ""}`;
      const status = merged.status || "upcoming";
      const label =
        status === "live" ? "Live" : status === "finished" ? "Full time" : "Upcoming";
      statusEl.textContent = `${label} · ${kick} · GW${merged.gw}${venueBit}`;
    }
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
    const reqId = String(id);
    fetch(`/api/fixtures/${id}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((data) => {
        if (data.error) throw new Error(data.error);
        if (selectedId !== reqId) return null;
        renderMatchDetail(data, { newsLoading: true });
        return data;
      })
      .then((data) => {
        if (!data) return;
        return fetch(`/api/fixtures/${id}/preview`)
          .then((r) => (r.ok ? r.json() : Promise.reject()))
          .then((enrich) => {
            if (selectedId !== reqId) return;
            applyMatchPreview(data, enrich);
          })
          .catch(() => {
            if (selectedId !== reqId) return;
            applyMatchPreview(data, {
              team_news: { home: [], away: [] },
              preview: null,
              pulse: null,
            });
          });
      })
      .catch(() => {
        if (selectedId === reqId) renderMatchError();
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
    rows.forEach(rememberFixtureMeta);
    if (!rows.length) {
      list.innerHTML = `<li class="empty-pick">No fixtures for this GW.</li>`;
      return;
    }
    list.innerHTML = rows
      .map((m) => {
        const scored = m.home.score != null && m.away.score != null;
        const top = fixtureTopHtml(m);
        const scoreInner = scored
          ? `<span class="fx-score-num">${m.home.score}</span><span class="fx-score-sep">–</span><span class="fx-score-num">${m.away.score}</span>`
          : `<span class="fx-score-num fx-score-empty">-</span><span class="fx-score-sep">–</span><span class="fx-score-num fx-score-empty">-</span>`;
        const scoreBlock = `<span class="fx-score-nums-row">${scoreInner}</span>${m.clock ? `<span class="fx-match-clock">${m.clock}</span>` : ""}`;
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
          <button type="button" class="fx-card status-${m.status}${hasMine ? " has-mine" : ""}${selected}" data-fixture-id="${m.id}" data-home-badge="${m.home.badge || ""}" data-away-badge="${m.away.badge || ""}">
            <div class="fx-card-top">${top}</div>
            <div class="fx-card-match">
              <div class="fx-club" title="Home">
                ${homeBadge}
                <strong class="fx-club-code">${m.home.code || ""}</strong>
                <span class="fx-club-name">${m.home.name || ""}</span>
                <span class="fx-ha-tag">Home</span>
              </div>
              <div class="fx-score-block" aria-label="Score">${scoreBlock}</div>
              <div class="fx-club away" title="Away">
                ${awayBadge}
                <strong class="fx-club-code">${m.away.code || ""}</strong>
                <span class="fx-club-name">${m.away.name || ""}</span>
                <span class="fx-ha-tag">Away</span>
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
      .then((data) => {
        renderList(data.fixtures || []);
        // Keep open match sheet fresh (score/clock + possession/SOT via preview).
        if (!selectedId) return;
        const reqId = String(selectedId);
        fetch(`/api/fixtures/${reqId}`)
          .then((r) => (r.ok ? r.json() : Promise.reject()))
          .then((detail) => {
            if (selectedId !== reqId || !detail || detail.error) return;
            const root = activeDetailBody();
            if (!root) return;
            const scoreEl = root.querySelector(".match-score-nums");
            if (scoreEl) {
              const hs = detail.home?.score;
              const as_ = detail.away?.score;
              if (hs != null && as_ != null) scoreEl.textContent = `${hs}–${as_}`;
            }
            const clock = root.querySelector(".fx-match-clock");
            if (clock && detail.clock) {
              clock.textContent = detail.clock;
            } else if (detail.clock) {
              const scoreWrap = root.querySelector(".match-score");
              if (scoreWrap && !root.querySelector(".fx-match-clock")) {
                const span = document.createElement("span");
                span.className = "fx-match-clock";
                span.textContent = detail.clock;
                scoreWrap.appendChild(span);
              }
            }
            // Status can flip upcoming → live without a full re-open.
            const statusEl = root.querySelector("[data-fx-status]");
            if (statusEl && detail.status) {
              const kick = formatKickoff(detail.kickoff);
              const clockBit = detail.clock ? ` · ${detail.clock}` : "";
              const st = detail.status;
              const label =
                st === "live" ? "Live" : st === "finished" ? "Full time" : "Upcoming";
              statusEl.textContent = `${label}${clockBit} · ${kick} · GW${detail.gw}`;
              statusEl.classList.toggle("is-live", st === "live");
            }
            // team_stats live on /preview (fast detail path returns null).
            return fetch(`/api/fixtures/${reqId}/preview`)
              .then((r) => (r.ok ? r.json() : Promise.reject()))
              .then((enrich) => {
                if (selectedId !== reqId) return;
                applyMatchPreview(detail, enrich);
              })
              .catch(() => {});
          })
          .catch(() => {});
      })
      .catch(() => {});
  }

  // Seed badge/name cache from the SSR list cards
  if (list) {
    list.querySelectorAll(".fx-card[data-fixture-id]").forEach((btn) => {
      const id = btn.getAttribute("data-fixture-id");
      const imgs = btn.querySelectorAll(".fx-badge");
      const codes = btn.querySelectorAll(".fx-club-code");
      const names = btn.querySelectorAll(".fx-club-name");
      FIXTURE_META[String(id)] = {
        homeBadge: btn.getAttribute("data-home-badge") || imgs[0]?.getAttribute("src") || "",
        awayBadge: btn.getAttribute("data-away-badge") || imgs[1]?.getAttribute("src") || "",
        homeCode: codes[0]?.textContent?.trim() || "",
        awayCode: codes[1]?.textContent?.trim() || "",
        homeName: names[0]?.textContent?.trim() || "",
        awayName: names[1]?.textContent?.trim() || "",
      };
    });
  }

  bindRows(list);
  function closeMatchDetail() {
    if (!matchDetail) return;
    if (typeof window.__ffCloseDrawer === "function") {
      window.__ffCloseDrawer(matchDetail);
    } else {
      matchDetail.hidden = true;
    }
  }
  if (closeMatch) closeMatch.addEventListener("click", closeMatchDetail);
  if (matchDetail) {
    matchDetail.addEventListener("click", (e) => {
      if (e.target === matchDetail) closeMatchDetail();
    });
  }
  const onMq = () => {
    if (isDesktop() && matchDetail) matchDetail.hidden = true;
  };
  if (DESK_MQ && typeof DESK_MQ.addEventListener === "function") {
    DESK_MQ.addEventListener("change", onMq);
  }

  // Live poll while any match may be in progress
  let pollTimer = null;
  if (BOOT.poll) {
    pollTimer = setInterval(refreshQuiet, 45000);
  }
  window.__ffTeardown = () => {
    if (pollTimer) clearInterval(pollTimer);
    if (DESK_MQ && typeof DESK_MQ.removeEventListener === "function") {
      DESK_MQ.removeEventListener("change", onMq);
    }
    document.querySelectorAll("body > .drawer").forEach((el) => el.remove());
  };
})();
