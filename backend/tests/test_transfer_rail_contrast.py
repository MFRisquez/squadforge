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


def _row_html(theme: str) -> str:
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    return f"""<!DOCTYPE html>
<html data-theme="{theme}">
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
<button class="transfer-rail-row" id="ok">
  <span class="tr-name"><span class="tr-name-text"><strong>Player OK</strong><span>MCI · ATT</span></span></span>
  <span class="tr-price">£9.0</span>
  <span class="tr-form">6.0</span>
  <span class="tr-pts">120</span>
</button>
</body></html>"""


def test_dark_theme_avail_rows_use_dark_warning_text():
    driver = _driver_with(_row_html("dark"))
    try:
        for row_id, expected in (("doubt", "rgb(106, 82, 0)"), ("out", "rgb(122, 16, 16)")):
            row = driver.find_element("id", row_id)
            for sel in (".tr-name strong", ".tr-name-text > span", ".tr-form", ".tr-pts"):
                el = row.find_element("css selector", sel)
                color = driver.execute_script(
                    "return getComputedStyle(arguments[0]).color", el
                )
                assert color == expected, f"{row_id} {sel}: {color} != {expected}"
            bg = driver.execute_script(
                "return getComputedStyle(arguments[0]).backgroundColor", row
            )
            assert bg in (
                "rgb(255, 243, 191)",
                "rgb(255, 201, 201)",
            ), f"{row_id} bg={bg}"
    finally:
        driver.quit()


def test_avail_row_price_stays_black_in_light_and_dark():
    """Price matches normal black (#000), not brown/red warning ink."""
    for theme in ("light", "dark"):
        driver = _driver_with(_row_html(theme))
        try:
            for row_id in ("doubt", "out"):
                row = driver.find_element("id", row_id)
                price = row.find_element("css selector", ".tr-price")
                color = driver.execute_script(
                    "return getComputedStyle(arguments[0]).color", price
                )
                assert color == "rgb(0, 0, 0)", f"{theme} {row_id} price={color}"
        finally:
            driver.quit()
