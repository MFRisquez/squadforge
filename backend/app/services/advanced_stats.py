"""API-Football helpers (team match stats + optional player metrics).

**Permanently disabled in production** until a paid plan is confirmed:
``run_gameweek_scoring`` does not call ``ingest_advanced_stats``, and the
Fixtures sheet preview does not call ``team_match_stats_result``. Free-tier
keys only cover older seasons; current-season possession/SOT will not work.

If re-enabled later: ``ingest_advanced_stats`` writes source=\"api_football\"
MatchEvents (tackles, interceptions, blocks, key_passes, shots_on_target)
via ``_write_metrics``, which upserts by metric and can overwrite FPL live
``tackles``. Scoring formulas themselves read FPL field names (tackles, cbi,
creativity, threat) from ``map_fpl_stats``.
"""

from __future__ import annotations

import logging
import re
import time
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
CHAMPIONSHIP_LEAGUE_ID = 40
RECENT_FETCH_MINUTES = 20
NAME_MATCH_THRESHOLD = 0.78
# Sheet team stats: short TTL so live possession/SOT can refresh without
# re-hitting resolve+statistics on every soft paint (~40s worst case).
TEAM_STATS_TTL_SEC = 30.0
_team_stats_cache: dict[int, tuple[float, dict[str, Any]]] = {}

_warned_missing_stat_shape = False

# FPL Club.code → API-Football team id (IDs are stable across seasons).
# Covers current PL + recent promotees so we don't depend on season team lists
# that omit clubs still listed under Championship for season-1.
_PL_CODE_TO_API_ID: dict[str, int] = {
    "ARS": 42,
    "AVL": 66,
    "BHA": 51,
    "BOU": 35,
    "BRE": 55,
    "BUR": 44,
    "CHE": 49,
    "COV": 71,  # Coventry City
    "CRY": 52,
    "EVE": 45,
    "FUL": 36,
    "HUL": 64,  # Hull City
    "IPS": 57,  # Ipswich Town
    "LEE": 63,  # Leeds United
    "LEI": 46,
    "LIV": 40,
    "MCI": 50,
    "MUN": 33,
    "NEW": 34,
    "NFO": 65,
    "SHU": 62,
    "SOU": 41,
    "SUN": 746,  # Sunderland
    "TOT": 47,
    "WHU": 48,
    "WOL": 39,
}


def _normalize_name(raw: str) -> str:
    text = unicodedata.normalize("NFKD", raw or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    # Drop apostrophes so "Nott'm Forest" → "nottm forest" (not "nott m forest").
    text = text.replace("'", "").replace("'", "").replace("'", "")
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


# Common FPL short names → API-Football team name forms (after _normalize_name).
_CLUB_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "nottm forest": ("nottingham forest",),
    "spurs": ("tottenham", "tottenham hotspur"),
    "man utd": ("manchester united",),
    "man city": ("manchester city",),
    "wolves": ("wolverhampton wanderers", "wolverhampton"),
    "brighton": ("brighton and hove albion", "brighton hove albion"),
    "west ham": ("west ham united",),
    "newcastle": ("newcastle united",),
    "leeds": ("leeds united",),
    "coventry city": ("coventry",),
    "hull city": ("hull",),
    "ipswich town": ("ipswich",),
    "sunderland": ("sunderland afc",),
}


def _season_candidates() -> list[int]:
    base = int(settings.api_football_season)
    out = [base]
    for alt in (base - 1, base + 1):
        if alt >= 2020 and alt not in out:
            out.append(alt)
    return out


