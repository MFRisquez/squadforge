(() => {
  const PLAYERS = JSON.parse(document.getElementById("playersData").textContent);
  const INITIAL = JSON.parse(document.getElementById("initialSquad").textContent);
  const BUDGET = Number(INITIAL.budget);
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

  // hydrate
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

  const board = document.getElementById("slotBoard");
  const budgetValue = document.getElementById("budgetValue");
  const hiddenFields = document.getElementById("hiddenFields");
  const picker = document.getElementById("picker");
  const pickerList = document.getElementById("pickerList");
  const pickerPos = document.getElementById("pickerPos");
  const search = document.getElementById("playerSearch");
  const filterTeam = document.getElementById("filterTeam");
  const filterMaxPrice = document.getElementById("filterMaxPrice");
  let active = null; // { pos, index }

  function spend() {
    return ORDER.flatMap((pos) => slots[pos])
      .filter(Boolean)
      .reduce((s, id) => s + (byId[id]?.price || 0), 0);
  }

  function takenIds() {
    return new Set(ORDER.flatMap((pos) => slots[pos]).filter(Boolean));
  }

  function renderBudget() {
    const left = BUDGET - spend();
    budgetValue.textContent = `£${left.toFixed(1)}m`;
    budgetValue.classList.toggle("over", left < -0.01);
  }

  function syncHidden() {
    hiddenFields.innerHTML = "";
    ORDER.flatMap((pos) => slots[pos])
      .filter(Boolean)
      .forEach((id) => {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = "player_id";
        input.value = String(id);
        hiddenFields.appendChild(input);
      });
  }

  function render() {
    board.innerHTML = "";
    ORDER.forEach((pos) => {
      const section = document.createElement("section");
      section.className = "panel";
      section.innerHTML = `<h2>${pos} <span class="muted">(${NEED[pos]})</span></h2>`;
      const row = document.createElement("div");
      row.className = "slot-row";
      slots[pos].forEach((id, index) => {
        const p = id ? byId[id] : null;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "shirt " + (p ? "filled" : "empty");
        if (p) {
          const avail = p.availability || "ok";
          btn.className = "shirt filled avail-" + avail;
          const badge = avail === "out" ? "OUT" : avail === "doubt" ? "DOUBT" : "";
          btn.innerHTML = `<span class="shirt-price">£${p.price.toFixed(1)}</span><span class="shirt-name">${p.name}</span><span class="shirt-team">${p.team}${badge ? " · " + badge : ""}</span>`;
          if (p.news) btn.title = p.news;
          btn.addEventListener("click", () => {
            slots[pos][index] = null;
            render();
          });
        } else {
          btn.innerHTML = `<span class="plus">+</span><span class="shirt-hint">${pos}</span>`;
          btn.addEventListener("click", () => openPicker(pos, index));
        }
        row.appendChild(btn);
      });
      section.appendChild(row);
      board.appendChild(section);
    });
    renderBudget();
    syncHidden();
  }

  function openPicker(pos, index) {
    active = { pos, index };
    pickerPos.textContent = pos;
    picker.hidden = false;
    search.value = "";
    filterTeam.value = "";
    filterMaxPrice.value = "";
    search.focus();
    renderPicker();
  }

  function closePicker() {
    picker.hidden = true;
    active = null;
  }

  function renderPicker() {
    if (!active) return;
    const q = search.value.trim().toLowerCase();
    const team = filterTeam.value;
    const maxP = filterMaxPrice.value ? Number(filterMaxPrice.value) : null;
    const taken = takenIds();
    const items = PLAYERS.filter((p) => {
      if (p.position !== active.pos) return false;
      if (taken.has(p.id)) return false;
      if (team && p.team !== team) return false;
      if (maxP != null && p.price > maxP) return false;
      if (q && !`${p.name} ${p.team}`.toLowerCase().includes(q)) return false;
      return true;
    }).sort((a, b) => b.price - a.price || a.name.localeCompare(b.name));

    pickerList.innerHTML = "";
    if (!items.length) {
      pickerList.innerHTML = `<li class="empty-pick">No players match.</li>`;
      return;
    }
    items.forEach((p) => {
      const li = document.createElement("li");
      li.innerHTML = `<button type="button" class="pick-row avail-${p.availability || "ok"}"><span class="grow"><strong>${p.name}</strong> <span class="muted">${p.team}${p.availability === "doubt" ? " · doubtful" : p.availability === "out" ? " · out" : ""}${p.chance != null ? " · " + p.chance + "%" : ""}</span></span><span>£${p.price.toFixed(1)}m</span></button>`;
      li.querySelector("button").addEventListener("click", () => {
        if (spend() - (byId[slots[active.pos][active.index]]?.price || 0) + p.price > BUDGET + 1e-9) {
          alert("Not enough budget");
          return;
        }
        slots[active.pos][active.index] = p.id;
        closePicker();
        render();
      });
      pickerList.appendChild(li);
    });
  }

  document.getElementById("closePicker").addEventListener("click", closePicker);
  picker.addEventListener("click", (e) => {
    if (e.target === picker) closePicker();
  });
  search.addEventListener("input", renderPicker);
  filterTeam.addEventListener("change", renderPicker);
  filterMaxPrice.addEventListener("change", renderPicker);

  document.getElementById("squadForm").addEventListener("submit", (e) => {
    const ids = ORDER.flatMap((pos) => slots[pos]);
    if (ids.some((x) => x == null)) {
      e.preventDefault();
      alert("Fill all 15 slots (2 GK, 5 DEF, 5 MID, 3 ATT).");
      return;
    }
    syncHidden();
  });

  render();
})();
