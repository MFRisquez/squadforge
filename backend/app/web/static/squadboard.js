(() => {
  const PLAYERS = JSON.parse(document.getElementById("playersData").textContent);
  const INITIAL = JSON.parse(document.getElementById("initialSquad").textContent);
  const BUDGET = Number(INITIAL.budget);
  const MAX_CLUB = Number(INITIAL.maxPerClub || 3);
  const UNLIMITED = Boolean(INITIAL.unlimited);
  const LOCKED = Boolean(INITIAL.locked);
  const FT_LEFT = Number(INITIAL.ft || 0);
  const HIT_COST = Number(INITIAL.hitCost || 4);
  const NEED = { GK: 2, DEF: 5, MID: 5, ATT: 3 };
  const ORDER = ["GK", "DEF", "MID", "ATT"];
  const byId = Object.fromEntries(PLAYERS.map((p) => [p.id, p]));

  /** @type {Record<string, (number|null)[]>} */
  const slots = {
    GK: Array(NEED.GK).fill(null),
    DEF: Array(NEED.DEF).fill(null),
    MID: Array(NEED.MID).fill(null),
    ATT: Array(NEED.ATT).fill(null),
  };

  const selected = INITIAL.selected || [];
  const used = new Set();
  selected.forEach((id) => {
    const p = byId[id];
    if (!p || used.has(id)) return;
    const arr = slots[p.position];
    const idx = arr.findIndex((x) => x == null);
    if (idx >= 0) {
      arr[idx] = id;
      used.add(id);
    }
  });

  const pitch = document.getElementById("squadPitch");
  const budgetValue = document.getElementById("budgetValue");
  const squadCount = document.getElementById("squadCount");
  const hiddenFields = document.getElementById("hiddenFields");
  const picker = document.getElementById("picker");
  const pickerList = document.getElementById("pickerList");
  const pickerPos = document.getElementById("pickerPos");
  const pickerEyebrow = document.getElementById("pickerEyebrow");
  const search = document.getElementById("playerSearch");
  const filterTeam = document.getElementById("filterTeam");
  const filterMaxPrice = document.getElementById("filterMaxPrice");
  const modeHint = document.getElementById("modeHint");
  const transferForm = document.getElementById("transferForm");
  const outIdEl = document.getElementById("outId");
  const inIdEl = document.getElementById("inId");
  const swapSummary = document.getElementById("swapSummary");
  const confirmSwap = document.getElementById("confirmSwap");
  const saveSquadBtn = document.getElementById("saveSquadBtn");
  const buildActions = document.getElementById("buildActions");
  const clearSwapBtn = document.getElementById("clearSwap");
  const squadForm = document.getElementById("squadForm");
  const playerDetail = document.getElementById("playerDetail");
  const detailEyebrow = document.getElementById("detailEyebrow");
  const detailName = document.getElementById("detailName");
  const detailBody = document.getElementById("detailBody");
  const detailActions = document.getElementById("detailActions");
  const closeDetailBtn = document.getElementById("closeDetail");

  let starterIds = new Set(); // unused on Squad — lineup lives on /lineup
  let captainId = null;
  let viceId = null;

  let active = null; // { pos, index }
  let outPlayer = null;
  let inPlayer = null;
  let pickerMode = "add"; // add | replace | transfer
  let detailContext = null; // { player, fromPicker, pos, index }

  const STATUS_LABEL = {
    a: "Available",
    d: "Doubtful",
    i: "Injured",
    s: "Suspended",
    u: "Unavailable",
  };

  function filledIds() {
    return ORDER.flatMap((pos) => slots[pos]).filter(Boolean);
  }

  function isComplete() {
    return filledIds().length === 15;
  }

  function freeEdit() {
    if (LOCKED) return false;
    return UNLIMITED || !INITIAL.hasSquad || !isComplete();
  }

  function spend() {
    return filledIds().reduce((s, id) => s + (byId[id]?.price || 0), 0);
  }

  function clubCounts(excludeId) {
    const counts = {};
    filledIds().forEach((id) => {
      if (excludeId && id === excludeId) return;
      const team = byId[id]?.team;
      if (!team) return;
      counts[team] = (counts[team] || 0) + 1;
    });
    return counts;
  }

  function shirtHtml(p) {
    const avail = p.availability || "ok";
    const flag = avail === "out" ? "OUT" : avail === "doubt" ? "DOUBT" : "";
    const img = p.shirt || "";
    const fdr = p.fdr;
    const fdrBadge = fdr
      ? `<span class="shirt-fdr fdr-${fdr.difficulty}" title="${fdr.opponent} (${fdr.venue}) · FDR ${fdr.difficulty}">${fdr.opponent}<em>${fdr.venue}</em></span>`
      : "";
    return `
      <img class="jersey-img" src="${img}" alt="${p.team} kit" width="66" height="87" loading="lazy" decoding="async" />
      ${fdrBadge}
      <span class="shirt-price">£${p.price.toFixed(1)}</span>
      <span class="shirt-name">${p.name}</span>
      <span class="shirt-team">${p.team}${flag ? " · " + flag : ""}</span>
    `;
  }

  function syncHidden() {
    hiddenFields.innerHTML = "";
    filledIds().forEach((id) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = "player_id";
      input.value = String(id);
      hiddenFields.appendChild(input);
    });
  }

  function refreshMeta() {
    const left = BUDGET - spend();
    budgetValue.textContent = `£${left.toFixed(1)}m`;
    budgetValue.classList.toggle("over", left < -0.01);
    squadCount.textContent = `${filledIds().length}/15`;
    if (LOCKED) {
      modeHint.textContent = "Gameweek locked — tap a player for info.";
      if (saveSquadBtn) saveSquadBtn.hidden = true;
      syncHidden();
      refreshSwapBar();
      return;
    }
    const canFree = freeEdit();
    if (canFree) {
      modeHint.textContent = isComplete()
        ? `Tap a player for stats · replace from the sheet (${PLAYERS.length} in catalogue).`
        : `Tap empty slots to pick · tap a player for stats (${PLAYERS.length} players).`;
      if (saveSquadBtn) saveSquadBtn.hidden = false;
      if (buildActions) buildActions.style.display = "";
    } else {
      modeHint.textContent =
        FT_LEFT < 1
          ? `Tap a player for stats / transfer (−${HIT_COST} hit). Or play WC / FH.`
          : `Tap a player for stats, transfers, or XI / bench.`;
      if (saveSquadBtn) saveSquadBtn.hidden = true;
    }
    syncHidden();
    refreshSwapBar();
  }

  function refreshSwapBar() {
    if (!outPlayer || freeEdit()) {
      transferForm.hidden = true;
      outIdEl.value = "";
      inIdEl.value = "";
      confirmSwap.disabled = true;
      return;
    }
    transferForm.hidden = false;
    outIdEl.value = String(outPlayer.id);
    if (inPlayer) {
      inIdEl.value = String(inPlayer.id);
      confirmSwap.disabled = false;
      const delta = inPlayer.price - outPlayer.price;
      const sign = delta >= 0 ? `+£${delta.toFixed(1)}m` : `−£${Math.abs(delta).toFixed(1)}m`;
      const hitNote = !UNLIMITED && FT_LEFT < 1 ? ` · −${HIT_COST} hit` : "";
      swapSummary.textContent = `${outPlayer.name} → ${inPlayer.name} (${sign})${hitNote}`;
    } else {
      inIdEl.value = "";
      confirmSwap.disabled = true;
      const hitHint = !UNLIMITED && FT_LEFT < 1 ? ` (−${HIT_COST} hit)` : "";
      swapSummary.textContent = `Out: ${outPlayer.name}${hitHint} — choose who comes in`;
    }
  }

  function statusLabel(p) {
    const avail = p.availability || "ok";
    const base = STATUS_LABEL[(p.status || "a").toLowerCase()] || "Available";
    if (avail === "out") return base === "Available" ? "Unavailable" : base;
    if (avail === "doubt" && base === "Available") return "Doubtful";
    return base;
  }

  function closeDetail() {
    if (!playerDetail) return;
    playerDetail.hidden = true;
    detailContext = null;
  }

  function playerHeroHtml(p, club) {
    const shirt = p.shirt || "";
    const photo = p.photo || "";
    return `
      <div class="player-detail-hero">
        <div class="kit-portrait">
          <img class="kit-shirt" src="${shirt}" alt="" width="66" height="87" />
          ${photo ? `<img class="kit-face" src="${photo}" alt="" width="56" height="56" loading="lazy" />` : ""}
        </div>
        <div class="meta">
          <strong>${club}</strong>
          <span class="muted">${p.position} · £${Number(p.price).toFixed(1)}m</span>
          <span class="avail-text-${(p.availability || "ok") === "ok" ? "ok" : p.availability || "ok"}">${statusLabel(p)}</span>
        </div>
      </div>`;
  }

  function openPlayerDetail(p, opts = {}) {
    if (!playerDetail || !p) return;
    detailContext = {
      player: p,
      fromPicker: Boolean(opts.fromPicker),
      pos: opts.pos ?? p.position,
      index: opts.index ?? null,
    };
    detailEyebrow.textContent = `Season · ${p.position}`;
    detailName.textContent = p.name;
    const club = p.club || p.team;
    const chance =
      p.chance == null || p.chance === ""
        ? "—"
        : `${p.chance}%`;
    const news = (p.news || "").trim();
    const avail = p.availability || "ok";
    detailBody.innerHTML = `
      ${playerHeroHtml(p, club)}
      <div class="player-detail-facts">
        <div class="fact"><span>Price</span><strong>£${Number(p.price).toFixed(1)}m</strong></div>
        <div class="fact"><span>Club</span><strong>${club}</strong></div>
        <div class="fact"><span>Status</span><strong>${statusLabel(p)}</strong></div>
        <div class="fact"><span>Chance next</span><strong>${chance}</strong></div>
      </div>
      <div class="kpi-block">
        <div class="player-fdr-head">
          <strong>Season KPIs</strong>
          <span class="muted tiny">${p.position}</span>
        </div>
        <div class="kpi-grid" id="detailKpis">
          <span class="muted tiny">Loading stats…</span>
        </div>
      </div>
      <div class="player-fdr" id="detailFdr">
        <div class="player-fdr-head">
          <strong>Next 3</strong>
          <span class="muted tiny">Fixture difficulty</span>
        </div>
        <div class="player-fdr-row" id="detailFdrRow">
          <span class="muted tiny">Loading fixtures…</span>
        </div>
      </div>
      ${
        news
          ? `<div class="player-detail-news ${avail === "out" ? "is-out" : ""}">${news}</div>`
          : `<p class="muted tiny">No injury news right now.</p>`
      }
    `;

    detailActions.innerHTML = "";
    if (!LOCKED) {
      if (opts.fromPicker) {
        const select = document.createElement("button");
        select.type = "button";
        select.className = "btn";
        select.textContent =
          pickerMode === "transfer" ? "Select for transfer" : pickerMode === "replace" ? "Select player" : "Add to squad";
        select.addEventListener("click", () => {
          closeDetail();
          pickPlayer(p);
        });
        detailActions.appendChild(select);
      } else if (opts.pos != null && opts.index != null) {
        const act = document.createElement("button");
        act.type = "button";
        act.className = "btn";
        act.textContent = freeEdit() ? "Replace player" : "Transfer out";
        act.addEventListener("click", () => {
          closeDetail();
          if (freeEdit()) {
            openPicker(opts.pos, opts.index, "replace");
          } else {
            outPlayer = p;
            inPlayer = null;
            active = { pos: opts.pos, index: opts.index };
            openPicker(opts.pos, opts.index, "transfer");
          }
        });
        detailActions.appendChild(act);
        const toLineup = document.createElement("a");
        toLineup.className = "btn ghost";
        toLineup.href = "/lineup";
        toLineup.textContent = "Set XI on Lineup";
        detailActions.appendChild(toLineup);
      }
    }
    playerDetail.hidden = false;
    loadPlayerProfile(p.id);
  }

  function loadPlayerProfile(playerId) {
    const row = document.getElementById("detailFdrRow");
    const kpis = document.getElementById("detailKpis");
    fetch(`/api/players/${playerId}?mode=season`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((data) => {
        if (!detailContext || detailContext.player.id !== playerId) return;
        if (data.error) throw new Error(data.error);
        if (data.photo && detailContext.player) {
          detailContext.player.photo = data.photo;
          const face = detailBody.querySelector(".kit-face");
          const portrait = detailBody.querySelector(".kit-portrait");
          if (!face && portrait && data.photo) {
            const img = document.createElement("img");
            img.className = "kit-face";
            img.src = data.photo;
            img.width = 56;
            img.height = 56;
            portrait.appendChild(img);
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
            : `<span class="muted tiny">No season stats yet — refresh players from FPL.</span>`;
        }
        if (row) {
          const items = data.fixtures || [];
          if (!items.length) {
            row.innerHTML =
              `<span class="muted tiny">No fixtures yet — use Fixtures → Refresh live.</span>`;
          } else {
            row.innerHTML = items
              .map(
                (fx) => `
              <div class="fdr-chip fdr-${fx.difficulty}" title="${fx.opponent_name} (${fx.venue}) · FDR ${fx.difficulty}">
                <span class="fdr-opp">${fx.opponent} (${fx.venue})</span>
                <span class="fdr-gw">GW${fx.gw}</span>
              </div>`
              )
              .join("");
          }
        }
      })
      .catch(() => {
        if (!detailContext || detailContext.player.id !== playerId) return;
        if (kpis) kpis.innerHTML = `<span class="muted tiny">Couldn’t load stats.</span>`;
        if (row) row.innerHTML = `<span class="muted tiny">Couldn’t load fixtures.</span>`;
      });
  }

  function render() {
    ORDER.forEach((pos) => {
      const row = pitch.querySelector(`[data-pos="${pos}"]`);
      row.innerHTML = "";
      slots[pos].forEach((id, index) => {
        const wrap = document.createElement("div");
        wrap.className = "shirt-card";
        const btn = document.createElement("button");
        btn.type = "button";
        const p = id ? byId[id] : null;
        if (p) {
          const avail = p.availability || "ok";
          btn.className =
            "shirt filled jersey avail-" +
            avail +
            (outPlayer && outPlayer.id === p.id ? " is-out" : "");
          btn.innerHTML = shirtHtml(p);
          if (p.news) btn.title = p.news;
          btn.addEventListener("click", () => openPlayerDetail(p, { pos, index }));
        } else {
          btn.className = "shirt empty jersey-empty";
          btn.innerHTML = `<span class="plus">+</span><span class="shirt-hint">${pos}</span>`;
          if (!LOCKED) {
            btn.addEventListener("click", () => openPicker(pos, index, "add"));
          } else {
            btn.disabled = true;
          }
        }
        wrap.appendChild(btn);
        row.appendChild(wrap);
      });
    });
    refreshMeta();
  }

  function openPicker(pos, index, mode) {
    active = { pos, index };
    pickerMode = mode;
    const current = slots[pos][index] ? byId[slots[pos][index]] : null;
    if (mode === "transfer") {
      pickerEyebrow.textContent = "Transfer in";
      pickerPos.textContent = `Replace ${outPlayer?.name || ""}`;
    } else if (mode === "replace") {
      pickerEyebrow.textContent = "Replace";
      pickerPos.textContent = current ? `Swap ${current.name}` : pos;
    } else {
      pickerEyebrow.textContent = "Add player";
      pickerPos.textContent = pos;
    }
    picker.hidden = false;
    search.value = "";
    filterTeam.value = "";
    filterMaxPrice.value = "";
    search.focus();
    renderPicker();
  }

  function closePicker() {
    picker.hidden = true;
  }

  function renderPicker() {
    if (!active) return;
    const q = search.value.trim().toLowerCase();
    const team = filterTeam.value;
    const maxP = filterMaxPrice.value ? Number(filterMaxPrice.value) : null;
    const currentId = slots[active.pos][active.index];
    const excludeForClub = pickerMode === "transfer" && outPlayer ? outPlayer.id : currentId;
    const taken = new Set(filledIds());
    if (excludeForClub) taken.delete(excludeForClub);
    const clubs = clubCounts(excludeForClub);

    const items = PLAYERS.filter((p) => {
      if (p.position !== active.pos) return false;
      if (taken.has(p.id)) return false;
      if (team && p.team !== team) return false;
      if (maxP != null && p.price > maxP) return false;
      if (q && !`${p.name} ${p.team} ${p.club || ""}`.toLowerCase().includes(q)) return false;
      return true;
    }).sort((a, b) => {
      const aBlocked = (clubs[a.team] || 0) >= MAX_CLUB ? 1 : 0;
      const bBlocked = (clubs[b.team] || 0) >= MAX_CLUB ? 1 : 0;
      if (aBlocked !== bBlocked) return aBlocked - bBlocked;
      return b.price - a.price || a.name.localeCompare(b.name);
    });

    pickerList.innerHTML = "";
    if (!items.length) {
      pickerList.innerHTML = `<li class="empty-pick">No players match.</li>`;
      return;
    }

    items.forEach((p) => {
      const clubN = clubs[p.team] || 0;
      const clubBlocked = clubN >= MAX_CLUB;
      const li = document.createElement("li");
      li.className = "pick-row-wrap";
      const clubNote = clubBlocked
        ? `<span class="club-limit">3/${MAX_CLUB} club</span>`
        : clubN > 0
          ? `<span class="muted tiny"> · ${clubN}/${MAX_CLUB}</span>`
          : "";
      const flag =
        p.availability === "out" ? "OUT" : p.availability === "doubt" ? "DOUBT" : "";
      li.innerHTML = `
        <button type="button" class="pick-row avail-${p.availability || "ok"}${clubBlocked ? " is-blocked" : ""}" ${clubBlocked ? "disabled" : ""}>
          <img class="pick-jersey" src="${p.shirt || ""}" alt="" width="28" height="37" loading="lazy" />
          <span class="pick-main">
            <span class="pick-name">${p.name}</span>
            <span class="pick-sub">${p.team}${flag ? ` · ${flag}` : ""}${clubNote}</span>
          </span>
          <span class="pick-price">£${p.price.toFixed(1)}</span>
        </button>
        <button type="button" class="pick-info-btn" aria-label="Player info">ⓘ</button>
      `;
      const btn = li.querySelector(".pick-row");
      const info = li.querySelector(".pick-info-btn");
      if (!clubBlocked) {
        btn.addEventListener("click", () => pickPlayer(p));
      }
      info.addEventListener("click", (e) => {
        e.stopPropagation();
        openPlayerDetail(p, {
          fromPicker: !clubBlocked,
          pos: active.pos,
          index: active.index,
        });
      });
      pickerList.appendChild(li);
    });
  }

  function pickPlayer(p) {
    if (!active) return;
    const currentId = slots[active.pos][active.index];
    const currentPrice = byId[currentId]?.price || 0;

    if (pickerMode === "transfer") {
      if (spend() - (outPlayer?.price || 0) + p.price > BUDGET + 1e-9) {
        alert("Not enough budget for that transfer");
        return;
      }
      inPlayer = p;
      closePicker();
      refreshSwapBar();
      render();
      return;
    }

    if (spend() - currentPrice + p.price > BUDGET + 1e-9) {
      alert("Not enough budget");
      return;
    }
    if ((clubCounts(currentId)[p.team] || 0) >= MAX_CLUB) {
      alert(`Max ${MAX_CLUB} players from ${p.team}`);
      return;
    }
    slots[active.pos][active.index] = p.id;
    outPlayer = null;
    inPlayer = null;
    closePicker();
    render();
  }

  if (closeDetailBtn) {
    closeDetailBtn.addEventListener("click", closeDetail);
  }
  if (playerDetail) {
    playerDetail.addEventListener("click", (e) => {
      if (e.target === playerDetail) closeDetail();
    });
  }

  if (!LOCKED) {
    document.getElementById("closePicker").addEventListener("click", closePicker);
    picker.addEventListener("click", (e) => {
      if (e.target === picker) closePicker();
    });
    search.addEventListener("input", renderPicker);
    filterTeam.addEventListener("change", renderPicker);
    filterMaxPrice.addEventListener("change", renderPicker);

    if (clearSwapBtn) {
      clearSwapBtn.addEventListener("click", () => {
        outPlayer = null;
        inPlayer = null;
        render();
      });
    }

    document.querySelectorAll("[data-browse]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const pos = btn.getAttribute("data-browse");
        const idx = slots[pos].findIndex((x) => x == null);
        const index = idx >= 0 ? idx : 0;
        if (slots[pos][index] == null) {
          openPicker(pos, index, "add");
        } else if (freeEdit()) {
          openPicker(pos, index, "replace");
        } else {
          outPlayer = byId[slots[pos][index]];
          inPlayer = null;
          openPicker(pos, index, "transfer");
        }
      });
    });

    if (squadForm) {
      squadForm.addEventListener("submit", (e) => {
        if (!freeEdit()) {
          e.preventDefault();
          alert("Use Confirm swap for transfers this week.");
          return;
        }
        const ids = ORDER.flatMap((pos) => slots[pos]);
        if (ids.some((x) => x == null)) {
          e.preventDefault();
          alert("Fill all 15 slots (2 GK, 5 DEF, 5 MID, 3 ATT).");
          return;
        }
        syncHidden();
      });
    }
  }

  if (!PLAYERS.length) {
    modeHint.textContent =
      "No players loaded — go Home and tap Refresh players from FPL.";
  }

  render();
})();
