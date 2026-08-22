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
TEMPLATES = ROOT / "app" / "web" / "templates"


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


def test_fixture_detail_is_local_only_no_pulse():
    """Fast path must not attach PulseLive enrichment."""
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
        db.commit()
        fid = fx.id

        with patch.object(pl_content, "resolve_pulse_fixture") as pulse_mock:
            detail = fixtures_svc.fixture_detail(db, fixture_id=fid)

        assert detail is not None
        assert detail["home"]["code"] == "ARS"
        assert "goals" in detail
        assert "team_news" not in detail
        assert "preview" not in detail
        assert "pulse" not in detail
        assert detail.get("team_stats") is None
        pulse_mock.assert_not_called()
    finally:
        db.close()


def test_fixture_sheet_preview_includes_team_news_and_preview():
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
            "pulse_id": 128923,
            "venue": "Emirates Stadium",
            "city": "London",
            "formations": [],
            "status": "C",
        }
        fake_stats = {
            "source": "pulselive",
            "pulse_id": 128923,
            "possession": {"home": "64%", "away": "36%"},
            "shots_on_target": {"home": 6, "away": 1},
            "chances_created": {"home": 20, "away": 4},
            "expected_goals": {"home": None, "away": None},
            "passes_accurate": {"home": 565, "away": 271},
            "duels_won": {"home": 37, "away": 34},
            "fouls": {"home": 10, "away": 13},
        }
        with patch.object(pl_content, "resolve_pulse_fixture", return_value=fake_pulse):
            with patch.object(pl_content, "fetch_pulse_match_stats", return_value=fake_stats):
                detail = fixtures_svc.fixture_sheet_preview(db, fixture_id=fid)

        assert detail is not None
        assert "team_news" in detail
        assert "home" in detail["team_news"] and "away" in detail["team_news"]
        assert detail.get("preview")
        assert "Emirates" in (detail["preview"].get("body") or "")
        assert detail["team_news"]["away"]
        assert all("title" in c and "body" in c for c in detail["team_news"]["away"])
        assert detail.get("team_stats") == fake_stats
        assert detail.get("team_stats_status") == "ok"
    finally:
        db.close()


def test_fixtures_js_match_sheet_section_order():
    js = (STATIC / "fixtures.js").read_text(encoding="utf-8")
    assert "match-side" in js
    assert "match-club-name" in js
    assert "In your XI" in js
    assert "fx-xi-table" in js
    assert "fx-news-section" in js
    assert "fx-preview-card" in js
    assert "team_news" in js
    assert "/preview" in js
    assert "newsLoading" in js
    assert "applyMatchPreview" in js
    assert "Possession &amp; shots stats unavailable this season." in js
    assert "API-Football key on the server" not in js
    assert "coming soon" not in js.lower()
    status_i = js.find("${statusLine}")
    stats_i = js.find("${watchBlock}")
    xi_i = js.find("${squadBlock}")
    news_i = js.find("${newsBlock}")
    assert 0 < status_i < stats_i < xi_i < news_i


