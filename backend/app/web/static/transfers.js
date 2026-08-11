(() => {
  const PLAYERS = JSON.parse(document.getElementById("playersData").textContent);
  const OWNED = JSON.parse(document.getElementById("ownedData").textContent);
  const META = JSON.parse(document.getElementById("transferMeta").textContent);
  const MAX_CLUB = Number(META.maxPerClub || 3);
  const BUDGET = Number(META.budget);
  const SPEND = Number(META.spend);
  const ownedIds = new Set(OWNED.map((p) => p.id));
  const byId = Object.fromEntries([...PLAYERS, ...OWNED].map((p) => [p.id, p]));

  const picker = document.getElementById("picker");
  const pickerList = document.getElementById("pickerList");
  const pickerPos = document.getElementById("pickerPos");
  const pickerEyebrow = document.getElementById("pickerEyebrow");
  const inFilters = document.getElementById("inFilters");
  const search = document.getElementById("playerSearch");
  const filterTeam = document.getElementById("filterTeam");
  const filterMaxPrice = document.getElementById("filterMaxPrice");
  const outId = document.getElementById("outId");
  const inId = document.getElementById("inId");
  const confirmBtn = document.getElementById("confirmSwap");
  const hint = document.getElementById("swapHint");
  const slotOut = document.getElementById("slotOut");
  const slotIn = document.getElementById("slotIn");
  const slotOutBody = document.getElementById("slotOutBody");
  const slotInBody = document.getElementById("slotInBody");

  let mode = null; // "out" | "in"
  let outPlayer = null;
  let inPlayer = null;

  function clubCountsAfterOut() {
    const counts = {};
    OWNED.forEach((p) => {
      if (outPlayer && p.id === outPlayer.id) return;
      counts[p.team] = (counts[p.team] || 0) + 1;
    });
    return counts;
  }

  function playerCardHtml(p) {
    return `<strong>${p.name}</strong><span class="muted">${p.position} · ${p.team} · £${p.price.toFixed(1)}m</span>`;
  }

  function refreshSlots() {
    if (outPlayer) {
      slotOut.classList.add("filled");
      slotOutBody.innerHTML = playerCardHtml(outPlayer);
      outId.value = String(outPlayer.id);
    } else {
      slotOut.classList.remove("filled");
      slotOutBody.innerHTML = `<span class="swap-empty">Tap to choose</span>`;
      outId.value = "";
    }

    if (inPlayer) {
      slotIn.classList.add("filled");
      slotInBody.innerHTML = playerCardHtml(inPlayer);
      inId.value = String(inPlayer.id);
    } else {
      slotIn.classList.remove("filled");
      slotInBody.innerHTML = `<span class="swap-empty">Tap to choose</span>`;
      inId.value = "";
    }

    document.querySelectorAll("[data-owned]").forEach((el) => {
      const id = Number(el.getAttribute("data-owned"));
      el.classList.toggle("is-selected-out", outPlayer && outPlayer.id === id);
    });

    const ready = Boolean(outPlayer && inPlayer);
    confirmBtn.disabled = !ready;
    if (!outPlayer) {
      hint.textContent = "Choose who leaves first.";
    } else if (!inPlayer) {
      hint.textContent = `Out: ${outPlayer.name}. Now choose who comes in.`;
    } else {
      const delta = inPlayer.price - outPlayer.price;
      const bank = BUDGET - (SPEND - outPlayer.price + inPlayer.price);
      const sign = delta >= 0 ? `+£${delta.toFixed(1)}m` : `−£${Math.abs(delta).toFixed(1)}m`;
      hint.textContent = `${outPlayer.name} → ${inPlayer.name} (${sign}) · bank left £${bank.toFixed(1)}m`;
    }
  }

  function openOutPicker() {
    mode = "out";
    pickerEyebrow.textContent = "Transfer out";
    pickerPos.textContent = "Who leaves?";
    inFilters.hidden = true;
    picker.hidden = false;
    renderPicker();
  }

  function openInPicker() {
    if (!outPlayer) {
      hint.textContent = "Pick Out first, then In.";
      openOutPicker();
      return;
    }
    mode = "in";
    pickerEyebrow.textContent = "Transfer in";
    pickerPos.textContent = `Replace ${outPlayer.name} (${outPlayer.position})`;
    inFilters.hidden = false;
    search.value = "";
    filterTeam.value = "";
    filterMaxPrice.value = "";
    picker.hidden = false;
    search.focus();
    renderPicker();
  }

  function closePicker() {
    picker.hidden = true;
    mode = null;
  }

  function renderPicker() {
    pickerList.innerHTML = "";
    if (mode === "out") {
      OWNED.forEach((p) => {
        const li = document.createElement("li");
        li.innerHTML = `<button type="button" class="pick-row avail-${p.availability || "ok"}"><span class="grow"><strong>${p.name}</strong> <span class="muted">${p.position} · ${p.team}</span></span><span>£${p.price.toFixed(1)}m</span></button>`;
        li.querySelector("button").addEventListener("click", () => {
          outPlayer = p;
          if (inPlayer && inPlayer.id === p.id) inPlayer = null;
          // Drop In if club rule would break after new Out
          if (inPlayer) {
            const clubs = clubCountsAfterOut();
            if ((clubs[inPlayer.team] || 0) >= MAX_CLUB) inPlayer = null;
          }
          closePicker();
          refreshSlots();
        });
        pickerList.appendChild(li);
      });
      return;
    }

    if (mode !== "in" || !outPlayer) return;
    const q = search.value.trim().toLowerCase();
    const team = filterTeam.value;
    const maxP = filterMaxPrice.value ? Number(filterMaxPrice.value) : null;
    const clubs = clubCountsAfterOut();
    const maxAfford = BUDGET - (SPEND - outPlayer.price);
    const items = PLAYERS.filter((p) => {
      if (ownedIds.has(p.id)) return false;
      if (q && !`${p.name} ${p.team}`.toLowerCase().includes(q)) return false;
      if (team && p.team !== team) return false;
      if (maxP != null && p.price > maxP) return false;
      return true;
    }).sort((a, b) => {
      const aBlocked =
        (clubs[a.team] || 0) >= MAX_CLUB || a.price > maxAfford + 1e-9 ? 1 : 0;
      const bBlocked =
        (clubs[b.team] || 0) >= MAX_CLUB || b.price > maxAfford + 1e-9 ? 1 : 0;
      if (aBlocked !== bBlocked) return aBlocked - bBlocked;
      const ap = a.position === outPlayer.position ? 0 : 1;
      const bp = b.position === outPlayer.position ? 0 : 1;
      if (ap !== bp) return ap - bp;
      return b.price - a.price;
    });

    items.slice(0, 100).forEach((p) => {
      const clubN = clubs[p.team] || 0;
      const clubBlocked = clubN >= MAX_CLUB;
      const budgetBlocked = p.price > maxAfford + 1e-9;
      const blocked = clubBlocked || budgetBlocked;
      const li = document.createElement("li");
      const availNote =
        p.availability === "doubt" ? " · doubtful" : p.availability === "out" ? " · out" : "";
      let limitNote = "";
      if (clubBlocked) {
        limitNote = `<span class="club-limit">3/${MAX_CLUB} club</span>`;
      } else if (budgetBlocked) {
        limitNote = `<span class="club-limit is-budget">Over budget</span>`;
      } else if (clubN > 0) {
        limitNote = `<span class="muted tiny"> · ${clubN}/${MAX_CLUB}</span>`;
      }
      li.innerHTML = `<button type="button" class="pick-row avail-${p.availability || "ok"}${blocked ? " is-blocked" : ""}" ${blocked ? "disabled" : ""}><span class="grow"><strong>${p.name}</strong> <span class="muted">${p.position} · ${p.team}${availNote}</span>${limitNote}</span><span>£${p.price.toFixed(1)}m</span></button>`;
      const btn = li.querySelector("button");
      if (!blocked) {
        btn.addEventListener("click", () => {
          inPlayer = p;
          closePicker();
          refreshSlots();
        });
      }
      pickerList.appendChild(li);
    });
  }

  function setOutFromList(id) {
    const player = OWNED.find((p) => p.id === id);
    if (!player) return;
    outPlayer = player;
    if (inPlayer && inPlayer.id === player.id) inPlayer = null;
    if (inPlayer) {
      const clubs = clubCountsAfterOut();
      if ((clubs[inPlayer.team] || 0) >= MAX_CLUB) inPlayer = null;
    }
    refreshSlots();
  }

  slotOut.addEventListener("click", openOutPicker);
  slotIn.addEventListener("click", openInPicker);

  document.querySelectorAll("[data-owned]").forEach((el) => {
    const pick = () => setOutFromList(Number(el.getAttribute("data-owned")));
    el.addEventListener("click", pick);
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        pick();
      }
    });
  });

  document.getElementById("closePicker").addEventListener("click", closePicker);
  picker.addEventListener("click", (e) => {
    if (e.target === picker) closePicker();
  });
  search.addEventListener("input", renderPicker);
  filterTeam.addEventListener("change", renderPicker);
  filterMaxPrice.addEventListener("change", renderPicker);

  document.getElementById("clearSwap").addEventListener("click", () => {
    outPlayer = null;
    inPlayer = null;
    refreshSlots();
  });

  document.getElementById("transferForm").addEventListener("submit", (e) => {
    if (!outPlayer || !inPlayer) {
      e.preventDefault();
      alert("Choose both Out and In, then confirm.");
      return;
    }
  });

  refreshSlots();
})();
