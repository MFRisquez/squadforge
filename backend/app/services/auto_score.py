"""Background auto-scoring after gameweek deadline."""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from app.db import SessionLocal
from app.services import deadline as deadline_svc
from app.services import live_scoring as live_svc
from app.services import squad as squad_svc

logger = logging.getLogger("squadforge.auto_score")

_lock = threading.Lock()
_last_run_at: float = 0.0
_last_gw: Optional[int] = None
_thread: Optional[threading.Thread] = None
MIN_INTERVAL_SEC = 90.0


def maybe_score_locked_gw(*, force: bool = False) -> Optional[dict]:
    """If current GW is past deadline, ingest + score (throttled)."""
    global _last_run_at, _last_gw
    now = time.time()
    with _lock:
        if not force and (now - _last_run_at) < MIN_INTERVAL_SEC:
            return None
        db = SessionLocal()
        try:
            gw = squad_svc.current_gameweek(db)
            if not deadline_svc.deadline_passed(gw):
                return None
            summary = live_svc.run_gameweek_scoring(db, prefer_live=True, force_demo=False)
            _last_run_at = now
            _last_gw = gw.number
            logger.info(
                "auto-scored GW%s · managers=%s players=%s",
                gw.number,
                summary.get("managers_scored"),
                summary.get("players_scored"),
            )
            return summary
        except Exception:
            logger.exception("auto-score failed")
            return None
        finally:
            db.close()


def start_auto_scorer(*, interval_sec: float = 120.0) -> None:
    """Daemon thread: every `interval_sec`, score if GW is locked."""
    global _thread
    if _thread and _thread.is_alive():
        return

    def loop() -> None:
        # First delay — let seed / sync settle
        time.sleep(8)
        while True:
            maybe_score_locked_gw()
            time.sleep(interval_sec)

    _thread = threading.Thread(target=loop, name="squadforge-auto-score", daemon=True)
    _thread.start()
    logger.info("auto-scorer started (every %ss)", interval_sec)
