(() => {
  const OWNED = JSON.parse(document.getElementById("ownedData").textContent);
  const INITIAL = JSON.parse(document.getElementById("initialLineup").textContent);
  const byId = Object.fromEntries(OWNED.map((p) => [p.id, p]));
  const BAND = { GK: [1, 1], DEF: [3, 5], MID: [3, 5], ATT: [1, 3] };

  let starterIds = new Set(INITIAL.starters || []);
  let captainId = INITIAL.captain || [...starterIds][0] || null;

  const pitch = document.getElementById("pitch");
  const bench = document.getElementById("bench");
  const formationLabel = document.getElementById("formationLabel");
  const hiddenFields = document.getElementById("hiddenFields");
  const captainSelect = document.getElementById("captainSelect");
  const captainName = document.getElementById("captainName");

  function counts() {
    const c = { GK: 0, DEF: 0, MID: 0, ATT: 0 };
    starterIds.forEach((id) => {
      const p = byId[id];
      if (p) c[p.position] += 1;
    });
    return c;
  }

  function canStart(player) {
    if (starterIds.has(player.id)) return true;
    if (starterIds.size >= 11) return false;
    const c = counts();
    const [, hi] = BAND[player.position];
    if (c[player.position] >= hi) return false;
    if (player.position === "GK" && c.GK >= 1) return false;
    return true;
  }

  function setCaptain(id) {
    if (!starterIds.has(id)) return;
    captainId = id;
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
  }

  function fillCaptainSelect() {
    const starters = OWNED.filter((p) => starterIds.has(p.id));
    captainSelect.innerHTML = "";
    if (!starters.length) {
      captainSelect.innerHTML = `<option value="">Add starters first</option>`;
      captainName.textContent = "—";
      return;
    }
    starters.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = String(p.id);
      opt.textContent = `${p.name} (${p.position} · ${p.team})`;
      if (p.id === captainId) opt.selected = true;
      captainSelect.appendChild(opt);
    });
    if (!captainId || !starterIds.has(captainId)) {
      captainId = starters[0].id;
      captainSelect.value = String(captainId);
    }
    const cap = byId[captainId];
    captainName.textContent = cap ? `${cap.name} (×2)` : "—";
  }

  function shirtCard(player, onBench) {
    const wrap = document.createElement("div");
    wrap.className = "shirt-card" + (player.id === captainId && !onBench ? " is-captain" : "");

    const main = document.createElement("button");
    main.type = "button";
    const avail = player.availability || "ok";
    main.className = "shirt filled avail-" + avail;
    const flag = avail === "out" ? "OUT" : avail === "doubt" ? "DOUBT" : "";
    main.innerHTML = `
      <span class="shirt-price">£${player.price.toFixed(1)}</span>
      <span class="shirt-name">${player.name}</span>
      <span class="shirt-team">${player.team}${player.id === captainId && !onBench ? " · C" : ""}${flag ? " · " + flag : ""}</span>
      <span class="shirt-action">${onBench ? "Tap to start" : "Tap to bench"}</span>
    `;
    if (player.news) main.title = player.news;
    main.addEventListener("click", () => {
      if (starterIds.has(player.id)) {
        starterIds.delete(player.id);
        if (captainId === player.id) {
          captainId = [...starterIds][0] || null;
        }
      } else if (canStart(player)) {
        starterIds.add(player.id);
        if (!captainId) captainId = player.id;
      } else {
        alert("That would break formation limits (1 GK, DEF 3–5, MID 3–5, ATT 1–3, 11 total).");
        return;
      }
      render();
    });
    wrap.appendChild(main);

    if (!onBench) {
      const armband = document.createElement("button");
      armband.type = "button";
      armband.className = "armband" + (player.id === captainId ? " active" : "");
      armband.textContent = player.id === captainId ? "Captain" : "Make C";
      armband.setAttribute("aria-label", `Make ${player.name} captain`);
      armband.addEventListener("click", (e) => {
        e.stopPropagation();
        setCaptain(player.id);
      });
      wrap.appendChild(armband);
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
    formationLabel.textContent = `Formation ${c.DEF}-${c.MID}-${c.ATT} · ${starterIds.size}/11 starters`;
    fillCaptainSelect();
    syncHidden();
  }

  captainSelect.addEventListener("change", () => {
    const id = Number(captainSelect.value);
    if (id) setCaptain(id);
  });

  document.getElementById("lineupForm").addEventListener("submit", (e) => {
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
    if (!captainId || !starterIds.has(captainId)) {
      e.preventDefault();
      alert("Choose a captain from the list or tap Make C on a starter.");
      return;
    }
    syncHidden();
  });

  render();
})();
