"""League News — AI sports-chronicle editions per league × gameweek.

Fase 1: pack ranked facts → Gemini → persist ``LeagueNewsEdition``.
Empty ``settings.gemini_api_key`` disables the feature (no-op).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Gameweek,
    League,
    LeagueNewsEdition,
    Manager,
    ManagerGameweekScore,
    Player,
    PlayerPoints,
)

logger = logging.getLogger("squadforge.league_news")

GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
EDITION_POST = "post_gw"
EDITION_PRE = "pre_gw"
EDITION_FORECAST = "forecast"
TOP_STORIES_MIN = 5
TOP_STORIES_MAX = 8
FORECAST_CANDIDATES = 5

SYSTEM_PROMPT = """\
Sos el redactor de League News de FutFantasy: una liga privada de fantasy entre amigos.
Escribís como periodismo deportivo hispanoamericano de barra — tapa de Olé, radio mexicana
de fútbol, crónica de grupo de WhatsApp — en español natural. NO mezcles portugués ni
calques raros del brasileño.

TONO
- Jocoso, con humor negro y picante entre amigos. Podés bardear (sin insultos personales feos).
- Lenguaje oral argentino/mexicano que suene de verdad: "se mandó la cagada", "lo vendieron
  como pan caliente", "quedó en offside", "se fue al tacho", "está que arde", "no da más",
  "le llovieron las cargadas", "papelón", "se durmió en los postes", "figuritá difícil".
- PROHIBIDO calcar del portugués o traducir literal frases foráneas. Nada de "frango",
  "geada", "salvar la ropa", "escobazo" forzado, ni otras traducciones que suenen a Google
  Translate. Si no se dice así en español de verdad, no lo uses.
- Tampoco inventes jerga rara ni mezcles inglés tipo "bandwagon", "buzón" en sentido
  inventado, o palabras que no saldrían en una charla real entre amigos.
- Evitá palabras hinchadas de manual: "zarpazo", "catapultó", "trituró", "abismal",
  "impresionante marca", "sólida cosecha", "reclama el trono", "estratega de elite".
- Preferí algo que diría un amigo en el grupo después del partido.
- Nombres de managers/equipos: usalos tal cual vienen en los datos.

HECHOS (regla dura)
- Recibís un JSON de FACTS ya rankeados por drama (de más brutal a menos).
- NO inventes números, resultados, posiciones, counts de transfers ni puntajes.
- Solo redactá y dale color a lo que está en los facts. Respetá el orden exacto.

LARGO Y FORMA
- No alcanza con un titular + dos oraciones. Queremos crónica de verdad.
- "lede": 2–3 párrafos de apertura de la edición (escenario de la jornada, clima de la liga).
- Cada "body": 4–8 oraciones en 2–3 párrafos cortos. Contá la anécdota, el contexto del
  manager, y cerrá con un dardo o una frase memorable.
- "headline": corto, canchero, tipo tapa de Olé — no titular de banco.

Devolvé SOLO JSON válido (sin fences markdown) con esta forma:
{
  "title": "título de edición mencionando la GW",
  "kicker": "una línea de gancho, jocosa",
  "lede": "apertura larga en 2-3 párrafos separados por \\n\\n",
  "stories": [
    {
      "headline": "titular canchero",
      "body": "crónica larga en 2-3 párrafos separados por \\n\\n",
      "player_id": null o el integer del fact si hay jugador foco
    }
  ]
}