def test_fixtures_list_shows_home_away_and_score_placeholder():
    tpl = (TEMPLATES / "fixtures.html").read_text(encoding="utf-8")
    js = (STATIC / "fixtures.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert 'class="fx-ha-tag">Home</span>' in tpl
    assert 'class="fx-ha-tag">Away</span>' in tpl
    assert "fx-score-empty" in tpl
    assert "fx-club-name" in tpl
    assert "fx-club-code" in tpl
    assert 'fx-score-empty">-</span>' in js
    assert "fx-ha-tag\">Home</span>" in js
    assert "font-size: 101.5%" in css
    assert "body.page-fixtures .fx-club-code" in css
    assert "full team name on phone" in css
    assert "width: 2.4rem" in css


def test_fixtures_js_xi_table_is_match_kpis():
    js = (STATIC / "fixtures.js").read_text(encoding="utf-8")
    assert "fx-xi-table" in js
    assert 'scope="col">G</th>' in js
    assert 'scope="col">A</th>' in js
    assert 'scope="col">CS</th>' in js
    assert 'scope="col">Pts</th>' in js
    assert "p.goals" in js
    assert "p.assists" in js
    assert "p.clean_sheets" in js
    assert "total_points" not in js
    assert "p.form" not in js


def test_fixtures_css_vs_aligned_with_crests():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert ".match-scoreline-badges" in css
    assert ".match-scoreline-badges .match-side" in css
    assert "justify-items: center" in css
    assert ".fx-xi-table" in css
    assert ".fx-news-card" in css
    assert ".fx-preview-card" in css
    assert "gap: 0.4rem" in css


def test_my_players_fixture_kpis_blank_before_kickoff():
    db = SessionLocal()
    try:
        if not db.query(Club).filter(Club.code == "ARS").one_or_none():
            db.add(Club(code="ARS", name="Arsenal", kit_code=3))
        if not db.query(Club).filter(Club.code == "LIV").one_or_none():
            db.add(Club(code="LIV", name="Liverpool", kit_code=14))
        fx = db.query(Fixture).filter(Fixture.fpl_id == 92001).one_or_none()
        if not fx:
            fx = Fixture(
                fpl_id=92001,
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
        fx.started = 0
        fx.finished = 0
        fx.stats_json = "[]"
        ext = "fpl-92001"
        p = db.query(Player).filter(Player.external_id == ext).one_or_none()
        if not p:
            p = Player(
                external_id=ext,
                name="Saka",
                position="MID",
                team_code="ARS",
                price=9.0,
            )
            db.add(p)
        p.season_stats_json = '{"form": 9.9, "total_points": 999}'
        db.commit()

        mine = fixtures_svc.my_players_for_fixture(db, fx, [p])
        assert len(mine["home"]) == 1
        row = mine["home"][0]
        assert row["name"] == "Saka"
        assert row["goals"] is None
        assert row["assists"] is None
        assert row["clean_sheets"] is None
        assert row["points"] is None
        assert "form" not in row
        assert "total_points" not in row
    finally:
        db.close()


def test_my_players_fixture_kpis_from_match_stats():
    import json

    db = SessionLocal()
    try:
        for code, name, kit in (("ARS", "Arsenal", 3), ("LIV", "Liverpool", 14)):
            if not db.query(Club).filter(Club.code == code).one_or_none():
                db.add(Club(code=code, name=name, kit_code=kit))
        fx = db.query(Fixture).filter(Fixture.fpl_id == 92002).one_or_none()
        if not fx:
            fx = Fixture(
                fpl_id=92002,
                gameweek_number=1,
                home_club_code="ARS",
                away_club_code="LIV",
                home_difficulty=3,
                away_difficulty=3,
                kickoff_at="2026-08-21T19:00:00Z",
                started=1,
                finished=1,
            )
            db.add(fx)
        fx.started = 1
        fx.finished = 1
        fx.home_score = 2
        fx.away_score = 0
        fx.stats_json = json.dumps(
            [
                {
                    "identifier": "goals_scored",
                    "h": [{"element": 55501, "value": 1}],
                    "a": [],
                },
                {
                    "identifier": "assists",
                    "h": [{"element": 55501, "value": 1}],
                    "a": [],
                },
            ]
        )
        ext = "fpl-55501"
        p = db.query(Player).filter(Player.external_id == ext).one_or_none()
        if not p:
            p = Player(
                external_id=ext,
                name="Saka",
                position="MID",
                team_code="ARS",
                price=9.0,
            )
            db.add(p)
        db.commit()

        mine = fixtures_svc.my_players_for_fixture(db, fx, [p])
        row = mine["home"][0]
        assert row["goals"] == 1
        assert row["assists"] == 1
        assert row["clean_sheets"] == 0  # MID
        assert row["points"] is not None
    finally:
        db.close()


def test_super_sub_bench_select_smaller_on_phone():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "font-size: 0.55rem !important" in css
    # Must override the global phone select { font-size: 16px !important }
    assert "select,\n  textarea {\n    font-size: 16px !important;" in css or "font-size: 16px !important" in css


def test_pick_row_wrap_avail_bg_covers_info_btn():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert ".pick-row-wrap.avail-doubt" in css
    assert ".pick-row-wrap.avail-out" in css
    assert ".pick-row-wrap.is-blocked" in css
    assert ".pick-row-wrap.is-blocked .pick-info-btn" in css
    js = (STATIC / "squadboard.js").read_text(encoding="utf-8")
    assert "pick-row-wrap avail-${avail}${blocked ? \" is-blocked\" : \"\"}" in js