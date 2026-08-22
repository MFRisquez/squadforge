"""PL fixtures + FPL-style fixture difficulty (mapped to 4 bands)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.kits import badge_url
from app.models import Club, Fixture, Gameweek, Player

FPL_FIXTURES = "https://fantasy.premierleague.com/api/fixtures/"


def map_fdr(fpl_diff: int | None) -> int:
    """Map official FPL difficulty (1–5) to SquadForge bands (1–4).

    1 easiest … 4 hardest. FPL 5 collapses into 4.
    """
    d = int(fpl_diff or 3)
    if d < 1:
        d = 1
    if d > 5:
        d = 5
    return min(4, d)


def fetch_fixtures(timeout: float = 45.0) -> list[dict[str, Any]]:
    headers = {
        "User-Agent": "SquadForge/0.3 (private fantasy; contact local)",
        "Accept": "application/json",
    }
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        response = client.get(FPL_FIXTURES)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []


def sync_fixtures(db: Session, rows: list[dict[str, Any]] | None = None) -> dict[str, int]:
    """Upsert FPL fixtures. Requires clubs.fpl_team_id from bootstrap sync."""
    payload = rows if rows is not None else fetch_fixtures()
    by_fpl_id = {
        int(c.fpl_team_id): c
        for c in db.query(Club).filter(Club.fpl_team_id.isnot(None)).all()
        if c.fpl_team_id
    }
    if not by_fpl_id:
        return {"fixtures": 0, "skipped": len(payload), "reason": "no_club_fpl_ids"}

    upserted = 0
    for fx in payload:
        fpl_id = int(fx.get("id") or 0)
        if not fpl_id:
            continue
        home = by_fpl_id.get(int(fx.get("team_h") or 0))
        away = by_fpl_id.get(int(fx.get("team_a") or 0))
        if not home or not away:
            continue
        event = fx.get("event")
        gw_number = int(event) if event is not None else 0
        stats = fx.get("stats") or []
        row = db.query(Fixture).filter(Fixture.fpl_id == fpl_id).one_or_none()
        fields = dict(
            gameweek_number=gw_number,
            home_club_code=home.code,
            away_club_code=away.code,
            home_difficulty=int(fx.get("team_h_difficulty") or 3),
            away_difficulty=int(fx.get("team_a_difficulty") or 3),
            kickoff_at=fx.get("kickoff_time"),
            started=1 if fx.get("started") else 0,
            finished=1 if (fx.get("finished") or fx.get("finished_provisional")) else 0,
            home_score=fx.get("team_h_score"),
            away_score=fx.get("team_a_score"),
            stats_json=json.dumps(stats),
        )
        if not row:
            db.add(Fixture(fpl_id=fpl_id, **fields))
        else:
            for k, v in fields.items():
                setattr(row, k, v)
        upserted += 1
    db.commit()
    return {"fixtures": upserted}


def next_fixtures_for_club(
    db: Session,
    *,
    club_code: str,
    from_gw: int,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Upcoming fixtures for a club starting at from_gw (inclusive), max `limit`."""
    club_code = (club_code or "").upper()
    clubs = {c.code: c for c in db.query(Club).all()}
    rows = (
        db.query(Fixture)
        .filter(
            Fixture.gameweek_number >= from_gw,
            Fixture.gameweek_number > 0,
            ((Fixture.home_club_code == club_code) | (Fixture.away_club_code == club_code)),
        )
        .order_by(Fixture.gameweek_number.asc(), Fixture.kickoff_at.asc())
        .limit(limit * 2)  # DGW may produce 2 in same GW
        .all()
    )
    out: list[dict[str, Any]] = []
    for fx in rows:
        if len(out) >= limit:
            break
        home = fx.home_club_code == club_code
        opp_code = fx.away_club_code if home else fx.home_club_code
        fpl_diff = fx.home_difficulty if home else fx.away_difficulty
        opp = clubs.get(opp_code)
        out.append(
            {
                "gw": fx.gameweek_number,
                "opponent": opp_code,
                "opponent_name": opp.name if opp else opp_code,
                "home": home,
                "venue": "H" if home else "A",
                "difficulty": map_fdr(fpl_diff),
                "fpl_difficulty": int(fpl_diff),
                "kickoff": fx.kickoff_at,
                "fixture_id": fx.id,
                "fpl_id": fx.fpl_id,
            }
        )
    return out


