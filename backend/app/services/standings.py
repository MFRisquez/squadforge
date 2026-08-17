"""Classic + Head-to-Head standings helpers (FPL-inspired)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import (
    ChipPlay,
    Gameweek,
    H2HMatch,
    League,
    Manager,
    ManagerGameweekScore,
    Membership,
    TransferLog,
    TransferState,
)
from app.services import squad as squad_svc
from app.services import td as td_svc


def _cumulative_total(db: Session, manager_id: int, through_number: int) -> float:
    """Season total using only gameweeks up to through_number (inclusive)."""
    rows = (
        db.query(ManagerGameweekScore)
        .join(Gameweek, Gameweek.id == ManagerGameweekScore.gameweek_id)
        .filter(
            ManagerGameweekScore.manager_id == manager_id,
            Gameweek.number <= through_number,
        )
        .all()
    )
    return float(sum(s.total for s in rows))


def _rank_by_manager(
    entries: list[tuple[int, float, float, str]],
) -> dict[int, int]:
    """entries: (manager_id, total, gw_points, name). Returns manager_id -> rank."""
    ordered = sorted(entries, key=lambda e: (-e[1], -e[2], e[3]))
    return {mid: i for i, (mid, *_rest) in enumerate(ordered, start=1)}


def _manager_row_base(db: Session, manager: Manager, gw) -> dict:
    owned = squad_svc.owned_players(db, manager.id)
    spend = squad_svc.squad_spend(owned)
    score = (
        db.query(ManagerGameweekScore)
        .filter(
            ManagerGameweekScore.manager_id == manager.id,
            ManagerGameweekScore.gameweek_id == gw.id,
        )
        .one_or_none()
    )
    total_points = _cumulative_total(db, manager.id, gw.number)
    gw_points = score.total if score else 0.0
    # Last 5 finished/current GW scores for a compact form string
    recent_gws = (
        db.query(Gameweek)
        .filter(Gameweek.number <= gw.number)
        .order_by(Gameweek.number.desc())
        .limit(5)
        .all()
    )
    recent_gws = list(reversed(recent_gws))
    form_parts: list[str] = []
    for rg in recent_gws:
        rs = (
            db.query(ManagerGameweekScore)
            .filter(
                ManagerGameweekScore.manager_id == manager.id,
                ManagerGameweekScore.gameweek_id == rg.id,
            )
            .one_or_none()
        )
        form_parts.append(str(int(rs.total)) if rs else "–")
    form = "·".join(form_parts) if form_parts else "—"
    transfers = (
        db.query(TransferLog)
        .filter(TransferLog.manager_id == manager.id, TransferLog.gameweek_id == gw.id)
        .count()
    )
    chip = (
        db.query(ChipPlay)
        .filter(ChipPlay.manager_id == manager.id, ChipPlay.gameweek_id == gw.id)
        .one_or_none()
    )
    from app.services.chips import CHIP_SHORT

    chip_key = chip.chip if chip else None
    td = td_svc.current_td(db, manager.id, gw.number)
    ft_state = db.query(TransferState).filter(TransferState.manager_id == manager.id).one_or_none()
    return {
        "manager": manager,
        "team_name": (manager.team_name or "").strip() or "—",
        "gw_points": gw_points,
        "total_points": total_points,
        "squad_value": spend,
        "transfers": transfers,
        "chip": CHIP_SHORT.get(chip_key, "—") if chip_key else "—",
        "chip_key": chip_key,
        "td_club": td.club_code if td else "—",
        "ft_left": ft_state.free_transfers if ft_state else 0,
        "players_owned": len(owned),
        "form": form,
    }


def classic_standings(db: Session, league: League, gw) -> list[dict]:
    members = db.query(Membership).filter(Membership.league_id == league.id).all()
    rows = [_manager_row_base(db, m.manager, gw) for m in members]
    rows.sort(key=lambda r: (-r["total_points"], -r["gw_points"], r["manager"].display_name.lower()))
    for i, row in enumerate(rows, start=1):
        row["rank"] = i

    # Rank movement vs previous gameweek (FPL-style: ↑ climbed, ↓ dropped)
    prev_ranks: dict[int, int] = {}
    if gw.number > 1:
        prev_entries = []
        for row in rows:
            mid = row["manager"].id
            prev_total = _cumulative_total(db, mid, gw.number - 1)
            prev_entries.append(
                (mid, prev_total, 0.0, row["manager"].display_name.lower())
            )
        prev_ranks = _rank_by_manager(prev_entries)

    for row in rows:
        prev = prev_ranks.get(row["manager"].id)
        if prev is None:
            row["prev_rank"] = None
            row["rank_delta"] = None
        else:
            row["prev_rank"] = prev
            row["rank_delta"] = prev - row["rank"]
    return rows


def ensure_h2h_pairings(db: Session, league: League, gw) -> list[H2HMatch]:
    """Pair managers for the current GW. Requires even count; stable shuffle by gw number."""
    existing = (
        db.query(H2HMatch)
        .filter(H2HMatch.league_id == league.id, H2HMatch.gameweek_id == gw.id)
        .all()
    )
    if existing:
        return existing

    members = [m.manager for m in db.query(Membership).filter(Membership.league_id == league.id).all()]
    if len(members) < 2 or len(members) % 2 != 0:
        return []

    ordered = sorted(members, key=lambda m: m.id)
    # Rotate by gameweek so opponents change
    rot = (gw.number - 1) % max(1, len(ordered))
    ordered = ordered[rot:] + ordered[:rot]
    matches = []
    for i in range(0, len(ordered), 2):
        home, away = ordered[i], ordered[i + 1]
        match = H2HMatch(
            league_id=league.id,
            gameweek_id=gw.id,
            home_manager_id=home.id,
            away_manager_id=away.id,
        )
        db.add(match)
        matches.append(match)
    db.commit()
    for m in matches:
        db.refresh(m)
    return matches


def h2h_standings(db: Session, league: League, gw) -> tuple[list[dict], list[dict]]:
    """Return (table_rows, this_week_fixtures)."""
    members = [m.manager for m in db.query(Membership).filter(Membership.league_id == league.id).all()]
    stats = {
        m.id: {
            **_manager_row_base(db, m, gw),
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "h2h_points": 0,
            "pf": 0.0,
            "pa": 0.0,
        }
        for m in members
    }

    all_matches = db.query(H2HMatch).filter(H2HMatch.league_id == league.id).all()
    for match in all_matches:
        if match.result == "pending":
            continue
        home = stats.get(match.home_manager_id)
        away = stats.get(match.away_manager_id)
        if not home or not away:
            continue
        home["played"] += 1
        away["played"] += 1
        home["pf"] += match.home_points
        home["pa"] += match.away_points
        away["pf"] += match.away_points
        away["pa"] += match.home_points
        if match.result == "home":
            home["wins"] += 1
            away["losses"] += 1
            home["h2h_points"] += 3
        elif match.result == "away":
            away["wins"] += 1
            home["losses"] += 1
            away["h2h_points"] += 3
        else:
            home["draws"] += 1
            away["draws"] += 1
            home["h2h_points"] += 1
            away["h2h_points"] += 1

    rows = list(stats.values())
    rows.sort(
        key=lambda r: (-r["h2h_points"], -r["pf"], -r["total_points"], r["manager"].display_name.lower())
    )
    for i, row in enumerate(rows, start=1):
        row["rank"] = i
        row["prev_rank"] = None
        row["rank_delta"] = None

    by_id = {m.id: m for m in members}
    fixtures = []
    for match in ensure_h2h_pairings(db, league, gw):
        home = by_id.get(match.home_manager_id)
        away = by_id.get(match.away_manager_id)
        fixtures.append(
            {
                "home": home,
                "away": away,
                "home_points": match.home_points,
                "away_points": match.away_points,
                "result": match.result,
            }
        )
    return rows, fixtures