Una story por fact, en el mismo orden. player_id del fact si existe; si no, null.
"""


def news_enabled() -> bool:
    import os

    key = (settings.gemini_api_key or "").strip()
    if not key:
        key = (os.environ.get("GEMINI_API_KEY") or "").strip()
        if key:
            # Keep settings in sync if env arrived after import (rare) or Blueprint lag.
            try:
                settings.gemini_api_key = key
            except Exception:
                pass
    return bool(key)


def get_edition(
    db: Session,
    *,
    league_id: int | None,
    edition_type: str,
    gameweek_number: int,
) -> LeagueNewsEdition | None:
    q = db.query(LeagueNewsEdition).filter(
        LeagueNewsEdition.edition_type == edition_type,
        LeagueNewsEdition.gameweek_number == int(gameweek_number),
    )
    if league_id is None:
        q = q.filter(LeagueNewsEdition.league_id.is_(None))
    else:
        q = q.filter(LeagueNewsEdition.league_id == int(league_id))
    return q.one_or_none()


def get_or_generate_edition(
    db: Session,
    *,
    league: League | None,
    edition_type: str,
    gameweek_number: int,
    force: bool = False,
) -> dict[str, Any]:
    """Return existing edition or generate once. Never regenerate unless force=True.

    ``league`` may be None for global ``forecast`` editions.
    """
    if not news_enabled():
        return {"ok": False, "skipped": "no_api_key", "reason": "GEMINI_API_KEY empty"}

    league_id = int(league.id) if league is not None else None
    if edition_type == EDITION_FORECAST:
        league_id = None
    elif league is None:
        return {"ok": False, "skipped": "no_league", "reason": "league required"}

    existing = get_edition(
        db,
        league_id=league_id,
        edition_type=edition_type,
        gameweek_number=int(gameweek_number),
    )
    if existing is not None and not force:
        return {
            "ok": True,
            "cached": True,
            "edition": existing,
            "content": _loads(existing.content_json),
        }

    gw = db.query(Gameweek).filter(Gameweek.number == int(gameweek_number)).one_or_none()
    if gw is None:
        return {"ok": False, "skipped": "no_gameweek", "reason": f"GW{gameweek_number} missing"}

    if edition_type == EDITION_POST:
        assert league is not None
        package = build_post_gw_package(db, league, gw)
    elif edition_type == EDITION_PRE:
        assert league is not None
        package = build_pre_gw_package(db, league, gw)
    elif edition_type == EDITION_FORECAST:
        package = build_forecast_package(db, gw)
    else:
        return {"ok": False, "skipped": "bad_type", "reason": f"unknown edition_type={edition_type}"}

    if not package.get("stories"):
        return {"ok": False, "skipped": "no_stories", "reason": "no ranked facts to write"}

    try:
        content = call_gemini_for_edition(package)
    except Exception as exc:  # noqa: BLE001 — surface to caller, don't crash request cycle
        logger.exception("league_news gemini failed: %s", exc)
        return {"ok": False, "skipped": "api_error", "reason": str(exc)}

    if existing is not None and force:
        existing.content_json = json.dumps(content, ensure_ascii=False)
        existing.generated_at = datetime.utcnow()
        db.add(existing)
        db.commit()
        db.refresh(existing)
        row = existing
    else:
        row = LeagueNewsEdition(
            league_id=league_id,
            edition_type=edition_type,
            gameweek_number=int(gameweek_number),
            content_json=json.dumps(content, ensure_ascii=False),
            generated_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

    return {"ok": True, "cached": False, "edition": row, "content": content, "package": package}


# ── Fact packages + drama ranking ───────────────────────────────────────────


def build_post_gw_package(db: Session, league: League, gw: Gameweek) -> dict[str, Any]:
    """Structured post-GW facts, already sorted by drama (desc), top 5–8."""
    from app.services import awards as awards_svc
    from app.services import desk_side as desk_side_svc
    from app.services import standings as standings_svc

    candidates: list[dict[str, Any]] = []

    # Rank movers (and GW1 fallback: biggest haul / worst GW score)
    if (league.league_type or "classic") == "h2h":
        rows, _fixtures = standings_svc.h2h_standings(db, league, gw)
    else:
        rows = standings_svc.classic_standings(db, league, gw)
    any_rank_move = False
    for row in rows:
        delta = row.get("rank_delta")
        if delta is None:
            continue
        d = int(delta)
        if d == 0:
            continue
        any_rank_move = True
        mgr = row.get("manager")
        name = getattr(mgr, "display_name", None) or row.get("team_name") or "?"
        team = row.get("team_name") or getattr(mgr, "team_name", "") or ""
        candidates.append(
            {
                "kind": "rank_move",
                "drama": float(abs(d)),
                "player_id": None,
                "fact": {
                    "kind": "rank_move",
                    "manager_name": name,
                    "team_name": team,
                    "rank": row.get("rank"),
                    "prev_rank": row.get("prev_rank"),
                    "rank_delta": d,
                    "gw_points": row.get("gw_points"),
                    "direction": "up" if d > 0 else "down",
                },
            }
        )
    if not any_rank_move and rows:
        scored = sorted(
            rows,
            key=lambda r: float(r.get("gw_points") or 0),
            reverse=True,
        )
        for kind, row, drama_boost in (
            ("gw_leader", scored[0], 1.0),
            ("gw_lantern", scored[-1], 0.85),
        ):
            if row is None:
                continue
            mgr = row.get("manager")
            name = getattr(mgr, "display_name", None) or row.get("team_name") or "?"
            team = row.get("team_name") or getattr(mgr, "team_name", "") or ""
            pts = float(row.get("gw_points") or 0)
            candidates.append(
                {
                    "kind": kind,
                    "drama": max(1.0, abs(pts) * drama_boost),
                    "player_id": None,
                    "fact": {
                        "kind": kind,
                        "manager_name": name,
                        "team_name": team,
                        "rank": row.get("rank"),
                        "gw_points": pts,
                    },
                }
            )

    # Transfers most IN / OUT (News ignores the desk "min 4 managers" gate)
    from app.services.desk_side import _member_ids

    mids = _member_ids(db, int(league.id))
    xfers = _league_transfers_for_news(db, mids, int(gw.id), limit=5)
    if xfers:
        for row in xfers.get("most_in") or []:
            candidates.append(
                {
                    "kind": "transfer_in",
                    "drama": float(row.get("count") or 0),
                    "player_id": row.get("player_id"),
                    "fact": {
                        "kind": "transfer_in",
                        "player_id": row.get("player_id"),
                        "player_name": row.get("name"),
                        "count": row.get("count"),
                        "manager_count": xfers.get("manager_count"),
                    },
                }
            )
        for row in xfers.get("most_out") or []:
            candidates.append(
                {
                    "kind": "transfer_out",
                    "drama": float(row.get("count") or 0),
                    "player_id": row.get("player_id"),
                    "fact": {
                        "kind": "transfer_out",
                        "player_id": row.get("player_id"),
                        "player_name": row.get("name"),
                        "count": row.get("count"),
                        "manager_count": xfers.get("manager_count"),
                    },
                }
            )

    # Most picked XI + popular captain
    picked = desk_side_svc.league_most_picked_xi(
        db,
        league_id=int(league.id),
        gameweek_id=int(gw.id),
        gw_number=int(gw.number),
        limit=5,
    )
    if picked:
        top = picked[0]
        candidates.append(
            {
                "kind": "most_picked",
                "drama": float(top.get("count") or 0) * 0.5,
                "player_id": top.get("player_id"),
                "fact": {
                    "kind": "most_picked",
                    "player_id": top.get("player_id"),
                    "player_name": top.get("name"),
                    "count": top.get("count"),
                    "pct": top.get("pct"),
                    "rival": top.get("rival"),
                },
            }
        )
    cap = desk_side_svc.league_popular_captain(
        db,
        league_id=int(league.id),
        gameweek_id=int(gw.id),
        gw_number=int(gw.number),
    )
    if cap:
        candidates.append(
            {
                "kind": "popular_captain",
                "drama": float(cap.get("count") or 0) * 0.6,
                "player_id": cap.get("player_id"),
                "fact": {
                    "kind": "popular_captain",
                    "player_id": cap.get("player_id"),
                    "player_name": cap.get("name"),
                    "count": cap.get("count"),
                    "pct": cap.get("pct"),
                    "rival": cap.get("rival"),
                },
            }
        )

    # Season awards snapshot (context, mild drama)
    awards = awards_svc.league_awards(db, int(league.id))
    for cat in awards.get("categories") or []:
        if cat.get("empty"):
            continue
        candidates.append(
            {
                "kind": "award",
                "drama": 1.5,
                "player_id": None,
                "fact": {
                    "kind": "award",
                    "award_key": cat.get("key"),
                    "title": cat.get("title"),
                    "manager_name": None,
                    "team_name": cat.get("team_name"),
                    "value_label": cat.get("value_label"),
                    "detail": cat.get("detail"),
                    "manager_id": cat.get("manager_id"),
                },
            }
        )
        # Resolve manager display name
        mid = cat.get("manager_id")
        if mid:
            mgr = db.query(Manager).filter(Manager.id == int(mid)).one_or_none()
            if mgr:
                candidates[-1]["fact"]["manager_name"] = mgr.display_name

    # Per-manager best / worst vs that player's historical league average
    candidates.extend(_manager_player_swings(db, league, gw))

    ranked = _select_top_stories(candidates)
    return {
        "edition_type": EDITION_POST,
        "league_id": int(league.id),
        "league_name": league.name,
        "league_type": league.league_type or "classic",
        "gameweek_number": int(gw.number),
        "stories": ranked,
    }


def build_pre_gw_package(db: Session, league: League, gw: Gameweek) -> dict[str, Any]:
    """Pre-GW package: transfers trends + popular picks for the upcoming GW.

    Timing (when to generate) is Fase 2; this only builds the data pack.
    """
    from app.services import desk_side as desk_side_svc

    candidates: list[dict[str, Any]] = []
    xfers = desk_side_svc.league_top_transfers(
        db, league_id=int(league.id), gameweek_id=int(gw.id), limit=5
    )
    if xfers:
        for row in xfers.get("most_in") or []:
            candidates.append(
                {
                    "kind": "transfer_in",
                    "drama": float(row.get("count") or 0),
                    "player_id": row.get("player_id"),
                    "fact": {
                        "kind": "transfer_in",
                        "player_id": row.get("player_id"),
                        "player_name": row.get("name"),
                        "count": row.get("count"),
                    },
                }
            )
        for row in xfers.get("most_out") or []:
            candidates.append(
                {
                    "kind": "transfer_out",
                    "drama": float(row.get("count") or 0),
                    "player_id": row.get("player_id"),
                    "fact": {
                        "kind": "transfer_out",
                        "player_id": row.get("player_id"),
                        "player_name": row.get("name"),
                        "count": row.get("count"),
                    },
                }
            )

    picked = desk_side_svc.league_most_picked_xi(
        db,
        league_id=int(league.id),
        gameweek_id=int(gw.id),
        gw_number=int(gw.number),
        limit=5,
    )
    if picked:
        for i, row in enumerate(picked[:3]):
            candidates.append(
                {
                    "kind": "most_picked",
                    "drama": float(row.get("count") or 0) * (1.0 - 0.1 * i),
                    "player_id": row.get("player_id"),
                    "fact": {
                        "kind": "most_picked",
                        "player_id": row.get("player_id"),
                        "player_name": row.get("name"),
                        "count": row.get("count"),
                        "pct": row.get("pct"),
                    },
                }
            )
    cap = desk_side_svc.league_popular_captain(
        db,
        league_id=int(league.id),
        gameweek_id=int(gw.id),
        gw_number=int(gw.number),
    )
    if cap:
        candidates.append(
            {
                "kind": "popular_captain",
                "drama": float(cap.get("count") or 0),
                "player_id": cap.get("player_id"),
                "fact": {
                    "kind": "popular_captain",
                    "player_id": cap.get("player_id"),
                    "player_name": cap.get("name"),
                    "count": cap.get("count"),
                    "pct": cap.get("pct"),
                },
            }
        )

    ranked = _select_top_stories(candidates)
    return {
        "edition_type": EDITION_PRE,
        "league_id": int(league.id),
        "league_name": league.name,
        "league_type": league.league_type or "classic",
        "gameweek_number": int(gw.number),
        "stories": ranked,
    }


def build_forecast_package(db: Session, gw: Gameweek) -> dict[str, Any]:
    """Global next-GW forecast from real FDR + form/threat/creativity (not invented by AI)."""
    from app.services import fixtures as fixtures_svc

    fdr_by_club = fixtures_svc.club_next_fdr_map(db, from_gw=int(gw.number))
    players = (
        db.query(Player)
        .filter(Player.status.in_(("a", "d")))
        .all()
    )
    candidates: list[dict[str, Any]] = []
    for pl in players:
        club = (pl.team_code or "").upper()
        fdr = fdr_by_club.get(club) or {}
        if not fdr:
            continue
        # map_fdr: 1 easiest … 4 hardest — lower is better for attacking upside
        difficulty = int(fdr.get("difficulty") or 3)
        if difficulty > 2:
            continue
        stats = _loads(pl.season_stats_json or "{}")
        try:
            form = float(stats.get("form") or 0)
        except (TypeError, ValueError):
            form = 0.0
        threat = float(stats.get("threat") or 0)
        creativity = float(stats.get("creativity") or 0)
        # Favorable FDR weight + recent signal
        fdr_boost = {1: 3.0, 2: 1.75}.get(difficulty, 0.0)
        signal = fdr_boost * 8.0 + form * 4.0 + (threat + creativity) / 80.0
        if signal < 6.0:
            continue
        candidates.append(
            {
                "kind": "forecast_pick",
                "drama": round(signal, 2),
                "player_id": int(pl.id),
                "fact": {
                    "kind": "forecast_pick",
                    "player_id": int(pl.id),
                    "player_name": pl.name,
                    "position": pl.position,
                    "team_code": club,
                    "opponent": fdr.get("opponent"),
                    "venue": fdr.get("venue"),
                    "fdr": difficulty,
                    "form": round(form, 1),
                    "threat": round(threat, 1),
                    "creativity": round(creativity, 1),
                    "signal": round(signal, 2),
                    "gw": int(fdr.get("gw") or gw.number),
                },
            }
        )
    ranked = _select_top_stories(candidates)[:FORECAST_CANDIDATES]
    return {
        "edition_type": EDITION_FORECAST,
        "league_id": None,
        "league_name": "FORECAST",
        "league_type": "forecast",
        "gameweek_number": int(gw.number),
        "stories": ranked,
        "prompt_note": (
            "These are REAL next-GW candidates ranked by favorable FDR + form/threat/creativity. "
            "Write a Forecast edition — do not invent other players or numbers."
        ),
    }


def _league_transfers_for_news(
    db: Session, manager_ids: list[int], gameweek_id: int, *, limit: int = 5
) -> dict[str, Any] | None:
    """Most IN/OUT for News — works even with small leagues (desk UI needs 4+)."""
    from sqlalchemy import func

    from app.models import TransferLog

    mids = [int(m) for m in manager_ids]
    if not mids:
        return None
    ins = (
        db.query(TransferLog.player_in_id, func.count().label("n"))
        .filter(TransferLog.gameweek_id == gameweek_id, TransferLog.manager_id.in_(mids))
        .group_by(TransferLog.player_in_id)
        .order_by(func.count().desc(), TransferLog.player_in_id.asc())
        .limit(limit)
        .all()
    )
    outs = (
        db.query(TransferLog.player_out_id, func.count().label("n"))
        .filter(TransferLog.gameweek_id == gameweek_id, TransferLog.manager_id.in_(mids))
        .group_by(TransferLog.player_out_id)
        .order_by(func.count().desc(), TransferLog.player_out_id.asc())
        .limit(limit)
        .all()
    )
    pids = {int(r[0]) for r in ins if r[0]} | {int(r[0]) for r in outs if r[0]}
    names: dict[int, str] = {}
    if pids:
        for row in db.query(Player.id, Player.name).filter(Player.id.in_(pids)).all():
            names[int(row[0])] = row[1]

    def _rows(raw: list) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for pid, n in raw:
            if not pid or not n:
                continue
            out.append(
                {"player_id": int(pid), "name": names.get(int(pid), f"#{pid}"), "count": int(n)}
            )
        return out

    most_in, most_out = _rows(ins), _rows(outs)
    if not most_in and not most_out:
        return None
    return {"most_in": most_in, "most_out": most_out, "manager_count": len(mids)}


def _manager_player_swings(db: Session, league: League, gw: Gameweek) -> list[dict[str, Any]]:
    """Best / worst XI player vs historical avg — or absolute pts on GW1."""
    from app.services.desk_side import _member_ids
    from app.services.standings import _parse_breakdown

    mids = _member_ids(db, int(league.id))
    if not mids:
        return []

    hist = _player_historical_averages(db, before_gw_number=int(gw.number))
    out: list[dict[str, Any]] = []

    scores = (
        db.query(ManagerGameweekScore)
        .filter(
            ManagerGameweekScore.gameweek_id == int(gw.id),
            ManagerGameweekScore.manager_id.in_(mids),
        )
        .all()
    )
    managers = {
        int(m.id): m for m in db.query(Manager).filter(Manager.id.in_(mids)).all()
    }
    player_cache: dict[int, Player] = {}

    for score in scores:
        mgr = managers.get(int(score.manager_id))
        if mgr is None:
            continue
        players = _parse_breakdown(score.breakdown_json).get("players") or []
        best: tuple[float, dict] | None = None
        worst: tuple[float, dict] | None = None
        for line in players:
            if not isinstance(line, dict):
                continue
            if line.get("bench") and not line.get("autosub") and not line.get("super_sub"):
                if not line.get("bench_boost"):
                    continue
            pid = line.get("player_id")
            if pid is None:
                continue
            pid_i = int(pid)
            gw_pts = float(
                line.get("base") if line.get("base") is not None else line.get("points") or 0
            )
            avg = hist.get(pid_i)
            if avg is None:
                # First GW / no history: score by absolute haul or blank.
                payload = {
                    "player_id": pid_i,
                    "gw_points": round(gw_pts, 1),
                    "historical_avg": None,
                    "delta": round(gw_pts, 1),
                }
                if best is None or gw_pts > best[0]:
                    best = (gw_pts, payload)
                if worst is None or gw_pts < worst[0]:
                    worst = (gw_pts, payload)
                continue
            delta = gw_pts - float(avg)
            payload = {
                "player_id": pid_i,
                "gw_points": round(gw_pts, 1),
                "historical_avg": round(float(avg), 1),
                "delta": round(delta, 1),
            }
            if best is None or delta > best[0]:
                best = (delta, payload)
            if worst is None or delta < worst[0]:
                worst = (delta, payload)

        for label, hit, min_abs in (("broke_out", best, 2.0), ("blew_up", worst, 2.0)):
            if hit is None:
                continue
            score_val, payload = hit
            # Absolute mode (no hist): haul needs ≥6, blank ≤2
            if payload.get("historical_avg") is None:
                if label == "broke_out" and float(payload["gw_points"]) < 6.0:
                    continue
                if label == "blew_up" and float(payload["gw_points"]) > 2.0:
                    continue
                drama = float(payload["gw_points"]) if label == "broke_out" else (
                    6.0 - float(payload["gw_points"])
                )
            else:
                if abs(float(payload["delta"])) < min_abs:
                    continue
                drama = float(abs(payload["delta"]))
            pid_i = int(payload["player_id"])
            pl = player_cache.get(pid_i)
            if pl is None:
                pl = db.query(Player).filter(Player.id == pid_i).one_or_none()
                if pl is not None:
                    player_cache[pid_i] = pl
            out.append(
                {
                    "kind": label,
                    "drama": max(1.0, drama),
                    "player_id": pid_i,
                    "fact": {
                        "kind": label,
                        "manager_name": mgr.display_name,
                        "team_name": mgr.team_name or "",
                        "player_id": pid_i,
                        "player_name": (pl.name if pl else f"#{pid_i}"),
                        "gw_points": payload["gw_points"],
                        "historical_avg": payload["historical_avg"],
                        "delta": payload["delta"],
                    },
                }
            )
    return out


def _player_historical_averages(
    db: Session, *, before_gw_number: int
) -> dict[int, float]:
    """Mean PlayerPoints.total per player across finished GWs before ``before_gw_number``."""
    formula = settings.formula_version
    prior = (
        db.query(Gameweek.id)
        .filter(Gameweek.number < int(before_gw_number))
        .all()
    )
    prior_ids = [int(r[0]) for r in prior]
    if not prior_ids:
        # First scored GW: use all available points for that player except current packing
        # falls back to empty → swings skipped. Use current season so far including none.
        return {}

    rows = (
        db.query(PlayerPoints.player_id, PlayerPoints.total)
        .filter(
            PlayerPoints.gameweek_id.in_(prior_ids),
            PlayerPoints.formula_version == formula,
        )
        .all()
    )
    buckets: dict[int, list[float]] = {}
    for pid, total in rows:
        buckets.setdefault(int(pid), []).append(float(total or 0))
    return {pid: sum(vals) / len(vals) for pid, vals in buckets.items() if vals}


def _select_top_stories(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort by drama desc, keep top 5–8, de-dupe near-identical stories."""
    ranked = sorted(candidates, key=lambda c: float(c.get("drama") or 0), reverse=True)
    seen: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for c in ranked:
        fact = c.get("fact") or {}
        kind = str(c.get("kind") or "")
        if kind in ("broke_out", "blew_up"):
            key: tuple = (kind, c.get("player_id"), fact.get("manager_name"))
        else:
            key = (kind, c.get("player_id"))
        if key in seen:
            continue
        seen.add(key)
        story = {
            "drama": round(float(c.get("drama") or 0), 2),
            "kind": kind,
            "player_id": c.get("player_id"),
        }
        for k, v in fact.items():
            if k == "kind":
                continue
            story[k] = v
        out.append(story)
        if len(out) >= TOP_STORIES_MAX:
            break
    return out


