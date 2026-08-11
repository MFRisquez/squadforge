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
  const clearSwapBtn = document.getElementById("clearSwap");
  const squadForm = document.getElementById("squadForm");
  const transferRailList = document.getElementById("transferRailList");
  const transferRailTitle = document.getElementById("transferRailTitle");
  const transferSort = document.getElementById("transferSort");
  const playerDetail = document.getElementById("playerDetail");
  const detailEyebrow = document.getElementById("detailEyebrow");
  const detailName = document.getElementById("detailName");
  const detailPhoto = document.getElementById("detailPhoto");
  const detailBody = document.getElementById("detailBody");
  const detailActions = document.getElementById("detailActions");
  const closeDetailBtn = document.getElementById("closeDetail");

  let starterIds = new Set(); // unused on Squad — lineup lives on /lineup
  let captainId = null;
  let viceId = null;

  let active = null; // { pos, index }
  let outPlayer = null;
  let inPlayer = null;
  let removedSlot = null; // { pos, index } while a transfer is pending
  let pickerMode = "add"; // add | replace | transfer
  let detailContext = null; // { player, fromPicker, pos, index }
  let scrollLockY = 0;
  let baselineSig = null;
  let baselineTd = "";
  let saveVisual = "idle"; // idle | dirty | saved | saving

  const SAVE_ICO = {
    idle: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zm-5 16a3 3 0 1 1 0-6 3 3 0 0 1 0 6zm3-10H5V5h10v4z"/></svg>`,
    dirty: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>`,
    saved: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z"/></svg>`,
    saving: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 4a8 8 0 1 0 8 8h-2a6 6 0 1 1-6-6V4z"/></svg>`,
  };

  function tdSelect() {
    return document.getElementById("tdClub");
  }

  function currentTd() {
    const sel = tdSelect();
    return sel && sel.value ? String(sel.value) : "";
  }

  function squadSignature() {
    return filledIds()
      .map(Number)
      .sort((a, b) => a - b)
      .join(",");
  }

  function squadDirty() {
    if (baselineSig == null) return false;
    return squadSignature() !== baselineSig;
  }

  function tdDirty() {
    const sel = tdSelect();
    if (!sel || sel.disabled) return false;
    const value = currentTd();
    if (!value) return false;
    return value !== baselineTd;
  }

  function isDirty() {
    return squadDirty() || tdDirty();
  }

  function canSaveSquadPlayers() {
    return freeEdit() && isComplete() && squadDirty() && !outPlayer && spend() <= BUDGET + 0.001;
  }

  function canSave() {
    if (LOCKED || outPlayer) return false;
    if (tdDirty() && !squadDirty()) return true;
    return canSaveSquadPlayers();
  }

  function paintSaveBtn() {
    if (!saveSquadBtn || LOCKED) return;
    const dirty = isDirty();
    let state = saveVisual;
    if (state !== "saving") {
      if (dirty) state = "dirty";
      else if (saveVisual === "saved") state = "saved";
      else state = "idle";
    }
    saveVisual = state;
    saveSquadBtn.classList.remove("is-idle", "is-dirty", "is-saved", "is-saving");
    saveSquadBtn.classList.add(`is-${state}`);
    saveSquadBtn.hidden = false;
    const ico = saveSquadBtn.querySelector(".pitch-save-ico");
    const label = saveSquadBtn.querySelector(".pitch-save-label");
    if (ico) ico.innerHTML = SAVE_ICO[state] || SAVE_ICO.idle;
    if (label) {
      label.textContent = state === "saved" ? "Saved" : state === "saving" ? "Saving…" : "Save";
    }
    if (state === "dirty") {
      saveSquadBtn.disabled = !canSave();
      saveSquadBtn.setAttribute(
        "aria-label",
        tdDirty() && !squadDirty() ? "Unsaved DT change" : "Unsaved squad changes"
      );
    } else if (state === "saved") {
      saveSquadBtn.disabled = true;
      saveSquadBtn.setAttribute("aria-label", "Saved");
    } else if (state === "saving") {
      saveSquadBtn.disabled = true;
      saveSquadBtn.setAttribute("aria-label", "Saving");
    } else {
      saveSquadBtn.disabled = true;
      saveSquadBtn.setAttribute("aria-label", "Save squad");
    }
  }

  function previewTdSelection(select) {
    const club = select && select.value;
    if (!club) return;
    const corner = document.querySelector(".td-corner");
    if (!corner) return;
    const meta = corner.querySelector(".td-corner-meta");
    if (!meta) return;
    const kicker = meta.querySelector(".td-kicker");
    if (kicker) kicker.textContent = club;
    const windowEl = meta.querySelector(".td-window");
    if (windowEl) windowEl.textContent = "Tap Save";
  }

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

  function shortName(name) {
    const parts = String(name || "").trim().split(/\s+/);
    if (parts.length <= 1) return parts[0] || "";
    return parts[parts.length - 1];
  }

  function shirtHtml(p) {
    const avail = p.availability || "ok";
    const flag = avail === "out" ? "OUT" : avail === "doubt" ? "!" : "";
    const img = p.shirt || "";
    const fdr = p.fdr;
    let footHtml;
    if (fdr) {
      const venue = fdr.venue === "H" ? "H" : "A";
      footHtml = `<span class="shirt-foot shirt-opp fdr-${fdr.difficulty}">${fdr.opponent} (${venue})</span>`;
    } else {
      footHtml = `<span class="shirt-foot shirt-opp">TBD</span>`;
    }
    return `
      <span class="shirt-kit">
        <img class="jersey-img" src="${img}" alt="${p.team} kit" width="66" height="87" loading="lazy" decoding="async" />
        ${flag ? `<span class="shirt-status-flag" title="${p.news || flag}">${flag}</span>` : ""}
        <span class="shirt-overlay">
          <span class="shirt-nameplate">${shortName(p.name)}</span>
          ${footHtml}
        </span>
      </span>
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
      if (modeHint) modeHint.textContent = "Gameweek locked.";
      if (saveSquadBtn) saveSquadBtn.hidden = true;
      syncHidden();
      refreshSwapBar();
      return;
    }
    const canFree = freeEdit();
    if (canFree) {
      if (modeHint) {
        modeHint.textContent = isComplete()
          ? "Squad full — tap a player to transfer them out."
          : "Tap empty slots to build your 15.";
      }
    } else if (outPlayer && !inPlayer) {
      if (modeHint) {
        modeHint.textContent = `${outPlayer.name} out — pick a ${outPlayer.position} from the list.`;
      }
    } else if (outPlayer && inPlayer) {
      if (modeHint) {
        modeHint.textContent = `Confirm ${outPlayer.name} → ${inPlayer.name} below, or cancel.`;
      }
    } else {
      if (modeHint) {
        modeHint.textContent =
          FT_LEFT < 1
            ? `Tap a player → Transfer out (−${HIT_COST} hit). Or play WC / FH.`
            : "Tap a player to transfer them out.";
      }
    }
    syncHidden();
    refreshSwapBar();
    paintSaveBtn();
    paintTransferRail();
  }

  function formScore(p) {
    const n = Number(p?.form);
    return Number.isFinite(n) ? n : 0;
  }

  function pointsScore(p) {
    const n = Number(p?.total_points);
    return Number.isFinite(n) ? n : 0;
  }

  function railSortKey() {
    const v = transferSort && transferSort.value;
    return v === "form" || v === "price" || v === "points" ? v : "points";
  }

  function sortRailPlayers(rows) {
    const key = railSortKey();
    return rows.slice().sort((a, b) => {
      if (a.locked !== b.locked) return a.locked ? 1 : -1;
      if (key === "form") {
        return formScore(b) - formScore(a) || pointsScore(b) - pointsScore(a) || b.price - a.price;
      }
      if (key === "price") {
        return b.price - a.price || pointsScore(b) - pointsScore(a) || formScore(b) - formScore(a);
      }
      return pointsScore(b) - pointsScore(a) || formScore(b) - formScore(a) || b.price - a.price;
    });
  }

  function railContext() {
    const bank = BUDGET - spend();
    if (outPlayer && removedSlot && !freeEdit()) {
      return {
        mode: "transfer",
        pos: outPlayer.position,
        // Slot already empty, so bank already includes the freed cash.
        maxPrice: bank + 1e-9,
        excludeId: outPlayer.id,
        title: `In for ${shortName(outPlayer.name)}`,
      };
    }
    if (freeEdit() && active && slots[active.pos][active.index] == null) {
      return {
        mode: "add",
        pos: active.pos,
        maxPrice: bank + 1e-9,
        excludeId: null,
        title: `${active.pos} options`,
      };
    }
    if (freeEdit() && !isComplete()) {
      return {
        mode: "browse",
        pos: null,
        maxPrice: bank + 1e-9,
        excludeId: null,
        title: "Add players",
      };
    }
    return {
      mode: "browse",
      pos: null,
      maxPrice: null,
      excludeId: null,
      title: "Top players",
    };
  }

  function transferCandidates() {
    const ctx = railContext();
    const owned = new Set(filledIds());
    if (ctx.excludeId) owned.delete(ctx.excludeId);
    const counts = clubCounts(ctx.excludeId);
    const lockBudget = ctx.maxPrice != null;
    const rows = PLAYERS.filter((p) => {
      if (!p || owned.has(p.id)) return false;
      if (ctx.pos && p.position !== ctx.pos) return false;
      return true;
    }).map((p) => {
      const clubBlocked = (counts[p.team] || 0) >= MAX_CLUB;
      const budgetBlocked = lockBudget && p.price > ctx.maxPrice;
      return {
        ...p,
        locked: clubBlocked || budgetBlocked,
        lockReason: clubBlocked
          ? `Max ${MAX_CLUB} from ${p.team}`
          : budgetBlocked
            ? "Over budget"
            : "",
      };
    });
    return sortRailPlayers(rows).slice(0, 24);
  }

  function paintTransferRail() {
    if (!transferRailList) return;
    const ctx = railContext();
    const rows = transferCandidates();
    if (transferRailTitle) transferRailTitle.textContent = ctx.title;
    transferRailList.innerHTML = "";
    if (!rows.length) {
      const empty = document.createElement("li");
      empty.className = "muted tiny fx-rail-empty";
      empty.textContent = LOCKED
        ? "Squad locked this GW."
        : ctx.pos
          ? `No ${ctx.pos} options right now.`
          : "No players to show.";
      transferRailList.appendChild(empty);
      return;
    }
    rows.forEach((p) => {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className =
        "transfer-rail-row" +
        (inPlayer && inPlayer.id === p.id ? " is-selected" : "") +
        (p.locked ? " is-locked" : "");
      btn.disabled = Boolean(p.locked);
      if (p.lockReason) btn.title = p.lockReason;
      const metric =
        railSortKey() === "form"
          ? formScore(p).toFixed(1)
          : railSortKey() === "price"
            ? `£${Number(p.price).toFixed(1)}`
            : String(pointsScore(p));
      btn.innerHTML = `
        <span class="tr-name">
          <strong>${p.name}</strong>
          <span>${p.team} · ${p.position}${p.lockReason ? ` · ${p.lockReason}` : ""}</span>
        </span>
        <span class="tr-metric">${metric}</span>
        <span class="tr-price">£${Number(p.price).toFixed(1)}</span>
      `;
      if (!p.locked) btn.addEventListener("click", () => pickFromTransferRail(p));
      li.appendChild(btn);
      transferRailList.appendChild(li);
    });
  }

  function pickFromTransferRail(p) {
    if (LOCKED || !p || p.locked) return;
    if (outPlayer && !freeEdit()) {
      const slot = removedSlot;
      if (!slot) {
        alert("Pick who to transfer out first.");
        return;
      }
      active = { pos: slot.pos, index: slot.index };
      pickerMode = "transfer";
      pickPlayer(p);
      return;
    }
    if (freeEdit()) {
      let target = active && slots[active.pos][active.index] == null ? active : null;
      if (!target) {
        const idx = slots[p.position].findIndex((id) => id == null);
        if (idx < 0) return;
        target = { pos: p.position, index: idx };
      }
      if (p.position !== target.pos) return;
      active = target;
      pickerMode = "add";
      pickPlayer(p);
      return;
    }
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
      swapSummary.textContent = `${outPlayer.name} out${hitHint} — tap empty ${outPlayer.position} slot to search`;
    }
  }

  function clearPendingTransfer() {
    if (removedSlot && outPlayer) {
      slots[removedSlot.pos][removedSlot.index] = outPlayer.id;
    }
    outPlayer = null;
    inPlayer = null;
    removedSlot = null;
    active = null;
    render();
  }

  function removeFromSquad(pos, index) {
    const id = slots[pos][index];
    if (!id || LOCKED) return;
    const p = byId[id];
    if (!p) return;

    if (freeEdit()) {
      slots[pos][index] = null;
      outPlayer = null;
      inPlayer = null;
      removedSlot = null;
      active = { pos, index };
      pickerMode = "add";
      closeDetail();
      render();
      return;
    }

    if (outPlayer && (!removedSlot || removedSlot.pos !== pos || removedSlot.index !== index)) {
      alert("Finish or cancel the current transfer first.");
      return;
    }

    outPlayer = p;
    inPlayer = null;
    removedSlot = { pos, index };
    active = { pos, index };
    pickerMode = "transfer";
    slots[pos][index] = null;
    closeDetail();
    render();
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

  function setDetailPhoto(p) {
    if (!detailPhoto) return;
    detailPhoto.onerror = null;
    const chain = p
      ? [p.photo, p.photoFallback, p.photoFallback2].filter(Boolean)
      : [];
    if (chain.length) {
      detailPhoto.hidden = false;
      detailPhoto.alt = (p && p.name) || "";
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
    setDetailPhoto(p);
    const club = p.club || p.team;
    const chance =
      p.chance == null || p.chance === ""
        ? "—"
        : `${p.chance}%`;
    const news = (p.news || "").trim();
    const avail = p.availability || "ok";
    const fdr = p.fdr;
    const fixtureLine = fdr
      ? `${fdr.opponent} (${fdr.venue === "H" ? "H" : "A"})`
      : "TBD";
    detailBody.innerHTML = `
      <div class="player-detail-hero player-detail-hero-meta">
        <div class="meta">
          <strong>${club}</strong>
          <span class="muted">${p.position} · vs ${fixtureLine}</span>
          <span class="avail-text-${(p.availability || "ok") === "ok" ? "ok" : p.availability || "ok"}">${statusLabel(p)}</span>
        </div>
      </div>
      <div class="player-detail-facts">
        <div class="fact fact-price"><span>Price</span><strong>£${Number(p.price).toFixed(1)}m</strong></div>
        <div class="fact"><span>Club</span><strong>${club}</strong></div>
        <div class="fact"><span>Status</span><strong>${statusLabel(p)}</strong></div>
        <div class="fact"><span>Chance next</span><strong>${chance}</strong></div>
      </div>
      <div class="kpi-block">
        <div class="player-fdr-head">
          <strong>Season stats</strong>
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
          pickerMode === "transfer"
            ? "Transfer in"
            : pickerMode === "replace"
              ? "Select player"
              : "Add to squad";
        select.addEventListener("click", () => {
          closeDetail();
          pickPlayer(p);
        });
        detailActions.appendChild(select);
      } else if (opts.pos != null && opts.index != null) {
        const transferBtn = document.createElement("button");
        transferBtn.type = "button";
        transferBtn.className = "btn danger-btn transfer-out-btn";
        transferBtn.textContent = freeEdit() ? "Transfer out" : "Transfer out";
        transferBtn.addEventListener("click", () => removeFromSquad(opts.pos, opts.index));
        detailActions.appendChild(transferBtn);

        const hint = document.createElement("p");
        hint.className = "muted tiny transfer-hint";
        hint.textContent = freeEdit()
          ? "Removes them, then opens the player search for this slot."
          : !UNLIMITED && FT_LEFT < 1
            ? `Uses a hit (−${HIT_COST}) if you have no free transfers.`
            : "Opens search to bring someone into this slot.";
        detailActions.appendChild(hint);

        const toLineup = document.createElement("a");
        toLineup.className = "btn ghost";
        toLineup.href = "/lineup";
        toLineup.textContent = "Set XI";
        detailActions.appendChild(toLineup);
      }
    } else {
      const lockedNote = document.createElement("p");
      lockedNote.className = "muted tiny";
      lockedNote.textContent = "Transfers locked for this gameweek.";
      detailActions.appendChild(lockedNote);
    }
    if (playerDetail.parentElement !== document.body) {
      document.body.appendChild(playerDetail);
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
          setDetailPhoto(detailContext.player);
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
        wrap.className = "shirt-card xi-card squad-card";
        const btn = document.createElement("button");
        btn.type = "button";
        const p = id ? byId[id] : null;
        if (p) {
          const avail = p.availability || "ok";
          const pendingIn =
            inPlayer &&
            removedSlot &&
            removedSlot.pos === pos &&
            removedSlot.index === index &&
            inPlayer.id === p.id;
          btn.className =
            "shirt filled jersey xi-shirt squad-shirt avail-" +
            avail +
            (pendingIn ? " is-pending-in" : "");
          btn.innerHTML = shirtHtml(p);
          if (p.news) btn.title = p.news;
          btn.addEventListener("click", () => {
            if (pendingIn) {
              active = { pos, index };
              pickerMode = "transfer";
              paintTransferRail();
              return;
            }
            openPlayerDetail(p, { pos, index });
          });
        } else {
          const waitingTransfer =
            outPlayer && removedSlot && removedSlot.pos === pos && removedSlot.index === index;
          btn.className =
            "shirt empty jersey-empty xi-shirt squad-shirt" +
            (waitingTransfer ? " is-transfer-slot" : "");
          btn.innerHTML = waitingTransfer
            ? `<span class="plus">+</span><span class="shirt-hint">IN</span>`
            : `<span class="plus">+</span><span class="shirt-hint">${pos}</span>`;
          if (!LOCKED) {
            btn.addEventListener("click", () => {
              if (outPlayer && !freeEdit()) {
                if (pos !== outPlayer.position) {
                  alert(`Pick a ${outPlayer.position} to replace ${outPlayer.name}.`);
                  return;
                }
                active = { pos, index };
                pickerMode = "transfer";
                paintTransferRail();
                return;
              }
              active = { pos, index };
              pickerMode = "add";
              paintTransferRail();
            });
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

  function lockScroll() {
    scrollLockY = window.scrollY || window.pageYOffset || 0;
    document.body.classList.add("picker-open");
    document.body.style.top = `-${scrollLockY}px`;
  }

  function unlockScroll() {
    document.body.classList.remove("picker-open");
    document.body.style.top = "";
    window.scrollTo(0, scrollLockY);
  }

  function restorePitchView() {
    unlockScroll();
    const target =
      (active &&
        pitch.querySelector(`[data-pos="${active.pos}"]`)?.children?.[active.index]) ||
      pitch;
    if (target && typeof target.scrollIntoView === "function") {
      requestAnimationFrame(() => {
        target.scrollIntoView({ block: "center", behavior: "auto" });
      });
    }
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
      pickerPos.textContent = `${pos} · search`;
    }
    lockScroll();
    picker.hidden = false;
    search.value = "";
    filterTeam.value = "";
    filterMaxPrice.value = "";
    renderPicker();
    requestAnimationFrame(() => {
      try {
        search.focus({ preventScroll: true });
      } catch (_) {
        search.focus();
      }
    });
  }

  function closePicker() {
    picker.hidden = true;
    if (document.body.classList.contains("picker-open")) {
      unlockScroll();
    }
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
      const previewId =
        removedSlot != null ? slots[removedSlot.pos][removedSlot.index] : currentId;
      const baseSpend = filledIds().reduce((s, id) => {
        if (previewId && id === previewId) return s;
        return s + (byId[id]?.price || 0);
      }, 0);
      if (baseSpend + p.price > BUDGET + 1e-9) {
        alert("Not enough budget for that transfer");
        return;
      }
      if ((clubCounts(outPlayer?.id)[p.team] || 0) >= MAX_CLUB) {
        alert(`Max ${MAX_CLUB} players from ${p.team}`);
        return;
      }
      inPlayer = p;
      slots[active.pos][active.index] = p.id;
      removedSlot = { pos: active.pos, index: active.index };
      picker.hidden = true;
      restorePitchView();
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
    removedSlot = null;
    picker.hidden = true;
    restorePitchView();
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
      clearSwapBtn.addEventListener("click", () => clearPendingTransfer());
    }
    if (transferSort) {
      transferSort.addEventListener("change", () => paintTransferRail());
    }

    if (squadForm) {
      squadForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const needSquad = squadDirty();
        const needTd = tdDirty();
        if (!needSquad && !needTd) return;
        if (outPlayer) {
          alert("Finish or cancel the transfer first.");
          return;
        }
        if (needSquad) {
          if (!freeEdit()) {
            alert("Use Confirm swap for transfers this week.");
            return;
          }
          if (!isComplete()) {
            alert("Fill all 15 slots (2 GK, 5 DEF, 5 MID, 3 ATT).");
            return;
          }
          if (spend() > BUDGET + 0.001) {
            alert("Squad is over budget.");
            return;
          }
        }
        syncHidden();
        saveVisual = "saving";
        paintSaveBtn();
        try {
          if (needSquad) {
            const body = new URLSearchParams();
            filledIds().forEach((id) => body.append("player_id", String(id)));
            const res = await fetch("/team/save?format=json", {
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
              throw new Error("Could not save squad — try again");
            }
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data.error || !data.ok) {
              throw new Error(data.error || "Could not save squad");
            }
            baselineSig = squadSignature();
            INITIAL.hasSquad = true;
            INITIAL.selected = filledIds().slice();
          }
          if (needTd) {
            await saveTdClub(tdSelect());
            baselineTd = currentTd();
          }
          saveVisual = "saved";
          paintSaveBtn();
        } catch (err) {
          saveVisual = "dirty";
          paintSaveBtn();
          alert(err.message || "Could not save");
        }
      });
    }
  }

  if (!PLAYERS.length && modeHint) {
    modeHint.textContent =
      "No players loaded — go Home and tap Refresh players from FPL.";
  }

  function paintTdCorner(info) {
    const corner = document.querySelector(".td-corner");
    if (!corner || !info || !info.club_code) return;

    let badge = corner.querySelector(".td-badge");
    if (info.badge) {
      if (!badge) {
        badge = document.createElement("img");
        badge.className = "td-badge";
        badge.width = 56;
        badge.height = 56;
        corner.insertBefore(badge, corner.firstChild);
      }
      badge.src = info.badge;
      badge.alt = `${info.club_code} badge`;
      badge.hidden = false;
    } else if (badge) {
      badge.hidden = true;
    }

    let meta = corner.querySelector(".td-corner-meta");
    if (!meta) {
      meta = document.createElement("div");
      meta.className = "td-corner-meta";
      const selectEl = corner.querySelector("#tdClub");
      if (selectEl) corner.insertBefore(meta, selectEl);
      else corner.appendChild(meta);
    }
    const foot = info.fixture_line
      ? `<span class="td-foot fdr-${info.fixture_fdr || 3}">${info.fixture_line}</span>`
      : info.start_gw
        ? `<span class="td-window">GW${info.start_gw}–${info.end_gw}</span>`
        : "";
    meta.innerHTML = `
      <span class="td-kicker">${info.club_code}</span>
      <strong>DT</strong>
      ${foot}
    `;

    const select = corner.querySelector("#tdClub");
    if (select) {
      select.value = info.club_code;
      // Drop placeholder once a club is chosen.
      const placeholder = select.querySelector('option[value=""]');
      if (placeholder) placeholder.remove();
    }

    let ban = corner.querySelector(".td-ban");
    if (info.banned_club) {
      if (!ban) {
        ban = document.createElement("p");
        ban.className = "td-ban muted tiny";
        corner.appendChild(ban);
      }
      ban.textContent = `Not ${info.banned_club} next`;
    } else if (ban) {
      ban.remove();
    }
  }

  async function saveTdClub(select) {
    const club = select && select.value;
    if (!club) throw new Error("Pick a DT club first");
    const corner = document.querySelector(".td-corner");
    select.disabled = true;
    if (corner) corner.classList.add("is-updating");
    try {
      const body = new URLSearchParams({ club_code: club });
      const res = await fetch("/td/save?format=json", {
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
        throw new Error("Could not update DT — try again");
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.error || !data.td) {
        throw new Error(data.error || "Could not update DT");
      }
      paintTdCorner(data.td);
      return data.td;
    } finally {
      select.disabled = false;
      if (corner) corner.classList.remove("is-updating");
    }
  }

  const tdForm = document.getElementById("tdForm");
  const tdCorner = document.querySelector(".td-corner");
  if (tdForm) {
    tdForm.addEventListener("submit", (e) => e.preventDefault());
  }
  if (tdCorner) {
    tdCorner.addEventListener("change", (e) => {
      const select = e.target && e.target.id === "tdClub" ? e.target : null;
      if (!select) return;
      previewTdSelection(select);
      saveVisual = "dirty";
      paintSaveBtn();
    });
  }

  baselineSig = squadSignature();
  baselineTd = currentTd();
  saveVisual = "idle";
  render();
})();
