"""Resolve player headshots when the Premier League CDN is missing them.

Order: local cache → PL 250 → PL 110 → FotMob search (current club when possible).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from app.kits import photo_code, photo_fallback_url, photo_url
from app.models import Player

CACHE_DIR = Path(__file__).resolve().parent.parent / "web" / "static" / "player-photos"
FOTMOB_INDEX = CACHE_DIR / "fotmob_ids.json"
FOTMOB_SUGGEST = "https://apigw.fotmob.com/searchapi/suggest"
FOTMOB_IMG = "https://images.fotmob.com/image_resources/playerimages/{fid}.png"

_UA = "Mozilla/5.0 (compatible; SquadForge/1.0; +https://github.com/MFRisquez/squadforge)"

# Rough club hints so FotMob picks the right namesake.
TEAM_NAME_HINTS: dict[str, tuple[str, ...]] = {
    "ARS": ("Arsenal",),
    "AVL": ("Aston Villa", "Villa"),
    "BOU": ("Bournemouth",),
    "BRE": ("Brentford",),
    "BHA": ("Brighton",),
    "CHE": ("Chelsea",),
    "CRY": ("Crystal Palace", "Palace"),
    "EVE": ("Everton",),
    "FUL": ("Fulham",),
    "IPS": ("Ipswich",),
    "LEE": ("Leeds",),
    "LIV": ("Liverpool",),
    "MCI": ("Manchester City", "Man City"),
    "MUN": ("Manchester United", "Man Utd", "Man United"),
    "NEW": ("Newcastle",),
    "NFO": ("Nottingham Forest", "Nott'm Forest", "Forest"),
    "SOU": ("Southampton",),
    "TOT": ("Tottenham", "Spurs"),
    "SUN": ("Sunderland",),
    "WHU": ("West Ham",),
    "WOL": ("Wolves", "Wolverhampton"),
}


def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _load_fotmob_index() -> dict[str, str]:
    if not FOTMOB_INDEX.exists():
        return {}
    try:
        return json.loads(FOTMOB_INDEX.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_fotmob_index(index: dict[str, str]) -> None:
    _ensure_cache_dir()
    FOTMOB_INDEX.write_text(json.dumps(index, indent=0, sort_keys=True), encoding="utf-8")


def _http_get(url: str, *, accept: str = "*/*", timeout: float = 10.0) -> bytes | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Accept": accept,
            "Origin": "https://www.premierleague.com",
            "Referer": "https://www.premierleague.com/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "image" in ctype or data[:4] == b"\x89PNG" or data[:3] == b"\xff\xd8":
                # Reject tiny placeholders / XML error bodies.
                if len(data) < 1500:
                    return None
                if data[:5] == b"<?xml" or data[:5] == b"<Error":
                    return None
                return data
            if "json" in ctype or accept.startswith("application/json"):
                return data
            return None
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
        return None


def _search_name(player: Player) -> str:
    raw = (player.name or "").strip()
    # "A.Becker" → "Alisson Becker" is ideal but we only have web-style names.
    # Expand a few common FPL abbreviations.
    aliases = {
        "A.Becker": "Alisson Becker",
        "M.Salah": "Mohamed Salah",
        "B.Fernandes": "Bruno Fernandes",
        "J.Timber": "Jurrien Timber",
        "Gabriel": "Gabriel Magalhaes",
    }
    if raw in aliases:
        return aliases[raw]
    # "M.Bizot" → "Bizot"; "Gyökeres" stays.
    if re.match(r"^[A-Z]\.[A-Za-z]", raw):
        return raw.split(".", 1)[-1]
    return raw.replace(".", " ")


def _fotmob_id_for(player: Player) -> str | None:
    key = str(player.id)
    index = _load_fotmob_index()
    if key in index:
        return index[key] or None

    term = _search_name(player)
    if not term:
        return None
    url = f"{FOTMOB_SUGGEST}?term={urllib.parse.quote(term)}"
    raw = _http_get(url, accept="application/json")
    if not raw:
        index[key] = ""
        _save_fotmob_index(index)
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        index[key] = ""
        _save_fotmob_index(index)
        return None

    options = []
    for block in data.get("squadMemberSuggest") or []:
        options.extend(block.get("options") or [])

    hints = TEAM_NAME_HINTS.get((player.team_code or "").upper(), ())
    chosen = None
    for opt in options:
        payload = opt.get("payload") or {}
        fid = str(payload.get("id") or "")
        if not fid and "|" in str(opt.get("text") or ""):
            fid = str(opt.get("text")).rsplit("|", 1)[-1]
        if not fid.isdigit():
            continue
        team = str(payload.get("teamName") or "")
        if hints and any(h.lower() in team.lower() for h in hints):
            chosen = fid
            break
        if chosen is None:
            chosen = fid

    index[key] = chosen or ""
    _save_fotmob_index(index)
    return chosen


def cached_path(player: Player) -> Path | None:
    code = photo_code(getattr(player, "photo", None))
    if code:
        for ext in (".png", ".jpg", ".webp"):
            path = CACHE_DIR / f"{code}{ext}"
            if path.exists() and path.stat().st_size > 1500:
                return path
    # Fallback key by internal id when photo code missing.
    path = CACHE_DIR / f"id{player.id}.png"
    if path.exists() and path.stat().st_size > 1500:
        return path
    return None


def _write_cache(player: Player, data: bytes) -> Path:
    _ensure_cache_dir()
    code = photo_code(getattr(player, "photo", None))
    ext = ".jpg" if data[:3] == b"\xff\xd8" else ".png"
    path = CACHE_DIR / (f"{code}{ext}" if code else f"id{player.id}{ext}")
    path.write_bytes(data)
    return path


def fetch_best_photo(player: Player) -> tuple[bytes, str] | None:
    """Return (bytes, content_type) for the best available headshot."""
    cached = cached_path(player)
    if cached:
        ctype = "image/jpeg" if cached.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        return cached.read_bytes(), ctype

    candidates: list[str] = []
    primary = photo_url(getattr(player, "photo", None))
    fallback = photo_fallback_url(getattr(player, "photo", None))
    if primary:
        candidates.append(primary)
    if fallback and fallback != primary:
        candidates.append(fallback)

    fid = _fotmob_id_for(player)
    if fid:
        candidates.append(FOTMOB_IMG.format(fid=fid))

    for url in candidates:
        data = _http_get(url)
        if not data:
            continue
        path = _write_cache(player, data)
        ctype = "image/jpeg" if data[:3] == b"\xff\xd8" else "image/png"
        # Keep path for future hits.
        _ = path
        return data, ctype
    return None


def photo_api_path(player_id: int) -> str:
    return f"/api/players/{int(player_id)}/photo"
