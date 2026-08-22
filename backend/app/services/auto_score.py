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
from app.services.fixtures import GW_SWEEP_INTERVAL_SEC

logger = logging.getLogger("squadforge.auto_score")

_lock = threading.Lock()
_last_run_at: float = 0.0
_last_gw: Optional[int] = None
_last_gw_sweep_at: float = 0.0
_thread: Optional[threading.Thread] = None
MIN_INTERVAL_SEC = 90.0


def maybe_score_locked_gw(*, force: bool = False) -> Optional[dict]:
    """If current GW is past deadline, ingest + score (throttled)."""
    global _last_run_at, _last_gw, _last_gw_sweep_at
    now = time.time()
    with _lock:
        if not force and (now - _last_run_at) < MIN_INTERVAL_SEC:
            return None
        db = SessionLocal()
        try:
            gw = squad_svc.current_gameweek(db)
            if not deadline_svc.deadline_passed(gw):
                return None
            # Keep Fixture.started/finished in sync with FPL every cycle — same
            # cadence as player points. Do not let a fixture refresh failure
            # block scoring (ingest also refreshes, but this makes the daemon
            # path explicit and logs skip reasons like missing club FPL ids).
            #
            # Hot path: live/resolving matches only (~2–4). Occasional GW sweep
            # (~10) so upcoming kickoffs still flip to live without 380 upserts.
            try:
                from app.services import fixtures as fixtures_svc

                gw_changed = _last_gw is not None and _last_gw != gw.number
                need_gw_sweep = (
                    force
                    or gw_changed
                    or (_last_gw_sweep_at <= 0)
                    or (now - _last_gw_sweep_at) >= GW_SWEEP_INTERVAL_SEC
                )
                scope = "gw" if need_gw_sweep else "live"
                fx_info = fixtures_svc.refresh_fixtures(
                    db, scope=scope, gw_number=int(gw.number)
                )
                if scope == "gw":
                    _last_gw_sweep_at = now
                logger.info(
                    "auto-score fixture sync GW%s · %s",
                    gw.number,
                    fx_info,
                )
            except Exception:
                logger.exception("auto-score fixture sync failed (continuing)")

            summary = live_svc.run_gameweek_scoring(db, prefer_live=True, force_demo=False)
            # Never invent demo points in the background loop.
            if summary.get("ingest", {}).get("demo_skipped"):
                logger.info(
                    "auto-score GW%s skipped demo (live empty) · managers=%s",
                    gw.number,
                    summary.get("managers_scored"),
                )
            advanced = squad_svc.maybe_advance_finished_gameweek(db)
            if advanced:
                logger.info("auto-advanced current gameweek after GW%s finished", gw.number)
            _last_run_at = now
            _last_gw = gw.number
            logger.info(
                "auto-scored GW%s · managers=%s players=%s source=%s",
                gw.number,
                summary.get("managers_scored"),
                summary.get("players_scored"),
                (summary.get("ingest") or {}).get("source"),
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