# ── Gemini call ─────────────────────────────────────────────────────────────


def call_gemini_for_edition(package: dict[str, Any]) -> dict[str, Any]:
    key = (settings.gemini_api_key or "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY empty")

    user_payload = {
        "instruction": (
            "Write the League News edition from these drama-ranked facts. "
            "Keep the story order exactly as given (highest drama first)."
        ),
        "facts": package,
    }
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [
            {
                "role": "user",
                "parts": [{"text": json.dumps(user_payload, ensure_ascii=False)}],
            }
        ],
        "generationConfig": {
            "temperature": 0.85,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
        },
    }
    headers = {
        "x-goog-api-key": key,
        "content-type": "application/json",
    }
    with httpx.Client(timeout=90.0) as client:
        resp = client.post(GEMINI_URL, headers=headers, json=body)
        status = int(getattr(resp, "status_code", 0) or 0)
        if status >= 400:
            detail = (getattr(resp, "text", None) or "")[:500]
            raise RuntimeError(f"Gemini HTTP {status}: {detail}")
        data = resp.json()

    text = _extract_text(data)
    parsed = _parse_json_content(text)
    # Attach player_ids + drama/fact stats from ranked facts if model omitted them
    stories_in = package.get("stories") or []
    stories_out = parsed.get("stories") or []
    fact_keys = (
        "drama",
        "kind",
        "gw_points",
        "rank",
        "prev_rank",
        "rank_delta",
        "count",
        "pct",
        "delta",
        "form",
        "threat",
        "creativity",
        "signal",
        "fdr",
        "opponent",
        "venue",
        "team_code",
        "position",
        "manager_name",
        "team_name",
        "player_name",
    )
    for i, story in enumerate(stories_out):
        if not isinstance(story, dict):
            continue
        src = stories_in[i] if i < len(stories_in) else {}
        if story.get("player_id") is None and src.get("player_id") is not None:
            story["player_id"] = src.get("player_id")
        for k in fact_keys:
            if story.get(k) is None and src.get(k) is not None:
                story[k] = src.get(k)
        # Prefer package drama order as authority
        if src.get("drama") is not None:
            story["drama"] = src.get("drama")
        if src.get("kind"):
            story["kind"] = src.get("kind")
    parsed["stories"] = stories_out
    parsed["edition_type"] = package.get("edition_type")
    parsed["gameweek_number"] = package.get("gameweek_number")
    parsed["league_id"] = package.get("league_id")
    return parsed


