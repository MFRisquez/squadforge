"""Player profile payloads for Squad (season) and Lineup (match) sheets."""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.kits import kit_for
from app.models import Club, Gameweek, MatchEvent, Player, PlayerPoints
from app.services import fixtures as fixtures_svc
from app.services.fpl_sync import availability_flag
from app.services.live_scoring import metrics_for_player

# Position-specific season KPI tables (label, stats key)
SEASON_KPI_TABLES: dict[str, list[tuple[str, str]]] = {
    "GK": [
        ("Total pts", "total_points"),
        ("PPG", "points_per_game"),
        ("Form", "form"),
        ("Selected", "selected_by"),
        ("Minutes", "minutes"),
        ("Mins / start", "minutes_per_start"),
        ("Starts", "starts"),
        ("Saves", "saves"),
        ("Clean sheets", "clean_sheets"),
        ("Goals conc.", "goals_conceded"),
        ("Pen saves", "penalties_saved"),
        ("Bonus", "bonus"),
    ],
    "DEF": [
        ("Total pts", "total_points"),
        ("PPG", "points_per_game"),
        ("Form", "form"),
        ("Selected", "selected_by"),
        ("Minutes", "minutes"),
        ("Mins / start", "minutes_per_start"),
        ("Starts", "starts"),
        ("Goals", "goals"),
        ("Assists", "assists"),
        ("Clean sheets", "clean_sheets"),
        ("Goals conc.", "goals_conceded"),
        ("Bonus", "bonus"),
    ],
    "MID": [
        ("Total pts", "total_points"),
        ("PPG", "points_per_game"),
        ("Form", "form"),
        ("Selected", "selected_by"),
        ("Minutes", "minutes"),
        ("Mins / start", "minutes_per_start"),
        ("Starts", "starts"),
        ("Goals", "goals"),
        ("Assists", "assists"),
        ("Clean sheets", "clean_sheets"),
        ("xG", "expected_goals"),
        ("xA", "expected_assists"),
        ("Bonus", "bonus"),
    ],
    "ATT": [
        ("Total pts", "total_points"),
        ("PPG", "points_per_game"),
        ("Form", "form"),
        ("Selected", "selected_by"),
        ("Minutes", "minutes"),
        ("Mins / start", "minutes_per_start"),
        ("Starts", "starts"),
        ("Goals", "goals"),
        ("Assists", "assists"),
        ("xG", "expected_goals"),
        ("xA", "expected_assists"),
        ("ICT", "ict_index"),
        ("Bonus", "bonus"),
    ],
}

# Match metrics shown in Lineup once the GW is live/locked
MATCH_METRIC_ROWS: list[tuple[str, str]] = [
    ("Minutes", "minutes"),
    ("Goals", "goals"),
    ("Assists", "assists"),
    ("Clean sheet", "clean_sheets"),
    ("Goals conc.", "goals_conceded"),
    ("Saves", "saves"),
    ("Pen saves", "penalties_saved"),
    ("Yellow", "yellow_cards"),
    ("Red", "red_cards"),
    ("Own goals", "own_goals"),
]


def _fmt(key: str, value: Any) -> str:
    if value is None or value == "":
        return "—"
    if key == "selected_by":
        try:
            return f"{float(value):.1f}%"
        except (TypeError, ValueError):
            return str(value)
    if key in {"form"}:
        return str(value)
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num == int(num) and key not in {
        "points_per_game",
        "minutes_per_start",
        "expected_goals",
        "expected_assists",
        "ict_index",
    }:
        return str(int(num))
    return f"{num:.1f}"


def build_season_kpi_rows(position: str, stats: dict[str, Any]) -> list[dict[str, str]]:
    spec = SEASON_KPI_TABLES.get(position) or SEASON_KPI_TABLES["MID"]
    return [{"label": label, "value": _fmt(key, stats.get(key)), "key": key} for label, key in spec]


