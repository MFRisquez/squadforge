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
  const playerDetail = document.getElementById("playerDetail");
  const detailEyebrow = document.getElementById("detailEyebrow");
  const detailName = document.getElementById("detailName");
  const detailBody = document.getElementById("detailBody");
  const detailActions = document.getElementById("detailActions");
  const closeDetailBtn = document.getElementById("closeDetail");
  const xiHint = document.getElementById("xiHint");
  const swapBar = document.getElementById("swapBar");
  const swapHint = document.getElementById("swapHint");
  const cancelSwapBtn = document.getElementById("cancelSwap");

  let detailPlayer = null;
  /** @type {null | { id: number, side: "xi" | "bench" }} */
  let swapPending = null;

  function countsFrom(set) {
    const c = { GK: 0, DEF: 0, MID: 0, ATT: 0 };
    set.forEach((id) => {
      const p = byId[id];
      if (p) c[p.position] += 1;
    });
    return c;
  }

  function counts() {
    return countsFrom(starterIds);
  }

  function formationOk(set) {
    if (set.size !== 11) return false;
    const c = countsFrom(set);
    return (
      c.GK === 1 &&
      c.DEF >= 3 &&
      c.DEF <= 5 &&
      c.MID >= 3 &&
      c.MID <= 5 &&
      c.ATT >= 1 &&
      c.ATT <= 3
    );
  }

  function canSwap(outId, inId) {
    if (!starterIds.has(outId) || starterIds.has(inId)) return false;
    if (!byId[outId] || !byId[inId]) return false;
    const next = new Set(starterIds);
    next.delete(outId);
    next.add(inId);
    return formationOk(next);
  }

  function eligiblePartners(player) {
    const onBench = !starterIds.has(player.id);
    if (onBench) {
      return OWNED.filter((p) => starterIds.has(p.id) && canSwap(p.id, player.id));
    }
    return OWNED.filter((p) => !starterIds.has(p.id) && canSwap(player.id, p.id));
  }

  function ensureRoles() {
    const starters = [...starterIds];
    if (!starters.length) {
      captainId = null;
      viceId = null;
      return;
    }
    if (!captainId || !starterIds.has(captainId)) {
      captainId = starters[0];
    }
    if (!viceId || !starterIds.has(viceId) || viceId === captainId) {
      viceId = starters.find((id) => id !== captainId) || null;
    }
  }

  function setCaptain(id) {
    if (!starterIds.has(id)) return;
    if (id === viceId) viceId = captainId;
    captainId = id;
    ensureRoles();
    closeDetail();
    render();
  }

  function setVice(id) {
    if (!starterIds.has(id)) return;
    if (id === captainId) captainId = viceId;
    viceId = id;
    ensureRoles();
    closeDetail();
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

  function closeDetail() {
    if (!playerDetail) return;
    playerDetail.hidden = true;
    detailPlayer = null;
  }

  function clearSwap() {
    swapPending = null;
    render();
  }

  function beginSwap(player) {
    if (LOCKED) return;
    const partners = eligiblePartners(player);
    if (!partners.length) {
      alert(
        starterIds.has(player.id)
          ? "No legal bench swap for this player (formation limits)."
          : "No legal XI swap for this player (formation limits)."
      );
      return;
    }
    swapPending = {
      id: player.id,
      side: starterIds.has(player.id) ? "xi" : "bench",
    };
    closeDetail();
    render();
  }

  function applySwap(outId, inId) {
    if (!canSwap(outId, inId)) {
      alert("That swap would break formation (1 GK, DEF 3–5, MID 3–5, ATT 1–3).");
      return false;
    }
    starterIds.delete(outId);
    starterIds.add(inId);
    if (captainId === outId) captainId = inId;
    if (viceId === outId) {
      viceId = [...starterIds].find((id) => id !== captainId) || null;
    }
    ensureRoles();
    swapPending = null;
    return true;
  }

  function tryCompleteSwap(player) {
    if (!swapPending || LOCKED) return false;
    if (player.id === swapPending.id) {
      clearSwap();
      return true;
    }
    const pending = byId[swapPending.id];
    if (!pending) {
      clearSwap();
      return true;
    }
    const pendingOnXi = swapPending.side === "xi";
    const targetOnXi = starterIds.has(player.id);
    if (pendingOnXi === targetOnXi) {
      // Same side — retarget swap to this player
      beginSwap(player);
      return true;
    }
    const outId = pendingOnXi ? pending.id : player.id;
    const inId = pendingOnXi ? player.id : pending.id;
    if (!applySwap(outId, inId)) return true;
    closeDetail();
    render();
    return true;
  }

  function actionBtn(label, className, onClick) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = className;
    btn.textContent = label;
    btn.addEventListener("click", onClick);
    return btn;
  }

  function updateHints() {
    if (LOCKED) return;
    if (swapPending) {
      const p = byId[swapPending.id];
      const name = p ? p.name : "player";
      if (swapBar) swapBar.hidden = false;
      if (swapHint) {
        swapHint.textContent =
          swapPending.side === "xi"
            ? `${name} out — tap a bench player to come in`
            : `${name} in — tap an XI player to go out`;
      }
      if (xiHint) {
        xiHint.textContent =
          swapPending.side === "xi"
            ? "Choose who comes in from the bench (legal formations only)."
            : "Choose who drops to the bench from the XI.";
      }
      return;
    }
    if (swapBar) swapBar.hidden = true;
    if (xiHint) {
      xiHint.innerHTML =
        'Tap a player to set <strong>C</strong> / <strong>V</strong>, or swap XI ↔ bench. Transfers on <a href="/team">Squad</a>.';
    }
  }

  function openDetail(player) {
    if (!LOCKED && swapPending) {
      tryCompleteSwap(player);
      return;
    }
    detailPlayer = player;
    const onBench = !starterIds.has(player.id);
    const pts = POINTS[String(player.id)];
    const isCap = player.id === captainId && !onBench;
    const isVice = player.id === viceId && !onBench;
    const partners = LOCKED ? [] : eligiblePartners(player);
    detailEyebrow.textContent = LOCKED ? `Match · GW${GW || ""}` : `XI · ${player.position}`;
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
          ${isCap ? `<span class="role-pill is-c">Captain ×2</span>` : ""}
          ${isVice ? `<span class="role-pill is-v">Vice-captain</span>` : ""}
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
      if (!onBench) {
        const cvRow = document.createElement("div");
        cvRow.className = "cv-action-row";
        const cBtn = actionBtn(
          isCap ? "Captain ✓" : "Make captain",
          `btn cv-btn is-c${isCap ? " is-active" : ""}`,
          () => setCaptain(player.id)
        );
        if (isCap) cBtn.disabled = true;
        const vBtn = actionBtn(
          isVice ? "Vice ✓" : "Make vice",
          `btn cv-btn is-v${isVice ? " is-active" : ""}`,
          () => setVice(player.id)
        );
        if (isVice) vBtn.disabled = true;
        cvRow.appendChild(cBtn);
        cvRow.appendChild(vBtn);
        detailActions.appendChild(cvRow);
      }
      const swapBtn = actionBtn(
        onBench ? "Swap into XI" : "Swap to bench",
        "btn",
        () => beginSwap(player)
      );
      if (!partners.length) {
        swapBtn.disabled = true;
        swapBtn.title = "No legal partner for this formation";
      }
      detailActions.appendChild(swapBtn);
      if (partners.length) {
        const note = document.createElement("p");
        note.className = "muted tiny";
        note.textContent = onBench
          ? `Then tap who leaves the XI (${partners.length} options).`
          : `Then tap who comes in from the bench (${partners.length} options).`;
        detailActions.appendChild(note);
      }
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
    if (swapPending && swapPending.id === player.id) wrap.classList.add("is-swap-selected");
    if (swapPending) {
      const pendingOnXi = swapPending.side === "xi";
      const isPartner =
        player.id !== swapPending.id &&
        pendingOnXi === onBench &&
        (pendingOnXi ? canSwap(swapPending.id, player.id) : canSwap(player.id, swapPending.id));
      if (isPartner) wrap.classList.add("is-swap-target");
      else if (player.id !== swapPending.id) wrap.classList.add("is-swap-dim");
    }

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
    `;
    if (player.news) main.title = player.news;
    main.addEventListener("click", () => {
      if (!LOCKED && swapPending) {
        tryCompleteSwap(player);
        return;
      }
      openDetail(player);
    });
    wrap.appendChild(main);

    if (!onBench && player.id === captainId) {
      const badge = document.createElement("span");
      badge.className = "role-badge role-c";
      badge.textContent = "C";
      badge.title = "Captain · tap player to change";
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
      : `Formation ${c.DEF}-${c.MID}-${c.ATT} · ${starterIds.size}/11`;
    ensureRoles();
    syncHidden();
    updateHints();
  }

  if (closeDetailBtn) closeDetailBtn.addEventListener("click", closeDetail);
  if (playerDetail) {
    playerDetail.addEventListener("click", (e) => {
      if (e.target === playerDetail) closeDetail();
    });
  }
  if (cancelSwapBtn) cancelSwapBtn.addEventListener("click", clearSwap);

  document.getElementById("lineupForm").addEventListener("submit", (e) => {
    if (LOCKED) {
      e.preventDefault();
      return;
    }
    if (swapPending) {
      e.preventDefault();
      alert("Finish or cancel the XI ↔ bench swap first.");
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
    ensureRoles();
    if (!captainId || !starterIds.has(captainId)) {
      e.preventDefault();
      alert("Tap a starter and choose Make captain.");
      return;
    }
    if (!viceId || !starterIds.has(viceId) || viceId === captainId) {
      e.preventDefault();
      alert("Tap a different starter and choose Make vice.");
      return;
    }
    syncHidden();
  });

  render();
})();
