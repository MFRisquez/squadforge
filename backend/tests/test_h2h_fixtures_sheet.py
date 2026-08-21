"""H2H fixtures on league page + match detail sheet."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import ChipState, Gameweek, H2HMatch, ManagerGameweekScore, Player
from app.services import league as league_svc
from app.services import standings as standings_svc
from app.services.seed import seed_if_empty


def setup_module():
    settings.reset_db_on_startup = False
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def test_h2h_fixture_cards_and_league_page_sheet():
    db = SessionLocal()
    try:
        a = league_svc.register_manager(
            db,
            display_name="FxA",
            password="secret12",
            email="fxa@example.com",
            team_name="Foxes",
        )
        b = league_svc.register_manager(
            db,
            display_name="FxB",
            password="secret12",
            email="fxb@example.com",
            team_name="Badgers",
        )
        league = league_svc.create_league(db, "H2H Fixtures", a, league_type="h2h")
        league_svc.join_league(db, league.invite_code, b)
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one_or_none()
        if not gw:
            gw = Gameweek(number=1, status="live", name="GW1", is_current=1)
            db.add(gw)
            db.flush()
        else:
            gw.status = "live"
            gw.is_current = 1
        # Past deadline required for scores / top XI to be public
        gw.deadline_at = (
            (datetime.now(timezone.utc) - timedelta(hours=2))
            .isoformat()
            .replace("+00:00", "Z")
        )
        player = db.query(Player).first()
        assert player is not None
        breakdown = json.dumps(
            {"players": [{"player_id": player.id, "points": 12, "base": 12, "mult": 1}]}
        )
        db.add(
            ManagerGameweekScore(
                manager_id=a.id,
                gameweek_id=gw.id,
                total=44,
                breakdown_json=breakdown,
            )
        )
        db.add(
            ManagerGameweekScore(
                manager_id=b.id,
                gameweek_id=gw.id,
                total=30,
                breakdown_json=json.dumps(
                    {"players": [{"player_id": player.id, "points": 8, "base": 8, "mult": 1}]}
                ),
            )
        )
        # Ensure chips remaining for A
        state = db.query(ChipState).filter(ChipState.manager_id == a.id).one()
        state.wildcard_remaining = 1
        state.triple_captain_remaining = 1
        db.commit()

        cards = standings_svc.h2h_fixture_cards(db, league, gw)
        assert len(cards) == 1
        card = cards[0]
        assert card["show_scores"] is True
        assert card["home"]["team_name"] in {"Foxes", "Badgers"}
        assert card["home"]["top_player"] is not None or card["away"]["top_player"] is not None
        assert "Wildcard" in (card["home"]["chips_left"] + card["away"]["chips_left"])
        lid = league.id
        pname = player.name
    finally:
        db.close()

    client = _client()
    client.post("/login", data={"login": "FxA", "password": "secret12"}, follow_redirects=False)
    html = client.get(f"/league/{lid}").text
    assert "H2H fixtures" in html
    assert "data-h2h-match" in html
    assert "h2hMatchDetail" in html
    assert "match-detail-sheet" in html
    assert "league_h2h.js" in html
    assert "h2hFixturesBoot" in html
    assert "league-gw-picker" in html
    assert "You vs rival" in html
    assert "Chips left" in html
    assert "Manager vs manager" not in html
    assert "Delete league" not in html
    assert "league-hero-compact" in html
    assert "Invite" in html
    assert "Foxes" in html and "Badgers" in html
    # Boot JSON includes top player payload
    assert pname.split()[0] in html or pname in html


def test_h2h_fixture_cards_hide_top_player_before_deadline():
    db = SessionLocal()
    try:
        a = league_svc.register_manager(
            db,
            display_name="PreDlA",
            password="secret12",
            email="predla@example.com",
            team_name="Pre Deadline A",
        )
        b = league_svc.register_manager(
            db,
            display_name="PreDlB",
            password="secret12",
            email="predlb@example.com",
            team_name="Pre Deadline B",
        )
        league = league_svc.create_league(db, "Pre Deadline Cup", a, league_type="h2h")
        league_svc.join_league(db, league.invite_code, b)
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        gw.status = "live"
        gw.is_current = 1
        gw.deadline_at = (
            (datetime.now(timezone.utc) + timedelta(days=2))
            .isoformat()
            .replace("+00:00", "Z")
        )
        player = db.query(Player).first()
        assert player is not None
        db.add(
            ManagerGameweekScore(
                manager_id=a.id,
                gameweek_id=gw.id,
                total=44,
                breakdown_json=json.dumps(
                    {"players": [{"player_id": player.id, "points": 12, "base": 12, "mult": 1}]}
                ),
            )
        )
        db.commit()
        cards = standings_svc.h2h_fixture_cards(db, league, gw)
        assert len(cards) == 1
        assert cards[0]["show_scores"] is False
        assert cards[0]["home"]["top_player"] is None
        assert cards[0]["away"]["top_player"] is None
    finally:
        db.close()


def test_h2h_fixture_cards_include_season_record():
    db = SessionLocal()
    try:
        a = league_svc.register_manager(
            db,
            display_name="RecA",
            password="secret12",
            email="reca@example.com",
            team_name="Alpha FC",
        )
        b = league_svc.register_manager(
            db,
            display_name="RecB",
            password="secret12",
            email="recb@example.com",
            team_name="Beta United",
        )
        league = league_svc.create_league(db, "Record Cup", a, league_type="h2h")
        league_svc.join_league(db, league.invite_code, b)
        gw1 = db.query(Gameweek).filter(Gameweek.number == 1).one()
        gw2 = db.query(Gameweek).filter(Gameweek.number == 2).one()
        gw2.status = "live"
        gw2.is_current = 1
        gw1.is_current = 0
        gw2.deadline_at = (
            (datetime.now(timezone.utc) - timedelta(hours=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
        # Prior settled meetings: A beat B twice, B beat A once (orientation flips)
        db.add(
            H2HMatch(
                league_id=league.id,
                gameweek_id=gw1.id,
                home_manager_id=a.id,
                away_manager_id=b.id,
                home_points=50,
                away_points=40,
                result="home",
            )
        )
        # Create a finished GW3 slot for the second prior meeting
        gw_prior = Gameweek(number=98, status="finished", name="GW98", is_current=0)
        db.add(gw_prior)
        db.flush()
        db.add(
            H2HMatch(
                league_id=league.id,
                gameweek_id=gw_prior.id,
                home_manager_id=b.id,
                away_manager_id=a.id,
                home_points=30,
                away_points=10,
                result="home",
            )
        )
        db.add(
            H2HMatch(
                league_id=league.id,
                gameweek_id=gw2.id,
                home_manager_id=a.id,
                away_manager_id=b.id,
                home_points=12,
                away_points=8,
                result="pending",
            )
        )
        # Another settled match where A wins as away
        gw_prior2 = Gameweek(number=97, status="finished", name="GW97", is_current=0)
        db.add(gw_prior2)
        db.flush()
        db.add(
            H2HMatch(
                league_id=league.id,
                gameweek_id=gw_prior2.id,
                home_manager_id=b.id,
                away_manager_id=a.id,
                home_points=5,
                away_points=22,
                result="away",
            )
        )
        db.commit()

        cards = standings_svc.h2h_fixture_cards(db, league, gw2)
        assert len(cards) == 1
        card = cards[0]
        assert card["home"]["initials"] == "AF"
        assert card["away"]["initials"] == "BU"
        assert "avatar_tone" in card["home"]
        assert "avatar_tone" in card["away"]
        assert 0 <= card["home"]["avatar_tone"] <= 7
        assert 0 <= card["away"]["avatar_tone"] <= 7
        assert card["season_record"] is not None
        # From home(A) perspective: A won gw1 + gw97, B won gw98 → 2-1
        assert card["season_record"]["home_wins"] == 2
        assert card["season_record"]["away_wins"] == 1
        assert card["season_record"]["label"] == "2-1 this season"
        lid = league.id
    finally:
        db.close()

    client = _client()
    client.post("/login", data={"login": "RecA", "password": "secret12"}, follow_redirects=False)
    # Force GW2 view via ensuring current is gw2 already in DB
    html = client.get(f"/league/{lid}").text
    assert "2-1 this season" in html
    assert "h2h-avatar" in html
    assert "h2h-vs-mark" in html
    assert "h2h-manager" in html
    assert "tone-" in html
    assert "live-dot" in html
    css = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "styles.css").read_text(
        encoding="utf-8"
    )
    assert "background: var(--panel)" in css
    assert "html[data-theme=\"dark\"] .h2h-card" in css
    assert ".h2h-avatar.tone-0" in css
    assert ".h2h-vs-mark" in css
    assert ".h2h-side.is-loser" in css
    assert ".h2h-card.is-draw" in css
    assert ".h2h-card.is-live" in css or ".h2h-card.is-pending" in css
    # League mid column keeps cards stacked (not multi-col grid)
    assert "body.page-league .league-col-mid .h2h-cards" in css
    assert "grid-template-columns: 1fr" in css


def test_h2h_preview_hides_scores_before_gw_starts():
    db = SessionLocal()
    try:
        a = league_svc.register_manager(
            db,
            display_name="PrevA",
            password="secret12",
            email="preva@example.com",
            team_name="Preview A",
        )
        b = league_svc.register_manager(
            db,
            display_name="PrevB",
            password="secret12",
            email="prevb@example.com",
            team_name="Preview B",
        )
        league = league_svc.create_league(db, "Preview Cup", a, league_type="h2h")
        league_svc.join_league(db, league.invite_code, b)
        gw = Gameweek(number=99, status="upcoming", name="GW99", is_current=0)
        db.add(gw)
        db.flush()
        db.add(
            H2HMatch(
                league_id=league.id,
                gameweek_id=gw.id,
                home_manager_id=a.id,
                away_manager_id=b.id,
                home_points=0,
                away_points=0,
                result="pending",
            )
        )
        db.commit()
        cards = standings_svc.h2h_fixture_cards(db, league, gw)
        assert len(cards) == 1
        assert cards[0]["show_scores"] is False
    finally:
        db.close()


def test_league_chips_board_and_rival_snapshot_on_page():
    from app.models import PlayerPoints, SquadPick

    db = SessionLocal()
    try:
        a = league_svc.register_manager(
            db,
            display_name="ChipA",
            password="secret12",
            email="chipa@example.com",
            team_name="Chip Alpha",
        )
        b = league_svc.register_manager(
            db,
            display_name="ChipB",
            password="secret12",
            email="chipb@example.com",
            team_name="Chip Beta",
        )
        league = league_svc.create_league(db, "Chip Cup", a, league_type="h2h")
        league_svc.join_league(db, league.invite_code, b)
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        db.query(Gameweek).update({"is_current": 0})
        gw.status = "live"
        gw.is_current = 1
        gw.deadline_at = (
            (datetime.now(timezone.utc) - timedelta(hours=2))
            .isoformat()
            .replace("+00:00", "Z")
        )
        db.add(
            H2HMatch(
                league_id=league.id,
                gameweek_id=gw.id,
                home_manager_id=a.id,
                away_manager_id=b.id,
                home_points=30,
                away_points=22,
                result="pending",
            )
        )
        players = db.query(Player).limit(11).all()
        assert len(players) >= 2
        for i, pl in enumerate(players[:11]):
            db.add(
                SquadPick(
                    manager_id=b.id,
                    gameweek_id=gw.id,
                    player_id=pl.id,
                    is_starter=1,
                    is_captain=1 if i == 0 else 0,
                    is_vice_captain=1 if i == 1 else 0,
                    bench_order=0,
                )
            )
            db.add(
                PlayerPoints(
                    player_id=pl.id,
                    gameweek_id=gw.id,
                    formula_version=settings.formula_version,
                    total=float(5 + i),
                )
            )
        db.add(ManagerGameweekScore(manager_id=a.id, gameweek_id=gw.id, total=30))
        db.add(ManagerGameweekScore(manager_id=b.id, gameweek_id=gw.id, total=22))
        db.commit()

        board = standings_svc.league_chips_board(db, league, me_id=a.id)
        assert len(board) == 2
        assert any(r["is_me"] for r in board)
        assert all(len(r["chips"]) == 5 for r in board)
        assert all("available" in c for r in board for c in r["chips"])

        snap = standings_svc.my_h2h_rival_snapshot(
            db, league, gw, a.id, edits_locked=True, current_gw_id=gw.id
        )
        assert snap is not None
        assert snap["bye"] is False
        assert snap["rival"]["manager_id"] == b.id
        assert snap["show_scores"] is True
        assert len(snap["rival_players"]) >= 2
        assert "me_players" in snap
        lid = league.id
    finally:
        db.close()

    client = _client()
    client.post("/login", data={"login": "ChipA", "password": "secret12"}, follow_redirects=False)
    html = client.get(f"/league/{lid}").text
    assert "league-gw-picker" in html
    assert "Chips left" in html
    assert "You vs rival" in html
    assert "league-matchup-xis" in html
    assert "Chip Beta" in html
    assert "is-used" in html or "league-chip-pill" in html
    # GW query param works
    html2 = client.get(f"/league/{lid}?gw=1").text
    assert "league-gw-picker" in html2