def club_next_fdr_map(
    db: Session,
    *,
    from_gw: int,
    clubs: dict[str, Club] | None = None,
) -> dict[str, dict[str, Any]]:
    """club_code → next fixture FDR summary (for pitch shirt badges).

    Pass ``clubs`` when the caller already loaded them (avoids a duplicate
    SELECT on catalog rebuild).
    """
    if clubs is None:
        clubs = {c.code: c for c in db.query(Club).all() if c.code}
    else:
        clubs = {code: c for code, c in clubs.items() if code}
    rows = (
        db.query(Fixture)
        .filter(Fixture.gameweek_number >= from_gw, Fixture.gameweek_number > 0)
        .order_by(Fixture.gameweek_number.asc(), Fixture.kickoff_at.asc())
        .all()
    )
    out: dict[str, dict[str, Any]] = {}
    for fx in rows:
        for code, home in ((fx.home_club_code, True), (fx.away_club_code, False)):
            if code in out or code not in clubs:
                continue
            opp_code = fx.away_club_code if home else fx.home_club_code
            fpl_diff = fx.home_difficulty if home else fx.away_difficulty
            out[code] = {
                "difficulty": map_fdr(fpl_diff),
                "opponent": opp_code,
                "venue": "H" if home else "A",
                "gw": fx.gameweek_number,
            }
        if len(out) >= len(clubs):
            break
    return out


def ensure_fixtures_ready(db: Session) -> dict[str, Any]:
    """Backfill club FPL ids + fixture rows if this DB predates fixture sync."""
    info: dict[str, Any] = {"ok": True}
    has_ids = db.query(Club).filter(Club.fpl_team_id.isnot(None)).count()
    has_fx = db.query(Fixture).count()
    if has_ids and has_fx:
        info["fixtures"] = has_fx
        return info
    try:
        from app.services.fpl_sync import fetch_bootstrap, sync_from_fpl

        if not has_ids:
            # Prefer lightweight club id backfill; fall back to full sync
            try:
                payload = fetch_bootstrap()
                for team in payload.get("teams") or []:
                    code = (team.get("short_name") or team["name"][:3]).upper()[:8]
                    club = db.query(Club).filter(Club.code == code).one_or_none()
                    if club:
                        club.fpl_team_id = int(team.get("id") or 0) or None
                        club.kit_code = int(team.get("code") or 0) or club.kit_code
                        club.name = team.get("name") or club.name
                db.commit()
            except Exception:
                sync_from_fpl(db)
        if db.query(Fixture).count() == 0:
            info.update(sync_fixtures(db))
        else:
            info["fixtures"] = db.query(Fixture).count()
    except Exception as exc:
        info = {"ok": False, "error": str(exc), "fixtures": db.query(Fixture).count()}
    return info


def next_fixtures_for_player(db: Session, *, player_id: int, limit: int = 3) -> list[dict[str, Any]]:
    ensure_fixtures_ready(db)
    player = db.query(Player).filter(Player.id == player_id).one_or_none()
    if not player or not player.team_code:
        return []
    current = db.query(Gameweek).filter(Gameweek.is_current == 1).one_or_none()
    from_gw = current.number if current else 1
    return next_fixtures_for_club(db, club_code=player.team_code, from_gw=from_gw, limit=limit)


