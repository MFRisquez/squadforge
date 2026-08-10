(() => {
  const PLAYERS = JSON.parse(document.getElementById("playersData").textContent);
  const OWNED = JSON.parse(document.getElementById("ownedData").textContent);
  const ownedIds = new Set(OWNED.map((p) => p.id));
  const byId = Object.fromEntries(PLAYERS.map((p) => [p.id, p]));

  const picker = document.getElementById("picker");
  const pickerList = document.getElementById("pickerList");
  const pickerPos = document.getElementById("pickerPos");
  const search = document.getElementById("playerSearch");
  const filterTeam = document.getElementById("filterTeam");
  const filterMaxPrice = document.getElementById("filterMaxPrice");
  const form = document.getElementById("transferForm");
  const outId = document.getElementById("outId");
  const inId = document.getElementById("inId");
  const summary = document.getElementById("transferSummary");

  let outPlayer = null;

  function openPicker(player) {
    outPlayer = player;
    pickerPos.textContent = `Replace ${player.name} (${player.position})`;
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
    if (!outPlayer) return;
    const q = search.value.trim().toLowerCase();
    const team = filterTeam.value;
    const maxP = filterMaxPrice.value ? Number(filterMaxPrice.value) : null;
    const items = PLAYERS.filter((p) => {
      if (ownedIds.has(p.id)) return false;
      // Keep composition easy: suggest same position first; allow any but warn in confirm
      if (q && !`${p.name} ${p.team}`.toLowerCase().includes(q)) return false;
      if (team && p.team !== team) return false;
      if (maxP != null && p.price > maxP) return false;
      return true;
    }).sort((a, b) => {
      const ap = a.position === outPlayer.position ? 0 : 1;
      const bp = b.position === outPlayer.position ? 0 : 1;
      if (ap !== bp) return ap - bp;
      return b.price - a.price;
    });

    pickerList.innerHTML = "";
    items.slice(0, 80).forEach((p) => {
      const li = document.createElement("li");
      li.innerHTML = `<button type="button" class="pick-row avail-${p.availability || "ok"}"><span class="grow"><strong>${p.name}</strong> <span class="muted">${p.position} · ${p.team}${p.availability === "doubt" ? " · doubtful" : p.availability === "out" ? " · out" : ""}${p.chance != null ? " · " + p.chance + "%" : ""}</span></span><span>£${p.price.toFixed(1)}m</span></button>`;
      li.querySelector("button").addEventListener("click", () => {
        outId.value = String(outPlayer.id);
        inId.value = String(p.id);
        summary.textContent = `${outPlayer.name} (£${outPlayer.price.toFixed(1)}m) → ${p.name} (£${p.price.toFixed(1)}m)`;
        form.hidden = false;
        closePicker();
        form.scrollIntoView({ behavior: "smooth" });
      });
      pickerList.appendChild(li);
    });
  }

  document.querySelectorAll("[data-out]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = Number(btn.getAttribute("data-out"));
      const player = OWNED.find((p) => p.id === id);
      if (player) openPicker(player);
    });
  });

  document.getElementById("closePicker").addEventListener("click", closePicker);
  picker.addEventListener("click", (e) => {
    if (e.target === picker) closePicker();
  });
  search.addEventListener("input", renderPicker);
  filterTeam.addEventListener("change", renderPicker);
  filterMaxPrice.addEventListener("change", renderPicker);
  document.getElementById("cancelTransfer").addEventListener("click", () => {
    form.hidden = true;
    outPlayer = null;
  });
})();
