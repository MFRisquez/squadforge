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


def test_mobile_pitch_scrolls_inside_page_fit():
    """Tall formations (3-4-3) must scroll inside the pitch on phone, not clip under Bench."""
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    # Find the phone page-fit media block and require overflow-y on pitches there.
    start = css.find("No page scroll / fixed viewport — phone only")
    assert start >= 0
    chunk = css[start : start + 3500]
    assert "body.page-fit .squad-pitch" in chunk
    assert "body.page-fit .xi-pitch" in chunk
    assert "overflow-y: auto" in chunk
    assert "-webkit-overflow-scrolling: touch" in chunk
