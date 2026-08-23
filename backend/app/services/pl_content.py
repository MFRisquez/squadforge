"""Premier League / FPL enrichment for fixture match sheets.

Team news comes from FPL bootstrap player `news` (synced into Player rows).
Venue + formations come from the public PulseLive football API that powers
premierleague.com. Possession / shots / passes come from the free sibling
endpoint ``GET /football/stats/match/{pulse_id}`` (not present on
``/fixtures/{id}`` itself).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.kits import photo_url
from app.models import Club, Fixture, Player
from app.services.fpl_sync import availability_flag

log = logging.getLogger(__name__)

PULSE_BASE = "https://footballapi.pulselive.com/football"
PULSE_HEADERS = {
    "User-Agent": "SquadForge/0.3 (private fantasy; contact local)",
    "Accept": "application/json",
    "Origin": "https://www.premierleague.com",
    "Referer": "https://www.premierleague.com/",
}

_STATUS_TITLE = {
    "i": "Injury update",
    "d": "Fitness doubt",
    "s": "Suspension",
    "u": "Squad update",
    "a": "Team news",
}

# Soft in-process cache so opening several match sheets stays snappy.
_season_cache: dict[str, Any] = {"id": None, "at": 0.0}
_fixture_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}

_GOAL_TEXT_RE = re.compile(
    r"Goal!\s*(?P<home>.+?)\s+(?P<hs>\d+),\s*(?P<away>.+?)\s+(?P<as_>\d+)\.\s*"
    r"(?P<player>.+?)\s*\((?P<club>[^)]+)\)",
    re.IGNORECASE,
)


def _http_get(url: str, *, params: dict | None = None, timeout: float = 8.0) -> Any | None:
    try:
        with httpx.Client(timeout=timeout, headers=PULSE_HEADERS, follow_redirects=True) as client:
            r = client.get(url, params=params)
            if r.status_code != 200:
                return None
            return r.json()
    except Exception as exc:  # noqa: BLE001 — network soft-fail for UI enrichment
        log.debug("PulseLive GET failed %s: %s", url, exc)
        return None


def current_comp_season_id() -> int | None:
    """Latest Premier League competition season id (PulseLive)."""
    import time

    now = time.time()
    if _season_cache["id"] and now - float(_season_cache["at"] or 0) < 3600:
        return int(_season_cache["id"])
    data = _http_get(f"{PULSE_BASE}/competitions/1/compseasons", params={"page": 0, "pageSize": 5})
    if not isinstance(data, dict):
        return None
    rows = data.get("content") or []
    if not rows:
        return None
    sid = int(rows[0].get("id") or 0) or None
    if sid:
        _season_cache["id"] = sid
        _season_cache["at"] = now
    return sid


def _kickoff_day(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return (iso or "")[:10] or None


def format_pulse_clock(clock: Any) -> str | None:
    """Turn Pulse ``clock`` into our display label (``67'``, ``90+7'``, ``MT``).

    Pulse uses labels like ``\"90+7'00\"`` (minute + seconds). We drop the
    trailing seconds so the UI matches FPL-style clocks.
    """
    if not isinstance(clock, dict):
        return None
    label = str(clock.get("label") or "").strip()
    if not label:
        return None
    upper = label.upper()
    if upper in {"FT", "FULL TIME"}:
        return "FT"
    if upper in {"HT", "HALF TIME", "MT"}:
        return "MT"
    # "90+7'00" / "45'00" / "67'" → strip optional two-digit seconds after '
    if "'" in label:
        head, _, tail = label.partition("'")
        head = head.strip()
        if head and (not tail or tail.strip().isdigit()):
            return f"{head}'"
        return f"{head}'" if head else None
    return label


def format_pulse_goal_minute(label: str | None) -> str | None:
    """``05`` / ``90+9`` / ``90+9'00`` → ``5'`` / ``90+9'``."""
    raw = str(label or "").strip()
    if not raw:
        return None
    if "'" in raw:
        raw = raw.split("'", 1)[0].strip()
    if re.fullmatch(r"\d+", raw):
        return f"{int(raw)}'"
    if re.fullmatch(r"\d+\+\d+", raw):
        return f"{raw}'"
    return f"{raw}'" if raw else None


