"""Fase 1: League News generation engine (pack → rank → Anthropic → persist)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import (
    Gameweek,
    League,
    LeagueNewsEdition,
    Manager,
    ManagerGameweekScore,
    Membership,
    Player,
    PlayerPoints,
    TransferLog,
)
from app.services import league_news as news_svc
from app.services.seed import seed_if_empty


@pytest.fixture()
def db():
    settings.reset_db_on_startup = False
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        seed_if_empty(session)
        yield session
    finally:
        session.close()


def _mgr(db, name: str, team: str) -> Manager:
    m = Manager(display_name=name, pin="1234", team_name=team)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _league_with_members(db, n: int = 4) -> tuple[League, list[Manager], Gameweek]:
    league = League(name="News League", invite_code="NEWS01", league_type="classic")
    db.add(league)
    db.commit()
    db.refresh(league)
    managers = [_mgr(db, f"Mgr{i}", f"Team{i}") for i in range(n)]
    for m in managers:
        db.add(Membership(league_id=league.id, manager_id=m.id))
    gw1 = db.query(Gameweek).filter(Gameweek.number == 1).one()
    gw2 = db.query(Gameweek).filter(Gameweek.number == 2).one()
    # Ensure GWs exist from seed
    assert gw1 and gw2
    db.commit()
    return league, managers, gw2


def _seed_scores_and_history(db, league, managers, gw2):
    players = db.query(Player).limit(8).all()
    assert len(players) >= 4
    gw1 = db.query(Gameweek).filter(Gameweek.number == 1).one()

    # Historical GW1 points for averages
    for i, pl in enumerate(players):
        db.add(
            PlayerPoints(
                gameweek_id=gw1.id,
                player_id=pl.id,
                total=4.0 + i,
                breakdown_json="{}",
                formula_version=settings.formula_version,
            )
        )
        db.add(
            PlayerPoints(
                gameweek_id=gw2.id,
                player_id=pl.id,
                total=10.0 if i == 0 else (1.0 if i == 1 else 5.0),
                breakdown_json="{}",
                formula_version=settings.formula_version,
            )
        )

    # Manager scores: first manager's star broke out, second blew up
    star, dud = players[0], players[1]
    for i, m in enumerate(managers):
        lines = [
            {
                "player_id": star.id if i == 0 else dud.id,
                "points": 20.0 if i == 0 else 0.5,
                "base": 10.0 if i == 0 else 1.0,
                "mult": 2.0 if i == 0 else 1.0,
                "captain": i == 0,
            },
            {
                "player_id": players[2].id,
                "points": 5.0,
                "base": 5.0,
                "mult": 1.0,
                "captain": False,
            },
        ]
        db.add(
            ManagerGameweekScore(
                manager_id=m.id,
                gameweek_id=gw2.id,
                squad_points=25.0 - i,
                td_points=0,
                total=25.0 - i,
                breakdown_json=json.dumps({"players": lines}),
            )
        )
        # Also need GW1 scores for standings rank_delta
        db.add(
            ManagerGameweekScore(
                manager_id=m.id,
                gameweek_id=gw1.id,
                squad_points=10.0 + i,
                td_points=0,
                total=10.0 + i,
                breakdown_json="{}",
            )
        )

    # Transfers for most in/out
    for m in managers:
        db.add(
            TransferLog(
                manager_id=m.id,
                gameweek_id=gw2.id,
                player_out_id=players[3].id,
                player_in_id=star.id,
                free_transfers_after=0,
                is_hit=0,
            )
        )
    db.commit()
    return star, dud


def test_news_disabled_without_api_key(db, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    assert news_svc.news_enabled() is False
    league, _, gw = _league_with_members(db)
    result = news_svc.get_or_generate_edition(
        db, league=league, edition_type="post_gw", gameweek_number=gw.number
    )
    assert result["ok"] is False
    assert result["skipped"] == "no_api_key"


def test_build_post_gw_package_ranks_by_drama(db):
    league, managers, gw2 = _league_with_members(db, n=4)
    star, dud = _seed_scores_and_history(db, league, managers, gw2)
    package = news_svc.build_post_gw_package(db, league, gw2)
    assert package["edition_type"] == "post_gw"
    assert package["league_id"] == league.id
    stories = package["stories"]
    assert 1 <= len(stories) <= 8
    dramas = [s["drama"] for s in stories]
    assert dramas == sorted(dramas, reverse=True)
    kinds = {s["kind"] for s in stories}
    # Expect transfer + swing stories when data present
    assert "transfer_in" in kinds or "broke_out" in kinds or "rank_move" in kinds
    # Drama for broke_out / blew_up uses abs(delta)
    swings = [s for s in stories if s["kind"] in ("broke_out", "blew_up")]
    for s in swings:
        assert s["player_id"] in (star.id, dud.id)
        assert "delta" in s
        assert abs(s["delta"]) == pytest.approx(s["drama"], abs=0.05)


def test_get_or_generate_persists_once(db, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key-not-real")
    league, managers, gw2 = _league_with_members(db, n=4)
    _seed_scores_and_history(db, league, managers, gw2)

    fake_content = {
        "title": "GW2 — locura",
        "kicker": "Subidas, bajadas y un crack",
        "stories": [
            {"headline": "H1", "body": "Body 1", "player_id": None},
        ],
    }

    with patch.object(news_svc, "call_gemini_for_edition", return_value=fake_content) as mock_call:
        first = news_svc.get_or_generate_edition(
            db, league=league, edition_type="post_gw", gameweek_number=gw2.number
        )
        assert first["ok"] is True
        assert first["cached"] is False
        assert mock_call.call_count == 1

        second = news_svc.get_or_generate_edition(
            db, league=league, edition_type="post_gw", gameweek_number=gw2.number
        )
        assert second["ok"] is True
        assert second["cached"] is True
        assert mock_call.call_count == 1  # no second API call

    rows = db.query(LeagueNewsEdition).all()
    assert len(rows) == 1
    assert rows[0].edition_type == "post_gw"
    assert rows[0].gameweek_number == gw2.number
    assert json.loads(rows[0].content_json)["title"] == "GW2 — locura"


def test_call_gemini_parses_json(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    package = {
        "edition_type": "post_gw",
        "league_id": 1,
        "gameweek_number": 2,
        "stories": [{"kind": "rank_move", "drama": 3, "player_id": None, "rank_delta": 3}],
    }
    api_body = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "title": "T",
                                    "kicker": "K",
                                    "stories": [{"headline": "H", "body": "B", "player_id": None}],
                                }
                            )
                        }
                    ]
                }
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = api_body

    with patch("app.services.league_news.httpx.Client") as client_cls:
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.post.return_value = mock_resp
        client_cls.return_value = client
        out = news_svc.call_gemini_for_edition(package)

    assert out["title"] == "T"
    assert len(out["stories"]) == 1
    kwargs = client.post.call_args
    assert kwargs[0][0] == news_svc.GEMINI_URL
    assert "gemini-3.6-flash" in kwargs[0][0]
    sent = kwargs[1]["json"]
    assert sent["generationConfig"]["responseMimeType"] == "application/json"
    assert kwargs[1]["headers"]["x-goog-api-key"] == "test-key"
