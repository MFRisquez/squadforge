"""Temporary request/server timing helpers for soft-nav diagnosis."""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

log = logging.getLogger("squadforge.server_perf")

_spans: ContextVar[list[dict[str, Any]] | None] = ContextVar("ff_perf_spans", default=None)

# Shared ring buffer (browser soft-nav + server HTML/catalog timings).
_PERF_EVENTS: list[dict[str, Any]] = []
_PERF_EVENTS_MAX = 120


def perf_begin() -> None:
    _spans.set([])


def perf_spans() -> list[dict[str, Any]]:
    return list(_spans.get() or [])


def perf_clear() -> None:
    _spans.set(None)


@contextmanager
def timed(name: str, **extra: Any) -> Iterator[None]:
    """Record one named span in ms on the current request."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        ms = (time.perf_counter() - t0) * 1000.0
        spans = _spans.get()
        if spans is not None:
            row: dict[str, Any] = {"name": name, "ms": round(ms, 1)}
            for k, v in extra.items():
                if v is not None:
                    row[k] = v
            spans.append(row)


def record_perf_event(entry: dict[str, Any]) -> None:
    """Append to the in-memory buffer readable via GET /api/client-perf."""
    row = dict(entry)
    row.setdefault("ts", time.time())
    _PERF_EVENTS.append(row)
    if len(_PERF_EVENTS) > _PERF_EVENTS_MAX:
        del _PERF_EVENTS[: len(_PERF_EVENTS) - _PERF_EVENTS_MAX]


def list_perf_events(limit: int = 40) -> list[dict[str, Any]]:
    n = max(1, min(int(limit or 40), _PERF_EVENTS_MAX))
    return list(_PERF_EVENTS[-n:])


def perf_event_count() -> int:
    return len(_PERF_EVENTS)


def attach_server_perf_header(response: Any, *, path: str, kind: str = "html") -> Any:
    """Stamp X-FF-Server-Perf on the response and stash in the ring buffer."""
    spans = perf_spans()
    server_ms = round(sum(float(s.get("ms") or 0) for s in spans), 1)
    payload = {
        "kind": kind,
        "path": path,
        "server_ms": server_ms,
        "spans": spans,
    }
    try:
        response.headers["X-FF-Server-Perf"] = json.dumps(payload, separators=(",", ":"))
    except Exception:
        pass
    record_perf_event(
        {
            "kind": kind,
            "url": path,
            "server_ms": server_ms,
            "spans": spans,
            "from_cache": False,
        }
    )
    log.info(
        "server_perf kind=%s path=%s server_ms=%.1f spans=%s",
        kind,
        path,
        server_ms,
        json.dumps(spans, separators=(",", ":")),
    )
    return response