def parse_pulse_textstream_goals(
    raw: dict[str, Any] | None,
    *,
    home_abbr: str,
    away_abbr: str,
) -> list[dict[str, Any]]:
    """Extract timed goals from Pulse Match Centre textstream."""
    if not isinstance(raw, dict):
        return []
    events = raw.get("events") if isinstance(raw.get("events"), dict) else raw
    content = (events or {}).get("content") if isinstance(events, dict) else None
    if not isinstance(content, list):
        return []
    home = (home_abbr or "").upper()
    away = (away_abbr or "").upper()
    out: list[dict[str, Any]] = []
    for row in content:
        if not isinstance(row, dict):
            continue
        typ = str(row.get("type") or "").lower()
        if "goal" not in typ:
            continue
        text = str(row.get("text") or "")
        m = _GOAL_TEXT_RE.search(text)
        if not m:
            continue
        player = (m.group("player") or "").strip()
        club = (m.group("club") or "").strip().upper()
        # Map club name / abbr in parentheses to home/away.
        side = None
        if home and (home in club or club.startswith(home) or home in club.replace(" ", "")):
            side = "home"
        elif away and (away in club or club.startswith(away) or away in club.replace(" ", "")):
            side = "away"
        else:
            # Fallback: compare against full names in the Goal! scoreline prefix.
            home_name = (m.group("home") or "").upper()
            away_name = (m.group("away") or "").upper()
            club_u = (m.group("club") or "").upper()
            if club_u and club_u in home_name:
                side = "home"
            elif club_u and club_u in away_name:
                side = "away"
        if side is None:
            continue
        minute = format_pulse_goal_minute(((row.get("time") or {}) if isinstance(row.get("time"), dict) else {}).get("label"))
        out.append(
            {
                "side": side,
                "name": player,
                "minute": minute,
                "own_goal": "own" in typ,
            }
        )
    return out


def fetch_pulse_goal_events(
    pulse_id: int,
    *,
    home_abbr: str,
    away_abbr: str,
) -> list[dict[str, Any]]:
    """Timed goals for a Pulse fixture (one textstream page, pageSize=200)."""
    if not pulse_id:
        return []
    raw = _http_get(
        f"{PULSE_BASE}/fixtures/{int(pulse_id)}/textstream/EN",
        params={"page": 0, "pageSize": 200},
        timeout=10.0,
    )
    return parse_pulse_textstream_goals(raw if isinstance(raw, dict) else None, home_abbr=home_abbr, away_abbr=away_abbr)


