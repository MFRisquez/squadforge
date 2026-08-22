"""Live ingest must stay fast enough to keep minutes fresh mid-match."""

from __future__ import annotations

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import Club, Fixture, Gameweek, MatchEvent, OwnedPlayer, Player
from app.services import live_scoring as live_svc
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


def test_write_metrics_bulk_upserts_without_per_row_select():
    db = SessionLocal()
    try:
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        p = db.query(Player).order_by(Player.id).first()
        assert p is not None
        live_svc._write_metrics_bulk(
            db,
            gameweek_id=gw.id,
            updates=[(p.id, {"minutes": 38.0, "goals": 0.0})],
            source="test",
        )
        db.commit()
        live_svc._write_metrics_bulk(
            db,
            gameweek_id=gw.id,
            updates=[(p.id, {"minutes": 51.0, "goals": 1.0})],
            source="test",
        )
        db.commit()
        metrics = live_svc.metrics_for_player(db, gw.id, p.id)
        assert metrics["minutes"] == 51.0
        assert metrics["goals"] == 1.0
        rows = (
            db.query(MatchEvent)
            .filter(MatchEvent.gameweek_id == gw.id, MatchEvent.player_id == p.id)
            .all()
        )
        assert {r.metric for r in rows} >= {"minutes", "goals"}
    finally:
        db.close()


def test_live_ingest_player_ids_includes_owned_and_live_clubs():
    db = SessionLocal()
    try:
        from app.models import Manager

        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        for code, name in (("ARS", "Arsenal"), ("MUN", "Man Utd"), ("BHA", "Brighton")):
            if not db.query(Club).filter(Club.code == code).one_or_none():
                db.add(Club(code=code, name=name))
        fx = db.query(Fixture).filter(Fixture.fpl_id == 77001).one_or_none()
        if not fx:
            db.add(
                Fixture(
                    fpl_id=77001,
                    gameweek_number=1,
                    home_club_code="ARS",
                    away_club_code="MUN",
                    started=1,
                    finished=0,
                )
            )
        else:
            fx.started = 1
            fx.finished = 0
            fx.gameweek_number = 1
        p = db.query(Player).filter(Player.team_code == "ARS").order_by(Player.id).first()
        if not p:
            p = Player(
                external_id="fpl-77001",
                name="Test ARS",
                position="MID",
                team_code="ARS",
                price=5.0,
            )
            db.add(p)
            db.flush()
        other = Player(
            external_id="fpl-77099",
            name="Owned Bench BHA",
            position="MID",
            team_code="BHA",
            price=5.0,
        )
        db.add(other)
        db.flush()
        mgr = db.query(Manager).first()
        if mgr is None:
            mgr = Manager(display_name="Hotpath Tester", pin="0000")
            db.add(mgr)
            db.flush()
        db.query(OwnedPlayer).delete()
        db.add(OwnedPlayer(manager_id=mgr.id, player_id=other.id))
        db.commit()

        ids = live_svc._live_ingest_player_ids(db, gw)
        assert p.id in ids
        assert other.id in ids
    finally:
        db.close()


def test_ingest_fpl_live_only_writes_targeted_players(monkeypatch):
    db = SessionLocal()
    try:
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        a = Player(
            external_id="fpl-88011",
            name="Hot Path A",
            position="MID",
            team_code="ARS",
            price=5.0,
        )
        b = Player(
            external_id="fpl-88012",
            name="Hot Path B",
            position="MID",
            team_code="MUN",
            price=5.0,
        )
        db.add(a)
        db.add(b)
        db.commit()
        db.refresh(a)
        db.refresh(b)

        monkeypatch.setattr(live_svc, "_live_ingest_player_ids", lambda _db, _gw: {a.id})
        monkeypatch.setattr(
            live_svc,
            "_http_get",
            lambda url: {
                "elements": [
                    {"id": 88011, "stats": {"minutes": 51}},
                    {"id": 88012, "stats": {"minutes": 90}},
                ]
            }
            if "/live" in url
            else [],
        )
        monkeypatch.setattr(live_svc.fixtures_svc, "refresh_fixtures", lambda *_a, **_k: {"fixtures": 0})
        monkeypatch.setattr(live_svc, "merge_fixture_stats_into_events", lambda *_a, **_k: 0)

        out = live_svc.ingest_fpl_live(db, gw)
        assert out["players_updated"] == 1
        assert live_svc.metrics_for_player(db, gw.id, a.id).get("minutes") == 51.0
        assert live_svc.metrics_for_player(db, gw.id, b.id) == {}
    finally:
        db.close()
