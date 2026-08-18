"""Transfer-rail avail-doubt/out keep dark warning text in dark theme."""

from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

STATIC = Path(__file__).resolve().parents[1] / "app" / "web" / "static"


def _driver_with(html: str):
    path = Path("/tmp/rail-avail-contrast-test.html")
    path.write_text(html, encoding="utf-8")
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=opts)
    driver.get(path.as_uri())
    return driver


def test_dark_theme_avail_rows_use_dark_warning_text():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    html = f"""<!DOCTYPE html>
<html data-theme="dark">
<head><meta charset="utf-8"><style>{css}</style></head>
<body>
<button class="transfer-rail-row avail-doubt" id="doubt">
  <span class="tr-name"><span class="tr-name-text"><strong>Player D</strong><span>ARS · MID</span></span></span>
  <span class="tr-price">£6.5</span>
  <span class="tr-form">4.2</span>
  <span class="tr-pts">88</span>
</button>
<button class="transfer-rail-row avail-out" id="out">
  <span class="tr-name"><span class="tr-name-text"><strong>Player O</strong><span>CHE · DEF</span></span></span>
  <span class="tr-price">£5.0</span>
  <span class="tr-form">1.0</span>
  <span class="tr-pts">10</span>
</button>
</body></html>"""
    driver = _driver_with(html)
    try:
        for row_id, expected in (("doubt", "rgb(106, 82, 0)"), ("out", "rgb(122, 16, 16)")):
            row = driver.find_element("id", row_id)
            for sel in (
                ".tr-name strong",
                ".tr-name-text > span",
                ".tr-price",
                ".tr-form",
                ".tr-pts",
            ):
                el = row.find_element("css selector", sel)
                color = driver.execute_script(
                    "return getComputedStyle(arguments[0]).color", el
                )
                assert color == expected, f"{row_id} {sel}: {color} != {expected}"
            bg = driver.execute_script(
                "return getComputedStyle(arguments[0]).backgroundColor", row
            )
            # Pale warning backgrounds (not darkened for theme)
            assert bg in (
                "rgb(255, 243, 191)",  # doubt #fff3bf
                "rgb(255, 201, 201)",  # out #ffc9c9
            ), f"{row_id} bg={bg}"
    finally:
        driver.quit()