def resolve_pulse_fixture(
    *,
    home_abbr: str,
    away_abbr: str,
    kickoff_at: str | None,
) -> dict[str, Any] | None:
    """Find PulseLive fixture detail for a PL match (venue, formations, etc.)."""
    import time

    home = (home_abbr or "").upper()
    away = (away_abbr or "").upper()
    day = _kickoff_day(kickoff_at)
    cache_key = f"{home}-{away}-{day}"
    hit = _fixture_cache.get(cache_key)
    if hit:
        cached_at, cached_val = hit
        # Live matches need a short TTL so Match Centre clock stays fresh.
        ttl = 25.0
        if isinstance(cached_val, dict):
            st = str(cached_val.get("status") or "").upper()
            if st in {"C", "U", ""}:
                ttl = 600.0
        if time.time() - cached_at < ttl:
            return cached_val

    season = current_comp_season_id()
    if not season or not home or not away:
        _fixture_cache[cache_key] = (time.time(), None)
        return None

    listing = _http_get(
        f"{PULSE_BASE}/fixtures",
        params={
            "comps": 1,
            "compSeasons": season,
            "page": 0,
            "pageSize": 40,
            "sort": "asc",
            "statuses": "U,L,C",
        },
        timeout=10.0,
    )
    if not isinstance(listing, dict):
        _fixture_cache[cache_key] = (time.time(), None)
        return None

    def _row_match(row: dict[str, Any]) -> bool:
        teams = row.get("teams") or []
        if len(teams) < 2:
            return False
        abbrs = [
            ((((t or {}).get("team") or {}).get("club") or {}).get("abbr") or "").upper()
            for t in teams
        ]
        # Pulse lists home then away
        if abbrs[0] != home or abbrs[1] != away:
            return False
        if not day:
            return True
        millis = (row.get("kickoff") or {}).get("millis")
        if not millis:
            return True
        try:
            row_day = datetime.fromtimestamp(float(millis) / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
            return row_day == day
        except (TypeError, ValueError, OSError):
            return True

    # Scan early pages only (near-term GWs) — avoid walking all 380 fixtures.
    pages: list[dict[str, Any]] = [listing]
    for page in range(1, 3):
        more = _http_get(
            f"{PULSE_BASE}/fixtures",
            params={
                "comps": 1,
                "compSeasons": season,
                "page": page,
                "pageSize": 40,
                "sort": "asc",
                "statuses": "U,L,C",
            },
            timeout=8.0,
        )
        if isinstance(more, dict):
            pages.append(more)
        else:
            break

    pulse_id = None
    listing_clock: Any = None
    for block in pages:
        for row in block.get("content") or []:
            if _row_match(row):
                pulse_id = int(row.get("id") or 0) or None
                listing_clock = row.get("clock")
                break
        if pulse_id:
            break

    if not pulse_id:
        _fixture_cache[cache_key] = (time.time(), None)
        return None

    detail = _http_get(f"{PULSE_BASE}/fixtures/{pulse_id}", timeout=10.0)
    if not isinstance(detail, dict):
        _fixture_cache[cache_key] = (time.time(), None)
        return None

    ground = detail.get("ground") or {}
    formations: list[dict[str, Any]] = []
    for block in detail.get("teamLists") or []:
        if not isinstance(block, dict):
            continue
        form = block.get("formation") or {}
        label = (form.get("label") or "").strip()
        if not label:
            continue
        formations.append(
            {
                "team_id": block.get("teamId"),
                "formation": label,
            }
        )

    status = detail.get("status")
    clock_label = format_pulse_clock(detail.get("clock")) or format_pulse_clock(listing_clock)
    # Do NOT force FT just because Pulse status is C — that often flips during
    # stoppage while FPL is still provisional and late goals are landing.
    # Our estimate_match_clock(finished=True) still shows FT once FPL finishes.

    goals: list[dict[str, Any]] = []
    try:
        goals = fetch_pulse_goal_events(int(pulse_id), home_abbr=home, away_abbr=away)
    except Exception as exc:  # noqa: BLE001
        log.debug("Pulse goals fetch failed %s: %s", pulse_id, exc)

    out = {
        "pulse_id": pulse_id,
        "venue": (ground.get("name") or "").strip() or None,
        "city": (ground.get("city") or "").strip() or None,
        "formations": formations,
        "status": status,
        "clock": clock_label,
        "goals": goals,
    }
    _fixture_cache[cache_key] = (time.time(), out)
    return out


def club_team_news(db: Session, club_code: str, *, limit: int = 4) -> list[dict[str, Any]]:
    """Latest FPL team-news cards for a club (injuries, suspensions, moves)."""
    code = (club_code or "").upper()
    players = (
        db.query(Player)
        .filter(Player.team_code == code)
        .order_by(Player.name.asc())
        .all()
    )
    cards: list[dict[str, Any]] = []
    for p in players:
        body = (getattr(p, "news", "") or "").strip()
        if not body:
            continue
        status = (getattr(p, "status", "a") or "a").lower()
        avail = availability_flag(status, getattr(p, "chance_of_playing", None))
        kind = _STATUS_TITLE.get(status, "Team news")
        # Prefer the news headline before the em-dash detail when present.
        if " - " in body:
            headline, detail = body.split(" - ", 1)
            title = f"{p.name}: {headline.strip()}"
            text = detail.strip() or body
        else:
            title = f"{p.name}: {kind}"
            text = body
        cards.append(
            {
                "player_id": p.id,
                "player": p.name,
                "position": p.position,
                "title": title,
                "body": text,
                "photo": photo_url(getattr(p, "photo", None)),
                "availability": avail,
                "status": status,
                "kind": kind,
            }
        )
    # Out / doubt first, then by name
    rank = {"out": 0, "doubt": 1, "ok": 2}
    cards.sort(key=lambda c: (rank.get(c["availability"], 9), c["player"]))
    return cards[: max(0, limit)]


def match_preview_blurb(
    *,
    home_name: str,
    away_name: str,
    pulse: dict[str, Any] | None,
    home_news: list[dict[str, Any]],
    away_news: list[dict[str, Any]],
) -> dict[str, Any]:
    """Short pre-match tactics / context block for the sheet."""
    bits: list[str] = []
    venue = (pulse or {}).get("venue")
    city = (pulse or {}).get("city")
    if venue and city:
        bits.append(f"Kickoff at {venue}, {city}.")
    elif venue:
        bits.append(f"Kickoff at {venue}.")

    forms = (pulse or {}).get("formations") or []
    if len(forms) >= 2:
        bits.append(
            f"Expected shapes: {home_name} {forms[0].get('formation')} · "
            f"{away_name} {forms[1].get('formation')}."
        )
    elif len(forms) == 1:
        bits.append(f"Formation watch: {forms[0].get('formation')}.")
    else:
        bits.append("Official line-ups and formations appear closer to kickoff.")

    absences = []
    for side, rows in (("Home", home_news), ("Away", away_news)):
        names = [r["player"] for r in rows if r.get("availability") in {"out", "doubt"}][:2]
        if names:
            absences.append(f"{side} watch: {', '.join(names)}")
    if absences:
        bits.append(" ".join(absences) + ".")

    return {
        "title": f"{home_name} vs {away_name}",
        "body": " ".join(bits).strip(),
        "venue": venue,
        "city": city,
        "formations": forms,
        "image": None,  # reserved — badge collage handled in UI
    }


def fetch_pulse_match_stats(pulse_id: int) -> dict[str, Any] | None:
    """Team match stats from PulseLive (same free API as premierleague.com Match Centre).

    ``GET /football/stats/match/{pulse_id}`` — not included on ``/fixtures/{id}``.
    """
    if not pulse_id:
        return None
    raw = _http_get(f"{PULSE_BASE}/stats/match/{int(pulse_id)}", timeout=10.0)
    if not isinstance(raw, dict):
        return None
    return map_pulse_match_stats(raw)


def map_pulse_match_stats(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Map Pulse ``stats/match`` payload → fixture sheet ``team_stats`` shape."""
    entity = raw.get("entity") if isinstance(raw.get("entity"), dict) else {}
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    teams = entity.get("teams") or []
    if len(teams) < 2 or not data:
        return None

    def _team_id(block: dict[str, Any]) -> str | None:
        tid = ((block or {}).get("team") or {}).get("id")
        return str(int(tid)) if tid is not None else None

    home_id = _team_id(teams[0] if isinstance(teams[0], dict) else {})
    away_id = _team_id(teams[1] if isinstance(teams[1], dict) else {})
    if not home_id or not away_id:
        return None

    def _metrics(tid: str) -> dict[str, float]:
        block = data.get(tid) or data.get(str(tid)) or {}
        rows = block.get("M") if isinstance(block, dict) else None
        out: dict[str, float] = {}
        if not isinstance(rows, list):
            return out
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row.get("name")
            if not name:
                continue
            try:
                out[str(name)] = float(row.get("value") or 0)
            except (TypeError, ValueError):
                continue
        return out

    home = _metrics(home_id)
    away = _metrics(away_id)
    if not home and not away:
        return None

    def _pair(metric: str, *, as_pct: bool = False, as_int: bool = False) -> dict[str, Any]:
        hv = home.get(metric)
        av = away.get(metric)

        def fmt(v: float | None) -> Any:
            if v is None:
                return None
            if as_pct:
                # Match Centre style whole percent.
                return f"{int(round(float(v)))}%"
            if as_int:
                return int(round(float(v)))
            return float(v)

        return {"home": fmt(hv), "away": fmt(av)}

    def _attempts(side: dict[str, float]) -> float | None:
        if not side:
            return None
        if "attempts_ibox" in side or "attempts_obox" in side:
            return float(side.get("attempts_ibox") or 0) + float(side.get("attempts_obox") or 0)
        if "shot_created" in side:
            return float(side.get("shot_created") or 0)
        return None

    ha = _attempts(home)
    aa = _attempts(away)

    return {
        "source": "pulselive",
        "pulse_id": entity.get("id"),
        "possession": _pair("possession_percentage", as_pct=True),
        "shots_on_target": _pair("ontarget_scoring_att", as_int=True),
        "chances_created": {
            "home": int(round(ha)) if ha is not None else None,
            "away": int(round(aa)) if aa is not None else None,
        },
        "passes_accurate": _pair("accurate_pass", as_int=True),
        "duels_won": _pair("duel_won", as_int=True),
        "fouls": _pair("fk_foul_lost", as_int=True),
    }


def enrich_fixture_sheet(db: Session, fx: Fixture, payload: dict[str, Any]) -> dict[str, Any]:
    """Attach team news + PL preview + Pulse match stats onto a fixture payload."""
    home_code = fx.home_club_code
    away_code = fx.away_club_code
    home_news = club_team_news(db, home_code, limit=4)
    away_news = club_team_news(db, away_code, limit=4)
    pulse = resolve_pulse_fixture(
        home_abbr=home_code,
        away_abbr=away_code,
        kickoff_at=fx.kickoff_at,
    )
    home_name = (payload.get("home") or {}).get("name") or home_code
    away_name = (payload.get("away") or {}).get("name") or away_code
    preview = match_preview_blurb(
        home_name=home_name,
        away_name=away_name,
        pulse=pulse,
        home_news=home_news,
        away_news=away_news,
    )
    # Prefer club badges as visual anchors when we lack editorial imagery.
    if not preview.get("image"):
        preview["image_home"] = (payload.get("home") or {}).get("badge")
        preview["image_away"] = (payload.get("away") or {}).get("badge")
    payload["team_news"] = {"home": home_news, "away": away_news}
    payload["preview"] = preview
    payload["pulse"] = pulse
    team_stats = None
    team_stats_status = "unavailable"
    pulse_id = (pulse or {}).get("pulse_id") if isinstance(pulse, dict) else None
    if pulse_id:
        try:
            team_stats = fetch_pulse_match_stats(int(pulse_id))
            team_stats_status = "ok" if team_stats else "no_statistics"
        except Exception:  # noqa: BLE001
            team_stats = None
            team_stats_status = "error"
    payload["team_stats"] = team_stats
    payload["team_stats_status"] = team_stats_status
    return payload
