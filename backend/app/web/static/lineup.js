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
  const CAPTAIN_EDITABLE = Boolean(INITIAL.captainEditable);
  const FIXTURE_STARTED = INITIAL.fixtureStarted || {};
  const CAPTAIN_ARMED = INITIAL.captainArmed || {};
  if (!viceId || viceId === captainId) {
    viceId = [...starterIds].find((id) => id !== captainId) || null;
  }

  function matchStarted(playerId) {
    return Boolean(FIXTURE_STARTED[String(playerId)] || FIXTURE_STARTED[playerId]);
  }

  function canPickAsCaptain(playerId) {
    return starterIds.has(playerId) && !matchStarted(playerId);
  }

  const pitch = document.getElementById("pitch");
  const bench = document.getElementById("bench");
  const hiddenFields = document.getElementById("hiddenFields");
  const playerDetail = document.getElementById("playerDetail");
  const detailEyebrow = document.getElementById("detailEyebrow");
  const detailName = document.getElementById("detailName");
  const detailPhoto = document.getElementById("detailPhoto");
  const detailBody = document.getElementById("detailBody");
  const detailActions = document.getElementById("detailActions");
  const closeDetailBtn = document.getElementById("closeDetail");
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
    if (CAPTAIN_EDITABLE && !canPickAsCaptain(id)) {
      alert("That player's match already started — pick someone still to play.");
      return;
    }
    if (id === viceId) viceId = captainId;
    captainId = id;
    ensureRoles();
    closeDetail();
    render();
  }

  function setVice(id) {
    if (!starterIds.has(id)) return;
    if (CAPTAIN_EDITABLE && !canPickAsCaptain(id)) {
      alert("That player's match already started — pick someone still to play.");
      return;
    }
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
    if (LOCKED) {
      if (swapBar) swapBar.hidden = true;
      return;
    }
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
      return;
    }
    if (swapBar) swapBar.hidden = true;
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
    const fdr = player.fdr;
    const oppLine = fdr
      ? `${fdr.opponent} (${fdr.venue === "H" ? "H" : "A"})`
      : "Fixture TBD";
    detailEyebrow.textContent = LOCKED ? `Match · GW${GW || ""}` : `XI · ${player.position}`;
    detailName.textContent = player.name;
    if (detailPhoto) {
      detailPhoto.onerror = null;
      const chain = [player.photo, player.photoFallback, player.photoFallback2].filter(Boolean);
      if (chain.length) {
        detailPhoto.hidden = false;
        detailPhoto.alt = player.name;
        let step = 0;
        detailPhoto.onerror = () => {
          step += 1;
          if (step < chain.length) {
            detailPhoto.src = chain[step];
            return;
          }
          detailPhoto.hidden = true;
        };
        detailPhoto.src = chain[0];
      } else {
        detailPhoto.removeAttribute("src");
        detailPhoto.hidden = true;
        detailPhoto.alt = "";
      }
    }
    detailBody.innerHTML = `
      <div class="player-detail-hero player-detail-hero-meta">
        <div class="meta">
          <strong>${player.team}</strong>
          <span class="muted">${player.position} · vs ${oppLine}</span>
          <span class="role-pill ${onBench ? "is-bench" : "is-xi"}">${onBench ? "Bench" : "Starting XI"}</span>
          ${isCap ? `<span class="role-pill is-c">Captain ×2</span>` : ""}
          ${isVice ? `<span class="role-pill is-v">Vice-captain</span>` : ""}
          ${LOCKED && pts != null ? `<strong class="match-pts">${Number(pts).toFixed(0)} pts</strong>` : ""}
        </div>
      </div>
      <div class="kpi-block">
        <div class="player-fdr-head">
          <strong>${LOCKED ? "This gameweek" : "Match stats"}</strong>
          <span class="muted tiny">${LOCKED ? "After kickoff" : "Unlock after deadline"}</span>
        </div>
        <div class="kpi-grid" id="detailKpis">
          <span class="muted tiny">${LOCKED ? "Loading match stats…" : "Scores appear here once the GW is locked."}</span>
        </div>
      </div>
    `;
    detailActions.innerHTML = "";
    if (!LOCKED || CAPTAIN_EDITABLE) {
      if (!onBench && (!LOCKED || CAPTAIN_EDITABLE)) {
        const cvRow = document.createElement("div");
        cvRow.className = "cv-action-row";
        const cBtn = actionBtn(
          isCap ? "Captain ✓" : "Make captain",
          `btn cv-btn is-c${isCap ? " is-active" : ""}`,
          () => setCaptain(player.id)
        );
        if (isCap || (CAPTAIN_EDITABLE && !canPickAsCaptain(player.id))) cBtn.disabled = true;
        if (CAPTAIN_EDITABLE && !canPickAsCaptain(player.id) && !isCap) {
          cBtn.title = "Match already started";
        }
        const vBtn = actionBtn(
          isVice ? "Vice ✓" : "Make vice",
          `btn cv-btn is-v${isVice ? " is-active" : ""}`,
          () => setVice(player.id)
        );
        if (isVice || (CAPTAIN_EDITABLE && !canPickAsCaptain(player.id))) vBtn.disabled = true;
        cvRow.appendChild(cBtn);
        cvRow.appendChild(vBtn);
        detailActions.appendChild(cvRow);
        if (CAPTAIN_EDITABLE && LOCKED) {
          const note = document.createElement("p");
          note.className = "muted tiny";
          note.textContent = matchStarted(player.id)
            ? "This match has started — captain points for them are locked."
            : "Tap Save captain below after changing C/V.";
          detailActions.appendChild(note);
        }
      }
      if (!LOCKED) {
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
    }
    if (playerDetail.parentElement !== document.body) {
      document.body.appendChild(playerDetail);
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
        if (detailPhoto && (data.photo || data.photoFallback || data.photoFallback2)) {
          detailPlayer.photo = data.photo || detailPlayer.photo;
          detailPlayer.photoFallback = data.photoFallback || detailPlayer.photoFallback;
          detailPlayer.photoFallback2 = data.photoFallback2 || detailPlayer.photoFallback2;
          const chain = [detailPlayer.photo, detailPlayer.photoFallback, detailPlayer.photoFallback2].filter(Boolean);
          let step = 0;
          detailPhoto.hidden = false;
          detailPhoto.alt = detailPlayer.name || "";
          detailPhoto.onerror = () => {
            step += 1;
            if (step < chain.length) {
              detailPhoto.src = chain[step];
              return;
            }
            detailPhoto.hidden = true;
          };
          detailPhoto.src = chain[0];
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

  function shortName(name) {
    const parts = String(name || "").trim().split(/\s+/);
    if (parts.length <= 1) return parts[0] || "";
    return parts[parts.length - 1];
  }

  function shirtCard(player, onBench) {
    const wrap = document.createElement("div");
    wrap.className = "shirt-card xi-card";
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
    main.className = "shirt filled jersey xi-shirt avail-" + avail;
    const flag = avail === "out" ? "OUT" : avail === "doubt" ? "!" : "";
    const pts = POINTS[String(player.id)];
    const fdr = player.fdr;
    let footHtml;
    if (LOCKED && pts != null && pts !== "") {
      const n = Number(pts);
      const cls = n < 0 ? "is-neg" : n > 0 ? "is-pos" : "";
      footHtml = `<span class="shirt-foot shirt-opp shirt-pts-fx ${cls}">${n.toFixed(0)}</span>`;
    } else if (fdr) {
      const venue = fdr.venue === "H" ? "H" : "A";
      footHtml = `<span class="shirt-foot shirt-opp fdr-${fdr.difficulty}">${fdr.opponent} (${venue})</span>`;
    } else {
      footHtml = `<span class="shirt-foot shirt-opp">TBD</span>`;
    }
    main.innerHTML = `
      <span class="shirt-kit">
        <img class="jersey-img" src="${player.shirt || ""}" alt="${player.team} kit" width="66" height="87" loading="lazy" decoding="async" />
        ${flag ? `<span class="shirt-status-flag" title="${player.news || flag}">${flag}</span>` : ""}
      </span>
      <span class="shirt-nameplate">${shortName(player.name)}</span>
      ${footHtml}
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
    if (LOCKED && CAPTAIN_EDITABLE) {
      ensureRoles();
      if (!captainId || !starterIds.has(captainId) || !canPickAsCaptain(captainId)) {
        e.preventDefault();
        alert("Pick a captain whose match has not started yet.");
        return;
      }
      if (!viceId || !starterIds.has(viceId) || viceId === captainId) {
        e.preventDefault();
        alert("Pick a different vice-captain.");
        return;
      }
      if (!canPickAsCaptain(viceId) && !(CAPTAIN_ARMED[String(viceId)] || CAPTAIN_ARMED[viceId])) {
        // allow existing vice if already set and match started only if unchanged — server validates
      }
      syncHidden();
      return;
    }
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
