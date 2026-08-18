"""Sticky app chrome: .top + .nav stick as one unit (no gap)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "web" / "templates"
STATIC = ROOT / "app" / "web" / "static"


def test_base_wraps_top_and_nav_in_app_chrome():
    html = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    chrome_open = html.find('<div class="app-chrome">')
    top_i = html.find('<header class="top">')
    nav_i = html.find('<nav class="nav"')
    chrome_close = html.find("</div>", nav_i if nav_i > 0 else top_i)
    assert chrome_open >= 0
    assert top_i > chrome_open
    assert nav_i > top_i
    assert chrome_close > nav_i
    # Shell starts after chrome closes
    assert html.find('<main class="shell', chrome_close) > chrome_close


def test_sticky_is_on_app_chrome_not_top_or_nav():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    # Chrome unit sticks at top: 0
    chrome_block = css[css.find(".app-chrome") : css.find(".app-chrome") + 120]
    assert "position: sticky" in chrome_block
    assert "top: 0" in chrome_block

    # Legacy manual offset must be gone
    assert "top: 3.15rem" not in css
    assert "top: calc(1.85rem + env(safe-area-inset-top" not in css

    # .top / .nav themselves are not sticky (scan their rule blocks)
    top_start = css.find("\n.top {")
    assert top_start >= 0
    top_block = css[top_start : top_start + 280]
    assert "position: sticky" not in top_block

    nav_start = css.find("\n.nav {")
    assert nav_start >= 0
    nav_block = css[nav_start : nav_start + 280]
    assert "position: sticky" not in nav_block
    assert "top: 3.15rem" not in nav_block


def test_page_fit_flex_targets_app_chrome():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    start = css.find("Height model: body is a flex column")
    assert start >= 0
    chunk = css[start : start + 4500]
    assert "body.page-fit > .app-chrome" in chunk
    assert "body.page-fit > .top" not in chunk
    assert "body.page-fit > .nav" not in chunk
    assert "body.page-fit > .shell" in chunk
