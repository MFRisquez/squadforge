(() => {
  const OWNED = JSON.parse(document.getElementById("ownedData").textContent);
  const INITIAL = JSON.parse(document.getElementById("initialLineup").textContent);
  const byId = Object.fromEntries(OWNED.map((p) => [p.id, p]));
  const BAND = { GK: [1, 1], DEF: [3, 5], MID: [3, 5], ATT: [1, 3] };
  const POINTS = INITIAL.points || {};
  const BREAKDOWNS = INITIAL.breakdowns || {};
  const GW = INITIAL.gw || null;
  const DESK_MQ = window.matchMedia("(min-width: 900px)");
  function isDesktop() {
    return Boolean(DESK_MQ && DESK_MQ.matches);
  }

  let starterIds = new Set(INITIAL.starters || []);
  let captainId = INITIAL.captain || [...starterIds][0] || null;
  let viceId = INITIAL.vice || null;
  const LOCKED = Boolean(INITIAL.locked);
  const CAPTAIN_EDITABLE = Boolean(INITIAL.captainEditable);
  const FIXTURE_STARTED = INITIAL.fixtureStarted || {};
  const CAPTAIN_ARMED = INITIAL.captainArmed || {};
  let activeChip = INITIAL.activeChip || null;
  let superSubPlayerId = INITIAL.superSubPlayerId || null;
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
  const benchDesk = document.getElementById("benchDesk");
  const hiddenFields = document.getElementById("hiddenFields");
  const playerDetail = document.getElementById("playerDetail");
  const detailEyebrow = document.getElementById("detailEyebrow");
  const detailName = document.getElementById("detailName");
  const detailSub = document.getElementById("detailSub");
  const detailPhoto = document.getElementById("detailPhoto");
  const detailBody = document.getElementById("detailBody");
  const detailActions = document.getElementById("detailActions");
  const detailHeadActions = document.getElementById("detailHeadActions");
  const closeDetailBtn = document.getElementById("closeDetail");

  const MATCH_STATS_BY_POS = {
    GK: ["Minutes", "Saves", "Clean sheet", "Goals conc.", "Pen saves", "Goals", "Assists", "Yellow", "Red"],
    DEF: ["Minutes", "Goals", "Assists", "Clean sheet", "Goals conc.", "Yellow", "Red", "Own goals"],
    MID: ["Minutes", "Goals", "Assists", "Clean sheet", "Yellow", "Red", "Pen missed"],
    ATT: ["Minutes", "Goals", "Assists", "Pen missed", "Yellow", "Red"],
  };

  function matchStatsTableHtml(position, rows, emptyHint) {
    const labels =
      MATCH_STATS_BY_POS[position] || MATCH_STATS_BY_POS.MID;
    const byLabel = Object.fromEntries((rows || []).map((r) => [r.label, r.value]));
    const body = labels
      .map(
        (label) => `
        <tr>
          <th scope="row">${label}</th>
          <td>${byLabel[label] != null ? byLabel[label] : "—"}</td>
        </tr>`
      )
      .join("");
    const extra = (rows || [])
      .filter((r) => String(r.label || "").startsWith("Pts ·"))
      .map(
        (r) => `
        <tr class="is-pts">
          <th scope="row">${r.label}</th>
          <td>${r.value}</td>
        </tr>`
      )
      .join("");
    return `
      <table class="match-stat-table" aria-label="Gameweek stats">
        <tbody>${body}${extra}</tbody>
      </table>
      ${emptyHint ? `<p class="muted tiny match-stat-hint">${emptyHint}</p>` : ""}
    `;
  }
  const swapBar = document.getElementById("swapBar");
  const swapHint = document.getElementById("swapHint");
  const cancelSwapBtn = document.getElementById("cancelSwap");
  // Swap UI is pitch-only: re-tap the selected player to cancel (no floating hint bar).
  const saveXiBtn =
    document.getElementById("saveXiBtn") || document.getElementById("saveCaptainBtn");
  const lineupForm = document.getElementById("lineupForm");
  const rolesOnly = Boolean(document.querySelector('input[name="roles_only"]'));
  const xiSideRail = document.getElementById("xiSideRail");
  const xiLiveTable = document.getElementById("xiLiveTable");
  const xiLiveLeader = document.getElementById("xiLiveLeader");
  const LIVE_COLS = [
    ["appearance", "App"],
    ["goals", "G"],
    ["assists", "A"],
    ["clean_sheet", "CS"],
    ["goals_conceded", "GC"],
    ["saves", "Sv"],
    ["penalties_saved", "PS"],
    ["penalties_missed", "PM"],
    ["yellow_cards", "YC"],
    ["red_cards", "RC"],
    ["own_goals", "OG"],
    ["scouting_bonus", "Scout"],
  ];

  let detailPlayer = null;
  /** @type {null | { id: number, side: "xi" | "bench" }} */
  let swapPending = null;
  let baselineSig = null;
  let saveVisual = "idle"; // idle | dirty | saved | saving

  const SAVE_ICO = {
    idle: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zm-5 16a3 3 0 1 1 0-6 3 3 0 0 1 0 6zm3-10H5V5h10v4z"/></svg>`,
    dirty: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>`,
    saved: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z"/></svg>`,
    saving: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 4a8 8 0 1 0 8 8h-2a6 6 0 1 1-6-6V4z"/></svg>`,
  };

  function lineupSignature() {
    const starters = [...starterIds]
      .map(Number)
      .sort((a, b) => a - b)
      .join(",");
    return `${starters}|${Number(captainId) || ""}|${Number(viceId) || ""}`;
  }

  function isDirty() {
    if (baselineSig == null) return false;
    return lineupSignature() !== baselineSig;
  }

  function canSaveLineup() {
    if (!isDirty() || swapPending) return false;
    ensureRoles();
    if (rolesOnly || (LOCKED && CAPTAIN_EDITABLE)) {
      return (
        Boolean(captainId) &&
        starterIds.has(captainId) &&
        canPickAsCaptain(captainId) &&
        Boolean(viceId) &&
        starterIds.has(viceId) &&
        viceId !== captainId
      );
    }
    if (LOCKED) return false;
    const c = counts();
    if (starterIds.size !== 11) return false;
    for (const [pos, [lo, hi]] of Object.entries(BAND)) {
      if (c[pos] < lo || c[pos] > hi) return false;
    }
    return Boolean(captainId && starterIds.has(captainId) && viceId && starterIds.has(viceId) && viceId !== captainId);
  }

  function paintSaveBtn() {
    if (!saveXiBtn) return;
    if (LOCKED && !CAPTAIN_EDITABLE) {
      saveXiBtn.hidden = true;
      return;
    }
    const dirty = isDirty();
    let state = saveVisual;
    if (state !== "saving") {
      if (dirty) state = "dirty";
      else if (saveVisual === "saved") state = "saved";
      else state = "idle";
    }
    saveVisual = state;
    saveXiBtn.classList.remove("is-idle", "is-dirty", "is-saved", "is-saving");
    saveXiBtn.classList.add(`is-${state}`);
    saveXiBtn.hidden = false;
    const ico = saveXiBtn.querySelector(".pitch-save-ico");
    const label = saveXiBtn.querySelector(".pitch-save-label");
    const baseLabel = rolesOnly || saveXiBtn.id === "saveCaptainBtn" ? "Save C" : "Save";
    if (ico) ico.innerHTML = SAVE_ICO[state] || SAVE_ICO.idle;
    if (label) {
      label.textContent =
        state === "saved" ? "Saved" : state === "saving" ? "Saving…" : baseLabel;
    }
    if (state === "dirty") {
      saveXiBtn.disabled = !canSaveLineup();
      saveXiBtn.setAttribute("aria-label", "Unsaved XI changes");
    } else if (state === "saved") {
      saveXiBtn.disabled = true;
      saveXiBtn.setAttribute("aria-label", "XI saved");
    } else if (state === "saving") {
      saveXiBtn.disabled = true;
      saveXiBtn.setAttribute("aria-label", "Saving XI");
    } else {
      saveXiBtn.disabled = true;
      saveXiBtn.setAttribute("aria-label", baseLabel);
    }
  }

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
    const finish = () => {
      detailPlayer = null;
    };
    if (typeof window.__ffCloseDrawer === "function") {
      window.__ffCloseDrawer(playerDetail).then(finish);
    } else {
      playerDetail.hidden = true;
      finish();
    }
  }

  function applyChipVisuals() {
    const bbOn = activeChip === "bench_boost";
    document.body.classList.toggle("chip-bb-on", bbOn);
    document.body.classList.toggle("chip-tc-on", activeChip === "triple_captain");
    document.body.classList.toggle("chip-ss-on", activeChip === "super_sub");
    document.querySelectorAll(".xi-bench-wrap, .xi-bench-stack, .xi-bench-panel").forEach((el) => {
      el.classList.toggle("bb-active", bbOn);
    });
    document.querySelectorAll("[data-bench-title]").forEach((el) => {
      el.textContent = bbOn ? "Bench Boost" : "Bench";
    });
  }

  document.addEventListener("ff:chip-change", (e) => {
    activeChip = e.detail?.chip || null;
    superSubPlayerId = e.detail?.superSubPlayerId ?? null;
    applyChipVisuals();
    render();
  });

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
    // Keep any leftover swap bar hidden; selection state is shown on the shirts.
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
    const roleLabel = onBench ? "Bench" : "Starting XI";
    detailEyebrow.textContent = LOCKED
      ? `Match · GW${GW || ""} · ${player.position}`
      : `${roleLabel} · ${player.position}`;
    detailName.textContent = player.name;
    if (detailSub) {
      const team = player.club || player.team || "";
      const price =
        player.price != null && player.price !== ""
          ? `£${Number(player.price).toFixed(1)}m`
          : "";
      detailSub.textContent = [team, price].filter(Boolean).join(" · ");
    }
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
    const isSS = activeChip === "super_sub" && Number(superSubPlayerId) === Number(player.id);
    detailBody.innerHTML = `
      <div class="player-detail-hero player-detail-hero-meta compact-meta">
        <div class="meta">
          ${isCap ? `<span class="role-pill is-c">${activeChip === "triple_captain" ? "Triple captain ×3" : "Captain ×2"}</span>` : ""}
          ${isVice ? `<span class="role-pill is-v">Vice-captain</span>` : ""}
          ${isSS ? `<span class="role-pill is-ss">Super Sub ×2</span>` : ""}
          ${LOCKED && pts != null ? `<strong class="match-pts">${Number(pts).toFixed(0)} pts</strong>` : ""}
        </div>
      </div>
      <div class="kpi-block">
        <div class="player-fdr-head">
          <strong>Gameweek stats · ${player.position}</strong>
        </div>
        <div id="detailKpis">
          ${
            LOCKED
              ? `<p class="muted tiny">Loading match stats…</p>`
              : matchStatsTableHtml(
                  player.position,
                  [],
                  "Values fill in after the deadline / kickoff."
                )
          }
        </div>
      </div>
    `;
    detailActions.innerHTML = "";
    if (detailHeadActions) detailHeadActions.innerHTML = "";
    if (!LOCKED || CAPTAIN_EDITABLE) {
      if (!onBench && (!LOCKED || CAPTAIN_EDITABLE)) {
        const cvRow = document.createElement("div");
        cvRow.className = "cv-action-row";
        const cBtn = actionBtn(
          isCap ? "Captain ✓" : "Make captain",
          `btn ghost cv-btn is-c${isCap ? " is-active" : ""}`,
          () => setCaptain(player.id)
        );
        if (isCap || (CAPTAIN_EDITABLE && !canPickAsCaptain(player.id))) cBtn.disabled = true;
        if (CAPTAIN_EDITABLE && !canPickAsCaptain(player.id) && !isCap) {
          cBtn.title = "Match already started";
        }
        const vBtn = actionBtn(
          isVice ? "Vice ✓" : "Make vice",
          `btn ghost cv-btn is-v${isVice ? " is-active" : ""}`,
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
          const pos = detailPlayer.position || data.position || "MID";
          kpis.innerHTML = matchStatsTableHtml(
            pos,
            items,
            items.length ? "" : "No live events yet — tap Refresh live scores."
          );
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
    // Only show live points once that player's club fixture has started.
    if (LOCKED && matchStarted(player.id) && pts != null && pts !== "") {
      const n = Number(pts);
      const cls = n < 0 ? "is-neg" : n > 0 ? "is-pos" : "";
      footHtml = `<span class="shirt-foot shirt-opp shirt-pts-fx ${cls}">${n.toFixed(0)}</span>`;
    } else if (fdr) {
      const venue = fdr.venue === "H" ? "H" : "A";
      footHtml = `<span class="shirt-foot shirt-opp fdr-${fdr.difficulty}">${fdr.opponent} (${venue})</span>`;
    } else {
      footHtml = `<span class="shirt-foot shirt-opp">TBD</span>`;
    }
    const isTC = activeChip === "triple_captain";
    const isSS = activeChip === "super_sub" && Number(superSubPlayerId) === Number(player.id);
    let roleChip = "";
    if (!onBench && player.id === captainId) {
      roleChip = isTC
        ? `<span class="role-badge role-c role-star" title="Triple Captain">★</span>`
        : `<span class="role-badge role-c" title="Captain">C</span>`;
      if (isTC) wrap.classList.add("is-tc-captain");
    } else if (!onBench && player.id === viceId) {
      roleChip = `<span class="role-badge role-v" title="Vice-captain">V</span>`;
    }
    if (isSS) {
      roleChip += `<span class="role-badge role-s" title="Super Sub">S</span>`;
      wrap.classList.add("is-super-sub");
    }
    main.innerHTML = `
      <span class="shirt-kit">
        <img class="jersey-img" src="${player.shirt || ""}" alt="${player.team} kit" width="66" height="87" loading="lazy" decoding="async" />
        ${flag ? `<span class="shirt-status-flag" title="${player.news || flag}">${flag}</span>` : ""}
        ${roleChip}
        <span class="shirt-overlay">
          <span class="shirt-nameplate">${shortName(player.name)}</span>
          ${footHtml}
        </span>
      </span>
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

    return wrap;
  }

  const POS_FULL = {
    GK: "Goalkeeper",
    DEF: "Defender",
    MID: "Midfielder",
    ATT: "Attacker",
  };

  function deskBenchCard(player) {
    const wrap = shirtCard(player, true);
    wrap.classList.add("xi-bench-row");
    const shirt = wrap.querySelector(".xi-shirt");
    if (shirt) shirt.classList.add("xi-bench-mini");
    const overlay = wrap.querySelector(".shirt-overlay");
    if (overlay) overlay.remove();
    const meta = document.createElement("div");
    meta.className = "xi-bench-meta";
    const fdr = player.fdr;
    let fixtureHtml;
    if (
      LOCKED &&
      matchStarted(player.id) &&
      POINTS[String(player.id)] != null &&
      POINTS[String(player.id)] !== ""
    ) {
      const n = Number(POINTS[String(player.id)]);
      const cls = n < 0 ? "is-neg" : n > 0 ? "is-pos" : "";
      fixtureHtml = `<span class="xi-bench-fixture shirt-pts-fx ${cls}">${n.toFixed(0)} pts</span>`;
    } else if (fdr) {
      const venue = fdr.venue === "H" ? "H" : "A";
      fixtureHtml = `<span class="xi-bench-fixture fdr-${fdr.difficulty}">${fdr.opponent} (${venue})</span>`;
    } else {
      fixtureHtml = `<span class="xi-bench-fixture">TBD</span>`;
    }
    const teamName = player.club || player.team || "";
    const posName = POS_FULL[player.position] || player.position || "";
    meta.innerHTML = `
      <strong class="xi-bench-name">${player.name}</strong>
      <span class="xi-bench-team">${teamName}</span>
      <span class="xi-bench-pos">${posName}</span>
      ${fixtureHtml}
    `;
    wrap.appendChild(meta);
    return wrap;
  }

  function paintBench() {
    const benchPlayers = OWNED.filter((p) => !starterIds.has(p.id));
    if (bench) {
      bench.innerHTML = "";
      if (!isDesktop()) {
        benchPlayers.forEach((p) => bench.appendChild(shirtCard(p, true)));
      }
    }
    if (benchDesk) {
      benchDesk.innerHTML = "";
      if (isDesktop()) {
        if (!benchPlayers.length) {
          benchDesk.innerHTML = `<p class="muted tiny">No bench players.</p>`;
        } else {
          const head = document.createElement("div");
          head.className = "xi-bench-cols";
          head.setAttribute("aria-hidden", "true");
          head.innerHTML = `
            <span class="xi-bench-cols-kit"></span>
            <span>Player</span>
            <span>Team</span>
            <span>Position</span>
            <span>Fixture</span>
          `;
          benchDesk.appendChild(head);
          benchPlayers.forEach((p) => benchDesk.appendChild(deskBenchCard(p)));
        }
      }
    }
  }

  function fmtPts(n) {
    const v = Number(n || 0);
    if (!Number.isFinite(v)) return "0";
    if (Math.abs(v) < 1e-9) return "0";
    return Number.isInteger(v) ? String(v) : v.toFixed(1);
  }

  function paintLiveTable() {
    if (!xiLiveTable) return;
    const thead = xiLiveTable.querySelector("thead");
    const tbody = xiLiveTable.querySelector("tbody");
    if (!thead || !tbody) return;

    const squad = OWNED.slice();
    const labelFor = Object.fromEntries(LIVE_COLS);
    const core = ["appearance", "goals", "assists", "clean_sheet"];
    const seen = new Set();
    const cols = [];
    function pushCol(key) {
      if (!key || seen.has(key)) return;
      seen.add(key);
      const short =
        labelFor[key] ||
        key
          .replace(/_threshold$/i, "")
          .replace(/_/g, " ")
          .replace(/\b\w/g, (c) => c.toUpperCase())
          .slice(0, 8);
      cols.push([key, short]);
    }
    core.forEach(pushCol);
    LIVE_COLS.forEach(([key]) => {
      if (squad.some((p) => Math.abs(Number((BREAKDOWNS[String(p.id)] || {})[key] || 0)) > 1e-9)) {
        pushCol(key);
      }
    });
    squad.forEach((p) => {
      Object.entries(BREAKDOWNS[String(p.id)] || {}).forEach(([key, val]) => {
        if (Math.abs(Number(val || 0)) > 1e-9) pushCol(key);
      });
    });

    thead.innerHTML = `<tr>
      <th>Player</th>
      ${cols.map(([, label]) => `<th>${label}</th>`).join("")}
      <th>Pts</th>
    </tr>`;

    const ranked = squad.map((p) => {
      const started = matchStarted(p.id);
      const base = started ? Number(POINTS[String(p.id)] || 0) : 0;
      const mult = p.id === captainId ? 2 : 1;
      const total = started ? base * mult : Number.NEGATIVE_INFINITY;
      return { p, base, mult, total, bd: BREAKDOWNS[String(p.id)] || {}, started };
    });
    const byPts = (a, b) =>
      b.total - a.total || String(a.p.name).localeCompare(String(b.p.name));
    const xiRanked = ranked.filter((r) => starterIds.has(r.p.id)).sort(byPts);
    const benchRanked = ranked.filter((r) => !starterIds.has(r.p.id)).sort(byPts);

    if (!ranked.length) {
      tbody.innerHTML = `<tr><td colspan="${cols.length + 2}" class="muted">No squad players.</td></tr>`;
      return;
    }

    const startedRanked = ranked.filter((r) => r.started);
    const topTotal = startedRanked.reduce((max, r) => Math.max(max, r.total), Number.NEGATIVE_INFINITY);
    const topRow =
      Number.isFinite(topTotal) && startedRanked.some((r) => r.total === topTotal && Math.abs(topTotal) > 1e-9)
        ? startedRanked.filter((r) => r.total === topTotal).sort(byPts)[0]
        : null;

    function roleMark(id) {
      if (id === captainId) return `<span class="live-role is-c" title="Captain">C</span>`;
      if (id === viceId) return `<span class="live-role is-v" title="Vice-captain">V</span>`;
      return "";
    }

    if (xiLiveLeader) {
      if (topRow) {
        xiLiveLeader.hidden = false;
        xiLiveLeader.innerHTML = `Top · ${topRow.p.name}${roleMark(topRow.p.id)} · ${fmtPts(topRow.total)} pts`;
      } else {
        xiLiveLeader.hidden = true;
        xiLiveLeader.textContent = "";
      }
    }

    function rowHtml({ p, base, mult, total, bd }, onBench) {
      const started = matchStarted(p.id);
      const cells = cols
        .map(([key]) => {
          if (!started) return `<td class="muted">–</td>`;
          const v = Number(bd[key] || 0);
          const cls = v < 0 ? ' class="is-neg"' : "";
          return `<td${cls}>${fmtPts(v)}</td>`;
        })
        .join("");
      let ptsLabel;
      if (!started) {
        const fdr = p.fdr;
        ptsLabel = fdr
          ? `${fdr.opponent} (${fdr.venue === "H" ? "H" : "A"})`
          : "TBD";
      } else {
        ptsLabel = mult > 1 ? `${fmtPts(base)}×${mult}` : fmtPts(total);
      }
      const isTop = Boolean(started && topRow && p.id === topRow.p.id);
      const classes = [isTop ? "is-top" : "", onBench ? "is-bench" : "is-xi"].filter(Boolean).join(" ");
      return `<tr class="${classes}">
        <td>${isTop ? "★ " : ""}${p.name}${roleMark(p.id)}</td>
        ${cells}
        <td class="pts-total">${ptsLabel}</td>
      </tr>`;
    }

    const parts = [];
    if (xiRanked.length) {
      parts.push(`<tr class="xi-live-section"><td colspan="${cols.length + 2}">Starting XI</td></tr>`);
      parts.push(...xiRanked.map((r) => rowHtml(r, false)));
    }
    if (benchRanked.length) {
      parts.push(`<tr class="xi-live-split"><td colspan="${cols.length + 2}">Bench</td></tr>`);
      parts.push(...benchRanked.map((r) => rowHtml(r, true)));
    }
    tbody.innerHTML = parts.join("");
    fitLiveTableType();
  }

  function fitLiveTableType() {
    const wrap = document.querySelector(".xi-live-table-wrap");
    if (!xiLiveTable || !wrap || !isDesktop()) {
      if (xiLiveTable) xiLiveTable.style.fontSize = "";
      return;
    }
    let size = 13.5;
    xiLiveTable.style.fontSize = `${size}px`;
    // Shrink until it fits the box
    while (size > 9 && xiLiveTable.scrollHeight > wrap.clientHeight + 1) {
      size -= 0.5;
      xiLiveTable.style.fontSize = `${size}px`;
    }
    // Grow to fill leftover space without overflowing
    while (size < 16 && xiLiveTable.scrollHeight < wrap.clientHeight - 10) {
      size += 0.5;
      xiLiveTable.style.fontSize = `${size}px`;
      if (xiLiveTable.scrollHeight > wrap.clientHeight + 1) {
        size -= 0.5;
        xiLiveTable.style.fontSize = `${size}px`;
        break;
      }
    }
  }

  function syncXiSideLayout() {
    if (!xiSideRail) return;
    // Desktop page-fit uses CSS stretch; clear any leftover inline heights.
    xiSideRail.style.height = "";
    xiSideRail.style.minHeight = "";
    fitLiveTableType();
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

    ensureRoles();
    syncHidden();
    updateHints();
    paintSaveBtn();
    paintBench();
    paintLiveTable();
    syncXiSideLayout();
  }

  if (closeDetailBtn) closeDetailBtn.addEventListener("click", closeDetail);
  if (playerDetail) {
    playerDetail.addEventListener("click", (e) => {
      if (e.target === playerDetail) closeDetail();
    });
  }
  if (cancelSwapBtn) cancelSwapBtn.addEventListener("click", clearSwap);

  if (lineupForm) {
    lineupForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (LOCKED && !CAPTAIN_EDITABLE) return;
      if (swapPending) {
        alert("Finish or cancel the XI ↔ bench swap first.");
        return;
      }
      ensureRoles();
      if (LOCKED && CAPTAIN_EDITABLE) {
        if (!captainId || !starterIds.has(captainId) || !canPickAsCaptain(captainId)) {
          alert("Pick a captain whose match has not started yet.");
          return;
        }
        if (!viceId || !starterIds.has(viceId) || viceId === captainId) {
          alert("Pick a different vice-captain.");
          return;
        }
      } else {
        const c = counts();
        if (starterIds.size !== 11) {
          alert("Need exactly 11 starters.");
          return;
        }
        for (const [pos, [lo, hi]] of Object.entries(BAND)) {
          if (c[pos] < lo || c[pos] > hi) {
            alert(`Need ${lo}–${hi} starting ${pos}.`);
            return;
          }
        }
        if (!captainId || !starterIds.has(captainId)) {
          alert("Tap a starter and choose Make captain.");
          return;
        }
        if (!viceId || !starterIds.has(viceId) || viceId === captainId) {
          alert("Tap a different starter and choose Make vice.");
          return;
        }
      }
      if (!isDirty()) return;
      syncHidden();
      saveVisual = "saving";
      paintSaveBtn();
      try {
        const body = new URLSearchParams();
        starterIds.forEach((id) => body.append("starter_id", String(id)));
        body.set("captain_id", String(captainId || ""));
        body.set("vice_id", String(viceId || ""));
        if (rolesOnly || (LOCKED && CAPTAIN_EDITABLE)) body.set("roles_only", "1");
        const res = await fetch("/lineup/save?format=json", {
          method: "POST",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "fetch",
          },
          credentials: "same-origin",
          redirect: "manual",
          body,
        });
        if (res.type === "opaqueredirect" || (res.status >= 300 && res.status < 400)) {
          throw new Error("Could not save XI — try again");
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.error || !data.ok) {
          throw new Error(data.error || "Could not save XI");
        }
        baselineSig = lineupSignature();
        saveVisual = "saved";
        paintSaveBtn();
      } catch (err) {
        saveVisual = "dirty";
        paintSaveBtn();
        alert(err.message || "Could not save XI");
      }
    });
  }

  ensureRoles();
  baselineSig = lineupSignature();
  saveVisual = "idle";
  applyChipVisuals();
  render();
  const onResize = () => {
    paintBench();
    syncXiSideLayout();
    fitLiveTableType();
  };
  window.addEventListener("resize", onResize);
  const onMq = () => render();
  if (DESK_MQ && typeof DESK_MQ.addEventListener === "function") {
    DESK_MQ.addEventListener("change", onMq);
  }
  let pitchRo = null;
  if (typeof ResizeObserver !== "undefined" && pitch) {
    pitchRo = new ResizeObserver(() => syncXiSideLayout());
    pitchRo.observe(pitch);
  }
  window.__ffTeardown = () => {
    window.removeEventListener("resize", onResize);
    if (DESK_MQ && typeof DESK_MQ.removeEventListener === "function") {
      DESK_MQ.removeEventListener("change", onMq);
    }
    if (pitchRo) pitchRo.disconnect();
    document.querySelectorAll("body > .drawer").forEach((el) => el.remove());
  };
})();