def club_match_state(db: Session, *, club_code: str, gw_number: int) -> str:
    """upcoming | live | finished for a club in a GW (DGW: live if any live, else finished if all done)."""
    rows = (
        db.query(Fixture)
        .filter(
            Fixture.gameweek_number == gw_number,
            ((Fixture.home_club_code == club_code) | (Fixture.away_club_code == club_code)),
        )
        .all()
    )
    if not rows:
        return "upcoming"
    if any(r.started and not r.finished for r in rows):
        return "live"
    if all(r.finished for r in rows):
        return "finished"
    if any(r.started or r.finished for r in rows):
        return "live"
    return "upcoming"


def club_fixture_started(db: Session, *, club_code: str, gw_number: int) -> bool:
    return club_match_state(db, club_code=club_code, gw_number=gw_number) in {"live", "finished"}


def club_fixture_finished(db: Session, *, club_code: str, gw_number: int) -> bool:
    """True when every fixture for this club in the GW is finished (DGW-safe)."""
    return club_match_state(db, club_code=club_code, gw_number=gw_number) == "finished"


def estimate_match_clock(
    *,
    kickoff_at: str | None,
    started: bool,
    finished: bool,
    now: datetime | None = None,
) -> str | None:
    """Display clock under the score: ``14'``, ``45+2'``, ``MT``, ``90+3'``, ``FT``.

    FPL fixtures do not expose a live minute — estimate from kickoff with a
    standard 15' half-time break. Cap stoppage so we show ``MT`` during the
    break (not unbounded ``45+10'``) and ``FT`` once the fixture is finished.
    """
    if finished:
        return "FT"
    if not started:
        return None
    if not kickoff_at:
        return "LIVE"
    try:
        text = str(kickoff_at).replace("Z", "+00:00")
        kick = datetime.fromisoformat(text)
    except ValueError:
        return "LIVE"
    if kick.tzinfo is None:
        kick = kick.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    elapsed = max(0, int((now - kick).total_seconds() // 60))
    # Assumed: 0–45 1H, short stoppage, then MT until ~60', then 2H (HT break ≈15').
    max_1h_stoppage = 7
    max_2h_stoppage = 10
    if elapsed < 45:
        return f"{elapsed}'"
    if elapsed <= 45 + max_1h_stoppage:
        extra = elapsed - 45
        return "45'" if extra == 0 else f"45+{extra}'"
    if elapsed < 60:
        return "MT"
    second = elapsed - 15  # remove HT break
    if second < 90:
        return f"{second}'"
    extra2 = second - 90
    if extra2 <= max_2h_stoppage:
        return "90'" if extra2 == 0 else f"90+{extra2}'"
    # Past assumed stoppage but FPL not finished yet — hold last stoppage label.
    return f"90+{max_2h_stoppage}'"


def fixtures_for_gameweek(db: Session, *, gw_number: int) -> list[dict[str, Any]]:
    clubs = {c.code: c for c in db.query(Club).all()}
    rows = (
        db.query(Fixture)
        .filter(Fixture.gameweek_number == gw_number)
        .order_by(Fixture.kickoff_at.asc(), Fixture.fpl_id.asc())
        .all()
    )
    out = []
    for fx in rows:
        home = clubs.get(fx.home_club_code)
        away = clubs.get(fx.away_club_code)
        status = "upcoming"
        if fx.finished:
            status = "finished"
        elif fx.started:
            status = "live"
        clock = estimate_match_clock(
            kickoff_at=fx.kickoff_at,
            started=bool(fx.started),
            finished=bool(fx.finished),
        )
        out.append(
            {
                "id": fx.id,
                "fpl_id": fx.fpl_id,
                "gw": fx.gameweek_number,
                "kickoff": fx.kickoff_at,
                "status": status,
                "clock": clock,
                "home": {
                    "code": fx.home_club_code,
                    "name": home.name if home else fx.home_club_code,
                    "score": fx.home_score,
                    "difficulty": map_fdr(fx.home_difficulty),
                    "badge": badge_url(fx.home_club_code, kit_code=home.kit_code if home else None),
                },
                "away": {
                    "code": fx.away_club_code,
                    "name": away.name if away else fx.away_club_code,
                    "score": fx.away_score,
                    "difficulty": map_fdr(fx.away_difficulty),
                    "badge": badge_url(fx.away_club_code, kit_code=away.kit_code if away else None),
                },
            }
        )
    return out


def _kickoff_day(kickoff: str | None) -> str | None:
    if not kickoff:
        return None
    text = str(kickoff)
    return text[:10] if len(text) >= 10 else None


def _scorer_lines(events: dict[str, Any], side: str) -> list[dict[str, Any]]:
    """Flatten goal rows for UI. FPL has no minute — minute stays null for now."""
    lines: list[dict[str, Any]] = []
    for row in (events.get("goals") or {}).get(side) or []:
        name = row.get("name") or "Player"
        count = int(row.get("value") or 1)
        for _ in range(max(1, count)):
            lines.append({"name": name, "minute": None, "own_goal": False})
    for row in (events.get("own_goals") or {}).get(side) or []:
        name = row.get("name") or "Player"
        count = int(row.get("value") or 1)
        for _ in range(max(1, count)):
            lines.append({"name": f"{name} (OG)", "minute": None, "own_goal": True})
    return lines


def squad_by_club(players: list[Player]) -> dict[str, list[dict[str, Any]]]:
    """club_code → owned players (for fixture highlights / light news)."""
    from app.services.fpl_sync import availability_flag

    out: dict[str, list[dict[str, Any]]] = {}
    for p in players:
        code = (p.team_code or "").upper()
        if not code:
            continue
        news = (getattr(p, "news", "") or "").strip()
        fpl_el = None
        ext = getattr(p, "external_id", "") or ""
        if ext.startswith("fpl-"):
            try:
                fpl_el = int(ext.split("-", 1)[1])
            except ValueError:
                fpl_el = None
        out.setdefault(code, []).append(
            {
                "id": p.id,
                "name": p.name,
                "position": p.position,
                "fpl_element": fpl_el,
                "news": news,
                "availability": availability_flag(
                    getattr(p, "status", "a") or "a",
                    getattr(p, "chance_of_playing", None),
                ),
            }
        )
    for rows in out.values():
        rows.sort(key=lambda r: (r["position"], r["name"]))
    return out


def _fixture_element_totals(fixture: Fixture) -> dict[int, dict[str, int]]:
    """FPL element id → goal/assist/etc counts from this fixture's stats_json."""
    try:
        stats = json.loads(fixture.stats_json or "[]")
    except json.JSONDecodeError:
        stats = []
    keys = {
        "goals_scored": "goals",
        "assists": "assists",
        "own_goals": "own_goals",
        "yellow_cards": "yellow_cards",
        "red_cards": "red_cards",
        "saves": "saves",
        "penalties_saved": "penalties_saved",
        "penalties_missed": "penalties_missed",
        "bonus": "bonus",
        "bps": "bps",
    }
    out: dict[int, dict[str, int]] = {}
    for block in stats:
        if not isinstance(block, dict):
            continue
        ident = block.get("identifier")
        metric = keys.get(ident) if isinstance(ident, str) else None
        if not metric:
            continue
        for side in ("h", "a"):
            for row in block.get(side) or []:
                el = int(row.get("element") or 0)
                val = int(row.get("value") or 0)
                if not el or val < 1:
                    continue
                bucket = out.setdefault(el, {})
                bucket[metric] = bucket.get(metric, 0) + val
    return out


def my_players_for_fixture(
    db: Session,
    fixture: Fixture,
    players: list[Player],
) -> dict[str, list[dict[str, Any]]]:
    """Owned players in this match with fixture/GW KPIs (G, A, CS, Pts).

    Before kickoff every KPI is null (UI shows —). Once the fixture has
    started, goals/assists come from this fixture's FPL stats; clean sheets
    and points come from GW MatchEvent / PlayerPoints (updated each GW).
    """
    from app.config import settings
    from app.models import Gameweek, PlayerPoints
    from app.scoring import score_player
    from app.services.fpl_sync import availability_flag
    from app.services.live_scoring import metrics_for_player

    by_club = squad_by_club(players)
    home_code = (fixture.home_club_code or "").upper()
    away_code = (fixture.away_club_code or "").upper()
    started = bool(fixture.started or fixture.finished)
    element_totals = _fixture_element_totals(fixture) if started else {}

    gw = (
        db.query(Gameweek).filter(Gameweek.number == fixture.gameweek_number).one_or_none()
        if fixture.gameweek_number
        else None
    )
    points_by_player: dict[int, float] = {}
    if started and gw is not None:
        rows = (
            db.query(PlayerPoints)
            .filter(
                PlayerPoints.gameweek_id == gw.id,
                PlayerPoints.formula_version == settings.formula_version,
            )
            .all()
        )
        points_by_player = {r.player_id: float(r.total) for r in rows}

    def enrich_side(code: str, side: str) -> list[dict[str, Any]]:
        rows = []
        conceded = None
        if started and fixture.home_score is not None and fixture.away_score is not None:
            conceded = (
                int(fixture.away_score) if side == "home" else int(fixture.home_score)
            )
        for base in by_club.get(code, []):
            row = dict(base)
            if not started:
                row.update(
                    {
                        "goals": None,
                        "assists": None,
                        "clean_sheets": None,
                        "points": None,
                    }
                )
                rows.append(row)
                continue

            el = base.get("fpl_element")
            fx_stats = element_totals.get(int(el), {}) if el else {}
            goals = int(fx_stats.get("goals") or 0)
            assists = int(fx_stats.get("assists") or 0)

            metrics: dict[str, float] = {}
            if gw is not None:
                metrics = dict(metrics_for_player(db, gw.id, int(base["id"])))

            # Prefer fixture G/A for both display AND points (live element lag).
            if goals:
                metrics["goals"] = max(float(metrics.get("goals") or 0), float(goals))
            if assists:
                metrics["assists"] = max(float(metrics.get("assists") or 0), float(assists))
            if (goals or assists) and float(metrics.get("minutes") or 0) <= 0:
                metrics["minutes"] = 1.0

            # Prefer fixture G/A; fill CS from live GW metrics when present.
            cs = metrics.get("clean_sheets")
            if cs is None and conceded is not None:
                pos = (base.get("position") or "").upper()
                minutes = float(metrics.get("minutes") or 0)
                if pos in {"GK", "DEF"} and conceded == 0 and minutes >= 60:
                    cs = 1.0
                elif pos in {"GK", "DEF"}:
                    cs = 0.0
                else:
                    cs = 0.0
            elif cs is None:
                cs = 0.0

            # Score from merged metrics so PTS matches G/A columns (not stale PlayerPoints).
            pts = 0.0
            try:
                pts = float(
                    score_player(base.get("position") or "MID", metrics or {"minutes": 0}).total
                )
            except ValueError:
                pts = float(points_by_player.get(int(base["id"])) or 0)

            row.update(
                {
                    "goals": goals,
                    "assists": assists,
                    "clean_sheets": int(cs),
                    "points": round(float(pts), 1),
                }
            )
            rows.append(row)
        return rows

    return {
        "home": enrich_side(home_code, "home"),
        "away": enrich_side(away_code, "away"),
    }


def enrich_fixtures_with_squad(
    matches: list[dict[str, Any]],
    by_club: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Attach my_players + light per-match news from owned squad."""
    enriched = []
    for row in matches:
        item = dict(row)
        home_code = (row.get("home") or {}).get("code") or ""
        away_code = (row.get("away") or {}).get("code") or ""
        home_mine = list(by_club.get(home_code, []))
        away_mine = list(by_club.get(away_code, []))
        item["my_players"] = {"home": home_mine, "away": away_mine}
        news: list[str] = []
        for p in home_mine + away_mine:
            text = (p.get("news") or "").strip()
            if not text:
                continue
            line = f"{p['name']}: {text}"
            if line not in news:
                news.append(line)
            if len(news) >= 3:
                break
        item["news"] = news
        enriched.append(item)
    return enriched


def fixtures_live_board(db: Session, *, gw_number: int, today: str | None = None) -> dict[str, Any]:
    """GW fixtures with scorers, preferring matches on `today` (YYYY-MM-DD)."""
    from datetime import datetime, timezone

    ensure_fixtures_ready(db)
    if not today:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = fixtures_for_gameweek(db, gw_number=gw_number)
    by_id = {
        fx.id: fx
        for fx in db.query(Fixture).filter(Fixture.gameweek_number == gw_number).all()
    }
    enriched = []
    for row in base:
        fx = by_id.get(row["id"])
        events = parse_match_events(db, fx) if fx else {"goals": {"home": [], "away": []}, "own_goals": {"home": [], "away": []}}
        item = dict(row)
        item["day"] = _kickoff_day(row.get("kickoff"))
        item["scorers"] = {
            "home": _scorer_lines(events, "home"),
            "away": _scorer_lines(events, "away"),
        }
        enriched.append(item)

    day_matches = [m for m in enriched if m.get("day") == today]
    use_day = bool(day_matches)
    matches = day_matches if use_day else enriched
    return {
        "today": today,
        "scope": "today" if use_day else "gameweek",
        "title": "Today's matches" if use_day else f"GW{gw_number} fixtures",
        "matches": matches,
    }


def _player_name_map(db: Session) -> dict[int, str]:
    """FPL element id → web name."""
    out: dict[int, str] = {}
    for p in db.query(Player).all():
        ext = p.external_id or ""
        if not ext.startswith("fpl-"):
            continue
        try:
            out[int(ext.split("-", 1)[1])] = p.name
        except ValueError:
            continue
    return out


def parse_match_events(db: Session, fixture: Fixture) -> dict[str, Any]:
    """Goals + assists from FPL fixture stats (home/away element lists)."""
    try:
        stats = json.loads(fixture.stats_json or "[]")
    except json.JSONDecodeError:
        stats = []
    names = _player_name_map(db)
    by_id = {s.get("identifier"): s for s in stats if isinstance(s, dict)}

    def side_list(identifier: str, side: str) -> list[dict[str, Any]]:
        block = by_id.get(identifier) or {}
        rows = block.get(side) or []
        out = []
        for row in rows:
            el = int(row.get("element") or 0)
            val = int(row.get("value") or 0)
            if not el or val < 1:
                continue
            out.append(
                {
                    "fpl_element": el,
                    "name": names.get(el) or f"Player {el}",
                    "value": val,
                }
            )
        return out

    return {
        "goals": {
            "home": side_list("goals_scored", "h"),
            "away": side_list("goals_scored", "a"),
        },
        "assists": {
            "home": side_list("assists", "h"),
            "away": side_list("assists", "a"),
        },
        "own_goals": {
            "home": side_list("own_goals", "h"),
            "away": side_list("own_goals", "a"),
        },
        "yellow_cards": {
            "home": side_list("yellow_cards", "h"),
            "away": side_list("yellow_cards", "a"),
        },
        "red_cards": {
            "home": side_list("red_cards", "h"),
            "away": side_list("red_cards", "a"),
        },
        "penalties_saved": {
            "home": side_list("penalties_saved", "h"),
            "away": side_list("penalties_saved", "a"),
        },
        "penalties_missed": {
            "home": side_list("penalties_missed", "h"),
            "away": side_list("penalties_missed", "a"),
        },
        "saves": {
            "home": side_list("saves", "h"),
            "away": side_list("saves", "a"),
        },
        "raw_identifiers": sorted(by_id.keys()),
    }


def fixture_detail(
    db: Session,
    *,
    fixture_id: int,
    owned_players: list[Player] | None = None,
) -> dict[str, Any] | None:
    """Fast path: scoreline, clubs, badges, status, events, my_players (local DB only).

    Does **not** call PulseLive / team-news enrichment — use
    ``fixture_sheet_preview`` for that so the match sheet can open in <1s.
    """
    fx = db.query(Fixture).filter(Fixture.id == fixture_id).one_or_none()
    if not fx:
        return None
    clubs = {c.code: c for c in db.query(Club).all()}
    events = parse_match_events(db, fx)
    status = "finished" if fx.finished else ("live" if fx.started else "upcoming")
    home = clubs.get(fx.home_club_code)
    away = clubs.get(fx.away_club_code)
    clock = estimate_match_clock(
        kickoff_at=fx.kickoff_at,
        started=bool(fx.started),
        finished=bool(fx.finished),
    )
    payload: dict[str, Any] = {
        "id": fx.id,
        "fpl_id": fx.fpl_id,
        "gw": fx.gameweek_number,
        "kickoff": fx.kickoff_at,
        "status": status,
        "clock": clock,
        "home": {
            "code": fx.home_club_code,
            "name": home.name if home else fx.home_club_code,
            "score": fx.home_score,
            "badge": badge_url(fx.home_club_code, kit_code=home.kit_code if home else None),
        },
        "away": {
            "code": fx.away_club_code,
            "name": away.name if away else fx.away_club_code,
            "score": fx.away_score,
            "badge": badge_url(fx.away_club_code, kit_code=away.kit_code if away else None),
        },
        **events,
    }
    if owned_players is not None:
        payload["my_players"] = my_players_for_fixture(db, fx, owned_players)
    # Team match stats are slow (API-Football) — loaded via /preview, not this fast path.
    payload["team_stats"] = None
    return payload


def fixture_sheet_preview(db: Session, *, fixture_id: int) -> dict[str, Any] | None:
    """Slow path: team news + PulseLive + optional API-Football team stats."""
    fx = db.query(Fixture).filter(Fixture.id == fixture_id).one_or_none()
    if not fx:
        return None
    clubs = {c.code: c for c in db.query(Club).all()}
    home = clubs.get(fx.home_club_code)
    away = clubs.get(fx.away_club_code)
    base: dict[str, Any] = {
        "id": fx.id,
        "home": {
            "code": fx.home_club_code,
            "name": home.name if home else fx.home_club_code,
            "badge": badge_url(fx.home_club_code, kit_code=home.kit_code if home else None),
        },
        "away": {
            "code": fx.away_club_code,
            "name": away.name if away else fx.away_club_code,
            "badge": badge_url(fx.away_club_code, kit_code=away.kit_code if away else None),
        },
    }
    team_stats = None
    team_stats_status = "unavailable"
    try:
        from app.services import advanced_stats as adv_svc

        result = adv_svc.team_match_stats_result(db, fx)
        team_stats = result.get("team_stats")
        team_stats_status = result.get("team_stats_status") or (
            "ok" if team_stats else "unavailable"
        )
    except Exception:
        team_stats = None
        team_stats_status = "error"
    try:
        from app.services import pl_content

        enriched = pl_content.enrich_fixture_sheet(db, fx, base)
    except Exception:  # noqa: BLE001 — sheet must still render without Pulse/news
        return {
            "id": fx.id,
            "team_news": {"home": [], "away": []},
            "preview": None,
            "pulse": None,
            "team_stats": team_stats,
            "team_stats_status": team_stats_status,
        }
    return {
        "id": fx.id,
        "team_news": enriched.get("team_news") or {"home": [], "away": []},
        "preview": enriched.get("preview"),
        "pulse": enriched.get("pulse"),
        "team_stats": team_stats,
        "team_stats_status": team_stats_status,
    }

def refresh_fixtures(db: Session) -> dict[str, int]:
    """Pull latest FPL fixtures (scores + started/finished + stats).

    If clubs lack ``fpl_team_id`` (common on older DBs), backfill via
    ``ensure_fixtures_ready`` then retry — otherwise started/finished never
    move off the seed snapshot.
    """
    info = sync_fixtures(db)
    if info.get("reason") == "no_club_fpl_ids" or int(info.get("fixtures") or 0) == 0:
        ensure_fixtures_ready(db)
        info = sync_fixtures(db)
    return info
