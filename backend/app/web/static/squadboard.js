(() => {
  const PLAYERS = JSON.parse(document.getElementById("playersData").textContent);
  const INITIAL = JSON.parse(document.getElementById("initialSquad").textContent);
  const BUDGET = Number(INITIAL.budget);
  const MAX_CLUB = Number(INITIAL.maxPerClub || 3);
  const UNLIMITED = Boolean(INITIAL.unlimited);
  const LOCKED = Boolean(INITIAL.locked);
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

  let active = null; // { pos, index }
  let outPlayer = null;
  let inPlayer = null;
  let pickerMode = "add"; // add | replace

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
    return `
      <img class="jersey-img" src="${img}" alt="${p.team} kit" width="66" height="87" loading="lazy" decoding="async" />
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
    const canFree = freeEdit();
    if (canFree) {
      modeHint.textContent = isComplete()
        ? `Unlimited changes — tap a player to replace (${PLAYERS.length} in catalogue).`
        : `Tap empty slots to open the player list (${PLAYERS.length} players).`;
      if (saveSquadBtn) saveSquadBtn.hidden = false;
      if (buildActions) buildActions.style.display = "";
    } else {
      modeHint.textContent =
        `Tap a player to transfer out (${PLAYERS.length} in catalogue), then Confirm swap.`;
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
      swapSummary.textContent = `${outPlayer.name} → ${inPlayer.name} (${sign})`;
    } else {
      inIdEl.value = "";
      confirmSwap.disabled = true;
      swapSummary.textContent = `Out: ${outPlayer.name} — choose who comes in`;
    }
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
          btn.addEventListener("click", () => onFilledTap(pos, index, p));
        } else {
          btn.className = "shirt empty jersey-empty";
          btn.innerHTML = `<span class="plus">+</span><span class="shirt-hint">${pos}</span>`;
          btn.addEventListener("click", () => openPicker(pos, index, "add"));
        }
        if (LOCKED) {
          btn.disabled = true;
          btn.style.pointerEvents = "none";
        }
        wrap.appendChild(btn);
        row.appendChild(wrap);
      });
    });
    refreshMeta();
  }

  function onFilledTap(pos, index, player) {
    if (LOCKED) return;
    if (freeEdit()) {
      openPicker(pos, index, "replace");
      return;
    }
    outPlayer = player;
    inPlayer = null;
    active = { pos, index };
    openPicker(pos, index, "transfer");
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
      if (q && !`${p.name} ${p.team}`.toLowerCase().includes(q)) return false;
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
      const clubNote = clubBlocked
        ? `<span class="club-limit">3/${MAX_CLUB} club</span>`
        : clubN > 0
          ? `<span class="muted tiny"> · ${clubN}/${MAX_CLUB}</span>`
          : "";
      li.innerHTML = `<button type="button" class="pick-row avail-${p.availability || "ok"}${clubBlocked ? " is-blocked" : ""}" ${clubBlocked ? "disabled" : ""}>
        <img class="pick-jersey" src="${p.shirt || ""}" alt="" width="36" height="47" loading="lazy" />
        <span class="grow"><strong>${p.name}</strong> <span class="muted">${p.team}</span>${clubNote}</span>
        <span>£${p.price.toFixed(1)}m</span>
      </button>`;
      const btn = li.querySelector("button");
      if (!clubBlocked) {
        btn.addEventListener("click", () => pickPlayer(p));
      }
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
