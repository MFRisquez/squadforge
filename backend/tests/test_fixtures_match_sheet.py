"""Fixture match sheet: layout contract + team news enrichment."""

from pathlib import Path
from unittest.mock import patch

from app.db import Base, SessionLocal, engine
from app.models import Club, Fixture, Player
from app.services import fixtures as fixtures_svc
from app.services import pl_content
from app.services.seed import seed_if_empty

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "web" / "static"


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()


def test_club_team_news_cards_use_photo_and_title():
    db = SessionLocal()
    try:
        if not db.query(Club).filter(Club.code == "ARS").one_or_none():
            db.add(Club(code="ARS", name="Arsenal", kit_code=3))
        ext = "news-ars-saliba"
        existing = db.query(Player).filter(Player.external_id == ext).one_or_none()
        if existing:
            p = existing
        else:
            p = Player(
                external_id=ext,
                name="Saliba",
                position="DEF",
                team_code="ARS",
                price=6.0,
            )
            db.add(p)
        p.status = "i"
        p.news = "Back injury - Unknown return date"
        p.photo = "462424.jpg"
        db.commit()

        cards = pl_content.club_team_news(db, "ARS", limit=5)
        assert cards
        hit = next(c for c in cards if c["player"] == "Saliba")
        assert hit["availability"] == "out"
        assert "Saliba" in hit["title"]
        assert "Unknown return date" in hit["body"] or "Back" in hit["body"]
        assert hit["photo"] and "462424" in hit["photo"]
        assert hit["kind"]
    finally:
        db.close()


def test_match_preview_blurb_includes_venue_and_absences():
    preview = pl_content.match_preview_blurb(
        home_name="Arsenal",
        away_name="Liverpool",
        pulse={"venue": "Emirates Stadium", "city": "London", "formations": []},
        home_news=[{"player": "Saliba", "availability": "out"}],
        away_news=[{"player": "Salah", "availability": "doubt"}],
    )
    assert preview["title"] == "Arsenal vs Liverpool"
    assert "Emirates Stadium" in preview["body"]
    assert "Saliba" in preview["body"]
    assert "Salah" in preview["body"]
    body_l = preview["body"].lower()
    assert "line-ups" in body_l or "formation" in body_l


def test_fixture_detail_includes_team_news_and_preview():
    db = SessionLocal()
    try:
        for code, name, kit in (("ARS", "Arsenal", 3), ("LIV", "Liverpool", 14)):
            if not db.query(Club).filter(Club.code == code).one_or_none():
                db.add(Club(code=code, name=name, kit_code=kit))
        fx = db.query(Fixture).filter(Fixture.fpl_id == 91001).one_or_none()
        if not fx:
            fx = Fixture(
                fpl_id=91001,
                gameweek_number=1,
                home_club_code="ARS",
                away_club_code="LIV",
                home_difficulty=3,
                away_difficulty=3,
                kickoff_at="2026-08-21T19:00:00Z",
                started=0,
                finished=0,
            )
            db.add(fx)
        ext = "news-liv-demo"
        if not db.query(Player).filter(Player.external_id == ext).one_or_none():
            db.add(
                Player(
                    external_id=ext,
                    name="Demo LIV",
                    position="MID",
                    team_code="LIV",
                    price=8.0,
                    status="d",
                    news="Knock - Expected back for GW2",
                    photo="118748.jpg",
                )
            )
        db.commit()
        fid = fx.id

        fake_pulse = {
            "pulse_id": 1,
            "venue": "Emirates Stadium",
            "city": "London",
            "formations": [],
            "status": "U",
        }
        with patch.object(pl_content, "resolve_pulse_fixture", return_value=fake_pulse):
            detail = fixtures_svc.fixture_detail(db, fixture_id=fid)

        assert detail is not None
        assert "team_news" in detail
        assert "home" in detail["team_news"] and "away" in detail["team_news"]
        assert detail.get("preview")
        assert "Emirates" in (detail["preview"].get("body") or "")
        assert detail["team_news"]["away"]
        assert all("title" in c and "body" in c for c in detail["team_news"]["away"])
    finally:
        db.close()


def test_fixtures_js_match_sheet_section_order():
    js = (STATIC / "fixtures.js").read_text(encoding="utf-8")
    assert "match-crests" in js
    assert "match-names" in js
    assert "In your XI" in js
    assert "fx-news-section" in js
    assert "fx-preview-card" in js
    assert "team_news" in js
    status_i = js.find("${statusLine}")
    stats_i = js.find("${watchBlock}")
    xi_i = js.find("${squadBlock}")
    news_i = js.find("${newsBlock}")
    assert 0 < status_i < stats_i < xi_i < news_i


def test_fixtures_css_vs_aligned_with_crests():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert ".match-scoreline .match-crests" in css
    assert "grid-template-columns: 1fr auto 1fr" in css
    assert ".fx-news-card" in css
    assert ".fx-preview-card" in css
    assert "gap: 0.4rem" in css