def ensure_club_team_ids(db: Session, *, force: bool = False) -> dict[str, Any]:
    """Map API-Football team ids onto Club rows (idempotent)."""
    if not _has_api_key():
        return {"skipped": "no_api_key", "updated": 0}

    missing = db.query(Club).filter(Club.api_football_team_id.is_(None)).count()
    if missing == 0 and not force:
        return {"skipped": "already_mapped", "updated": 0}

    updated = 0

    # 1) Hardcoded FPL code → API id (covers promotees missing from PL season lists).
    for club in db.query(Club).all():
        if club.api_football_team_id and not force:
            continue
        tid = _PL_CODE_TO_API_ID.get((club.code or "").upper())
        if tid is not None and club.api_football_team_id != tid:
            club.api_football_team_id = tid
            updated += 1

    still = [c for c in db.query(Club).all() if not c.api_football_team_id]
    if not still and not force:
        if updated:
            db.commit()
        return {
            "updated": updated,
            "api_teams": 0,
            "season": None,
            "still_missing": 0,
            "via": "code_map",
        }

    # 2) League season team lists (PL, then Championship for promotees).
    api_teams: list = []
    used_season = None
    by_norm: dict[str, int] = {}
    for league_id in (PL_LEAGUE_ID, CHAMPIONSHIP_LEAGUE_ID):
        for season in _season_candidates():
            data = _api_get(
                "/teams",
                {"league": league_id, "season": season},
            )
            rows = data.get("response") or []
            if not rows:
                continue
            if used_season is None:
                used_season = season
            api_teams.extend(rows)
            for row in rows:
                team = (row or {}).get("team") or {}
                tid = team.get("id")
                name = team.get("name") or ""
                if not tid or not name:
                    continue
                by_norm[_normalize_name(name)] = int(tid)

    for club in db.query(Club).filter(Club.api_football_team_id.is_(None)).all():
        norm = _normalize_name(club.name)
        tid = by_norm.get(norm)
        if tid is None:
            for alias in _CLUB_NAME_ALIASES.get(norm, ()):
                tid = by_norm.get(alias)
                if tid is not None:
                    break
        if tid is None:
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

    # 3) Name search for any remaining gaps (1 request per club).
    for club in db.query(Club).filter(Club.api_football_team_id.is_(None)).all():
        q = (club.name or club.code or "").strip()
        if len(q) < 3:
            continue
        data = _api_get("/teams", {"search": q[:40]}, timeout=20.0)
        best_id = None
        best_score = 0.0
        target = _normalize_name(club.name)
        for row in data.get("response") or []:
            team = (row or {}).get("team") or {}
            tid = team.get("id")
            name = team.get("name") or ""
            country = (team.get("country") or "").lower()
            if not tid or not name:
                continue
            if country and country not in {"england", "wales"}:
                continue
            score = SequenceMatcher(None, target, _normalize_name(name)).ratio()
            if score > best_score:
                best_score = score
                best_id = int(tid)
        if best_id is not None and best_score >= NAME_MATCH_THRESHOLD:
            club.api_football_team_id = best_id
            updated += 1
        else:
            logger.warning("API-Football: could not map club %s (%s)", club.code, club.name)

    if updated:
        db.commit()
    return {
        "updated": updated,
        "api_teams": len(api_teams),
        "season": used_season,
        "still_missing": db.query(Club).filter(Club.api_football_team_id.is_(None)).count(),
    }


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

    fixture_ids: list[int] = []
    for season in _season_candidates():
        data = _api_get(
            "/fixtures",
            {
                "league": PL_LEAGUE_ID,
                "season": season,
                "round": f"Regular Season - {int(gw_number)}",
            },
        )
        rows = data.get("response") or []
        if not rows:
            continue
        for row in rows:
            fixture = (row or {}).get("fixture") or {}
            teams = (row or {}).get("teams") or {}
            home_id = ((teams.get("home") or {}).get("id"))
            away_id = ((teams.get("away") or {}).get("id"))
            fid = fixture.get("id")
            if not fid or not home_id or not away_id:
                continue
            if int(home_id) in mapped and int(away_id) in mapped:
                fixture_ids.append(int(fid))
        if fixture_ids:
            break
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


