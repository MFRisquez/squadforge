"""Club profile payloads for Technical Director picker sheets."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.kits import badge_url
from app.models import Club, Fixture, Gameweek, Player
from app.services import fixtures as fixtures_svc
from app.services.fpl_sync import availability_flag


STATUS_LABELS = {
    "a": "Available",
    "d": "Doubtful",
    "i": "Injured",
    "s": "Suspended",
    "u": "Unavailable",
}


def season_scoring_started(db: Session) -> bool:
    """True once any PL fixture has kicked off or finished this season."""
    row = (
        db.query(Fixture.id)
        .filter((Fixture.started == 1) | (Fixture.finished == 1))
        .limit(1)
        .first()
    )
    return row is not None


def _season_stats(player: Player) -> dict[str, Any]:
    try:
        stats = json.loads(getattr(player, "season_stats_json", None) or "{}")
    except json.JSONDecodeError:
        stats = {}
    return stats if isinstance(stats, dict) else {}


def _player_points(player: Player, *, scoring_started: bool) -> float:
    """Current-season FPL points for club leaderboards.

    Before any match has started, always 0 — bootstrap can still carry stale
    totals. After kickoff, use total_points only when the player has minutes
    (avoids previous-season bleed with minutes still at 0).
    """
    if not scoring_started:
        return 0.0
    stats = _season_stats(player)
    try:
        minutes = float(stats.get("minutes") or 0)
    except (TypeError, ValueError):
        minutes = 0.0
    try:
        pts = float(stats.get("total_points") or 0)
    except (TypeError, ValueError):
        pts = 0.0
    if minutes <= 0:
        return 0.0
    return pts


def club_table_stats(db: Session, club_code: str) -> dict[str, int]:
    """Season W/D/L + goals from finished fixtures with scores."""
    code = (club_code or "").upper()
    rows = (
        db.query(Fixture)
        .filter(
            Fixture.finished == 1,
            ((Fixture.home_club_code == code) | (Fixture.away_club_code == code)),
            Fixture.home_score.isnot(None),
            Fixture.away_score.isnot(None),
        )
        .all()
    )
    played = wins = draws = losses = gf = ga = 0
    for fx in rows:
        home = fx.home_club_code == code
        my = int(fx.home_score if home else fx.away_score)
        opp = int(fx.away_score if home else fx.home_score)
        played += 1
        gf += my
        ga += opp
        if my > opp:
            wins += 1
        elif my < opp:
            losses += 1
        else:
            draws += 1
    return {
        "played": played,
        "points": wins * 3 + draws,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "gf": gf,
        "ga": ga,
        "gd": gf - ga,
    }


def club_top_players(db: Session, club_code: str, *, limit: int = 3) -> list[dict[str, Any]]:
    """Top scorers for a club — re-ranked from live season_stats on every call."""
    code = (club_code or "").upper()
    scoring_started = season_scoring_started(db)
    players = db.query(Player).filter(Player.team_code == code).all()

    def sort_key(p: Player) -> tuple[float, float, str]:
        pts = _player_points(p, scoring_started=scoring_started)
        price = float(getattr(p, "price", 0) or 0)
        # Pre-season: price as stand-in so the sheet still lists three names at 0 pts.
        if not scoring_started:
            return (price, 0.0, p.name or "")
        return (pts, price, p.name or "")

    ranked = sorted(players, key=sort_key, reverse=True)[: max(0, limit)]
    out: list[dict[str, Any]] = []
    for p in ranked:
        status = (getattr(p, "status", "a") or "a").lower()
        avail = availability_flag(status, getattr(p, "chance_of_playing", None))
        label = STATUS_LABELS.get(status, "Available")
        if avail == "out" and label == "Available":
            label = "Unavailable"
        elif avail == "doubt" and label == "Available":
            label = "Doubtful"
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "position": p.position,
                "points": _player_points(p, scoring_started=scoring_started),
                "availability": avail,
                "status": status,
                "status_label": label,
            }
        )
    return out


def club_profile(db: Session, club_code: str, *, from_gw: int | None = None) -> dict[str, Any] | None:
    code = (club_code or "").upper()
    club = db.query(Club).filter(Club.code == code).one_or_none()
    if not club:
        return None
    if from_gw is None:
        current = db.query(Gameweek).filter(Gameweek.is_current == 1).one_or_none()
        from_gw = current.number if current else 1
    table = club_table_stats(db, code)
    return {
        "ok": True,
        "code": club.code,
        "name": club.name,
        "badge": badge_url(club.code, kit_code=club.kit_code),
        "table": table,
        "scoring_started": season_scoring_started(db),
        "top_players": club_top_players(db, code, limit=3),
        "fixtures": fixtures_svc.next_fixtures_for_club(
            db, club_code=code, from_gw=int(from_gw), limit=3
        ),
    }


def clubs_list(db: Session, *, exclude: str | None = None) -> list[dict[str, Any]]:
    banned = (exclude or "").upper() or None
    rows = db.query(Club).order_by(Club.name.asc()).all()
    out = []
    for c in rows:
        if not c.code:
            continue
        out.append(
            {
                "code": c.code,
                "name": c.name,
                "badge": badge_url(c.code, kit_code=c.kit_code),
                "banned": bool(banned and c.code == banned),
            }
        )
    return out
