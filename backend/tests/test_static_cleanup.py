"""Static cleanup: app.js gone; dead CSS selectors not revived."""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "web" / "templates"
API_INIT = Path(__file__).resolve().parents[1] / "app" / "api" / "__init__.py"


def test_app_js_removed_and_unreferenced():
    assert not (STATIC / "app.js").exists()
    blob = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in TEMPLATES.rglob("*.html"))
    blob += "\n" + "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in STATIC.glob("*.js"))
    assert "/static/app.js" not in blob
    assert "loadDemo" not in blob


def test_dead_prototype_css_selectors_removed():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    for dead in (
        ".howto-grid",
        ".phone-demo-panel",
        ".armband",
        ".kit-portrait",
        ".fdr-rail-list",
        ".chip-grid",
        ".welcome-row",
        ".player-cards",
        ".auth-links",
        ".rail-kpis",
    ):
        assert dead not in css, dead
    # live classes must remain
    for live in (".chip-card-fpl", ".desk-board", ".fx-rail-empty", ".transfer-rail-row"):
        assert live in css, live


def test_mobile_pwa_and_input_zoom_guards():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "background-color: var(--bg)" in css
    assert "-webkit-fill-available" in css
    assert "display-mode: standalone" in css
    assert "html.is-standalone" in css
    assert "font-size: 16px !important" in css
    assert "phone-friendly table" in css

    ui = (STATIC / "ui.js").read_text(encoding="utf-8")
    assert 'classList.add("is-standalone")' in ui

    manifest = (STATIC / "manifest.webmanifest").read_text(encoding="utf-8")
    assert '"background_color": "#121212"' in manifest


def test_mobile_pitch_scales_rows_inside_page_fit():
    """Phone pitch rows share height; shirts scale — no internal pitch scroll."""
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    start = css.find("Phone XI/Squad: proportional pitch tokens")
    assert start >= 0
    chunk = css[start : start + 4500]
    assert "body.page-fit .xi-pitch" in chunk or "body.page-fit.page-xi .xi-pitch" in chunk
    assert "body.page-fit .squad-pitch" in chunk or "body.page-fit.page-squad .squad-pitch" in chunk
    assert "flex: 1 1 0" in chunk
    assert "clamp(3rem" in chunk
    assert "container-type: size" in chunk
    assert "overflow: hidden" in chunk
    assert "overflow-y: auto" not in chunk
    # Phone page-fit pitch block (not desktop): equal flex rows, no scroll
    phone = css.find("No page scroll / fixed viewport — phone only")
    assert phone >= 0
    phone_pitch = css.find("Equal row bands — shirts scale with row height", phone)
    assert phone_pitch >= 0
    phone_rules = css[phone_pitch : phone_pitch + 600]
    assert "overflow: hidden" in phone_rules
    assert "overflow-y: auto" not in phone_rules
    assert "flex-direction: column" in phone_rules


def test_xi_phone_shell_uses_flex_not_fit_chrome():
    """page-fit phone: body flex column fills viewport; --fit-chrome must not exist."""
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "--fit-chrome" not in css
    assert "fit-chrome" not in css
    assert "calc(100dvh - var(" not in css
    start = css.find("Height model: body is a flex column")
    assert start >= 0
    chunk = css[start : start + 4500]
    assert "@media (max-width: 899px)" in chunk
    assert "body.page-fit" in chunk
    assert "display: flex" in chunk
    assert "flex-direction: column" in chunk
    assert "body.page-fit > .app-chrome" in chunk
    assert "flex: 0 0 auto" in chunk
    assert "body.page-fit > .shell" in chunk
    assert "flex: 1 1 auto" in chunk
    assert "min-height: 0" in chunk
    assert "height: auto" in chunk
    assert "max-height: none" in chunk
    # Free Agents rail must stay hidden on phone page-fit
    assert "body.page-squad.page-fit .transfer-rail" in chunk
    assert "display: none !important" in chunk