_STAT_ALIASES = {
    "possession": ("Ball Possession", "Possession"),
    "shots_on_target": ("Shots on Goal", "Shots on Target"),
    "chances_created": ("Total Shots", "Goal Attempts", "Shots insidebox"),
    "expected_goals": ("expected_goals", "Expected Goals", "xG"),
    "passes_accurate": ("Passes accurate", "Accurate Passes"),
    "duels_won": ("Duels won", "Total Duels Won", "Duels Won"),
    "fouls": ("Fouls",),
}


def _stat_value(rows: list[dict[str, Any]], *names: str) -> Any:
    by_type = {
        str((r or {}).get("type") or "").strip().lower(): (r or {}).get("value")
        for r in rows
    }
    for name in names:
        key = name.strip().lower()
        if key in by_type and by_type[key] is not None:
            return by_type[key]
    return None


def _fmt_stat(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.2f}"


def resolve_api_fixture_id(db: Session, fx) -> int | None:
    """Map our Fixture row → API-Football fixture id via club team ids + kickoff day."""
    result = resolve_api_fixture_id_detailed(db, fx)
    return result.get("api_fixture_id")


def resolve_api_fixture_id_detailed(db: Session, fx) -> dict[str, Any]:
    """Like resolve_api_fixture_id but includes a machine-readable ``reason`` on failure."""
    if not _has_api_key() or fx is None:
        return {"api_fixture_id": None, "reason": "no_api_key"}
    ensure_club_team_ids(db)
    home = db.query(Club).filter(Club.code == fx.home_club_code).one_or_none()
    away = db.query(Club).filter(Club.code == fx.away_club_code).one_or_none()
    if not home or not away:
        return {"api_fixture_id": None, "reason": "club_missing"}
    if not home.api_football_team_id or not away.api_football_team_id:
        # Retry with force in case season list was empty on first boot.
        ensure_club_team_ids(db, force=True)
        db.refresh(home)
        db.refresh(away)
    if not home.api_football_team_id or not away.api_football_team_id:
        missing = []
        if not home.api_football_team_id:
            missing.append(home.code)
        if not away.api_football_team_id:
            missing.append(away.code)
        return {
            "api_fixture_id": None,
            "reason": "no_club_ids",
            "missing_clubs": missing,
        }

    day = str(fx.kickoff_at or "")[:10]
    home_id = int(home.api_football_team_id)
    away_id = int(away.api_football_team_id)
    gw_number = int(getattr(fx, "gameweek_number", 0) or 0)

    def _match_rows(rows: list) -> int | None:
        for row in rows:
            teams = (row or {}).get("teams") or {}
            home_row = (teams.get("home") or {}).get("id")
            away_row = (teams.get("away") or {}).get("id")
            fid = ((row or {}).get("fixture") or {}).get("id")
            if not fid or not home_row or not away_row:
                continue
            if int(home_row) == home_id and int(away_row) == away_id:
                return int(fid)
        return None

    # 1) Prefer exact kickoff day + home team.
    for season in _season_candidates():
        params: dict[str, Any] = {
            "league": PL_LEAGUE_ID,
            "season": season,
            "team": home_id,
        }
        if day:
            params["date"] = day
        data = _api_get("/fixtures", params, timeout=20.0)
        found = _match_rows(data.get("response") or [])
        if found:
            return {"api_fixture_id": found, "reason": "ok", "season": season}

    # 2) Same teams, no date filter (timezone / delayed kickoff mismatches).
    for season in _season_candidates():
        data = _api_get(
            "/fixtures",
            {
                "league": PL_LEAGUE_ID,
                "season": season,
                "team": home_id,
            },
            timeout=20.0,
        )
        found = _match_rows(data.get("response") or [])
        if found:
            return {"api_fixture_id": found, "reason": "ok", "season": season, "via": "team"}

    # 3) GW round listing.
    if gw_number > 0:
        for season in _season_candidates():
            data = _api_get(
                "/fixtures",
                {
                    "league": PL_LEAGUE_ID,
                    "season": season,
                    "round": f"Regular Season - {gw_number}",
                },
                timeout=20.0,
            )
            found = _match_rows(data.get("response") or [])
            if found:
                return {"api_fixture_id": found, "reason": "ok", "season": season, "via": "round"}

    return {"api_fixture_id": None, "reason": "no_fixture_match", "day": day or None}


