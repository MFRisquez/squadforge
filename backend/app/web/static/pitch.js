(() => {
  const PLAYERS = JSON.parse(document.getElementById("playersData").textContent);
  const INITIAL = JSON.parse(document.getElementById("initialSquad").textContent);
  const BUDGET = Number(INITIAL.budget);

  const byId = Object.fromEntries(PLAYERS.map((p) => [p.id, p]));

  /** @type {{id:number, starter:boolean, captain:boolean}[]} */
  let squad = [];

  (INITIAL.selected || []).forEach((id) => {
    squad.push({
      id,
      starter: (INITIAL.starters || []).includes(id),
      captain: INITIAL.captain === id,
    });
  });

  const pitch = document.getElementById("pitch");
  const benchEl = document.getElementById("bench");
  const budgetValue = document.getElementById("budgetValue");
  const formationLabel = document.getElementById("formationLabel");
  const picker = document.getElementById("picker");
  const pickerList = document.getElementById("pickerList");
  const pickerPos = document.getElementById("pickerPos");
  const search = document.getElementById("playerSearch");
  const filterTeam = document.getElementById("filterTeam");
  const filterMaxPrice = document.getElementById("filterMaxPrice");
  const hiddenFields = document.getElementById("hiddenFields");
  const form = document.getElementById("squadForm");
  const wildcardToggle = document.getElementById("wildcardToggle");
  const playWildcard = document.getElementById("playWildcard");

  let activeSlot = null; // { position, starter, index }

  const NEED = { GK: 2, DEF: 5, MID: 5, ATT: 3 };
  const STARTER_BAND = { GK: [1, 1], DEF: [3, 5], MID: [3, 5], ATT: [1, 3] };

  function spend() {
    return squad.reduce((s, row) => s + (byId[row.id]?.price || 0), 0);
  }

  function counts(starterOnly = false) {
    const c = { GK: 0, DEF: 0, MID: 0, ATT: 0 };
    squad.forEach((row) => {
      if (starterOnly && !row.starter) return;
      const p = byId[row.id];
      if (p) c[p.position] += 1;
    });
    return c;
  }

  function remainingFor(pos) {
    return NEED[pos] - counts(false)[pos];
  }

  function renderBudget() {
    const left = BUDGET - spend();
    budgetValue.textContent = `£${left.toFixed(1)}m`;
    budgetValue.classList.toggle("over", left < -0.01);
  }

  function starterIds() {
    return squad.filter((r) => r.starter).map((r) => r.id);
  }

  function formationText() {
    const c = counts(true);
    if (c.GK + c.DEF + c.MID + c.ATT === 0) return "Formation —";
    return `Formation ${c.DEF}-${c.MID}-${c.ATT}`;
  }

  function slotButton(player, { emptyLabel, onClick, onRemove, isCaptain }) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "shirt" + (player ? " filled" : " empty");
    if (player) {
      btn.innerHTML = `
        <span class="shirt-price">£${player.price.toFixed(1)}</span>
        <span class="shirt-name">${player.name}</span>
        <span class="shirt-team">${player.team}${isCaptain ? " · C" : ""}</span>
      `;
      btn.addEventListener("click", onRemove);
    } else {
      btn.innerHTML = `<span class="plus">+</span><span class="shirt-hint">${emptyLabel}</span>`;
      btn.addEventListener("click", onClick);
    }
    return btn;
  }

  function renderPitch() {
    const starters = squad.filter((r) => r.starter).map((r) => byId[r.id]).filter(Boolean);
    const byPos = { GK: [], DEF: [], MID: [], ATT: [] };
    starters.forEach((p) => byPos[p.position].push(p));

    const rows = {
      gk: pitch.querySelector('[data-row="gk"]'),
      def: pitch.querySelector('[data-row="def"]'),
      mid: pitch.querySelector('[data-row="mid"]'),
      att: pitch.querySelector('[data-row="att"]'),
    };
    Object.values(rows).forEach((el) => (el.innerHTML = ""));

    const paint = (rowKey, pos, maxSlots) => {
      const list = byPos[pos];
      const slots = Math.max(list.length, Math.min(maxSlots, Math.max(STARTER_BAND[pos][0], list.length || (pos === "GK" ? 1 : STARTER_BAND[pos][0]))));
      // Show up to max band so user can fill; prefer showing empty targets
      const show = pos === "GK" ? 1 : Math.max(STARTER_BAND[pos][0], Math.min(STARTER_BAND[pos][1], Math.max(list.length + (remainingFor(pos) > 0 && list.length < STARTER_BAND[pos][1] ? 1 : 0), STARTER_BAND[pos][0])));
      for (let i = 0; i < show; i++) {
        const player = list[i];
        rows[rowKey].appendChild(
          slotButton(player, {
            emptyLabel: pos,
            onClick: () => openPicker(pos, true),
            onRemove: () => removePlayer(player.id),
            isCaptain: player && squad.find((s) => s.id === player.id)?.captain,
          })
        );
      }
    };

    paint("gk", "GK", 1);
    paint("def", "DEF", 5);
    paint("mid", "MID", 5);
    paint("att", "ATT", 3);

    // Bench
    benchEl.innerHTML = "";
    const bench = squad.filter((r) => !r.starter);
    const benchNeed = NEED.GK + NEED.DEF + NEED.MID + NEED.ATT - 11;
    for (let i = 0; i < Math.max(4, bench.length); i++) {
      const row = bench[i];
      const player = row ? byId[row.id] : null;
      const posHint = !player
        ? counts(false).GK < 2
          ? "GK"
          : counts(false).DEF < 5
            ? "DEF"
            : counts(false).MID < 5
              ? "MID"
              : "ATT"
        : player.position;
      benchEl.appendChild(
        slotButton(player, {
          emptyLabel: posHint,
          onClick: () => openPicker(posHint, false),
          onRemove: () => removePlayer(player.id),
          isCaptain: false,
        })
      );
    }

    formationLabel.textContent = formationText();
    renderBudget();
    syncHidden();
  }

  function removePlayer(id) {
    squad = squad.filter((r) => r.id !== id);
    if (!squad.some((r) => r.captain) && squad.some((r) => r.starter)) {
      squad.find((r) => r.starter).captain = true;
    }
    renderPitch();
  }

  function openPicker(position, asStarter) {
    activeSlot = { position, starter: asStarter };
    pickerPos.textContent = `${position} · ${asStarter ? "Starting XI" : "Bench"}`;
    picker.hidden = false;
    search.value = "";
    filterTeam.value = "";
    filterMaxPrice.value = "";
    search.focus();
    renderPickerList();
  }

  function closePicker() {
    picker.hidden = true;
    activeSlot = null;
  }

  function renderPickerList() {
    if (!activeSlot) return;
    const q = search.value.trim().toLowerCase();
    const team = filterTeam.value;
    const maxP = filterMaxPrice.value ? Number(filterMaxPrice.value) : null;
    const taken = new Set(squad.map((r) => r.id));

    const items = PLAYERS.filter((p) => {
      if (p.position !== activeSlot.position) return false;
      if (taken.has(p.id)) return false;
      if (team && p.team !== team) return false;
      if (maxP != null && p.price > maxP + 1e-9) return false;
      if (q && !(`${p.name} ${p.team}`.toLowerCase().includes(q))) return false;
      return true;
    }).sort((a, b) => b.price - a.price || a.name.localeCompare(b.name));

    pickerList.innerHTML = "";
    if (!items.length) {
      pickerList.innerHTML = `<li class="empty-pick">No players match.</li>`;
      return;
    }
    items.forEach((p) => {
      const li = document.createElement("li");
      li.innerHTML = `
        <button type="button" class="pick-row">
          <span class="grow"><strong>${p.name}</strong> <span class="muted">${p.team}</span></span>
          <span>£${p.price.toFixed(1)}m</span>
        </button>`;
      li.querySelector("button").addEventListener("click", () => addPlayer(p));
      pickerList.appendChild(li);
    });
  }

  function addPlayer(player) {
    if (remainingFor(player.position) <= 0) {
      alert(`You already have ${NEED[player.position]} ${player.position}s.`);
      return;
    }
    if (spend() + player.price > BUDGET + 1e-9) {
      alert("Not enough budget.");
      return;
    }

    let asStarter = activeSlot?.starter;
    const sc = counts(true);
    if (asStarter) {
      const band = STARTER_BAND[player.position];
      if (sc[player.position] >= band[1]) {
        asStarter = false; // spill to bench
      }
      if (player.position !== "GK" && sc.GK + sc.DEF + sc.MID + sc.ATT >= 11) {
        asStarter = false;
      }
      if (player.position === "GK" && sc.GK >= 1) {
        asStarter = false;
      }
    }

    // Ensure we don't exceed 11 starters
    if (asStarter && starterIds().length >= 11) asStarter = false;

    const row = { id: player.id, starter: !!asStarter, captain: false };
    if (row.starter && !squad.some((r) => r.captain)) row.captain = true;
    squad.push(row);
    closePicker();
    renderPitch();
  }

  function syncHidden() {
    hiddenFields.innerHTML = "";
    squad.forEach((row) => {
      const a = document.createElement("input");
      a.type = "hidden";
      a.name = "player_id";
      a.value = String(row.id);
      hiddenFields.appendChild(a);
      if (row.starter) {
        const b = document.createElement("input");
        b.type = "hidden";
        b.name = "starter_id";
        b.value = String(row.id);
        hiddenFields.appendChild(b);
      }
      if (row.captain) {
        const c = document.createElement("input");
        c.type = "hidden";
        c.name = "captain_id";
        c.value = String(row.id);
        hiddenFields.appendChild(c);
      }
    });
  }

  // Long-press / double-click captain: click filled starter toggles captain via context
  pitch.addEventListener("contextmenu", (e) => {
    const shirt = e.target.closest(".shirt.filled");
    if (!shirt) return;
    e.preventDefault();
  });

  document.getElementById("closePicker").addEventListener("click", closePicker);
  picker.addEventListener("click", (e) => {
    if (e.target === picker) closePicker();
  });
  search.addEventListener("input", renderPickerList);
  filterTeam.addEventListener("change", renderPickerList);
  filterMaxPrice.addEventListener("change", renderPickerList);

  if (wildcardToggle) {
    wildcardToggle.addEventListener("change", () => {
      playWildcard.value = wildcardToggle.checked ? "1" : "0";
    });
  }

  form.addEventListener("submit", (e) => {
    const c = counts(false);
    const sc = counts(true);
    if (squad.length !== 15) {
      e.preventDefault();
      alert(`Need 15 players (have ${squad.length}).`);
      return;
    }
    for (const pos of Object.keys(NEED)) {
      if (c[pos] !== NEED[pos]) {
        e.preventDefault();
        alert(`Need ${NEED[pos]} ${pos} (have ${c[pos]}).`);
        return;
      }
    }
    if (starterIds().length !== 11) {
      e.preventDefault();
      alert("Need exactly 11 starters.");
      return;
    }
    for (const [pos, [lo, hi]] of Object.entries(STARTER_BAND)) {
      if (sc[pos] < lo || sc[pos] > hi) {
        e.preventDefault();
        alert(`Starters need ${lo}–${hi} ${pos} (have ${sc[pos]}).`);
        return;
      }
    }
    if (!squad.some((r) => r.captain && r.starter)) {
      e.preventDefault();
      alert("Pick a captain in the starting XI (click a starter, then use Set captain below — or we auto-assign first starter).");
      const first = squad.find((r) => r.starter);
      if (first) first.captain = true;
      syncHidden();
    }
    syncHidden();
  });

  // Tap filled starter to set captain
  pitch.addEventListener("click", (e) => {
    const shirt = e.target.closest(".shirt.filled");
    if (!shirt || !e.shiftKey) return;
  });

  // Dedicated: double-click sets captain
  pitch.addEventListener("dblclick", (e) => {
    const shirt = e.target.closest(".shirt.filled");
    if (!shirt) return;
    const name = shirt.querySelector(".shirt-name")?.textContent;
    const player = PLAYERS.find((p) => p.name === name && squad.some((s) => s.id === p.id && s.starter));
    if (!player) return;
    squad.forEach((r) => (r.captain = r.id === player.id));
    renderPitch();
  });

  renderPitch();
})();