def test_transfer_rail_hidden_on_phone_page_fit():
    """team.html uses page-fit+page-squad; phone CSS must hide .transfer-rail."""
    team = (TEMPLATES / "team.html").read_text(encoding="utf-8")
    assert "page-fit" in team and "page-squad" in team
    assert 'class="desk-rail transfer-rail"' in team or "desk-rail transfer-rail" in team

    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    # Hardened hide lives in the ≤899px page-fit flex block
    start = css.find("Free Agents rail is desktop-only")
    assert start >= 0
    chunk = css[start : start + 500]
    block = css[css.rfind("@media (max-width: 899px)", 0, start) : start + 500]
    assert "@media (max-width: 899px)" in block
    assert "display: none !important" in chunk
    assert "body.page-squad.page-fit .transfer-rail" in chunk

    # JS must not strip page-fit / page-squad (would un-hide the rail)
    squad = (STATIC / "squadboard.js").read_text(encoding="utf-8")
    assert 'classList.remove("page-fit")' not in squad
    assert 'classList.remove("page-squad")' not in squad
    assert 'classList.remove("page-fit")' not in (STATIC / "appshell.js").read_text(encoding="utf-8")

    # SW cache bump so phones drop stale CSS / catalog that showed wrong avail flags
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert 'CACHE = "futfantasy-v153"' in sw
    assert "if (isStatic || isBadgeCdn) return cached || fetched" in sw
    assert "CSS is network-first" in sw
    # Must not cache-first the catalog (stale availability after FPL sync).
    assert "if (isStatic || isCatalog || isBadgeCdn) return cached || fetched" not in sw
    assert "/static/styles.css?v=152" in sw
    assert "/static/league_h2h.js" in sw
    assert "/static/club-sheet.js" in sw
    assert 'BADGE_CDN_HOST = "resources.premierleague.com"' in sw
    assert "isBadgeCdn" in sw
    assert "isStatic || isCatalog || isBadgeCdn" in sw
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "sw.js?v=152" in base
    assert "styles.css?v=152" in base

    squad = (STATIC / "squadboard.js").read_text(encoding="utf-8")
    assert "ff-players-updated" in squad
    assert "function applyPlayersCatalog" in squad
    assert "notify: true" in squad
    # ADD PLAYER picker: columns, no mini-radar triangle mistaken for doubt
    assert 'class="pick-team"' in squad
    assert 'class="pick-avail' in squad
    assert "Available" in squad and "Doubt" in squad
    assert "pick-radar" not in squad or "display: none" in (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "miniRadarSvg(p)" not in squad[squad.find("pickerList.innerHTML") : squad.find("function pickPlayer")]

    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    # Desktop: XI pitch 5.4rem; Transfers −20% (4.32); bench −30% (3.78).
    assert "--pitch-token-w: 5.4rem" in css
    assert "--pitch-token-w: 4.32rem" in css
    assert "body.page-squad .squad-pitch .pitch-row { gap: 1.15rem; }" in css
    assert css.count("--pitch-token-w: 4.9rem") == 0
    assert "width: var(--pitch-token-w, 3.7rem)" in css

    # Fixtures desk detail: stack sections by content (no stretch to list height).
    panel_idx = css.find("body.page-fixtures .fixture-detail-panel {")
    assert panel_idx >= 0
    panel_chunk = css[panel_idx : panel_idx + 420]
    assert "height: auto" in panel_chunk
    assert "align-self: start" in panel_chunk
    assert "height: 100%" not in panel_chunk
    body_idx = css.find("body.page-fixtures .fixture-detail-panel .match-detail-body {")
    assert body_idx >= 0
    body_chunk = css[body_idx : body_idx + 380]
    assert "flex: 0 0 auto" in body_chunk
    assert "align-content: start" in body_chunk
    assert "flex: 1 1 auto" not in body_chunk


def test_desk_side_left_layout_phase0():
    """XI + Transfers share a 3-col desk with equal side rails; pitch stays middle."""
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    lineup = (TEMPLATES / "lineup.html").read_text(encoding="utf-8")
    team = (TEMPLATES / "team.html").read_text(encoding="utf-8")

    assert 'id="xiSideLeft"' in lineup
    assert 'class="desk-rail desk-side-left"' in lineup
    assert 'id="squadSideLeft"' in team
    assert 'class="desk-rail desk-side-left"' in team
    # Free Agents rail still present on Transfers
    assert 'id="transferRail"' in team
    assert "desk-side-left" in team[: team.find("transferRail")]

    assert ".desk-xi:has(> .desk-side-left)" in css
    assert ".desk-squad:has(> .desk-side-left)" in css
    # Side rails grow with leftover width; pitch column is capped (not fixed rem | 1fr | fixed rem).
    assert "minmax(var(--desk-side-w), 1fr)" in css
    assert "minmax(0, var(--desk-pitch-col))" in css
    assert "grid-template-columns: var(--desk-side-w) minmax(0, 1fr) var(--desk-side-w)" not in css
    assert "--desk-side-w: 20rem" in css
    assert css.count("--desk-side-w: 20rem") >= 2
    assert "--desk-side-w: 19.5rem" not in css
    # XI desktop reorder: pitch | bench | DT (order + remapped tracks)
    assert "XI desktop column reorder" in css
    assert ".desk-xi > .desk-main.desk-xi-main" in css
    assert "order: 1" in css and "order: 2" in css and "order: 3" in css
    # Transfers desktop reorder: pitch | Free Agents | left panel (.desk-squad only)
    assert "Transfers desktop column reorder" in css
    assert ".desk-squad > .transfer-rail" in css
    assert "XI untouched" in css
    assert ".desk-squad:has(> .desk-side-left)" in css
    assert "body.page-xi:not(.page-opponent).page-fit .shell" in css
    assert "width: 100%" in css
    assert "max-width: none" in css
    assert "--desk-pitch-col: 45.6rem" in css
    assert "--desk-pitch-col: 38rem" not in css
    # Pitch tokens: XI 5.4rem; Transfers −20% → 4.32rem; bench −10% more → 3.4rem
    assert "--pitch-token-w: 5.4rem" in css
    assert "--pitch-token-w: 4.32rem" in css
    assert "--bench-token-w: 3.4rem" in css
    assert "body.page-xi .xi-bench-stack .xi-shirt" in css
    assert "width: var(--bench-token-w, 3.4rem) !important" in css
    assert "max-width: none" in css  # bench rows must not inherit pitch-token max-width
    assert "width: var(--pitch-token-w, 5.4rem) !important" not in css
    assert "width: 2.55rem !important" not in css
    # Name + fixture type bumped on both pitches
    assert "body.page-xi .xi-pitch-wrap .shirt-nameplate" in css
    assert "font-size: 0.78rem" in css
    assert "body.page-xi .xi-pitch-wrap .shirt-foot" in css
    assert "font-size: 0.70rem" in css
    # Phase 2 left rail: DT + leagues side-by-side, centered scorers, rank spark
    assert "desk-side-top-row" in css
    assert "desk-side-rank-spark" in css
    assert "desk-side-top-row" in lineup
    assert "xi-side.js" in lineup
    assert "xiPositionBlock" in lineup
    assert "/api/xi/side-kpis" in lineup
    assert "desk-xi-chips" in css
    assert 'class="desk-main desk-xi-main"' in lineup
    assert "desk-xi-chips" in lineup
    # Chips live inside the pitch column (desk-xi-chips), not above the full board
    assert "desk-xi-chips" in lineup
    chips_block = lineup[lineup.find("desk-xi-chips") : lineup.find("lineupForm")]
    assert "chip_strip" in chips_block
    assert lineup.find('id="xiSideLeft"') < lineup.find("desk-xi-chips")
    # Fase 1–2 side panel chrome present
    assert "desk-side-league-list" in css
    assert "desk-side-xfer-list" in css
    assert "desk-side-xfer-tables" in css
    assert "desk-side-my-xfer-list" in css
    assert "desk-side-scorer-list" in css
    assert "chip-name-stack" in css
    assert "desk-side-position" in css
    assert "League Transfer Trends" in team
    assert "Most transferred IN" in team
    assert "Most transferred OUT" in team
    assert "Most picked in XI" not in team
    assert "Most popular captain" not in team
    assert "rgba(255, 255, 255, 0.04)" in css
    assert "overflow-y: auto" in css
    assert "Preview — real data after deadline" in team
    assert "desk-side-preview-mark" in css
    assert 'id="myGwTransfers"' in team
    assert "Your top scorers" in (TEMPLATES / "lineup.html").read_text(encoding="utf-8")
    assert 'id="saveConfirm"' not in team
    assert "openSaveConfirm" not in (STATIC / "squadboard.js").read_text(encoding="utf-8")
    assert "appendMyGwTransfers" in (STATIC / "squadboard.js").read_text(encoding="utf-8")
    assert "xi_side_left" in (TEMPLATES / "lineup.html").read_text(encoding="utf-8")
    assert "transfers_side_left" in (TEMPLATES / "team.html").read_text(encoding="utf-8")
    assert "trends.most_in" in team
    assert "{% for block in side.leagues %}" not in team


def test_transfers_pitch_price_frame_and_pending_white_border():
    """Squad pitch shirts show price in a gray frame; unsaved IN uses fine white contour until Save."""
    squad = (STATIC / "squadboard.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    # Price is a direct child of the shirt button (above kit), not stacked under jersey grid
    shirt_html_fn = squad[squad.find("function shirtHtml") : squad.find("function syncHidden")]
    assert 'class="shirt-price"' in shirt_html_fn
    assert shirt_html_fn.find("shirt-price") < shirt_html_fn.find('class="shirt-kit"')
    assert "toFixed(1)}m" in shirt_html_fn
    assert "is-pending-in" in squad
    assert "function captureBaseline()" in squad
    assert "function isUnsavedPitchPlayer(" in squad
    assert "isUnsavedPitchPlayer(p.id)" in squad
    assert "captureBaseline()" in squad

    assert "body.page-squad .squad-pitch .squad-shirt.filled" in css
    assert "rgba(55, 58, 64, 0.42)" in css
    assert "body.page-squad .squad-pitch .squad-shirt.filled > .shirt-price" in css
    # Overlay in normal flow so the dark box fully wraps jersey + nameplate
    assert "body.page-squad .squad-pitch .squad-shirt.filled .shirt-overlay" in css
    assert "position: relative" in css[css.find("body.page-squad .squad-pitch .squad-shirt.filled .shirt-overlay") : css.find("body.page-squad .squad-pitch .squad-shirt.filled .shirt-overlay") + 220]
    assert "body.page-squad .squad-pitch .squad-shirt.filled.is-pending-in" in css
    pending_idx = css.find("body.page-squad .squad-pitch .squad-shirt.filled.is-pending-in")
    assert pending_idx >= 0
    pending_chunk = css[pending_idx : pending_idx + 420]
    # iOS-safe white ring via box-shadow (button borders are unreliable)
    assert "0 0 0 1.5px #ffffff" in pending_chunk
    assert "outline: none" in pending_chunk
    assert "shirt-price" in css


def test_dt_club_picker_hides_list_while_viewing_and_updates_badge():
    """Viewing a club tucks the list away; Choose updates the DT badge; dismiss restores list."""
    club = (STATIC / "club-sheet.js").read_text(encoding="utf-8")
    squad = (STATIC / "squadboard.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert "fromPicker" in club
    assert "restorePickerOnClose" in club
    assert "hideClubPicker" in club
    assert "showClubPicker" in club
    assert "dismissClubDetail" in club
    assert "choseClub" in club

    assert "fromPicker: true" in squad
    assert "previewTdSelection(data)" in squad
    assert 'badge.className = "td-badge"' in squad or "td-badge" in squad
    assert "info.badge" in squad

    assert "#clubDetail.drawer" in css
    assert "z-index: 90" in css


def test_appshell_warms_all_nav_tabs():
    """Cold-start prefetch covers Home, Rules, and League (standings or hub)."""
    js = (STATIC / "appshell.js").read_text(encoding="utf-8")
    assert "function leagueWarmUrl()" in js
    assert 'prefetch("/")' in js
    assert 'prefetch("/rules")' in js
    assert "prefetch(leagueWarmUrl())" in js
    assert 'prefetch("/lineup")' in js
    assert 'prefetch("/team")' in js
    assert 'prefetch("/fixtures")' in js
    # Splash still waits a fixed 2s and does not await warm completion before hide
    assert "setTimeout(r, 2000)" in js
    assert "hideSplash();" in js
    warm_block = js[js.find("async function warmShellData()") : js.find("function hideSplash()")]
    assert "Promise.allSettled" in warm_block
    assert "await Promise.allSettled" in warm_block
    splash = js[js.find("async function runColdStartSplash()") : js.find("function updateNavActive")]
    assert "const warm = warmShellData()" in splash
    assert "await new Promise((r) => setTimeout(r, 2000))" in splash
    # warm continues in background after splash hides
    assert "void warm" in splash
    # League URL mirrors nav: single standings id or /leagues hub
    assert 'href === "/leagues"' in js or "href === \"/leagues\"" in js
    assert "/standings/" in js


def test_appshell_softnav_perf_instrumentation():
    """softNavigate reports fetch vs scripts timing (console + /api/client-perf)."""
    js = (STATIC / "appshell.js").read_text(encoding="utf-8")
    assert "function reportSoftNavTiming(" in js
    assert "performance.now()" in js
    assert 'fetch("/api/client-perf"' in js
    assert "fromCache" in js
    assert "readServerPerfHeader" in js
    assert "X-FF-Server-Perf" in js
    soft = js[js.find("async function softNavigate") : js.find("function bindGwPicker")]
    assert "const t1 = performance.now()" in soft
    assert "const t2 = performance.now()" in soft
    assert "const t3 = performance.now()" in soft
    assert "reportSoftNavTiming(" in soft
    assert "fetchMs:" in soft and "scriptsMs:" in soft and "totalMs:" in soft
    assert "serverPerf:" in soft

    api = API_INIT.read_text(encoding="utf-8")
    assert '="/client-perf"' in api or '"/client-perf"' in api
    assert "squadforge.client_perf" in api
    assert "server_perf" in api

    routes = (Path(__file__).resolve().parents[1] / "app" / "web_routes.py").read_text(encoding="utf-8")
    assert 'timed("ctx.current_manager")' in routes
    assert 'timed("team.owned_players")' in routes
    assert "attach_server_perf_header" in routes
    # /team reuses auth manager + resolve_gw current + known squad flag in _ctx
    assert "manager=manager," in routes
    assert 'gw=view["current_gw"]' in routes
    assert "has_complete_squad=squad_complete" in routes
    assert "manager_leagues_and_owned_count" in (
        Path(__file__).resolve().parents[1] / "app" / "services" / "league.py"
    ).read_text(encoding="utf-8")
    assert "ctx.leagues_and_owned" in routes
    assert "_ctx(request, db, manager=manager)" in routes
    live = (
        Path(__file__).resolve().parents[1] / "app" / "services" / "live_scoring.py"
    ).read_text(encoding="utf-8")
    assert "is_live_demo_active(db, gw)" in live
    catalog = (
        Path(__file__).resolve().parents[1] / "app" / "services" / "player_catalog.py"
    ).read_text(encoding="utf-8")
    assert "catalog.build_loop" in catalog
    assert "per_player_ms" in catalog


def test_desktop_pitch_rail_uses_flex_leftover_height():
    """Desktop (≥900) squad/XI: leftover viewport via flex; rail list scrolls, page does not.

    Content pages (standings/league/fixtures/home) keep normal document scroll.
    No --fit-chrome rem guess, no max-height: none on the rail list.
    """
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "--fit-chrome" not in css
    assert "calc(100vh - 8.5rem)" not in css
    assert "min-height: min(68vh, 40rem)" not in css
    assert "min-height: min(72vh, 40rem)" not in css

    marker = "Desktop pitch pages (≥900px): leftover viewport via flex"
    start = css.find(marker)
    assert start >= 0
    end = css.find("Bigger pitch shirts", start)
    assert end > start
    chunk = css[start:end]

    # Viewport lock is pitch pages only — not all page-fit
    assert "html:has(body.page-squad.page-fit)" in chunk
    assert "html:has(body.page-xi.page-fit)" in chunk
    assert "html:has(body.page-fit)" not in chunk
    assert "body.page-standings" not in chunk
    assert "body.page-fixtures" not in chunk
    assert "body.page-league" not in chunk
    assert "body.page-home" not in chunk

    assert "flex-direction: column" in chunk
    assert "flex: 0 0 auto" in chunk
    assert "flex: 1 1 auto" in chunk
    assert "min-height: 0" in chunk
    assert "align-self: stretch" in chunk
    assert "align-items: stretch" in chunk

    assert "body.page-fit .transfer-rail-list" in chunk
    assert "max-height: 100%" in chunk
    assert "height: 100%" in chunk
    assert "overflow: auto" in chunk
    assert "max-height: none" not in chunk
    assert "--fit-chrome" not in chunk
    assert "fit-chrome" not in chunk
    assert "calc(100vh" not in chunk
    assert "8.5rem" not in chunk
    assert "68vh" not in chunk
    assert "40rem" not in chunk

    # Desktop rail list override (same 900px board block): bounded, not none
    rail = css.find(".transfer-rail-list {", css.find("Align with stat strip"))
    assert rail >= 0
    rail_chunk = css[rail : rail + 280]
    assert "max-height: none" not in rail_chunk
    assert "max-height: 100%" in rail_chunk
    assert "overflow: auto" in rail_chunk
    assert "min-height: 0" in rail_chunk


def test_mobile_picker_rows_are_horizontal():
    """Phone picker: Name | Team | Avail | Club | Price (+ ⓘ) — no stacked columns."""
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    start = css.find("Mobile picker: Name | Team | Avail | Club | Price")
    assert start >= 0
    chunk = css[start : start + 1800]
    assert "text-align: center" not in chunk
    assert "justify-items: center" not in chunk
    assert "grid-template-columns: minmax(0, 1.2fr) 2.35rem 3.9rem 2.35rem 2.85rem" in chunk
    assert ".pick-team" in css
    assert ".pick-avail" in css
    assert ".pick-club" in css
    assert "display: none" in css[css.find(".pick-radar") : css.find(".pick-radar") + 120]

    """Owned rows use accent bar only — no side ✓ mark."""
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert ".transfer-rail-row.is-owned .tr-owned-mark" not in css
    assert "tr-owned-mark" not in css
    squad = (STATIC / "squadboard.js").read_text(encoding="utf-8")
    assert "tr-owned-mark" not in squad
    # Accent bar cue remains
    assert "box-shadow: inset 4px 0 0 var(--accent)" in css


def test_super_sub_mobile_layout_consolidated():
    """Phone Super Sub: one ≤899 block with display:contents; dead dual-body selector gone."""
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    marker = "Super Sub phone/tablet (≤899): one layout"
    start = css.find(marker)
    assert start >= 0
    chunk = css[start : start + 2400]
    assert "@media (max-width: 899px)" in chunk
    assert "display: contents" in chunk
    assert "grid-template-columns: auto minmax(0, 1fr) auto minmax(0, 1.35fr) auto" in chunk
    assert "body.page-xi .chip-card-fpl.chip-card-ss .chip-ss-form" in chunk
    assert "font-size: 0.55rem !important" in chunk
    # Dead selector never matches (two body classes as descendant)
    assert "body.page-squad body.page-xi .chip-card-fpl.chip-card-ss" not in css
    # Narrow wrap keeps toggle on row 1, select under title
    wrap = css.find("Narrow phones: keep Off/On on the title row")
    assert wrap >= 0
    wrap_chunk = css[wrap : wrap + 900]
    assert "@media (max-width: 390px)" in wrap_chunk
    assert "grid-row: 2" in wrap_chunk
    assert "grid-column: 2 / 5" in wrap_chunk
    # Desktop one-line Super Sub must remain
    desk = css.find("Super Sub: icon · title · info · Off · bench select")
    assert desk >= 0
    desk_chunk = css[desk : desk + 900]
    assert "display: contents" in desk_chunk
    assert "minmax(0, 1.65fr)" in desk_chunk
    assert "font-size: 0.72rem" in desk_chunk
    assert "max-width: none" in desk_chunk