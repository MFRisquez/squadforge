"""Classic + Head-to-Head standings helpers (FPL-inspired)."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    ChipPlay,
    Gameweek,
    H2HMatch,
    League,
    Manager,
    ManagerGameweekScore,
    Membership,
    OwnedPlayer,
    Player,
    TechnicalDirectorPick,
    TransferLog,
    TransferState,
)
from app.services import squad as squad_svc


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


def gw_points_trend(db: Session, manager_id: int, last_n: int = 6) -> list[float]:
    """Last N scored gameweeks for a manager, oldest → newest (by gameweek_id)."""
    rows = (
        db.query(ManagerGameweekScore)
        .filter(ManagerGameweekScore.manager_id == manager_id)
        .order_by(ManagerGameweekScore.gameweek_id.desc())
        .limit(last_n)
        .all()
    )
    return [float(r.total or 0) for r in reversed(rows)]


def _trend_is_rising(values: list[float]) -> bool:
    """True when avg of last 3 GWs beats avg of the 3 before that."""
    if len(values) < 6:
        return False
    recent = values[-3:]
    previous = values[-6:-3]
    return (sum(recent) / 3) > (sum(previous) / 3)


def trend_polyline(values: list[float], width: float = 60, height: float = 20, pad: float = 2) -> str:
    """Min-max normalized SVG polyline points for a sparkline."""
    if len(values) < 2:
        return ""
    lo = min(values)
    hi = max(values)
    span = (hi - lo) or 1.0
    n = len(values)
    pts: list[str] = []
    for i, v in enumerate(values):
        x = pad + (width - 2 * pad) * (i / (n - 1))
        y = (height - pad) - (height - 2 * pad) * ((v - lo) / span)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def _rank_by_manager(
    entries: list[tuple[int, float, float, str]],
) -> dict[int, int]:
    """entries: (manager_id, total, gw_points, name). Returns manager_id -> rank."""
    ordered = sorted(entries, key=lambda e: (-e[1], -e[2], e[3]))
    return {mid: i for i, (mid, *_rest) in enumerate(ordered, start=1)}


def _trend_from_scores(scores_by_gw_id: dict[int, float], last_n: int = 6) -> list[float]:
    """Last N totals ordered by gameweek_id ascending (matches gw_points_trend)."""
    if not scores_by_gw_id:
        return []
    ordered_ids = sorted(scores_by_gw_id.keys())[-last_n:]
    return [float(scores_by_gw_id[gid]) for gid in ordered_ids]


def _batch_manager_row_bases(db: Session, managers: list[Manager], gw) -> list[dict]:
    """Build standings row bases for many managers with a handful of bulk queries."""
    from app.services.chips import CHIP_SHORT

    if not managers:
        return []

    manager_ids = [m.id for m in managers]

    # One pull of all scores for these managers (totals / form / trend / current GW).
    score_join_rows = (
        db.query(ManagerGameweekScore, Gameweek)
        .join(Gameweek, Gameweek.id == ManagerGameweekScore.gameweek_id)
        .filter(ManagerGameweekScore.manager_id.in_(manager_ids))
        .all()
    )
    scores_by_mgr_gw_id: dict[int, dict[int, float]] = defaultdict(dict)
    scores_by_mgr_number: dict[int, dict[int, float]] = defaultdict(dict)
    for score, gweek in score_join_rows:
        total = float(score.total or 0)
        scores_by_mgr_gw_id[score.manager_id][gweek.id] = total
        scores_by_mgr_number[score.manager_id][gweek.number] = total

    recent_gws = (
        db.query(Gameweek)
        .filter(Gameweek.number <= gw.number)
        .order_by(Gameweek.number.desc())
        .limit(5)
        .all()
    )
    recent_gws = list(reversed(recent_gws))

    transfer_counts = dict(
        db.query(TransferLog.manager_id, func.count(TransferLog.id))
        .filter(
            TransferLog.manager_id.in_(manager_ids),
            TransferLog.gameweek_id == gw.id,
        )
        .group_by(TransferLog.manager_id)
        .all()
    )

    chips_by_mgr = {
        c.manager_id: c
        for c in db.query(ChipPlay)
        .filter(ChipPlay.manager_id.in_(manager_ids), ChipPlay.gameweek_id == gw.id)
        .all()
    }

    ft_by_mgr = {
        s.manager_id: s
        for s in db.query(TransferState).filter(TransferState.manager_id.in_(manager_ids)).all()
    }

    td_by_mgr = {
        p.manager_id: p
        for p in db.query(TechnicalDirectorPick)
        .filter(
            TechnicalDirectorPick.manager_id.in_(manager_ids),
            TechnicalDirectorPick.start_gw <= gw.number,
            TechnicalDirectorPick.end_gw >= gw.number,
        )
        .all()
    }

    owned_links = (
        db.query(OwnedPlayer).filter(OwnedPlayer.manager_id.in_(manager_ids)).all()
    )
    player_ids = {row.player_id for row in owned_links}
    players_by_id: dict[int, Player] = {}
    if player_ids:
        players_by_id = {
            p.id: p for p in db.query(Player).filter(Player.id.in_(player_ids)).all()
        }
    owned_by_mgr: dict[int, list[Player]] = defaultdict(list)
    for link in owned_links:
        player = players_by_id.get(link.player_id)
        if player:
            owned_by_mgr[link.manager_id].append(player)

    rows: list[dict] = []
    for manager in managers:
        mid = manager.id
        by_number = scores_by_mgr_number.get(mid, {})
        by_gw_id = scores_by_mgr_gw_id.get(mid, {})
        owned = owned_by_mgr.get(mid, [])
        spend = squad_svc.squad_spend(owned)
        gw_points = float(by_gw_id.get(gw.id, 0.0))
        total_points = float(sum(v for n, v in by_number.items() if n <= gw.number))

        form_parts: list[str] = []
        for rg in recent_gws:
            rs = by_gw_id.get(rg.id)
            form_parts.append(str(int(rs)) if rs is not None else "–")
        form = "·".join(form_parts) if form_parts else "—"

        chip = chips_by_mgr.get(mid)
        chip_key = chip.chip if chip else None
        td = td_by_mgr.get(mid)
        ft_state = ft_by_mgr.get(mid)
        trend = _trend_from_scores(by_gw_id, last_n=6)

        rows.append(
            {
                "manager": manager,
                "team_name": (manager.team_name or "").strip() or "—",
                "gw_points": gw_points,
                "total_points": total_points,
                "squad_value": spend,
                "transfers": int(transfer_counts.get(mid, 0)),
                "chip": CHIP_SHORT.get(chip_key, "—") if chip_key else "—",
                "chip_key": chip_key,
                "td_club": td.club_code if td else "—",
                "ft_left": ft_state.free_transfers if ft_state else 0,
                "players_owned": len(owned),
                "form": form,
                "trend": trend,
                "trend_rising": _trend_is_rising(trend),
                "trend_polyline": trend_polyline(trend),
                # Used by classic_standings for prev-rank without extra queries.
                "_totals_by_number": by_number,
            }
        )
    return rows


def _manager_row_base(db: Session, manager: Manager, gw) -> dict:
    """Single-manager helper (tests / callers). Same fields as the batch path."""
    row = _batch_manager_row_bases(db, [manager], gw)[0]
    row.pop("_totals_by_number", None)
    return row


def classic_standings(db: Session, league: League, gw) -> list[dict]:
    members = db.query(Membership).filter(Membership.league_id == league.id).all()
    managers = [m.manager for m in members]
    rows = _batch_manager_row_bases(db, managers, gw)
    rows.sort(key=lambda r: (-r["total_points"], -r["gw_points"], r["manager"].display_name.lower()))
    for i, row in enumerate(rows, start=1):
        row["rank"] = i

    # Rank movement vs previous gameweek (FPL-style: ↑ climbed, ↓ dropped)
    prev_ranks: dict[int, int] = {}
    if gw.number > 1:
        prev_entries = []
        for row in rows:
            mid = row["manager"].id
            by_number = row.get("_totals_by_number") or {}
            prev_total = float(sum(v for n, v in by_number.items() if n <= gw.number - 1))
            prev_entries.append(
                (mid, prev_total, 0.0, row["manager"].display_name.lower())
            )
        prev_ranks = _rank_by_manager(prev_entries)

    for row in rows:
        row.pop("_totals_by_number", None)
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
    base_rows = _batch_manager_row_bases(db, members, gw)
    stats = {}
    for base in base_rows:
        base.pop("_totals_by_number", None)
        mid = base["manager"].id
        stats[mid] = {
            **base,
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "h2h_points": 0,
            "pf": 0.0,
            "pa": 0.0,
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


def my_rank_in_league(
    db: Session,
    league: League,
    manager_id: int,
    gw,
) -> tuple[int | None, int]:
    """Return (rank, member_count) for one manager using the same standings path."""
    if getattr(league, "league_type", "classic") == "h2h":
        rows, _ = h2h_standings(db, league, gw)
    else:
        rows = classic_standings(db, league, gw)
    n = len(rows)
    for row in rows:
        if row["manager"].id == manager_id:
            return int(row["rank"]), n
    return None, n


def _rank_polyline(
    ranks: list[int],
    *,
    max_rank: int,
    width: float = 360,
    height: float = 140,
    pad: float = 10,
) -> str:
    """SVG polyline for rank-over-time. Rank 1 sits at the top of the chart."""
    pts = _rank_points(ranks, max_rank=max_rank, width=width, height=height, pad=pad)
    return " ".join(f"{p['x']:.1f},{p['y']:.1f}" for p in pts)


def _rank_points(
    ranks: list[int],
    *,
    max_rank: int,
    width: float = 360,
    height: float = 140,
    pad: float = 10,
) -> list[dict]:
    """SVG point coords for rank-over-time. Rank 1 sits at the top of the chart."""
    if len(ranks) < 2 or max_rank < 1:
        return []
    n = len(ranks)
    span = float(max(1, max_rank - 1))
    pts: list[dict] = []
    for i, rank in enumerate(ranks):
        x = pad + (width - 2 * pad) * (i / (n - 1))
        y = pad + (height - 2 * pad) * ((float(rank) - 1.0) / span)
        pts.append({"x": round(x, 1), "y": round(y, 1), "rank": int(rank)})
    return pts


# Distinct strokes for timeline lines (avoid purple/indigo cluster).
_TIMELINE_COLORS = (
    "#1a1a1a",
    "#c45c26",
    "#1f7a4d",
    "#1d5f8a",
    "#b08900",
    "#8b3a3a",
    "#2f6f6f",
    "#5c4a2a",
)


def rank_history(db: Session, league: League, through_gw) -> dict:
    """Cumulative classic ranks for each scored GW up to ``through_gw``.

    One batch ``ManagerGameweekScore`` query (same idea as ``classic_standings``).

    Returns::
      {
        "gameweeks": [1, 2, 3, ...],
        "managers": [{"name": "...", "ranks": [3, 2, 2, 1, ...], "manager_id": ...}, ...]
      }
    """
    members = db.query(Membership).filter(Membership.league_id == league.id).all()
    managers = [m.manager for m in members]
    empty = {"gameweeks": [], "managers": []}
    if not managers or through_gw is None:
        return empty

    through_n = int(getattr(through_gw, "number", through_gw))
    manager_ids = [m.id for m in managers]
    score_rows = (
        db.query(ManagerGameweekScore, Gameweek)
        .join(Gameweek, Gameweek.id == ManagerGameweekScore.gameweek_id)
        .filter(
            ManagerGameweekScore.manager_id.in_(manager_ids),
            Gameweek.number <= through_n,
        )
        .all()
    )
    by_mgr_number: dict[int, dict[int, float]] = defaultdict(dict)
    gw_numbers_set: set[int] = set()
    for score, gweek in score_rows:
        by_mgr_number[score.manager_id][gweek.number] = float(score.total or 0)
        gw_numbers_set.add(gweek.number)

    gameweeks = sorted(gw_numbers_set)
    if not gameweeks:
        return empty

    ranks_by_mgr: dict[int, list[int]] = {m.id: [] for m in managers}
    for n in gameweeks:
        entries = []
        for manager in managers:
            by_n = by_mgr_number.get(manager.id, {})
            cum = float(sum(v for gn, v in by_n.items() if gn <= n))
            gw_pts = float(by_n.get(n, 0.0))
            entries.append((manager.id, cum, gw_pts, manager.display_name.lower()))
        ranks = _rank_by_manager(entries)
        for mid in ranks_by_mgr:
            ranks_by_mgr[mid].append(int(ranks[mid]))

    # Current rank ascending, then name — stable chart legend order
    current_rank = {mid: ranks[-1] for mid, ranks in ranks_by_mgr.items() if ranks}
    ordered = sorted(
        managers,
        key=lambda m: (current_rank.get(m.id, 999), m.display_name.lower()),
    )
    return {
        "gameweeks": gameweeks,
        "managers": [
            {
                "manager_id": m.id,
                "name": (m.team_name or "").strip() or m.display_name,
                "ranks": ranks_by_mgr[m.id],
            }
            for m in ordered
        ],
    }


def classic_rank_history(
    db: Session,
    league: League,
    through_gw,
    *,
    me_id: int | None = None,
) -> dict:
    """GW-by-GW classic ranks + SVG geometry for the league timeline chart.

    Built on ``rank_history`` (batch score query). Rank 1 is drawn at the top.
    """
    raw = rank_history(db, league, through_gw)
    gameweeks = raw["gameweeks"]
    managers_raw = raw["managers"]
    max_rank = len(managers_raw)
    if not gameweeks or not managers_raw:
        return {
            "gw_numbers": [],
            "series": [],
            "max_rank": max_rank,
            "gw_labels": [],
            "grid": [],
            "chart_width": 360,
            "chart_height": 140,
        }

    chart_width = 360.0
    chart_height = 140.0
    pad = 10.0
    span = float(max(1, max_rank - 1))
    grid = []
    for tick in range(1, max_rank + 1):
        y = pad + (chart_height - 2 * pad) * ((float(tick) - 1.0) / span)
        grid.append({"rank": tick, "y": round(y, 1)})
    gw_labels = []
    n_gw = len(gameweeks)
    for i, n in enumerate(gameweeks):
        x = pad if n_gw == 1 else pad + (chart_width - 2 * pad) * (i / (n_gw - 1))
        gw_labels.append({"number": n, "x": round(x, 1)})

    # Viewer first for stroke emphasis, then keep rank_history order
    ordered = sorted(
        managers_raw,
        key=lambda m: (
            0 if me_id is not None and m["manager_id"] == me_id else 1,
            m["ranks"][-1] if m["ranks"] else 999,
            m["name"].lower(),
        ),
    )

    series = []
    for i, manager in enumerate(ordered):
        ranks = manager["ranks"]
        color = _TIMELINE_COLORS[i % len(_TIMELINE_COLORS)]
        if me_id is not None and manager["manager_id"] == me_id:
            color = "#111111"
        pts = _rank_points(
            ranks, max_rank=max_rank, width=chart_width, height=chart_height, pad=pad
        )
        points = []
        for j, pt in enumerate(pts):
            gw_n = gameweeks[j]
            points.append(
                {
                    **pt,
                    "gw": gw_n,
                    "title": f"{manager['name']} · GW{gw_n} · #{pt['rank']}",
                }
            )
        series.append(
            {
                "manager_id": manager["manager_id"],
                "team_name": manager["name"],
                "is_me": me_id is not None and manager["manager_id"] == me_id,
                "color": color,
                "ranks": ranks,
                "polyline": _rank_polyline(
                    ranks, max_rank=max_rank, width=chart_width, height=chart_height, pad=pad
                ),
                "points": points,
            }
        )
    return {
        "gw_numbers": gameweeks,
        "gw_labels": gw_labels,
        "grid": grid,
        "series": series,
        "max_rank": max_rank,
        "chart_width": int(chart_width),
        "chart_height": int(chart_height),
    }
