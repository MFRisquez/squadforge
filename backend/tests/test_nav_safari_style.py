"""Safari-style main nav + transfers picker color parity with desktop rail."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "web" / "templates"
STATIC = ROOT / "app" / "web" / "static"


def test_nav_has_no_icons_and_uses_text_only():
    html = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "nav-ico" not in html
    assert "⌂" not in html
    assert ">Home<" in html or ">Home</a>" in html
    assert ">Transfers<" in html or ">Transfers</a>" in html
    assert ">Rules<" in html or ">Rules</a>" in html


def test_nav_css_is_safari_tab_style():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    # Separators between items
    assert "border-right: 1px solid rgba(0, 0, 0, 0.12)" in css
    assert "rgba(255, 255, 255, 0.15)" in css
    # No pill active treatment
    nav_active = css[css.find(".nav a.is-active") : css.find(".nav a.is-active") + 160]
    assert "border-radius: 999px" not in nav_active
    assert "inset 0 -2px 0 #B6DB00" in css
    # Active background transparent (not lime pill)
    assert "background: transparent" in nav_active or "background:transparent" in nav_active.replace(" ", "")


def test_pick_row_avail_matches_transfer_rail_ink():
    """Mobile transfers picker warning text uses the same ink as desktop rail."""
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert ".pick-row.avail-doubt" in css
    assert "#6a5200" in css  # rail + pick doubt
    assert "#7a1010" in css  # rail + pick out
    assert 'html[data-theme="dark"] .pick-price' in css
    assert 'html[data-theme="dark"] .pick-row.avail-doubt .pick-price' in css
    assert 'html[data-theme="dark"] .pick-row.avail-out .pick-price' in css


def test_dark_pick_row_price_ink_matches_rail_contract():
    """Dark ok price is white; avail-doubt/out keep warning ink (same hex as rgb checks)."""
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    pick_price_dark = css[css.find('html[data-theme="dark"] .pick-price') :][:120]
    assert "#fff" in pick_price_dark or "#ffffff" in pick_price_dark.lower() or "color: #fff" in pick_price_dark

    doubt_chunk = css[
        css.find('html[data-theme="dark"] .pick-row.avail-doubt .pick-price') : css.find(
            'html[data-theme="dark"] .pick-row.avail-doubt .pick-price'
        )
        + 280
    ]
    assert "#6a5200" in doubt_chunk
    assert "!important" in doubt_chunk

    out_chunk = css[
        css.find('html[data-theme="dark"] .pick-row.avail-out .pick-price') : css.find(
            'html[data-theme="dark"] .pick-row.avail-out .pick-price'
        )
        + 280
    ]
    assert "#7a1010" in out_chunk
    assert "!important" in out_chunk


def test_sticky_chrome_keeps_top_and_nav_together():
    """`.app-chrome` wraps `.top`+`.nav` as one sticky unit — no separate sticky gap."""
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    html = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert 'class="app-chrome"' in html or "class='app-chrome'" in html
    assert ".app-chrome" in css
    chrome = css[css.find(".app-chrome") : css.find(".app-chrome") + 120]
    assert "position: sticky" in chrome
    assert "top: 0" in chrome
    # Inner .top must not also be sticky (would open a gap under the brand bar)
    # Scope: first .top rule after .app-chrome should be flex layout only.
    top_idx = css.find(".top {", css.find(".app-chrome"))
    assert top_idx > 0
    top_rule = css[top_idx : top_idx + 200]
    assert "position: sticky" not in top_rule
