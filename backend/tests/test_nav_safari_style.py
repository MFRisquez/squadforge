"""Safari-style main nav + transfers picker color parity with desktop rail."""

from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

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
    assert "html[data-theme=\"dark\"] .pick-price" in css
    assert "html[data-theme=\"dark\"] .pick-row.avail-doubt .pick-price" in css
    assert "html[data-theme=\"dark\"] .pick-row.avail-out .pick-price" in css


def _driver_with(html: str):
    path = Path("/tmp/nav-pick-contrast-test.html")
    path.write_text(html, encoding="utf-8")
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=opts)
    driver.get(path.as_uri())
    return driver


def test_dark_pick_row_price_is_white_like_desktop_rail():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    html = f"""<!DOCTYPE html>
<html data-theme="dark">
<head><meta charset="utf-8"><style>{css}</style></head>
<body>
<button class="pick-row" id="ok">
  <span class="pick-main"><strong class="pick-name">Salah</strong><span class="pick-sub">LIV · MID</span></span>
  <span class="pick-price">£14.5</span>
</button>
<button class="pick-row avail-doubt" id="doubt">
  <span class="pick-main"><strong class="pick-name">Player D</strong><span class="pick-sub">ARS · MID</span></span>
  <span class="pick-price">£6.5</span>
</button>
</body></html>"""
    try:
        driver = _driver_with(html)
    except Exception:
        # Chrome may be unavailable in some CI images — structural asserts above still run.
        return
    try:
        ok_price = driver.find_element("css selector", "#ok .pick-price")
        color = driver.execute_script("return getComputedStyle(arguments[0]).color", ok_price)
        assert color == "rgb(255, 255, 255)", color

        doubt_price = driver.find_element("css selector", "#doubt .pick-price")
        dcolor = driver.execute_script("return getComputedStyle(arguments[0]).color", doubt_price)
        assert dcolor == "rgb(106, 82, 0)", dcolor
    finally:
        driver.quit()


def test_sticky_chrome_no_gap_when_scrolled():
    """Measure .top/.nav adjacency after scroll on a tall page (Rules-like)."""
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    html = f"""<!DOCTYPE html>
<html data-theme="dark">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>{css}
body {{ margin:0; }}
.shell {{ min-height: 220vh; padding: 1rem; }}
</style></head>
<body>
<div class="app-chrome">
  <header class="top"><a class="brand" href="/"><span class="brand-text">Fut Fantasy</span></a></header>
  <nav class="nav" aria-label="Main">
    <a href="/">Home</a><a class="is-active" href="/rules">Rules</a><a href="/team">Transfers</a>
  </nav>
</div>
<main class="shell"><p>long page</p></main>
</body></html>"""
    try:
        driver = _driver_with(html)
    except Exception:
        return
    try:
        driver.set_window_size(390, 844)
        driver.execute_script("window.scrollTo(0, 420)")
        gap = driver.execute_script(
            """
            const top = document.querySelector('.top');
            const nav = document.querySelector('.nav');
            const t = top.getBoundingClientRect();
            const n = nav.getBoundingClientRect();
            return Math.round((n.top - t.bottom) * 100) / 100;
            """
        )
        assert abs(gap) <= 1.0, f"unexpected gap between .top and .nav while sticky: {gap}px"

        # Second “short page” case: tiny scroll still flush
        driver.execute_script("window.scrollTo(0, 40)")
        gap2 = driver.execute_script(
            """
            const t = document.querySelector('.top').getBoundingClientRect();
            const n = document.querySelector('.nav').getBoundingClientRect();
            return Math.round((n.top - t.bottom) * 100) / 100;
            """
        )
        assert abs(gap2) <= 1.0, f"gap after short scroll: {gap2}px"
    finally:
        driver.quit()
