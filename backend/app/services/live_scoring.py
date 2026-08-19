"""Gameweek scoring: ingest FPL live → player points → manager totals → H2H."""

from __future__ import annotations

from collections import Counter
import json
import hashlib
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    ChipPlay,
    Club,
    ClubResult,
    Gameweek,
    H2HMatch,
    League,
    Manager,
    ManagerGameweekScore,
    MatchEvent,
    Membership,
    OwnedPlayer,
    Player,
    PlayerPoints,
    SquadPick,
)
from app.scoring import score_player
from app.services import fixtures as fixtures_svc
from app.services import squad as squad_svc
from app.services import standings as standings_svc
from app.services import td as td_svc
from app.services.fpl_sync import availability_flag

FPL_EVENT_LIVE = "https://fantasy.premierleague.com/api/event/{gw}/live/"
FPL_FIXTURES = "https://fantasy.premierleague.com/api/fixtures/"
HEADERS = {
    "User-Agent": "SquadForge/0.4 (private fantasy)",
    "Accept": "application/json",
}


class ScoreError(ValueError):
    pass


def _http_get(url: str) -> dict | list:
    with httpx.Client(timeout=45.0, headers=HEADERS, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def fpl_id_from_external(external_id: str) -> int | None:
    if not external_id.startswith("fpl-"):
        return None
    try:
        return int(external_id.split("-", 1)[1])
    except ValueError:
        return None


def map_fpl_stats(stats: dict[str, Any]) -> dict[str, float]:
    """Map FPL live/bootstrap element stats → our formula metric names."""
    return {
        "minutes": float(stats.get("minutes") or 0),
        "goals": float(stats.get("goals_scored") or 0),
        "assists": float(stats.get("assists") or 0),
        "clean_sheets": float(stats.get("clean_sheets") or 0),
        "goals_conceded": float(stats.get("goals_conceded") or 0),
        "own_goals": float(stats.get("own_goals") or 0),
        "penalties_saved": float(stats.get("penalties_saved") or 0),
        "penalties_missed": float(stats.get("penalties_missed") or 0),
        "yellow_cards": float(stats.get("yellow_cards") or 0),
        "red_cards": float(stats.get("red_cards") or 0),
        "saves": float(stats.get("saves") or 0),
        # Advanced FPL fields (live + bootstrap)
        "tackles": float(stats.get("tackles") or 0),
        "cbi": float(stats.get("clearances_blocks_interceptions") or 0),
        "creativity": float(stats.get("creativity") or 0),
        "threat": float(stats.get("threat") or 0),
        "xg": float(stats.get("expected_goals") or 0),
        # No free feed exposes goal-line clearances; kept for a future source.
        "goal_line_clearances": 0.0,
    }


def _write_metrics(db: Session, *, gameweek_id: int, player_id: int, metrics: dict[str, float], source: str) -> None:
    now = datetime.utcnow()
    for metric, value in metrics.items():
        row = (
            db.query(MatchEvent)
            .filter(
                MatchEvent.gameweek_id == gameweek_id,
                MatchEvent.player_id == player_id,
                MatchEvent.metric == metric,
            )
            .one_or_none()
        )
        if row:
            row.value = float(value)
            row.source = source
            row.fetched_at = now
        else:
            db.add(
                MatchEvent(
                    gameweek_id=gameweek_id,
                    player_id=player_id,
                    metric=metric,
                    value=float(value),
                    source=source,
                    fetched_at=now,
                )
            )


def ingest_fpl_live(db: Session, gw: Gameweek) -> dict[str, Any]:
    """Pull FPL event live + fixtures; write MatchEvent + ClubResult rows."""
    live = _http_get(FPL_EVENT_LIVE.format(gw=gw.number))
    elements = live.get("elements") or []
    by_fpl = {fpl_id_from_external(p.external_id): p for p in db.query(Player).all() if fpl_id_from_external(p.external_id)}

    updated = 0
    for el in elements:
        pid = by_fpl.get(int(el.get("id") or 0))
        if not pid:
            continue
        metrics = map_fpl_stats(el.get("stats") or {})
        _write_metrics(db, gameweek_id=gw.id, player_id=pid.id, metrics=metrics, source="fpl_live")
        updated += 1

    # Club results from fixtures for TD
    fixtures = _http_get(f"{FPL_FIXTURES}?event={gw.number}")
    teams = {c.code: c for c in db.query(Club).all()}
    # Need FPL team id → short_name; re-fetch bootstrap teams via club.kit_code reverse or codes from sync
    # Clubs store kit_code = FPL teams[].code, but fixtures use teams[].id. Map via fresh bootstrap.
    from app.services.fpl_sync import fetch_bootstrap

    bootstrap = fetch_bootstrap()
    id_to_short = {
        int(t["id"]): (t.get("short_name") or t["name"][:3]).upper()[:8] for t in bootstrap["teams"]
    }

    club_results = 0
    db.query(ClubResult).filter(ClubResult.gameweek_id == gw.id).delete()
    for fx in fixtures:
        if not fx.get("finished") and not fx.get("finished_provisional"):
            continue
        hs = fx.get("team_h_score")
        as_ = fx.get("team_a_score")
        if hs is None or as_ is None:
            continue
        home = id_to_short.get(int(fx["team_h"]))
        away = id_to_short.get(int(fx["team_a"]))
        if not home or not away:
            continue
        if hs > as_:
            results = ((home, "W"), (away, "L"))
        elif hs < as_:
            results = ((home, "L"), (away, "W"))
        else:
            results = ((home, "D"), (away, "D"))
        # DGW: use fixture id order as index per club
        for club_code, result in results:
            if club_code not in teams:
                continue
            existing = (
                db.query(ClubResult)
                .filter(ClubResult.gameweek_id == gw.id, ClubResult.club_code == club_code)
                .count()
            )
            db.add(
                ClubResult(
                    gameweek_id=gw.id,
                    club_code=club_code,
                    fixture_index=existing,
                    result=result,
                )
            )
            club_results += 1

    db.commit()
    return {
        "source": "fpl_live",
        "players_updated": updated,
        "club_results": club_results,
        "live_empty": len(elements) == 0,
    }


def simulate_demo_metrics(db: Session, gw: Gameweek) -> dict[str, Any]:
    """Invent plausible metrics for owned players (explicit demo / debug only).

    Writes MatchEvent rows with source=\"demo_sim\" so they can be cleared later.
    Never called by the background auto-scorer.
    """
    owned_ids = {r.player_id for r in db.query(OwnedPlayer).all()}
    if not owned_ids:
        # Fall back: score a slice of the catalogue so formulas still exercise
        owned_ids = {p.id for p in db.query(Player).order_by(Player.price.desc()).limit(40).all()}

    players = db.query(Player).filter(Player.id.in_(owned_ids)).all()
    updated = 0
    for p in players:
        seed = f"{gw.number}:{p.id}:{p.external_id}".encode()
        h = hashlib.sha256(seed).hexdigest()
        n = int(h[:8], 16)
        avail_out = (getattr(p, "status", "a") or "a") in {"i", "s", "u"} or getattr(p, "chance_of_playing", 100) == 0
        if avail_out or (n % 11 == 0):
            metrics = map_fpl_stats({})
        else:
            minutes = 90 if n % 5 else (60 if n % 3 else 30)
            goals = 1 if (n % 17 == 0 and p.position in {"MID", "ATT"}) else (1 if n % 43 == 0 else 0)
            assists = 1 if n % 19 == 0 else 0
            cs = 1 if minutes >= 60 and p.position in {"GK", "DEF"} and n % 4 == 0 else 0
            gc = 0 if cs else (n % 3)
            saves = (n % 9) if p.position == "GK" else 0
            metrics = {
                **map_fpl_stats({}),
                "minutes": float(minutes),
                "goals": float(goals),
                "assists": float(assists),
                "clean_sheets": float(cs),
                "goals_conceded": float(gc if p.position in {"GK", "DEF"} else 0),
                "saves": float(saves),
                "yellow_cards": 1.0 if n % 23 == 0 else 0.0,
            }
        _write_metrics(db, gameweek_id=gw.id, player_id=p.id, metrics=metrics, source="demo_sim")
        updated += 1

    # Fake club results for TD demos
    clubs = db.query(Club).order_by(Club.code).all()
    db.query(ClubResult).filter(ClubResult.gameweek_id == gw.id).delete()
    for i, club in enumerate(clubs):
        result = ["W", "D", "L"][(gw.number + i) % 3]
        db.add(ClubResult(gameweek_id=gw.id, club_code=club.code, fixture_index=0, result=result))

    db.commit()
    return {"source": "demo_sim", "players_updated": updated, "club_results": len(clubs)}


def metrics_for_player(db: Session, gameweek_id: int, player_id: int) -> dict[str, float]:
    rows = (
        db.query(MatchEvent)
        .filter(MatchEvent.gameweek_id == gameweek_id, MatchEvent.player_id == player_id)
        .all()
    )
    return {r.metric: float(r.value) for r in rows}


def score_players(db: Session, gw: Gameweek) -> int:
    """Score every player who has MatchEvents this GW (and clear stale points)."""
    player_ids = {
        r.player_id
        for r in db.query(MatchEvent.player_id).filter(MatchEvent.gameweek_id == gw.id).distinct()
    }
    # Also include all owned players so blanks get 0
    player_ids |= {r.player_id for r in db.query(OwnedPlayer).all()}

    # League ownership for scouting — use largest league or first
    league = db.query(League).order_by(League.id).first()
    league_size = (
        db.query(Membership).filter(Membership.league_id == league.id).count() if league else 0
    )
    owners: dict[int, int] = {}
    if league and league_size:
        member_ids = [
            m.manager_id for m in db.query(Membership).filter(Membership.league_id == league.id).all()
        ]
        for oid in (
            db.query(OwnedPlayer)
            .filter(OwnedPlayer.manager_id.in_(member_ids))
            .all()
        ):
            owners[oid.player_id] = owners.get(oid.player_id, 0) + 1

    counted = 0
    for pid in player_ids:
        player = db.query(Player).filter(Player.id == pid).one_or_none()
        if not player:
            continue
        metrics = metrics_for_player(db, gw.id, pid)
        result = score_player(
            player.position,
            metrics,
            owners_count=owners.get(pid, 0) if league_size else None,
            league_size=league_size or None,
        )
        row = (
            db.query(PlayerPoints)
            .filter(
                PlayerPoints.gameweek_id == gw.id,
                PlayerPoints.player_id == pid,
                PlayerPoints.formula_version == settings.formula_version,
            )
            .one_or_none()
        )
        if row:
            row.total = result.total
            row.breakdown_json = json.dumps(result.breakdown)
        else:
            db.add(
                PlayerPoints(
                    gameweek_id=gw.id,
                    player_id=pid,
                    total=result.total,
                    breakdown_json=json.dumps(result.breakdown),
                    formula_version=settings.formula_version,
                )
            )
        counted += 1
    db.commit()
    return counted


def player_points_map(db: Session, gw: Gameweek) -> dict[int, float]:
    rows = (
        db.query(PlayerPoints)
        .filter(
            PlayerPoints.gameweek_id == gw.id,
            PlayerPoints.formula_version == settings.formula_version,
        )
        .all()
    )
    return {r.player_id: float(r.total) for r in rows}


def _apply_autosubs(
    db: Session,
    *,
    owned: list[Player],
    picks: list[SquadPick],
    minutes: dict[int, float],
) -> tuple[set[int], int | None, int | None]:
    """Simple FPL-like autosubs: blank starters replaced by bench who played.

    Returns (effective_starters, captain_id, vice_id).
    """
    by_id = {p.id: p for p in owned}
    starters = {p.player_id for p in picks if p.is_starter}
    captain = next((p.player_id for p in picks if p.is_captain), None)
    vice = next((p.player_id for p in picks if getattr(p, "is_vice_captain", 0)), None)
    bench = sorted(
        [p for p in picks if not p.is_starter],
        key=lambda x: x.bench_order or 99,
    )

    effective = set(starters)
    for sid in list(starters):
        if (minutes.get(sid, 0) or 0) > 0:
            continue
        starter = by_id.get(sid)
        if not starter:
            continue
        # Find bench player who played and keeps a legal XI shape
        for b in bench:
            if b.player_id in effective:
                continue
            if (minutes.get(b.player_id, 0) or 0) <= 0:
                continue
            bp = by_id.get(b.player_id)
            if not bp:
                continue
            trial = (effective - {sid}) | {b.player_id}
            counts = Counter(by_id[i].position for i in trial if i in by_id)
            try:
                squad_svc.validate_starter_shape(counts)
            except squad_svc.SquadError:
                continue
            effective = trial
            if captain == sid:
                captain = b.player_id
            if vice == sid:
                vice = b.player_id
            break

    return effective, captain, vice


def freeze_kickoff_captains(db: Session, gw: Gameweek) -> None:
    """Mark current captains as armed once their club fixture has started."""
    picks = (
        db.query(SquadPick)
        .filter(SquadPick.gameweek_id == gw.id, SquadPick.is_captain == 1)
        .all()
    )
    if not picks:
        return
    players = {
        p.id: p
        for p in db.query(Player).filter(Player.id.in_([x.player_id for x in picks])).all()
    }
    dirty = False
    for pick in picks:
        if pick.captain_armed:
            continue
        pl = players.get(pick.player_id)
        if not pl:
            continue
        if fixtures_svc.club_fixture_started(db, club_code=pl.team_code, gw_number=gw.number):
            pick.captain_armed = 1
            dirty = True
    if dirty:
        db.commit()


def unavailable_xi_penalty(db: Session, picks: list[SquadPick], by_id: dict[int, Player]) -> tuple[float, list[int]]:
    """−1 per injured/suspended/unavailable player left in the Starting XI at GW lock."""
    flagged: list[int] = []
    for pick in picks:
        if not pick.is_starter:
            continue
        p = by_id.get(pick.player_id)
        if not p:
            continue
        flag = availability_flag(getattr(p, "status", "a") or "a", getattr(p, "chance_of_playing", None))
        if flag == "out":
            flagged.append(p.id)
    return (-1.0 * len(flagged), flagged)


def score_managers(db: Session, gw: Gameweek) -> int:
    freeze_kickoff_captains(db, gw)
    pts = player_points_map(db, gw)
    managers = db.query(Manager).all()
    scored = 0
    for manager in managers:
        owned = squad_svc.owned_players(db, manager.id)
        if len(owned) != settings.squad_size:
            continue
        picks = (
            db.query(SquadPick)
            .filter(SquadPick.manager_id == manager.id, SquadPick.gameweek_id == gw.id)
            .all()
        )
        if not picks:
            starters, _, captain, vice = squad_svc.default_lineup_from_owned(owned)
            squad_svc.save_lineup(
                db,
                manager_id=manager.id,
                gameweek_id=gw.id,
                starter_ids=starters,
                captain_id=captain,
                vice_id=vice,
            )
            picks = (
                db.query(SquadPick)
                .filter(SquadPick.manager_id == manager.id, SquadPick.gameweek_id == gw.id)
                .all()
            )

        minutes = {
            pid: metrics_for_player(db, gw.id, pid).get("minutes", 0.0)
            for pid in {p.player_id for p in picks}
        }
        chip = (
            db.query(ChipPlay)
            .filter(ChipPlay.manager_id == manager.id, ChipPlay.gameweek_id == gw.id)
            .one_or_none()
        )
        chip_name = chip.chip if chip else None
        ss_id = None
        if chip_name == "super_sub" and chip:
            try:
                ss_id = int(json.loads(chip.meta_json or "{}").get("player_id") or 0) or None
            except (TypeError, ValueError, json.JSONDecodeError):
                ss_id = None

        effective, captain_id, vice_id = _apply_autosubs(
            db, owned=owned, picks=picks, minutes=minutes
        )
        armband = squad_svc.effective_captain_id(
            captain_id or 0,
            vice_id,
            minutes,
        )
        armed_ids = {p.player_id for p in picks if getattr(p, "captain_armed", 0)}
        # Provisional: current captain still counts before their kickoff
        if captain_id and captain_id not in armed_ids:
            cap_player = next((p for p in owned if p.id == captain_id), None)
            if cap_player and not fixtures_svc.club_fixture_started(
                db, club_code=cap_player.team_code, gw_number=gw.number
            ):
                armed_ids.add(captain_id)
        if not armed_ids and armband:
            armed_ids.add(armband)

        player_lines = []
        squad_points = 0.0
        starter_ids = {p.player_id for p in picks if p.is_starter}
        by_id = {p.id: p for p in owned}
        for pid in effective:
            base = pts.get(pid, 0.0)
            mult = 1.0
            is_cap = pid in armed_ids or pid == armband
            if pid in armed_ids:
                mult = 3.0 if chip_name == "triple_captain" else 2.0
            elif pid == armband:
                mult = 3.0 if chip_name == "triple_captain" else 2.0
            elif ss_id and pid == ss_id:
                mult = 2.0
            scored_pts = round(base * mult, 2)
            squad_points += scored_pts
            player_lines.append(
                {
                    "player_id": pid,
                    "points": scored_pts,
                    "base": base,
                    "mult": mult,
                    "captain": is_cap,
                    "autosub": pid not in starter_ids,
                    "super_sub": bool(ss_id and pid == ss_id),
                }
            )

        if chip_name == "bench_boost":
            bench_ids = {p.player_id for p in picks if not p.is_starter} - set(effective)
            for pid in bench_ids:
                base = pts.get(pid, 0.0)
                squad_points += base
                player_lines.append(
                    {"player_id": pid, "points": base, "base": base, "mult": 1.0, "bench_boost": True}
                )
        elif chip_name == "super_sub" and ss_id and ss_id not in set(effective):
            # Remains on bench: if they played any minutes, count ×2; else 0 (chip already consumed)
            mins = minutes.get(ss_id, 0.0) or 0.0
            if mins > 0:
                base = pts.get(ss_id, 0.0)
                scored_pts = round(base * 2.0, 2)
                squad_points += scored_pts
                player_lines.append(
                    {
                        "player_id": ss_id,
                        "points": scored_pts,
                        "base": base,
                        "mult": 2.0,
                        "super_sub": True,
                        "bench": True,
                    }
                )

        td_pts = td_svc.td_points_for_gw(
            db, manager_id=manager.id, gw_number=gw.number, gameweek_id=gw.id
        )
        hit_pts = squad_svc.transfer_hit_points(db, manager.id, gw.id)
        hit_n = squad_svc.hit_transfers_this_gw(db, manager.id, gw.id)
        neglect_pts, neglect_ids = unavailable_xi_penalty(db, picks, by_id)
        total = round(squad_points + td_pts + hit_pts + neglect_pts, 2)
        breakdown = {
            "squad": round(squad_points, 2),
            "td": td_pts,
            "hits": hit_n,
            "hit_points": hit_pts,
            "unavailable_xi_penalty": neglect_pts,
            "unavailable_xi_players": neglect_ids,
            "armband_player_id": armband,
            "armed_captain_ids": sorted(armed_ids),
            "chip": chip_name or "—",
            "players": player_lines,
        }

        row = (
            db.query(ManagerGameweekScore)
            .filter(
                ManagerGameweekScore.manager_id == manager.id,
                ManagerGameweekScore.gameweek_id == gw.id,
            )
            .one_or_none()
        )
        if row:
            row.squad_points = round(squad_points, 2)
            row.td_points = td_pts
            row.total = total
            row.breakdown_json = json.dumps(breakdown)
        else:
            db.add(
                ManagerGameweekScore(
                    manager_id=manager.id,
                    gameweek_id=gw.id,
                    squad_points=round(squad_points, 2),
                    td_points=td_pts,
                    total=total,
                    breakdown_json=json.dumps(breakdown),
                )
            )
        scored += 1
    db.commit()
    return scored


def resolve_h2h(db: Session, gw: Gameweek) -> int:
    """Settle H2H results for ``gw``.

    Stays ``pending`` until at least one PL fixture in the GW has started —
    otherwise 0–0 before kickoff was incorrectly recorded as a draw.
    """
    from sqlalchemy import or_

    from app.models import Fixture

    any_started = (
        db.query(Fixture.id)
        .filter(
            Fixture.gameweek_number == int(gw.number),
            or_(Fixture.started == 1, Fixture.finished == 1),
        )
        .first()
    )
    leagues = db.query(League).filter(League.league_type == "h2h").all()
    updated = 0
    for league in leagues:
        matches = standings_svc.ensure_h2h_pairings(db, league, gw)
        for match in matches:
            if not any_started:
                # Undo premature settlements (e.g. 0–0 draw after deadline, pre-kickoff).
                if match.result != "pending" or match.home_points or match.away_points:
                    match.home_points = 0.0
                    match.away_points = 0.0
                    match.result = "pending"
                    updated += 1
                continue
            home = (
                db.query(ManagerGameweekScore)
                .filter(
                    ManagerGameweekScore.manager_id == match.home_manager_id,
                    ManagerGameweekScore.gameweek_id == gw.id,
                )
                .one_or_none()
            )
            away = (
                db.query(ManagerGameweekScore)
                .filter(
                    ManagerGameweekScore.manager_id == match.away_manager_id,
                    ManagerGameweekScore.gameweek_id == gw.id,
                )
                .one_or_none()
            )
            hp = float(home.total) if home else 0.0
            ap = float(away.total) if away else 0.0
            match.home_points = hp
            match.away_points = ap
            if hp > ap:
                match.result = "home"
            elif ap > hp:
                match.result = "away"
            else:
                match.result = "draw"
            updated += 1
    db.commit()
    return updated


def run_gameweek_scoring(
    db: Session,
    *,
    prefer_live: bool = True,
    force_demo: bool = False,
) -> dict[str, Any]:
    """Full pipeline for the current gameweek.

    Demo metrics are **never** applied automatically. Pass ``force_demo=True``
    only from an explicit developer action (e.g. Score with demo data).
    """
    gw = squad_svc.current_gameweek(db)
    ingest: dict[str, Any]
    if force_demo:
        ingest = simulate_demo_metrics(db, gw)
    else:
        try:
            ingest = ingest_fpl_live(db, gw) if prefer_live else {"live_empty": True, "source": "skipped"}
        except Exception as exc:
            ingest = {"source": "fpl_error", "error": str(exc), "live_empty": True}
        # Pre-kickoff / empty live: leave real zeros — do NOT invent demo_sim points.
        if ingest.get("live_empty") or ingest.get("players_updated", 0) == 0:
            ingest = {
                **ingest,
                "demo_skipped": True,
                "source": ingest.get("source") or "fpl_live",
            }

    # Advanced defensive/create stats from API-Football (optional; never blocks scoring).
    try:
        from app.services import advanced_stats as adv_svc

        ingest["api_football"] = adv_svc.ingest_advanced_stats(db, gw)
    except Exception as exc:
        ingest["api_football"] = {"error": str(exc)}

    n_players = score_players(db, gw)
    n_managers = score_managers(db, gw)
    n_h2h = resolve_h2h(db, gw)
    return {
        "gameweek": gw.number,
        "ingest": ingest,
        "players_scored": n_players,
        "managers_scored": n_managers,
        "h2h_updated": n_h2h,
        "formula_version": settings.formula_version,
    }


def clear_demo_scoring_data(db: Session, *, gameweek_id: int | None = None) -> dict[str, Any]:
    """Delete demo_sim MatchEvents and derived scores so tables show real zeros.

    Durable signal: MatchEvent.source == \"demo_sim\" (fell_back_demo was never persisted).
    """
    q = db.query(MatchEvent).filter(MatchEvent.source == "demo_sim")
    if gameweek_id is not None:
        q = q.filter(MatchEvent.gameweek_id == gameweek_id)
    gw_ids = sorted({int(r[0]) for r in q.with_entities(MatchEvent.gameweek_id).distinct().all()})
    deleted_events = q.delete(synchronize_session=False)

    deleted_scores = 0
    deleted_player_pts = 0
    reset_h2h = 0
    deleted_club_results = 0
    for gid in gw_ids:
        deleted_scores += (
            db.query(ManagerGameweekScore)
            .filter(ManagerGameweekScore.gameweek_id == gid)
            .delete(synchronize_session=False)
        )
        deleted_player_pts += (
            db.query(PlayerPoints)
            .filter(PlayerPoints.gameweek_id == gid)
            .delete(synchronize_session=False)
        )
        for match in db.query(H2HMatch).filter(H2HMatch.gameweek_id == gid).all():
            match.home_points = 0.0
            match.away_points = 0.0
            match.result = "pending"
            reset_h2h += 1
        # Demo rewrite wiped + replaced ClubResult for the GW; if no real events remain, clear.
        remaining = (
            db.query(MatchEvent)
            .filter(MatchEvent.gameweek_id == gid)
            .count()
        )
        if remaining == 0:
            deleted_club_results += (
                db.query(ClubResult)
                .filter(ClubResult.gameweek_id == gid)
                .delete(synchronize_session=False)
            )
    db.commit()
    return {
        "gameweek_ids": gw_ids,
        "match_events_deleted": int(deleted_events or 0),
        "manager_scores_deleted": int(deleted_scores or 0),
        "player_points_deleted": int(deleted_player_pts or 0),
        "h2h_reset": reset_h2h,
        "club_results_deleted": int(deleted_club_results or 0),
    }


def is_demo_scoring_active(db: Session, gw: Gameweek | None = None) -> bool:
    """True when demo_sim MatchEvents exist for the GW (or a live demo session is on)."""
    if gw is None:
        try:
            gw = squad_svc.current_gameweek(db)
        except Exception:
            return False
    try:
        from app.services import demo_live as demo_svc

        # Pass gw so is_live_demo_active does not re-query current_gameweek (~62ms).
        if demo_svc.is_live_demo_active(db, gw):
            return True
    except Exception:
        pass
    return (
        db.query(MatchEvent.id)
        .filter(MatchEvent.gameweek_id == gw.id, MatchEvent.source == "demo_sim")
        .first()
        is not None
    )
