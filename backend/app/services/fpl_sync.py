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


def sync_from_fpl(db: Session, data: dict[str, Any] | None = None) -> dict[str, int]:
    """Upsert the full PL player list + clubs + gameweeks from FPL."""
    payload = data or fetch_bootstrap()
    teams = {t["id"]: t for t in payload["teams"]}
    now = datetime.utcnow()

    club_count = 0
    for team in payload["teams"]:
        code = (team.get("short_name") or team["name"][:3]).upper()[:8]
        kit_code = int(team.get("code") or 0) or None
        club = db.query(Club).filter(Club.code == code).one_or_none()
        if not club:
            club = Club(code=code, name=team["name"], kit_code=kit_code)
            db.add(club)
        else:
            club.name = team["name"]
            club.kit_code = kit_code
        club_count += 1

    player_count = 0
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
    if current_number is None:
        current_number = 1
    for gw in db.query(Gameweek).all():
        gw.is_current = 1 if gw.number == current_number else 0

    db.commit()
    return {
        "clubs": club_count,
        "players": player_count,
        "current_gw": current_number,
        "synced_at": now.isoformat() + "Z",
    }
