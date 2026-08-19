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

    # SW cache bump so phones drop stale CSS that still showed the rail
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert 'CACHE = "futfantasy-v120"' in sw
    assert "/static/styles.css" in sw
    assert "/static/league_h2h.js" in sw
    assert "/static/club-sheet.js" in sw
    assert 'BADGE_CDN_HOST = "resources.premierleague.com"' in sw
    assert "isBadgeCdn" in sw
    assert "isStatic || isCatalog || isBadgeCdn" in sw
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "sw.js?v=120" in base


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
    soft = js[js.find("async function softNavigate") : js.find("function bindGwPicker")]
    assert "const t1 = performance.now()" in soft
    assert "const t2 = performance.now()" in soft
    assert "const t3 = performance.now()" in soft
    assert "reportSoftNavTiming(" in soft
    assert "fetchMs:" in soft and "scriptsMs:" in soft and "totalMs:" in soft

    api = API_INIT.read_text(encoding="utf-8")
    assert '="/client-perf"' in api or '"/client-perf"' in api
    assert "squadforge.client_perf" in api
    assert "_SOFTNAV_PERF" in api
    assert "def client_perf_list" in api


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
    """Phone picker: name/team/price share one row (not stacked/centered columns)."""
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    start = css.find("Mobile picker: one horizontal row")
    assert start >= 0
    chunk = css[start : start + 1600]
    assert "flex-direction: row" in chunk
    assert "text-align: center" not in chunk
    assert "justify-items: center" not in chunk
    assert "grid-template-columns: minmax(0, 1fr) auto auto" in chunk
    assert ".pick-row .grow" in chunk

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
    desk_chunk = css[desk : desk + 800]
    assert "display: contents" in desk_chunk
    assert "minmax(0, 1.2fr)" in desk_chunk