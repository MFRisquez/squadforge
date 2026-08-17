"""Ingest advanced PL stats from API-Football into MatchEvent rows.

Writes source="api_football" metrics (tackles, interceptions, blocks,
key_passes, shots_on_target). Clearances are not available from this API
and stay 0. When API_FOOTBALL_KEY is empty, all public entrypoints no-op.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Club, Gameweek, MatchEvent, Player

logger = logging.getLogger("squadforge.advanced_stats")

API_BASE = "https://v3.football.api-sports.io"
PL_LEAGUE_ID = 39
RECENT_FETCH_MINUTES = 20
NAME_MATCH_THRESHOLD = 0.78

_warned_missing_stat_shape = False


def _normalize_name(raw: str) -> str:
    text = unicodedata.normalize("NFKD", raw or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"\b(fc|afc|cf|sc)\b", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _has_api_key() -> bool:
    return bool((settings.api_football_key or "").strip())


def _api_get(path: str, params: dict[str, Any] | None = None, *, timeout: float = 45.0) -> dict[str, Any]:
    key = (settings.api_football_key or "").strip()
    if not key:
        return {"response": []}
    headers = {
        "x-apisports-key": key,
        "Accept": "application/json",
    }
    url = f"{API_BASE}{path}"
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        response = client.get(url, params=params or {})
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            return {"response": []}
        return data


def _safe_int(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def ensure_club_team_ids(db: Session) -> dict[str, Any]:
    """Map API-Football team ids onto Club rows (idempotent)."""
    if not _has_api_key():
        return {"skipped": "no_api_key", "updated": 0}

    missing = db.query(Club).filter(Club.api_football_team_id.is_(None)).count()
    if missing == 0:
        return {"skipped": "already_mapped", "updated": 0}

    data = _api_get(
        "/teams",
        {"league": PL_LEAGUE_ID, "season": settings.api_football_season},
    )
    api_teams = data.get("response") or []
    by_norm: dict[str, int] = {}
    for row in api_teams:
        team = (row or {}).get("team") or {}
        tid = team.get("id")
        name = team.get("name") or ""
        if not tid or not name:
            continue
        by_norm[_normalize_name(name)] = int(tid)

    updated = 0
    for club in db.query(Club).filter(Club.api_football_team_id.is_(None)).all():
        norm = _normalize_name(club.name)
        tid = by_norm.get(norm)
        if tid is None:
            # Fuzzy fallback against API names
            best_id = None
            best_score = 0.0
            for api_name, api_id in by_norm.items():
                score = SequenceMatcher(None, norm, api_name).ratio()
                if score > best_score:
                    best_score = score
                    best_id = api_id
            if best_id is not None and best_score >= NAME_MATCH_THRESHOLD:
                tid = best_id
        if tid is not None:
            club.api_football_team_id = tid
            updated += 1
        else:
            logger.warning("API-Football: could not map club %s (%s)", club.code, club.name)

    if updated:
        db.commit()
    return {"updated": updated, "api_teams": len(api_teams)}


def fetch_round_fixtures(db: Session, gw_number: int) -> list[int]:
    """Return API-Football fixture ids for PL round matching our mapped clubs."""
    if not _has_api_key():
        return []

    mapped = {
        c.api_football_team_id: c
        for c in db.query(Club).filter(Club.api_football_team_id.isnot(None)).all()
        if c.api_football_team_id
    }
    if not mapped:
        return []

    data = _api_get(
        "/fixtures",
        {
            "league": PL_LEAGUE_ID,
            "season": settings.api_football_season,
            "round": f"Regular Season - {int(gw_number)}",
        },
    )
    fixture_ids: list[int] = []
    for row in data.get("response") or []:
        fixture = (row or {}).get("fixture") or {}
        teams = (row or {}).get("teams") or {}
        home_id = ((teams.get("home") or {}).get("id"))
        away_id = ((teams.get("away") or {}).get("id"))
        fid = fixture.get("id")
        if not fid or not home_id or not away_id:
            continue
        if int(home_id) in mapped and int(away_id) in mapped:
            fixture_ids.append(int(fid))
    return fixture_ids


def _parse_player_statistics(stats_block: Any) -> dict[str, float]:
    """Extract advanced metrics; missing fields become 0 (warn once on odd shape)."""
    global _warned_missing_stat_shape
    tackles = interceptions = blocks = key_passes = shots_on = 0.0
    try:
        block = stats_block[0] if isinstance(stats_block, list) and stats_block else stats_block
        if not isinstance(block, dict):
            block = {}
        t = block.get("tackles") or {}
        p = block.get("passes") or {}
        s = block.get("shots") or {}
        if not isinstance(t, dict):
            t = {}
        if not isinstance(p, dict):
            p = {}
        if not isinstance(s, dict):
            s = {}
        tackles = _safe_int(t.get("total"))
        interceptions = _safe_int(t.get("interceptions"))
        blocks = _safe_int(t.get("blocks"))
        key_passes = _safe_int(p.get("key"))
        shots_on = _safe_int(s.get("on"))
    except Exception as exc:
        if not _warned_missing_stat_shape:
            logger.warning("API-Football: unexpected player statistics shape: %s", exc)
            _warned_missing_stat_shape = True
    return {
        "tackles": tackles,
        "interceptions": interceptions,
        "blocks": blocks,
        "key_passes": key_passes,
        "shots_on_target": shots_on,
    }


def fetch_fixture_players(fixture_id: int) -> list[dict[str, Any]]:
    """Flat list of advanced stats rows for one API-Football fixture."""
    if not _has_api_key():
        return []

    data = _api_get("/fixtures/players", {"fixture": int(fixture_id)})
    out: list[dict[str, Any]] = []
    for team_block in data.get("response") or []:
        team = (team_block or {}).get("team") or {}
        team_api_id = team.get("id")
        if not team_api_id:
            continue
        for entry in (team_block or {}).get("players") or []:
            player = (entry or {}).get("player") or {}
            name = player.get("name") or ""
            metrics = _parse_player_statistics((entry or {}).get("statistics"))
            out.append(
                {
                    "name": name,
                    "team_api_id": int(team_api_id),
                    **metrics,
                }
            )
    return out


def _match_player(
    *,
    name: str,
    team_api_id: int,
    clubs_by_api_id: dict[int, Club],
    players_by_team: dict[str, list[Player]],
) -> Player | None:
    club = clubs_by_api_id.get(team_api_id)
    if not club:
        return None
    candidates = players_by_team.get(club.code) or []
    if not candidates:
        return None

    target = _normalize_name(name)
    if not target:
        return None

    # Exact normalized full name
    for player in candidates:
        if _normalize_name(player.name) == target:
            return player

    # Last-token (surname) exact among candidates
    target_last = target.split()[-1] if target.split() else target
    surname_hits = [
        p for p in candidates if (_normalize_name(p.name).split() or [""])[-1] == target_last
    ]
    if len(surname_hits) == 1:
        return surname_hits[0]

    # Fuzzy full-name ratio
    best: Player | None = None
    best_score = 0.0
    for player in candidates:
        score = SequenceMatcher(None, target, _normalize_name(player.name)).ratio()
        if score > best_score:
            best_score = score
            best = player
    if best is not None and best_score >= NAME_MATCH_THRESHOLD:
        return best
    return None


def _recently_fetched(db: Session, gameweek_id: int) -> bool:
    cutoff = datetime.utcnow() - timedelta(minutes=RECENT_FETCH_MINUTES)
    row = (
        db.query(MatchEvent)
        .filter(
            MatchEvent.gameweek_id == gameweek_id,
            MatchEvent.source == "api_football",
            MatchEvent.fetched_at >= cutoff,
        )
        .first()
    )
    return row is not None


def ingest_advanced_stats(db: Session, gw: Gameweek, *, force: bool = False) -> dict[str, Any]:
    """Pull API-Football advanced metrics into MatchEvent for a gameweek."""
    try:
        if not _has_api_key():
            return {"skipped": "no_api_key"}

        if not force and _recently_fetched(db, gw.id):
            return {"skipped": "recently_fetched"}

        from app.services.live_scoring import _write_metrics

        map_info = ensure_club_team_ids(db)
        fixture_ids = fetch_round_fixtures(db, gw.number)

        clubs_by_api_id = {
            int(c.api_football_team_id): c
            for c in db.query(Club).filter(Club.api_football_team_id.isnot(None)).all()
            if c.api_football_team_id
        }
        players_by_team: dict[str, list[Player]] = {}
        for player in db.query(Player).all():
            players_by_team.setdefault(player.team_code, []).append(player)

        players_updated = 0
        unmatched: list[str] = []
        fixtures_ok = 0
        fixtures_failed = 0

        for fixture_id in fixture_ids:
            try:
                rows = fetch_fixture_players(fixture_id)
            except Exception as exc:
                fixtures_failed += 1
                logger.warning("API-Football fixture %s failed: %s", fixture_id, exc)
                continue

            fixtures_ok += 1
            for row in rows:
                player = _match_player(
                    name=row.get("name") or "",
                    team_api_id=int(row.get("team_api_id") or 0),
                    clubs_by_api_id=clubs_by_api_id,
                    players_by_team=players_by_team,
                )
                if not player:
                    unmatched.append(f"{row.get('name')}@{row.get('team_api_id')}")
                    continue
                metrics = {
                    "tackles": float(row.get("tackles") or 0),
                    "interceptions": float(row.get("interceptions") or 0),
                    "blocks": float(row.get("blocks") or 0),
                    "key_passes": float(row.get("key_passes") or 0),
                    "shots_on_target": float(row.get("shots_on_target") or 0),
                }
                _write_metrics(
                    db,
                    gameweek_id=gw.id,
                    player_id=player.id,
                    metrics=metrics,
                    source="api_football",
                )
                players_updated += 1

        if players_updated:
            db.commit()

        if unmatched:
            logger.info(
                "API-Football: %s players unmatched (showing up to 12): %s",
                len(unmatched),
                unmatched[:12],
            )

        return {
            "source": "api_football",
            "club_map": map_info,
            "fixtures_processed": fixtures_ok,
            "fixtures_failed": fixtures_failed,
            "players_updated": players_updated,
            "unmatched": len(unmatched),
        }
    except Exception as exc:
        logger.exception("API-Football ingest failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return {"source": "api_football", "error": str(exc)}
