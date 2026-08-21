"""Detect whether the request should receive desktop left-rail payloads."""

from __future__ import annotations

from starlette.requests import Request

# Same breakpoint as CSS / JS ``matchMedia("(min-width: 900px)")``.
DESK_MIN_PX = 900


def request_wants_desk_side(request: Request) -> bool:
    """Left rails are CSS-desktop only (≥900px). Skip payload work on phones.

    Prefer the soft-nav hint (same breakpoint as JS isDesktop), then Client Hints
    (mobile + viewport width), then the ``ff_desk`` cookie set by the shell, then
    a conservative User-Agent phone check. Unknown → compute (desktop-safe).
    """
    explicit = (request.headers.get("x-ff-desktop") or "").strip().lower()
    if explicit in ("1", "true", "yes"):
        return True
    if explicit in ("0", "false", "no"):
        return False

    ch_mobile = (request.headers.get("sec-ch-ua-mobile") or "").strip()
    if ch_mobile == "?1":
        return False
    if ch_mobile == "?0":
        return True

    for key in ("sec-ch-viewport-width", "viewport-width"):
        raw = (request.headers.get(key) or "").strip()
        if raw.isdigit():
            return int(raw) >= DESK_MIN_PX

    desk_cookie = (request.cookies.get("ff_desk") or "").strip()
    if desk_cookie in ("1", "true", "yes"):
        return True
    if desk_cookie in ("0", "false", "no"):
        return False

    ua = (request.headers.get("user-agent") or "").lower()
    if not ua:
        return True
    # Phones: "Mobile" / iPhone / iPod. Android tablets usually lack "mobi".
    if "iphone" in ua or "ipod" in ua or "windows phone" in ua or "opera mini" in ua:
        return False
    if "android" in ua and "mobi" in ua:
        return False
    if "mobi" in ua and "ipad" not in ua:
        return False
    return True
