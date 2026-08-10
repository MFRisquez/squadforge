"""Premier League shirt assets (FPL CDN kit codes by short_name)."""

from __future__ import annotations

# FPL team `code` used in shirt_{code}-66.webp (updated for current season bootstrap)
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


def photo_url(photo: str | None) -> str | None:
    """FPL headshot URL from bootstrap `photo` field (e.g. 80201.jpg)."""
    raw = (photo or "").strip()
    if not raw:
        return None
    code = raw.split(".")[0]
    if not code.isdigit():
        return None
    return f"{PHOTO_CDN}/p{code}.png"


def kit_for(
    team_code: str,
    *,
    position: str = "MID",
    kit_code: int | None = None,
    photo: str | None = None,
) -> dict[str, str | int | None]:
    code = kit_code_for(team_code, kit_code)
    return {
        "kitCode": code,
        "shirt": shirt_url(team_code, position=position, kit_code=code),
        "photo": photo_url(photo),
    }