def _extract_text(data: dict[str, Any]) -> str:
    """Pull plain text from a Gemini generateContent response."""
    candidates = data.get("candidates") or []
    parts_out: list[str] = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        content = cand.get("content") or {}
        for part in content.get("parts") or []:
            if isinstance(part, dict) and part.get("text"):
                parts_out.append(str(part["text"]))
    return "\n".join(parts_out).strip()


def _parse_json_content(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty Gemini response")
    # Strip accidental markdown fences
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Try to find first {...} blob
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("Gemini JSON root must be an object")
    if "stories" not in data or not isinstance(data["stories"], list):
        raise ValueError("Gemini JSON missing stories list")
    return data


def _loads(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


# ── Fase 2: timing ──────────────────────────────────────────────────────────


def all_fixtures_finished(db: Session, gw: Gameweek) -> bool:
    """True when every Fixture for this GW is finished (or GW marked finished)."""
    from app.models import Fixture

    flags = (
        db.query(Fixture.finished)
        .filter(Fixture.gameweek_number == int(gw.number))
        .all()
    )
    if flags:
        return all(int(row[0] or 0) == 1 for row in flags)
    return (gw.status or "").lower() == "finished"


def gw_ready_for_post(db: Session, gw: Gameweek) -> bool:
    """Post-GW news can run once the jornada is done in practice.

    Covers: all fixtures finished, GW status finished, or the season has
    already advanced past this GW (scores exist even if a fixture flag lagged).
    """
    if (gw.status or "").lower() == "finished":
        return True
    if all_fixtures_finished(db, gw):
        return True
    current = (
        db.query(Gameweek)
        .filter(Gameweek.is_current == 1)
        .order_by(Gameweek.number.desc())
        .first()
    )
    if current is not None and int(current.number) > int(gw.number):
        return True
    return False


def pre_gw_window_open(gw: Gameweek, *, now: datetime | None = None, hours: float = 48.0) -> bool:
    """True from (deadline − hours) until the GW is finished (pre stays current until post)."""
    from app.services import deadline as deadline_svc

    if (gw.status or "").lower() == "finished":
        return False
    dl = deadline_svc.parse_deadline(gw)
    if not dl:
        return False
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    from datetime import timedelta

    return now >= (dl - timedelta(hours=hours))


def maybe_generate_due_editions(db: Session) -> dict[str, Any]:
    """Generate post_gw / pre_gw / forecast editions when timing rules say so.

    - post_gw: once the GW is done (finished fixtures / status / advanced past)
    - pre_gw: once we are inside the 48h window before that GW's deadline
    - forecast: global, once pre window is open for that GW (same timing as pre)
    Idempotent via get_or_generate_edition (no re-spend if row exists).
    """
    if not news_enabled():
        return {"ok": False, "skipped": "no_api_key"}

    leagues = db.query(League).all()
    if not leagues:
        return {"ok": True, "leagues": 0, "generated": []}

    gws = db.query(Gameweek).order_by(Gameweek.number.asc()).all()
    generated: list[dict[str, Any]] = []

    for gw in gws:
        if gw_ready_for_post(db, gw):
            for league in leagues:
                result = get_or_generate_edition(
                    db,
                    league=league,
                    edition_type=EDITION_POST,
                    gameweek_number=int(gw.number),
                )
                if result.get("ok") and not result.get("cached"):
                    generated.append(
                        {
                            "league_id": int(league.id),
                            "type": EDITION_POST,
                            "gw": int(gw.number),
                        }
                    )
                elif not result.get("ok") and result.get("skipped") not in (
                    "no_stories",
                    "no_api_key",
                ):
                    logger.info(
                        "league_news post GW%s league=%s skipped=%s reason=%s",
                        gw.number,
                        league.id,
                        result.get("skipped"),
                        result.get("reason"),
                    )

        if pre_gw_window_open(gw):
            for league in leagues:
                result = get_or_generate_edition(
                    db,
                    league=league,
                    edition_type=EDITION_PRE,
                    gameweek_number=int(gw.number),
                )
                if result.get("ok") and not result.get("cached"):
                    generated.append(
                        {
                            "league_id": int(league.id),
                            "type": EDITION_PRE,
                            "gw": int(gw.number),
                        }
                    )
            # Global Forecast once per GW (not per league)
            fc = get_or_generate_edition(
                db,
                league=None,
                edition_type=EDITION_FORECAST,
                gameweek_number=int(gw.number),
            )
            if fc.get("ok") and not fc.get("cached"):
                generated.append(
                    {"league_id": None, "type": EDITION_FORECAST, "gw": int(gw.number)}
                )

    return {"ok": True, "leagues": len(leagues), "generated": generated}


def ensure_league_news(db: Session, league: League) -> dict[str, Any]:
    """Generate missing editions for one league (used on League page load).

    Prefer this over the global sweep so opening League with GW1 data already
    in the DB creates the post article without waiting for the daemon.
    """
    if not news_enabled():
        return {"ok": False, "skipped": "no_api_key", "reason": "GEMINI_API_KEY empty", "errors": []}

    generated: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    gws = db.query(Gameweek).order_by(Gameweek.number.asc()).all()
    for gw in gws:
        if gw_ready_for_post(db, gw):
            result = get_or_generate_edition(
                db,
                league=league,
                edition_type=EDITION_POST,
                gameweek_number=int(gw.number),
            )
            if result.get("ok") and not result.get("cached"):
                generated.append({"type": EDITION_POST, "gw": int(gw.number)})
            elif not result.get("ok"):
                err = {
                    "type": EDITION_POST,
                    "gw": int(gw.number),
                    "skipped": result.get("skipped"),
                    "reason": result.get("reason"),
                }
                errors.append(err)
                logger.info(
                    "ensure_league_news post GW%s league=%s skipped=%s reason=%s",
                    gw.number,
                    league.id,
                    result.get("skipped"),
                    result.get("reason"),
                )
        if pre_gw_window_open(gw):
            result = get_or_generate_edition(
                db,
                league=league,
                edition_type=EDITION_PRE,
                gameweek_number=int(gw.number),
            )
            if result.get("ok") and not result.get("cached"):
                generated.append({"type": EDITION_PRE, "gw": int(gw.number)})
            elif not result.get("ok"):
                errors.append(
                    {
                        "type": EDITION_PRE,
                        "gw": int(gw.number),
                        "skipped": result.get("skipped"),
                        "reason": result.get("reason"),
                    }
                )
    return {"ok": True, "generated": generated, "errors": errors}


def resolve_current_edition(db: Session, league: League) -> dict[str, Any] | None:
    """Pick the latest edition for one league (legacy helper; News tab uses feed)."""
    gws = db.query(Gameweek).order_by(Gameweek.number.desc()).all()
    for gw in gws:
        post = get_edition(
            db,
            league_id=int(league.id),
            edition_type=EDITION_POST,
            gameweek_number=int(gw.number),
        )
        pre = get_edition(
            db,
            league_id=int(league.id),
            edition_type=EDITION_PRE,
            gameweek_number=int(gw.number),
        )
        if post is not None:
            return _edition_view(db, post)
        if pre is not None and pre_gw_window_open(gw):
            return _edition_view(db, pre)

    row = (
        db.query(LeagueNewsEdition)
        .filter(LeagueNewsEdition.league_id == int(league.id))
        .order_by(
            LeagueNewsEdition.gameweek_number.desc(),
            LeagueNewsEdition.generated_at.desc(),
        )
        .first()
    )
    if row is None:
        return None
    return _edition_view(db, row)


def _edition_view(db: Session, row: LeagueNewsEdition) -> dict[str, Any]:
    """Content dict + photo URLs for stories that carry a player_id."""
    from app.kits import kit_for

    content = _loads(row.content_json)
    stories = content.get("stories") or []
    enriched: list[dict[str, Any]] = []
    for story in stories:
        if not isinstance(story, dict):
            continue
        item = dict(story)
        pid = item.get("player_id")
        if pid:
            pl = db.query(Player).filter(Player.id == int(pid)).one_or_none()
            if pl is not None:
                kit = kit_for(None, photo=pl.photo or "", player_id=pl.id)
                item["photo"] = kit.get("photo")
                item["photo_fallback"] = kit.get("photoFallback")
                item["player_name"] = item.get("player_name") or pl.name
        enriched.append(item)
    content["stories"] = enriched
    content["edition_type"] = row.edition_type
    content["gameweek_number"] = row.gameweek_number
    content["generated_at"] = row.generated_at.isoformat() if row.generated_at else None
    content["league_id"] = row.league_id
    return content


def _story_summary(body: str | None, *, max_len: int = 140) -> str:
    text = " ".join((body or "").replace("\n", " ").split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _story_stat_chips(story: dict[str, Any]) -> list[dict[str, str]]:
    """Numeric chips for the detail sheet (real facts, not AI fluff)."""
    chips: list[dict[str, str]] = []
    if story.get("gw_points") is not None:
        chips.append({"label": "GW pts", "value": str(story.get("gw_points"))})
    if story.get("rank_delta") is not None:
        d = int(story.get("rank_delta") or 0)
        chips.append({"label": "Rank", "value": f"{'+' if d > 0 else ''}{d}"})
    if story.get("count") is not None:
        chips.append({"label": "Count", "value": str(story.get("count"))})
    if story.get("pct") is not None:
        chips.append({"label": "Pick %", "value": f"{story.get('pct')}%"})
    if story.get("form") is not None:
        chips.append({"label": "Form", "value": str(story.get("form"))})
    if story.get("fdr") is not None:
        chips.append({"label": "FDR", "value": str(story.get("fdr"))})
    if story.get("opponent"):
        venue = story.get("venue") or ""
        chips.append(
            {
                "label": "Next",
                "value": f"{story.get('opponent')} ({venue})" if venue else str(story.get("opponent")),
            }
        )
    if story.get("threat") is not None:
        chips.append({"label": "Threat", "value": str(story.get("threat"))})
    if story.get("creativity") is not None:
        chips.append({"label": "Creat", "value": str(story.get("creativity"))})
    if story.get("signal") is not None:
        chips.append({"label": "Signal", "value": str(story.get("signal"))})
    return chips


def build_manager_news_feed(db: Session, manager_id: int) -> dict[str, Any]:
    """Aggregate stories from all Classic + H2H leagues + global Forecast.

    Returns magazine payload: featured card + grid cards with league labels.
    """
    from app.services import league as league_svc
    from app.kits import kit_for

    leagues = league_svc.manager_leagues(db, int(manager_id))
    league_by_id = {int(lg.id): lg for lg in leagues}
    league_ids = list(league_by_id.keys())

    rows: list[LeagueNewsEdition] = []
    if league_ids:
        rows.extend(
            db.query(LeagueNewsEdition)
            .filter(LeagueNewsEdition.league_id.in_(league_ids))
            .order_by(
                LeagueNewsEdition.gameweek_number.desc(),
                LeagueNewsEdition.generated_at.desc(),
            )
            .all()
        )
    # Global forecast editions (league_id NULL)
    rows.extend(
        db.query(LeagueNewsEdition)
        .filter(
            LeagueNewsEdition.edition_type == EDITION_FORECAST,
            LeagueNewsEdition.league_id.is_(None),
        )
        .order_by(
            LeagueNewsEdition.gameweek_number.desc(),
            LeagueNewsEdition.generated_at.desc(),
        )
        .all()
    )

    cards: list[dict[str, Any]] = []
    for row in rows:
        content = _loads(row.content_json)
        stories = content.get("stories") or []
        is_forecast = row.edition_type == EDITION_FORECAST
        lg = league_by_id.get(int(row.league_id)) if row.league_id is not None else None
        if not is_forecast and lg is None:
            continue
        label = "FORECAST" if is_forecast else (lg.name if lg else "League")
        league_type = "forecast" if is_forecast else ((lg.league_type if lg else "classic") or "classic")
        filter_key = "forecast" if is_forecast else league_type
        generated = row.generated_at.isoformat() if row.generated_at else None
        for idx, story in enumerate(stories):
            if not isinstance(story, dict):
                continue
            headline = (story.get("headline") or "").strip()
            body = (story.get("body") or "").strip()
            if not headline and not body:
                continue
            drama = story.get("drama")
            if drama is None:
                drama = float(TOP_STORIES_MAX - idx)
            pid = story.get("player_id")
            photo = story.get("photo")
            photo_fallback = story.get("photo_fallback")
            player_name = story.get("player_name")
            if pid and not photo:
                pl = db.query(Player).filter(Player.id == int(pid)).one_or_none()
                if pl is not None:
                    kit = kit_for(None, photo=pl.photo or "", player_id=pl.id)
                    photo = kit.get("photo")
                    photo_fallback = kit.get("photoFallback")
                    player_name = player_name or pl.name
            card_id = f"{row.id}-{idx}"
            cards.append(
                {
                    "id": card_id,
                    "edition_id": int(row.id),
                    "story_index": idx,
                    "headline": headline or "Sin titular",
                    "summary": _story_summary(body),
                    "body": body,
                    "drama": float(drama or 0),
                    "label": label,
                    "league_id": int(lg.id) if lg else None,
                    "league_type": league_type,
                    "filter": filter_key,
                    "edition_type": row.edition_type,
                    "gameweek_number": int(row.gameweek_number),
                    "generated_at": generated,
                    "player_id": int(pid) if pid else None,
                    "player_name": player_name,
                    "photo": photo,
                    "photo_fallback": photo_fallback,
                    "stats": _story_stat_chips(story),
                    "kind": story.get("kind"),
                }
            )

    cards.sort(
        key=lambda c: (
            float(c.get("drama") or 0),
            int(c.get("gameweek_number") or 0),
            str(c.get("generated_at") or ""),
        ),
        reverse=True,
    )
    featured = cards[0] if cards else None
    grid = cards[1:] if len(cards) > 1 else []
    return {
        "enabled": news_enabled(),
        "featured": featured,
        "grid": grid,
        "cards": cards,
        "league_count": len(leagues),
    }


def ensure_manager_news(db: Session, manager_id: int) -> dict[str, Any]:
    """Kick due editions for every league the manager is in + global forecast."""
    from app.services import league as league_svc

    if not news_enabled():
        return {"ok": False, "skipped": "no_api_key", "generated": []}

    generated: list[dict[str, Any]] = []
    for league in league_svc.manager_leagues(db, int(manager_id)):
        result = ensure_league_news(db, league)
        generated.extend(result.get("generated") or [])

    for gw in db.query(Gameweek).order_by(Gameweek.number.asc()).all():
        if pre_gw_window_open(gw):
            fc = get_or_generate_edition(
                db,
                league=None,
                edition_type=EDITION_FORECAST,
                gameweek_number=int(gw.number),
            )
            if fc.get("ok") and not fc.get("cached"):
                generated.append({"type": EDITION_FORECAST, "gw": int(gw.number)})
    return {"ok": True, "generated": generated}