def build_match_kpi_rows(metrics: dict[str, Any], breakdown: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for label, key in MATCH_METRIC_ROWS:
        if key not in metrics and float(metrics.get(key) or 0) == 0 and key not in {"minutes", "goals", "assists"}:
            # Still show core lines; skip empty rare lines to reduce noise
            if key in {"penalties_saved", "own_goals", "red_cards"} and not metrics.get(key):
                continue
        rows.append({"label": label, "value": _fmt(key, metrics.get(key, 0)), "key": key})
    # Points contribution lines from formula breakdown
    for key, val in (breakdown or {}).items():
        if abs(float(val or 0)) < 1e-9:
            continue
        nice = key.replace("_", " ").title()
        rows.append({"label": f"Pts · {nice}", "value": _fmt(key, val), "key": f"pts_{key}"})
    return rows


def player_profile(
    db: Session,
    *,
    player_id: int,
    mode: str = "season",
    gameweek_id: Optional[int] = None,
) -> dict[str, Any] | None:
    player = db.query(Player).filter(Player.id == player_id).one_or_none()
    if not player:
        return None
    clubs = {c.code: c for c in db.query(Club).all()}
    club = clubs.get(player.team_code)
    kit = kit_for(
        player.team_code,
        position=player.position,
        kit_code=getattr(club, "kit_code", None),
        photo=getattr(player, "photo", "") or "",
        player_id=player.id,
    )
    base = {
        "id": player.id,
        "name": player.name,
        "position": player.position,
        "team": player.team_code,
        "club": club.name if club else player.team_code,
        "price": player.price,
        "status": getattr(player, "status", "a") or "a",
        "chance": getattr(player, "chance_of_playing", None),
        "news": getattr(player, "news", "") or "",
        "availability": availability_flag(
            getattr(player, "status", "a") or "a",
            getattr(player, "chance_of_playing", None),
        ),
        "shirt": kit.get("shirt"),
        "photo": kit.get("photo"),
        "photoFallback": kit.get("photoFallback"),
        "photoFallback2": kit.get("photoFallback2"),
        "mode": mode,
    }

    if mode == "match":
        gw = None
        if gameweek_id:
            gw = db.query(Gameweek).filter(Gameweek.id == gameweek_id).one_or_none()
        if not gw:
            gw = db.query(Gameweek).filter(Gameweek.is_current == 1).one_or_none()
        metrics: dict[str, Any] = {}
        breakdown: dict[str, Any] = {}
        total = 0.0
        if gw:
            metrics = metrics_for_player(db, gw.id, player.id)
            pp = (
                db.query(PlayerPoints)
                .filter(
                    PlayerPoints.gameweek_id == gw.id,
                    PlayerPoints.player_id == player.id,
                    PlayerPoints.formula_version == settings.formula_version,
                )
                .one_or_none()
            )
            if pp:
                total = float(pp.total or 0)
                try:
                    breakdown = json.loads(pp.breakdown_json or "{}")
                except json.JSONDecodeError:
                    breakdown = {}
        return {
            **base,
            "gw": gw.number if gw else None,
            "gw_points": total,
            "metrics": metrics,
            "breakdown": breakdown,
            "kpis": build_match_kpi_rows(metrics, breakdown),
            "fixtures": [],
            "events_count": db.query(MatchEvent)
            .filter(MatchEvent.player_id == player.id, MatchEvent.gameweek_id == (gw.id if gw else -1))
            .count()
            if gw
            else 0,
        }

    try:
        stats = json.loads(getattr(player, "season_stats_json", None) or "{}")
    except json.JSONDecodeError:
        stats = {}
    if not isinstance(stats, dict):
        stats = {}
    fixtures = fixtures_svc.next_fixtures_for_player(db, player_id=player.id, limit=3)
    return {
        **base,
        "stats": stats,
        "kpis": build_season_kpi_rows(player.position, stats),
        "fixtures": fixtures,
    }
