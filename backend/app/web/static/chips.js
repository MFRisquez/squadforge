(() => {
  const JSON_HEADERS = {
    Accept: "application/json",
    "X-Requested-With": "fetch",
  };

  let busy = false;

  function strips() {
    return Array.from(document.querySelectorAll("[data-chip-strip]"));
  }

  function postForm(url, fields) {
    const body = new URLSearchParams();
    Object.entries(fields).forEach(([k, v]) => {
      if (v != null && v !== "") body.set(k, String(v));
    });
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        ...JSON_HEADERS,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body,
    }).then(async (res) => {
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        const err = new Error(data.error || "Chip update failed");
        err.status = res.status;
        throw err;
      }
      return data;
    });
  }

  function updateFtDisplay(unlimited, ft) {
    const strong = document.querySelector(
      ".stat-strip .stat:nth-child(2) strong, #ftValue"
    );
    const sub = document.querySelector(
      ".stat-strip .stat:nth-child(2) .stat-sub, #ftSub"
    );
    if (strong) strong.textContent = unlimited ? "∞" : String(ft ?? strong.textContent);
    if (sub) sub.textContent = unlimited ? "unlimited" : "banked";
    if (window.__ffSquadState) {
      window.__ffSquadState.unlimited = !!unlimited;
    }
  }

  function broadcastChip(data) {
    window.__ffActiveChip = {
      chip: data.active_chip || null,
      superSubPlayerId: data.super_sub_player_id ?? null,
    };
    document.dispatchEvent(
      new CustomEvent("ff:chip-change", {
        detail: {
          chip: data.active_chip || null,
          superSubPlayerId: data.super_sub_player_id ?? null,
        },
      })
    );
  }

  function applyState(data) {
    const active = data.active_chip || "";
    const remaining = data.remaining || {};

    strips().forEach((strip) => {
      strip.dataset.active = active;
      strip.querySelectorAll("[data-chip-card]").forEach((card) => {
        const key = card.dataset.chip;
        const gwLocked = card.dataset.gwLocked === "1";
        let left = Number(card.dataset.left || 0);
        if (remaining[key] != null) {
          left = Number(remaining[key]);
          card.dataset.left = String(left);
        }
        const isActive = !!active && active === key;
        const spent = left < 1 && !isActive;
        const otherActive = !!active && !isActive;
        const canToggle = !spent && !gwLocked;

        card.classList.toggle("is-active", isActive);
        card.classList.toggle("is-spent", spent);
        card.classList.toggle("is-dim", otherActive && canToggle);
        card.classList.toggle("is-unavailable", gwLocked || (spent && !isActive));

        const toggle = card.querySelector("[data-chip-toggle]");
        const status = card.querySelector("[data-chip-status]");
        const ssSelect = card.querySelector("[data-ss-player]");

        if (toggle) {
          toggle.disabled = false;
          toggle.classList.toggle("is-on", isActive);
          toggle.setAttribute("aria-pressed", isActive ? "true" : "false");
          toggle.textContent = isActive ? "On" : "Off";
          toggle.hidden = spent || gwLocked;
        }
        if (status) {
          if (spent) {
            status.hidden = false;
            status.textContent = "Used";
          } else if (gwLocked) {
            status.hidden = false;
            status.textContent = "GW2+";
          } else if (toggle) {
            status.hidden = true;
          }
        }
        if (ssSelect) ssSelect.disabled = isActive;
      });
    });

    if (typeof data.unlimited_transfers === "boolean") {
      updateFtDisplay(data.unlimited_transfers);
    }

    broadcastChip(data);

    if (data.reload_squad && typeof window.__ffNavigate === "function") {
      const path = window.location.pathname + window.location.search;
      window.__ffNavigate(path.startsWith("/team") ? path : "/team");
    }
  }

  async function cancelActive(nextPath) {
    return postForm("/team/chip/cancel", { next: nextPath || "/team" });
  }

  async function playChip(chip, nextPath, playerId) {
    const fields = { chip, next: nextPath || "/team" };
    if (playerId != null) fields.player_id = playerId;
    return postForm("/team/chip", fields);
  }

  async function onToggle(btn) {
    if (busy) return;
    const card = btn.closest("[data-chip-card]");
    const strip = btn.closest("[data-chip-strip]");
    if (!card || !strip) return;

    const chip = card.dataset.chip;
    const nextPath = strip.dataset.next || "/team";
    const active = strip.dataset.active || "";
    const gwLocked = card.dataset.gwLocked === "1";
    const left = Number(card.dataset.left || 0);
    if (gwLocked) return;
    if (left < 1 && active !== chip) return;

    let playerId = null;
    if (chip === "super_sub" && active !== chip) {
      const sel = card.querySelector("[data-ss-player]");
      playerId = sel && sel.value ? Number(sel.value) : null;
      if (!playerId) {
        flashChipError(strip, "Pick a bench player first");
        return;
      }
    }

    busy = true;
    strip.classList.add("is-busy");
    btn.disabled = true;
    try {
      let data;
      if (active === chip) {
        data = await cancelActive(nextPath);
      } else {
        if (active) {
          data = await cancelActive(nextPath);
          applyState(data);
          if (data.reload_squad) return;
        }
        data = await playChip(chip, nextPath, playerId);
      }
      applyState(data);
      clearChipError(strip);
    } catch (err) {
      flashChipError(strip, err.message || "Couldn’t update chip");
    } finally {
      busy = false;
      strip.classList.remove("is-busy");
      strip.querySelectorAll("[data-chip-toggle]").forEach((b) => {
        b.disabled = false;
      });
    }
  }

  function flashChipError(strip, msg) {
    let el = strip.querySelector("[data-chip-error]");
    if (!el) {
      el = document.createElement("p");
      el.className = "chip-strip-error";
      el.setAttribute("data-chip-error", "");
      el.setAttribute("role", "alert");
      strip.appendChild(el);
    }
    el.textContent = msg;
    el.hidden = false;
  }

  function clearChipError(strip) {
    const el = strip.querySelector("[data-chip-error]");
    if (el) {
      el.hidden = true;
      el.textContent = "";
    }
  }

  function onClick(e) {
    const btn = e.target.closest("[data-chip-toggle]");
    if (!btn) return;
    e.preventDefault();
    onToggle(btn);
  }

  document.addEventListener("click", onClick);

  window.__ffChipsApply = applyState;
})();
