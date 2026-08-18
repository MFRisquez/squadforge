"""Transfer-rail avail-doubt/out keep dark warning text in dark theme."""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "web" / "static"


def _rule_body_after(css: str, marker: str) -> str:
    """Return the `{ ... }` body that follows the first occurrence of marker."""
    idx = css.find(marker)
    assert idx >= 0, f"missing marker: {marker}"
    brace = css.find("{", idx)
    assert brace >= 0
    end = css.find("}", brace)
    assert end >= 0
    return css[brace : end + 1]


def test_dark_theme_avail_rows_use_dark_warning_text():
    """Doubt/out rows force warning ink + fill on name/price/form/pts (incl. dark)."""
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert ".transfer-rail-row.avail-doubt" in css
    assert ".transfer-rail-row.avail-out" in css

    # Background fills (rgb(255, 243, 191) / rgb(255, 201, 201))
    assert "#fff3bf" in css
    assert "#ffc9c9" in css

    # Shared child selector lists include every KPI cell the old Selenium test sampled
    for kind, hex_color in (("doubt", "#6a5200"), ("out", "#7a1010")):
        marker = f".transfer-rail-row.avail-{kind} .tr-name,"
        body = _rule_body_after(css, marker)
        # Selector list (before `{`) must name price/form/pts together
        head = css[css.find(marker) : css.find("{", css.find(marker))]
        assert ".tr-price" in head
        assert ".tr-form" in head
        assert ".tr-pts" in head
        assert 'html[data-theme="dark"]' in head
        assert 'html[data-theme="light"]' in head
        assert hex_color in body
        assert "!important" in body

    # Row-level dark overrides keep the same ink
    dark_doubt = _rule_body_after(css, 'html[data-theme="dark"] .transfer-rail-row.avail-doubt')
    assert "#6a5200" in dark_doubt
    dark_out = _rule_body_after(css, 'html[data-theme="dark"] .transfer-rail-row.avail-out')
    assert "#7a1010" in dark_out


def test_avail_row_price_matches_other_kpis():
    """Price uses the same warning ink selectors as form/pts (not forced black)."""
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    for kind, hex_color in (("doubt", "#6a5200"), ("out", "#7a1010")):
        marker = f".transfer-rail-row.avail-{kind} .tr-price"
        idx = css.find(marker)
        assert idx >= 0
        brace = css.find("{", idx)
        head = css[css.rfind(".transfer-rail-row.avail-", 0, idx + 1) : brace]
        body = css[brace : css.find("}", brace) + 1]
        assert ".tr-price" in head
        assert ".tr-form" in head
        assert ".tr-pts" in head
        assert hex_color in body
        assert "!important" in body
        for theme in ("dark", "light"):
            themed = f'html[data-theme="{theme}"] .transfer-rail-row.avail-{kind} .tr-price'
            assert themed in css
