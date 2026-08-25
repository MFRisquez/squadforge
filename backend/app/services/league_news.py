"""League News — AI sports-chronicle editions per league × gameweek.

Fase 1: pack ranked facts → Gemini → persist ``LeagueNewsEdition``.
Empty ``settings.gemini_api_key`` disables the feature (no-op).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
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
TOP_STORIES_MIN = 5
TOP_STORIES_MAX = 8

SYSTEM_PROMPT = """\
You are the League News desk for FutFantasy — a private friends fantasy football league.

You receive a JSON package of FACTS already ranked by drama score (highest first).
Your job is ONLY to write — never invent numbers, results, rank moves, transfer counts,
player scores, or events that are not in the facts. You may add colour, wit, and
sports-chronicle flair around the given facts. Use the real manager names and team names.

Write in Spanish (LatAm-friendly sports Spanish), unless a name is English — keep names as-is.

Respect the given order of stories exactly (most brutal → least brutal). Do not reorder.

Return ONLY valid JSON (no markdown fences) with this shape:
{
  "title": "short edition title mentioning the GW",
  "kicker": "one-line teaser",
  "stories": [
    {
      "headline": "punchy headline",
      "body": "2-4 sentences of chronicle",
      "player_id": null or integer from the fact (when a specific player is the focus)
    }
  ]
}

Include one story object per ranked fact, in the same order. Set player_id from the fact
when present; otherwise null.
"""


def news_enabled() -> bool:
    return bool((settings.gemini_api_key or "").strip())


def get_edition(
    db: Session,
    *,
    league_id: int,
    edition_type: str,
    gameweek_number: int,
) -> LeagueNewsEdition | None:
    return (
        db.query(LeagueNewsEdition)
        .filter(
            LeagueNewsEdition.league_id == int(league_id),
            LeagueNewsEdition.edition_type == edition_type,
            LeagueNewsEdition.gameweek_number == int(gameweek_number),
        )
        .one_or_none()
    )


def get_or_generate_edition(
    db: Session,
    *,
    league: League,
    edition_type: str,
    gameweek_number: int,
    force: bool = False,
) -> dict[str, Any]:
    """Return existing edition or generate once. Never regenerate unless force=True.

    Returns a dict suitable for API/UI:
      {ok, skipped?, reason?, edition?, content?}
    """
    if not news_enabled():
        return {"ok": False, "skipped": "no_api_key", "reason": "GEMINI_API_KEY empty"}

    existing = get_edition(
        db,
        league_id=int(league.id),
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
        package = build_post_gw_package(db, league, gw)
    elif edition_type == EDITION_PRE:
        package = build_pre_gw_package(db, league, gw)
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
            league_id=int(league.id),
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

    # Rank movers
    if (league.league_type or "classic") == "h2h":
        rows, _fixtures = standings_svc.h2h_standings(db, league, gw)
    else:
        rows = standings_svc.classic_standings(db, league, gw)
    for row in rows:
        delta = row.get("rank_delta")
        if delta is None:
            continue
        d = int(delta)
        if d == 0:
            continue
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

    # Transfers most IN / OUT
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


def _manager_player_swings(db: Session, league: League, gw: Gameweek) -> list[dict[str, Any]]:
    """Best / worst XI player vs that player's historical SquadForge GW average."""
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
        int(m.id): m
        for m in db.query(Manager).filter(Manager.id.in_(mids)).all()
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
            # Prefer raw player performance (base); fall back to credited points.
            if line.get("bench") and not line.get("autosub") and not line.get("super_sub"):
                if line.get("bench_boost"):
                    pass
                else:
                    continue
            pid = line.get("player_id")
            if pid is None:
                continue
            pid_i = int(pid)
            gw_pts = float(line.get("base") if line.get("base") is not None else line.get("points") or 0)
            avg = hist.get(pid_i)
            if avg is None:
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

        for label, hit in (("broke_out", best), ("blew_up", worst)):
            if hit is None:
                continue
            delta, payload = hit
            # Skip tiny noise
            if abs(delta) < 2.0:
                continue
            pid_i = int(payload["player_id"])
            pl = player_cache.get(pid_i)
            if pl is None:
                pl = db.query(Player).filter(Player.id == pid_i).one_or_none()
                if pl is not None:
                    player_cache[pid_i] = pl
            out.append(
                {
                    "kind": label,
                    "drama": float(abs(delta)),
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
            "temperature": 0.7,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
        },
    }
    headers = {
        "x-goog-api-key": key,
        "content-type": "application/json",
    }
    with httpx.Client(timeout=90.0) as client:
        resp = client.post(GEMINI_URL, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

    text = _extract_text(data)
    parsed = _parse_json_content(text)
    # Attach player_ids from ranked facts if model omitted them
    stories_in = package.get("stories") or []
    stories_out = parsed.get("stories") or []
    for i, story in enumerate(stories_out):
        if not isinstance(story, dict):
            continue
        if story.get("player_id") is None and i < len(stories_in):
            story["player_id"] = stories_in[i].get("player_id")
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
