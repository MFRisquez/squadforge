(() => {
  const OWNED = JSON.parse(document.getElementById("ownedData").textContent);
  const INITIAL = JSON.parse(document.getElementById("initialLineup").textContent);
  const byId = Object.fromEntries(OWNED.map((p) => [p.id, p]));
  const BAND = { GK: [1, 1], DEF: [3, 5], MID: [3, 5], ATT: [1, 3] };
  const POINTS = INITIAL.points || {};
  const GW = INITIAL.gw || null;

  let starterIds = new Set(INITIAL.starters || []);
  let captainId = INITIAL.captain || [...starterIds][0] || null;
  let viceId = INITIAL.vice || null;
  const LOCKED = Boolean(INITIAL.locked);
  if (!viceId || viceId === captainId) {
    viceId = [...starterIds].find((id) => id !== captainId) || null;
  }

  const pitch = document.getElementById("pitch");
  const bench = document.getElementById("bench");
  const formationLabel = document.getElementById("formationLabel");
  const hiddenFields = document.getElementById("hiddenFields");
  const captainSelect = document.getElementById("captainSelect");
  const viceSelect = document.getElementById("viceSelect");
  const captainName = document.getElementById("captainName");
  const viceName = document.getElementById("viceName");
  const playerDetail = document.getElementById("playerDetail");
  const detailEyebrow = document.getElementById("detailEyebrow");
  const detailName = document.getElementById("detailName");
  const detailBody = document.getElementById("detailBody");
  const detailActions = document.getElementById("detailActions");
  const closeDetailBtn = document.getElementById("closeDetail");

  let detailPlayer = null;

  function counts() {
    const c = { GK: 0, DEF: 0, MID: 0, ATT: 0 };
    starterIds.forEach((id) => {
      const p = byId[id];
      if (p) c[p.position] += 1;
    });
    return c;
  }

  function canStart(player) {
    if (starterIds.has(player.id)) return true;
    if (starterIds.size >= 11) return false;
    const c = counts();
    const [, hi] = BAND[player.position];
    if (c[player.position] >= hi) return false;
    if (player.position === "GK" && c.GK >= 1) return false;
    return true;
  }

  function setCaptain(id) {
    if (!starterIds.has(id)) return;
    if (id === viceId) viceId = captainId;
    captainId = id;
    render();
  }

  function setVice(id) {
    if (!starterIds.has(id)) return;
    if (id === captainId) captainId = viceId;
    viceId = id;
    render();
  }

  function syncHidden() {
    hiddenFields.innerHTML = "";
    starterIds.forEach((id) => {
      const a = document.createElement("input");
      a.type = "hidden";
      a.name = "starter_id";
      a.value = String(id);
      hiddenFields.appendChild(a);
    });
    const c = document.createElement("input");
    c.type = "hidden";
    c.name = "captain_id";
    c.value = String(captainId || "");
    hiddenFields.appendChild(c);
    const v = document.createElement("input");
    v.type = "hidden";
    v.name = "vice_id";
    v.value = String(viceId || "");
    hiddenFields.appendChild(v);
  }

  function fillSelects() {
    if (!captainSelect || captainSelect.hidden) return;
    const starters = OWNED.filter((p) => starterIds.has(p.id));
    captainSelect.innerHTML = "";
    viceSelect.innerHTML = "";
    if (!starters.length) {
      captainSelect.innerHTML = `<option value="">Add starters first</option>`;
      viceSelect.innerHTML = `<option value="">Add starters first</option>`;
      captainName.textContent = "—";
      viceName.textContent = "—";
      return;
    }
    starters.forEach((p) => {
      const optC = document.createElement("option");
      optC.value = String(p.id);
      optC.textContent = `${p.name} (${p.position})`;
      if (p.id === captainId) optC.selected = true;
      captainSelect.appendChild(optC);

      const optV = document.createElement("option");
      optV.value = String(p.id);
      optV.textContent = `${p.name} (${p.position})`;
      if (p.id === viceId) optV.selected = true;
      viceSelect.appendChild(optV);
    });
    if (!captainId || !starterIds.has(captainId)) {
      captainId = starters[0].id;
      captainSelect.value = String(captainId);
    }
    if (!viceId || !starterIds.has(viceId) || viceId === captainId) {
      viceId = starters.find((p) => p.id !== captainId)?.id || null;
      if (viceId) viceSelect.value = String(viceId);
    }
    const cap = byId[captainId];
    const vice = byId[viceId];
    captainName.textContent = cap ? `${cap.name} (×2)` : "—";
    viceName.textContent = vice ? vice.name : "—";
  }

  function closeDetail() {
    if (!playerDetail) return;
    playerDetail.hidden = true;
    detailPlayer = null;
  }

  function toggleRole(player) {
    if (LOCKED) return;
    if (starterIds.has(player.id)) {
      starterIds.delete(player.id);
      if (captainId === player.id) captainId = [...starterIds][0] || null;
      if (viceId === player.id) {
        viceId = [...starterIds].find((id) => id !== captainId) || null;
      }
    } else if (canStart(player)) {
      starterIds.add(player.id);
      if (!captainId) captainId = player.id;
      else if (!viceId || viceId === captainId) viceId = player.id;
    } else {
      alert("That would break formation limits (1 GK, DEF 3–5, MID 3–5, ATT 1–3, 11 total).");
      return;
    }
    closeDetail();
    render();
  }

  function openDetail(player) {
    detailPlayer = player;
    const onBench = !starterIds.has(player.id);
    const pts = POINTS[String(player.id)];
    detailEyebrow.textContent = LOCKED ? `Match · GW${GW || ""}` : `Lineup · ${player.position}`;
    detailName.textContent = player.name;
    detailBody.innerHTML = `
      <div class="player-detail-hero">
        <div class="kit-portrait">
          <img class="kit-shirt" src="${player.shirt || ""}" alt="" width="66" height="87" />
          ${player.photo ? `<img class="kit-face" src="${player.photo}" alt="" width="56" height="56" loading="lazy" />` : ""}
        </div>
        <div class="meta">
          <strong>${player.team}</strong>
          <span class="muted">${player.position} · £${Number(player.price).toFixed(1)}m</span>
          <span class="role-pill ${onBench ? "is-bench" : "is-xi"}">${onBench ? "Bench" : "Starting XI"}</span>
          ${LOCKED && pts != null ? `<strong class="match-pts">${Number(pts).toFixed(0)} pts</strong>` : ""}
        </div>
      </div>
      <div class="kpi-block">
        <div class="player-fdr-head">
          <strong>${LOCKED ? "This gameweek" : "Match KPIs"}</strong>
          <span class="muted tiny">${LOCKED ? "After kickoff" : "Unlock after deadline"}</span>
        </div>
        <div class="kpi-grid" id="detailKpis">
          <span class="muted tiny">${LOCKED ? "Loading match stats…" : "Scores appear here once the GW is locked."}</span>
        </div>
      </div>
    `;
    detailActions.innerHTML = "";
    if (!LOCKED) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn";
      btn.textContent = onBench ? "Move to starting XI" : "Move to bench";
      btn.addEventListener("click", () => toggleRole(player));
      detailActions.appendChild(btn);
      const squad = document.createElement("a");
      squad.className = "btn ghost";
      squad.href = "/team";
      squad.textContent = "Season stats on Squad";
      detailActions.appendChild(squad);
    }
    playerDetail.hidden = false;
    if (LOCKED) loadMatchProfile(player.id);
  }

  function loadMatchProfile(playerId) {
    const kpis = document.getElementById("detailKpis");
    const qs = GW ? `?mode=match&gw=${GW}` : `?mode=match`;
    fetch(`/api/players/${playerId}${qs}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((data) => {
        if (!detailPlayer || detailPlayer.id !== playerId) return;
        if (data.photo) {
          const portrait = detailBody.querySelector(".kit-portrait");
          if (portrait && !portrait.querySelector(".kit-face")) {
            const img = document.createElement("img");
            img.className = "kit-face";
            img.src = data.photo;
            img.width = 56;
            img.height = 56;
            portrait.appendChild(img);
          }
        }
        if (data.gw_points != null) {
          const meta = detailBody.querySelector(".meta");
          if (meta && !meta.querySelector(".match-pts")) {
            const s = document.createElement("strong");
            s.className = "match-pts";
            s.textContent = `${Number(data.gw_points).toFixed(0)} pts`;
            meta.appendChild(s);
          }
        }
        if (kpis) {
          const items = data.kpis || [];
          kpis.innerHTML = items.length
            ? items
                .map(
                  (k) => `
              <div class="kpi-cell">
                <span>${k.label}</span>
                <strong>${k.value}</strong>
              </div>`
                )
                .join("")
            : `<span class="muted tiny">No live events yet — tap Refresh live scores.</span>`;
        }
      })
      .catch(() => {
        if (kpis) kpis.innerHTML = `<span class="muted tiny">Couldn’t load match stats.</span>`;
      });
  }

  function shirtCard(player, onBench) {
    const wrap = document.createElement("div");
    wrap.className = "shirt-card";
    if (player.id === captainId && !onBench) wrap.classList.add("is-captain");
    if (player.id === viceId && !onBench) wrap.classList.add("is-vice");

    const main = document.createElement("button");
    main.type = "button";
    const avail = player.availability || "ok";
    main.className = "shirt filled jersey avail-" + avail;
    const flag = avail === "out" ? "OUT" : avail === "doubt" ? "DOUBT" : "";
    const pts = POINTS[String(player.id)];
    const ptsHtml =
      LOCKED && pts != null
        ? `<span class="shirt-pts">${Number(pts).toFixed(0)}</span>`
        : `<span class="shirt-price">£${player.price.toFixed(1)}</span>`;
    main.innerHTML = `
      <img class="jersey-img" src="${player.shirt || ""}" alt="${player.team} kit" width="66" height="87" loading="lazy" decoding="async" />
      ${ptsHtml}
      <span class="shirt-name">${player.name}</span>
      <span class="shirt-team">${player.team}${flag ? " · " + flag : ""}</span>
      <span class="shirt-action">${LOCKED ? "Tap for match KPIs" : onBench ? "Tap for options" : "Tap for options"}</span>
    `;
    if (player.news) main.title = player.news;
    main.addEventListener("click", () => openDetail(player));
    wrap.appendChild(main);

    if (!onBench && player.id === captainId) {
      const badge = document.createElement("span");
      badge.className = "role-badge role-c";
      badge.textContent = "C";
      badge.title = "Captain";
      wrap.appendChild(badge);
    }
    if (!onBench && player.id === viceId) {
      const badge = document.createElement("span");
      badge.className = "role-badge role-v";
      badge.textContent = "V";
      badge.title = "Vice-captain · receives ×2 if captain does not play";
      wrap.appendChild(badge);
    }

    return wrap;
  }

  function render() {
    const rows = {
      gk: pitch.querySelector('[data-row="gk"]'),
      def: pitch.querySelector('[data-row="def"]'),
      mid: pitch.querySelector('[data-row="mid"]'),
      att: pitch.querySelector('[data-row="att"]'),
    };
    Object.values(rows).forEach((el) => (el.innerHTML = ""));
    const starters = OWNED.filter((p) => starterIds.has(p.id));
    const byPos = { GK: [], DEF: [], MID: [], ATT: [] };
    starters.forEach((p) => byPos[p.position].push(p));
    byPos.GK.forEach((p) => rows.gk.appendChild(shirtCard(p, false)));
    byPos.DEF.forEach((p) => rows.def.appendChild(shirtCard(p, false)));
    byPos.MID.forEach((p) => rows.mid.appendChild(shirtCard(p, false)));
    byPos.ATT.forEach((p) => rows.att.appendChild(shirtCard(p, false)));

    bench.innerHTML = "";
    OWNED.filter((p) => !starterIds.has(p.id)).forEach((p) => bench.appendChild(shirtCard(p, true)));

    const c = counts();
    formationLabel.textContent = LOCKED
      ? `Formation ${c.DEF}-${c.MID}-${c.ATT} · locked`
      : `Formation ${c.DEF}-${c.MID}-${c.ATT} · ${starterIds.size}/11 starters`;
    fillSelects();
    syncHidden();
  }

  if (captainSelect) {
    captainSelect.addEventListener("change", () => {
      const id = Number(captainSelect.value);
      if (id) setCaptain(id);
    });
  }
  if (viceSelect) {
    viceSelect.addEventListener("change", () => {
      const id = Number(viceSelect.value);
      if (id) setVice(id);
    });
  }
  if (closeDetailBtn) closeDetailBtn.addEventListener("click", closeDetail);
  if (playerDetail) {
    playerDetail.addEventListener("click", (e) => {
      if (e.target === playerDetail) closeDetail();
    });
  }

  document.getElementById("lineupForm").addEventListener("submit", (e) => {
    if (LOCKED) {
      e.preventDefault();
      return;
    }
    const c = counts();
    if (starterIds.size !== 11) {
      e.preventDefault();
      alert("Need exactly 11 starters.");
      return;
    }
    for (const [pos, [lo, hi]] of Object.entries(BAND)) {
      if (c[pos] < lo || c[pos] > hi) {
        e.preventDefault();
        alert(`Need ${lo}–${hi} starting ${pos}.`);
        return;
      }
    }
    if (!captainId || !starterIds.has(captainId)) {
      e.preventDefault();
      alert("Choose a captain from the dropdown.");
      return;
    }
    if (!viceId || !starterIds.has(viceId) || viceId === captainId) {
      e.preventDefault();
      alert("Choose a different vice-captain from the dropdown.");
      return;
    }
    syncHidden();
  });

  render();
})();