def team_match_stats_for_fixture(
    db: Session, fx, *, force: bool = False
) -> dict[str, Any] | None:
    """Team-vs-team live stats for the Fixtures match sheet.

    Keys: possession, shots_on_target, chances_created, expected_goals,
    passes_accurate, duels_won, fouls — each ``{home, away, label}``.
    Returns None when API key missing or lookup fails.
    """
    result = team_match_stats_result(db, fx, force=force)
    return result.get("team_stats")


def team_match_stats_result(
    db: Session, fx, *, force: bool = False
) -> dict[str, Any]:
    """Return ``{team_stats, team_stats_status, ...}`` for diagnostics + UI."""
    if not _has_api_key() or fx is None:
        return {"team_stats": None, "team_stats_status": "no_api_key"}
    fx_id = int(getattr(fx, "id", 0) or 0)
    if not force and fx_id:
        hit = _team_stats_cache.get(fx_id)
        if hit and (time.time() - hit[0]) < TEAM_STATS_TTL_SEC:
            return {
                "team_stats": hit[1],
                "team_stats_status": "ok",
                "cached": True,
            }
    try:
        resolved = resolve_api_fixture_id_detailed(db, fx)
        api_id = resolved.get("api_fixture_id")
        if not api_id:
            return {
                "team_stats": None,
                "team_stats_status": resolved.get("reason") or "no_fixture_match",
                "missing_clubs": resolved.get("missing_clubs"),
            }
        data = _api_get("/fixtures/statistics", {"fixture": int(api_id)}, timeout=20.0)
        response = data.get("response") or []
        if len(response) < 2:
            return {
                "team_stats": None,
                "team_stats_status": "no_statistics",
                "api_fixture_id": api_id,
            }
        home_club = db.query(Club).filter(Club.code == fx.home_club_code).one_or_none()
        away_club = db.query(Club).filter(Club.code == fx.away_club_code).one_or_none()
        home_api = (
            int(home_club.api_football_team_id)
            if home_club and home_club.api_football_team_id
            else None
        )
        away_api = (
            int(away_club.api_football_team_id)
            if away_club and away_club.api_football_team_id
            else None
        )
        blocks: dict[str, list] = {"home": [], "away": []}
        for block in response:
            team = (block or {}).get("team") or {}
            tid = team.get("id")
            stats = (block or {}).get("statistics") or []
            if not isinstance(stats, list):
                stats = []
            if home_api and tid is not None and int(tid) == home_api:
                blocks["home"] = stats
            elif away_api and tid is not None and int(tid) == away_api:
                blocks["away"] = stats
            elif not blocks["home"]:
                blocks["home"] = stats
            else:
                blocks["away"] = stats

        if not blocks["home"] or not blocks["away"]:
            return {
                "team_stats": None,
                "team_stats_status": "no_statistics",
                "api_fixture_id": api_id,
            }

        labels = {
            "possession": "Possession",
            "shots_on_target": "Shots on target",
            "chances_created": "Goal attempts",
            "expected_goals": "Expected goals (xG)",
            "passes_accurate": "Passes completed",
            "duels_won": "Duels won",
            "fouls": "Fouls",
        }
        out: dict[str, Any] = {"source": "api_football", "api_fixture_id": api_id}
        for key, aliases in _STAT_ALIASES.items():
            hv = _fmt_stat(_stat_value(blocks["home"], *aliases))
            av = _fmt_stat(_stat_value(blocks["away"], *aliases))
            out[key] = {"home": hv, "away": av, "label": labels[key]}
        if fx_id:
            _team_stats_cache[fx_id] = (time.time(), out)
        return {"team_stats": out, "team_stats_status": "ok", "api_fixture_id": api_id}
    except Exception as exc:
        logger.info("API-Football team stats skipped: %s", exc)
        return {"team_stats": None, "team_stats_status": "error", "error": str(exc)}
