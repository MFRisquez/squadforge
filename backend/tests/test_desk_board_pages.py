"""Desktop desk-board / page-fit shell on content pages."""

from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "web" / "templates"

PAGES = (
    "standings.html",
    "transfers.html",
    "fixtures.html",
    "td.html",
    "home.html",
    "league.html",
    "leagues.html",
    "team_edit.html",
)


def test_content_pages_use_desk_board_page_fit():
    for name in PAGES:
        src = (TEMPLATES / name).read_text(encoding="utf-8")
        assert "page-fit" in src, f"{name} missing page-fit body class"
        assert 'class="desk-board desk-page"' in src or "class='desk-board desk-page'" in src, (
            f"{name} missing desk-board desk-page wrapper"
        )
        assert "desk-main" in src, f"{name} missing desk-main"
