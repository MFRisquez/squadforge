"""Premier League shirt / badge / photo assets (FPL CDN)."""

from __future__ import annotations

# FPL team `code` used in shirt_{code}-66.webp and badges/{code}.svg
KIT_CODE_BY_SHORT: dict[str, int] = {
    "ARS": 3,
    "AVL": 7,
    "BOU": 91,
    "BRE": 94,
    "BHA": 36,
    "CHE": 8,
    "COV": 9,
    "CRY": 31,
    "EVE": 11,
    "FUL": 54,
    "HUL": 88,
    "IPS": 40,
    "LEE": 2,
    "LIV": 14,
    "MCI": 43,
    "MUN": 1,
    "NEW": 4,
    "NFO": 17,
    "SOU": 20,
    "TOT": 6,
    "SUN": 56,
    "WHU": 21,
    "WOL": 39,
}

SHIRT_CDN = "https://fantasy.premierleague.com/dist/img/shirts/standard"
PHOTO_CDN = "https://resources.premierleague.com/premierleague/photos/players/250x250"
PHOTO_CDN_FALLBACK = "https://resources.premierleague.com/premierleague/photos/players/110x140"
BADGE_CDN = "https://resources.premierleague.com/premierleague25/badges"


def kit_code_for(team_code: str, stored: int | None = None) -> int | None:
    if stored:
        return int(stored)
    return KIT_CODE_BY_SHORT.get((team_code or "").upper())


def shirt_url(team_code: str, *, position: str = "MID", kit_code: int | None = None) -> str:
    """Official FPL shirt artwork URL (outfield vs GK variant)."""
    code = kit_code_for(team_code, kit_code)
    if not code:
        return f"{SHIRT_CDN}/shirt_0-66.webp"
    if (position or "").upper() == "GK":
        return f"{SHIRT_CDN}/shirt_{code}_1-66.webp"
    return f"{SHIRT_CDN}/shirt_{code}-66.webp"


def photo_code(photo: str | None) -> str | None:
    raw = (photo or "").strip()
    if not raw:
        return None
    code = raw.split(".")[0]
    return code if code.isdigit() else None


def photo_url(photo: str | None) -> str | None:
    """FPL headshot URL from bootstrap `photo` field (e.g. 80201.jpg)."""
    code = photo_code(photo)
    if not code:
        return None
    return f"{PHOTO_CDN}/p{code}.png"


def photo_fallback_url(photo: str | None) -> str | None:
    code = photo_code(photo)
    if not code:
        return None
    return f"{PHOTO_CDN_FALLBACK}/p{code}.png"


def badge_url(
    team_code: str = "",
    *,
    kit_code: int | None = None,
    fpl_team_id: int | None = None,
) -> str | None:
    """PL badge SVG — uses FPL kit/team *code* (not bootstrap team id)."""
    code = kit_code_for(team_code, kit_code)
    # Never use fpl_team_id here: badges are keyed by kit code (NEW=4, NFO=17).
    if not code:
        return None
    return f"{BADGE_CDN}/{int(code)}.svg"


def kit_for(
    team_code: str,
    *,
    position: str = "MID",
    kit_code: int | None = None,
    photo: str | None = None,
    player_id: int | None = None,
) -> dict[str, str | int | None]:
    code = kit_code_for(team_code, kit_code)
    # Prefer our resolver (PL CDN → FotMob cache) so missing PL assets still show.
    resolved = f"/api/players/{int(player_id)}/photo" if player_id else None
    return {
        "kitCode": code,
        "shirt": shirt_url(team_code, position=position, kit_code=code),
        "photo": resolved or photo_url(photo),
        "photoFallback": photo_url(photo),
        "photoFallback2": photo_fallback_url(photo),
        "badge": badge_url(team_code, kit_code=code),
    }
