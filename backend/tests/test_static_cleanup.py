"""Static cleanup: app.js gone; dead CSS selectors not revived."""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "web" / "templates"


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
    """XI mobile fills leftover viewport via flex; no magic --fit-chrome height."""
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    start = css.find("XI phone only: fill the viewport with flex")
    assert start >= 0
    chunk = css[start : start + 1200]
    assert "body.page-xi.page-fit" in chunk
    assert "display: flex" in chunk
    assert "flex-direction: column" in chunk
    assert "body.page-xi.page-fit > .top" in chunk
    assert "body.page-xi.page-fit > .nav" in chunk
    assert "flex: 0 0 auto" in chunk
    assert "body.page-xi.page-fit > .shell" in chunk
    assert "flex: 1 1 auto" in chunk
    assert "min-height: 0" in chunk
    assert "height: auto" in chunk
    assert "max-height: none" in chunk
    # Must not calc shell height from --fit-chrome in this XI block
    assert "calc(100dvh - var(--fit-chrome))" not in chunk
    # Selectors in this block must stay XI-only (do not migrate Transfers here)
    assert "body.page-squad" not in chunk
    assert "body.page-xi.page-fit > .shell" in chunk
