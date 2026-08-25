"""Background auto-scoring after gameweek deadline + League News timing."""

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
_news_lock = threading.Lock()
_last_run_at: float = 0.0
_last_gw: Optional[int] = None
_last_gw_sweep_at: float = 0.0
_last_news_at: float = 0.0
_thread: Optional[threading.Thread] = None
_news_thread: Optional[threading.Thread] = None
MIN_INTERVAL_SEC = 90.0
NEWS_INTERVAL_SEC = 90.0


def maybe_generate_league_news(*, force: bool = False) -> Optional[dict]:
    """Generate due League News editions (post_gw / pre_gw). Throttled.

    Runs on its own lock so Gemini never blocks live scoring.
    """
    global _last_news_at
    now = time.time()
    if not force and (now - _last_news_at) < NEWS_INTERVAL_SEC:
        return None
    if not _news_lock.acquire(blocking=False):
        return None
    try:
        if not force and (time.time() - _last_news_at) < NEWS_INTERVAL_SEC:
            return None
        db = SessionLocal()
        try:
            from app.services import league_news as news_svc

            if not news_svc.news_enabled():
                return None
            result = news_svc.maybe_generate_due_editions(db)
            _last_news_at = time.time()
            generated = result.get("generated") or []
            if generated:
                logger.info("league_news generated %s edition(s)", len(generated))
            return result
        except Exception:
            logger.exception("league_news generation failed")
            return None
        finally:
            db.close()
    finally:
        _news_lock.release()


def kick_league_news(*, force: bool = False) -> None:
    """Fire-and-forget news generation on a daemon thread."""

    def _run() -> None:
        maybe_generate_league_news(force=force)

    threading.Thread(target=_run, name="squadforge-league-news", daemon=True).start()


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
            if summary.get("ingest", {}).get("demo_skipped"):
                logger.info(
                    "auto-score GW%s skipped demo (live empty) · managers=%s",
                    gw.number,
                    summary.get("managers_scored"),
                )
            advanced = squad_svc.maybe_advance_finished_gameweek(db)
            if advanced:
                logger.info("auto-advanced current gameweek after GW%s finished", gw.number)
            # Post-GW news after fixtures/advance — never block this scoring thread.
            kick_league_news(force=True)
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
    """Daemon: score locked GWs; separately tick League News (post/pre timing)."""
    global _thread, _news_thread
    if _thread and _thread.is_alive():
        return

    def score_loop() -> None:
        time.sleep(8)
        while True:
            maybe_score_locked_gw()
            time.sleep(interval_sec)

    def news_loop() -> None:
        # Slightly offset so PRE (<48h) runs even when deadline not yet passed.
        time.sleep(12)
        while True:
            maybe_generate_league_news()
            time.sleep(interval_sec)

    _thread = threading.Thread(target=score_loop, name="squadforge-auto-score", daemon=True)
    _thread.start()
    _news_thread = threading.Thread(target=news_loop, name="squadforge-league-news-loop", daemon=True)
    _news_thread.start()
    logger.info("auto-scorer + league-news loops started (every %ss)", interval_sec)
