"""Sync clubs, players, and gameweeks from the live FPL API (2025/26+)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.models import Club, Gameweek, Player

FPL_BOOTSTRAP = "https://fantasy.premierleague.com/api/bootstrap-static/"
POSITION_MAP = {1: "GK", 2: "DEF", 3: "MID", 4: "ATT"}


def fetch_bootstrap(timeout: float = 45.0) -> dict[str, Any]:
    headers = {
        "User-Agent": "SquadForge/0.3 (private fantasy; contact local)",
        "Accept": "application/json",
    }
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        response = client.get(FPL_BOOTSTRAP)
        response.raise_for_status()
        return response.json()


def availability_flag(status: str, chance: int | None) -> str:
    """ok | doubt | out — drives UI colors."""
    st = (status or "a").lower()
    if st in {"i", "s", "u"} or chance == 0:
        return "out"
    if st == "d" or (chance is not None and chance <= 75):
        return "doubt"
    return "ok"


def _season_stats_from_element(el: dict[str, Any]) -> dict[str, Any]:
    """Compact FPL season KPIs for player detail."""
    minutes = float(el.get("minutes") or 0)
    starts = float(el.get("starts") or 0)
    return {
        "total_points": float(el.get("total_points") or 0),
        "points_per_game": float(el.get("points_per_game") or 0),
        "form": str(el.get("form") or "0"),
        "selected_by": float(el.get("selected_by_percent") or 0),
        "minutes": minutes,
        "starts": starts,
        "minutes_per_start": round(minutes / starts, 1) if starts else 0.0,
        "goals": float(el.get("goals_scored") or 0),
        "assists": float(el.get("assists") or 0),
        "clean_sheets": float(el.get("clean_sheets") or 0),
        "goals_conceded": float(el.get("goals_conceded") or 0),
        "saves": float(el.get("saves") or 0),
        "penalties_saved": float(el.get("penalties_saved") or 0),
        "yellow_cards": float(el.get("yellow_cards") or 0),
        "red_cards": float(el.get("red_cards") or 0),
        "bonus": float(el.get("bonus") or 0),
        "bps": float(el.get("bps") or 0),
        "ict_index": float(el.get("ict_index") or 0),
        "creativity": float(el.get("creativity") or 0),
        "threat": float(el.get("threat") or 0),
        # Season CBI when FPL exposes it on bootstrap; else 0 until live/advanced ingest.
        "cbi": float(el.get("clearances_blocks_interceptions") or 0),
        "expected_goals": float(el.get("expected_goals") or 0),
        "expected_assists": float(el.get("expected_assists") or 0),
    }


def sync_from_fpl(db: Session, data: dict[str, Any] | None = None) -> dict[str, int]:
    """Upsert the full PL player list + clubs + gameweeks from FPL."""
    payload = data or fetch_bootstrap()
    teams = {t["id"]: t for t in payload["teams"]}
    now = datetime.utcnow()

    club_count = 0
    for team in payload["teams"]:
        code = (team.get("short_name") or team["name"][:3]).upper()[:8]
        kit_code = int(team.get("code") or 0) or None
        fpl_team_id = int(team.get("id") or 0) or None
        club = db.query(Club).filter(Club.code == code).one_or_none()
        if not club:
            club = Club(code=code, name=team["name"], kit_code=kit_code, fpl_team_id=fpl_team_id)
            db.add(club)
        else:
            club.name = team["name"]
            club.kit_code = kit_code
            club.fpl_team_id = fpl_team_id
        club_count += 1

    player_count = 0
    import json as _json

    for el in payload["elements"]:
        team = teams.get(el["team"])
        if not team:
            continue
        team_code = (team.get("short_name") or team["name"][:3]).upper()[:8]
        ext = f"fpl-{el['id']}"
        position = POSITION_MAP.get(el["element_type"], "MID")
        price = float(el["now_cost"]) / 10.0
        name = el.get("web_name") or f"{el.get('first_name', '')} {el.get('second_name', '')}".strip()
        status = (el.get("status") or "a")[:8]
        chance = el.get("chance_of_playing_next_round")
        news = (el.get("news") or "")[:255]
        photo = (el.get("photo") or "")[:64]
        stats_json = _json.dumps(_season_stats_from_element(el))
        player = db.query(Player).filter(Player.external_id == ext).one_or_none()
        if not player:
            player = Player(
                external_id=ext,
                name=name,
                position=position,
                team_code=team_code,
                price=price,
                status=status,
                chance_of_playing=chance,
                news=news,
                photo=photo,
                season_stats_json=stats_json,
            )
            db.add(player)
        else:
            player.name = name
            player.position = position
            player.team_code = team_code
            player.price = price
            player.status = status
            player.chance_of_playing = chance
            player.news = news
            player.photo = photo
            player.season_stats_json = stats_json
        player_count += 1

    current_number = None
    for event in payload["events"]:
        number = int(event["id"])
        status = "upcoming"
        if event.get("finished"):
            status = "finished"
        elif event.get("is_current"):
            status = "live"
            current_number = number
        elif event.get("is_next"):
            status = "upcoming"
            if current_number is None:
                current_number = number
        gw = db.query(Gameweek).filter(Gameweek.number == number).one_or_none()
        name = event.get("name") or f"Gameweek {number}"
        deadline = event.get("deadline_time")
        if not gw:
            db.add(
                Gameweek(
                    number=number,
                    name=name,
                    status=status,
                    is_current=0,
                    deadline_at=deadline,
                )
            )
        else:
            gw.name = name
            gw.status = status
            if deadline:
                gw.deadline_at = deadline

    db.flush()
    # Prefer FPL's idea of current, but never roll *backward* if we already
    # advanced locally (FPL often keeps the old event ``is_current`` until BPS).
    local_current = (
        db.query(Gameweek)
        .filter(Gameweek.is_current == 1)
        .order_by(Gameweek.number.desc())
        .first()
    )
    if current_number is None:
        current_number = int(local_current.number) if local_current else 1
    elif local_current is not None and int(local_current.number) > int(current_number):
        current_number = int(local_current.number)
    for gw in db.query(Gameweek).all():
        gw.is_current = 1 if gw.number == current_number else 0

    db.commit()

    fixture_info: dict[str, int] = {"fixtures": 0}
    try:
        from app.services import fixtures as fixtures_svc

        fixture_info = fixtures_svc.sync_fixtures(db)
    except Exception:
        fixture_info = {"fixtures": 0}

    # After fixture flags land, roll current GW forward if every match is done.
    try:
        from app.services import squad as squad_svc

        if squad_svc.maybe_advance_finished_gameweek(db):
            cur = db.query(Gameweek).filter(Gameweek.is_current == 1).one_or_none()
            if cur:
                current_number = int(cur.number)
    except Exception:
        pass

    return {
        "clubs": club_count,
        "players": player_count,
        "fixtures": int(fixture_info.get("fixtures") or 0),
        "current_gw": current_number,
        "synced_at": now.isoformat() + "Z",
    }
