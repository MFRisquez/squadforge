"""Isolate tests from the live SquadForge SQLite DB."""

from __future__ import annotations

import os
from pathlib import Path

# Must run before app.db / settings are imported by test modules.
_TEST_DB = Path(__file__).resolve().parent / "_test_squadforge.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
