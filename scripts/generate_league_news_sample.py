#!/usr/bin/env python3
"""Generate a League News sample (post_gw) for tone review.

Usage (from repo root):
  PYTHONPATH=backend ANTHROPIC_API_KEY=sk-... python3 scripts/generate_league_news_sample.py

Without a key, prints the drama-ranked facts package only (no API call).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# Isolate from live DB when SAMPLE_ISOLATE=1 (default)
if os.environ.get("SAMPLE_ISOLATE", "1") == "1":
    sample_db = ROOT / "backend" / "data" / "_news_sample.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{sample_db}"


def main() -> int:
    from app.config import settings
    from app.db import Base, SessionLocal, engine
    from app.models import (
        Gameweek,
        League,
        Manager,
        ManagerGameweekScore,
        Membership,
        Player,
        PlayerPoints,
        TransferLog,
    )
    from app.services import league_news as news_svc
    from app.services.seed import seed_if_empty

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
        # Build a mini "Friends League" with drama
        league = League(name="Friends League", invite_code="FRIEND", league_type="classic")
        db.add(league)
        db.commit()
        db.refresh(league)

        names = [
            ("Manuel", "FutFantasy FC"),
            ("Diego", "Los Pibes"),
            ("Carla", "Night Watch"),
            ("Tomi", "Red Mist"),
        ]
        managers = []
        for dn, tn in names:
            m = Manager(display_name=dn, pin="0000", team_name=tn)
            db.add(m)
            db.commit()
            db.refresh(m)
            db.add(Membership(league_id=league.id, manager_id=m.id))
            managers.append(m)
        db.commit()

        players = db.query(Player).limit(10).all()
        if len(players) < 6:
            print("Not enough players seeded", file=sys.stderr)
            return 1
        gw1 = db.query(Gameweek).filter(Gameweek.number == 1).one()
        gw2 = db.query(Gameweek).filter(Gameweek.number == 2).one()

        for i, pl in enumerate(players):
            db.add(
                PlayerPoints(
                    gameweek_id=gw1.id,
                    player_id=pl.id,
                    total=5.0 + (i % 3),
                    breakdown_json="{}",
                    formula_version=settings.formula_version,
                )
            )
            # GW2: first player hauls, second blanks
            tot = 14.0 if i == 0 else (0.5 if i == 1 else 6.0 + (i % 2))
            db.add(
                PlayerPoints(
                    gameweek_id=gw2.id,
                    player_id=pl.id,
                    total=tot,
                    breakdown_json="{}",
                    formula_version=settings.formula_version,
                )
            )

        # Standings swing: Manuel climbs, Diego drops
        totals_gw1 = [8, 22, 15, 12]
        totals_gw2 = [28, 6, 14, 18]
        for i, m in enumerate(managers):
            star = players[0] if i == 0 else players[1]
            base = 14.0 if i == 0 else (0.5 if i == 1 else 6.0)
            lines = [
                {
                    "player_id": star.id,
                    "points": base * (2 if i == 0 else 1),
                    "base": base,
                    "mult": 2.0 if i == 0 else 1.0,
                    "captain": i == 0,
                },
                {
                    "player_id": players[2].id,
                    "points": 6.0,
                    "base": 6.0,
                    "mult": 1.0,
                    "captain": False,
                },
            ]
            db.add(
                ManagerGameweekScore(
                    manager_id=m.id,
                    gameweek_id=gw1.id,
                    squad_points=float(totals_gw1[i]),
                    td_points=0,
                    total=float(totals_gw1[i]),
                    breakdown_json="{}",
                )
            )
            db.add(
                ManagerGameweekScore(
                    manager_id=m.id,
                    gameweek_id=gw2.id,
                    squad_points=float(totals_gw2[i]),
                    td_points=0,
                    total=float(totals_gw2[i]),
                    breakdown_json=json.dumps({"players": lines}),
                )
            )
            db.add(
                TransferLog(
                    manager_id=m.id,
                    gameweek_id=gw2.id,
                    player_out_id=players[3].id,
                    player_in_id=players[0].id,
                    free_transfers_after=0,
                    is_hit=0,
                )
            )
        db.commit()

        package = news_svc.build_post_gw_package(db, league, gw2)
        out_dir = Path("/opt/cursor/artifacts")
        out_dir.mkdir(parents=True, exist_ok=True)
        package_path = out_dir / "league-news-gw2-facts.json"
        package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        print("=== Drama-ranked facts package ===")
        print(json.dumps(package, ensure_ascii=False, indent=2))
        print(f"\nWrote {package_path}")

        if not news_svc.news_enabled():
            print(
                "\nANTHROPIC_API_KEY empty — skipping Claude call. "
                "Add the key and re-run for a real article sample.",
                file=sys.stderr,
            )
            return 0

        result = news_svc.get_or_generate_edition(
            db,
            league=league,
            edition_type="post_gw",
            gameweek_number=2,
            force=True,
        )
        if not result.get("ok"):
            print("Generation failed:", result, file=sys.stderr)
            return 1
        content = result["content"]
        article_path = out_dir / "league-news-gw2-sample.json"
        article_path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n=== Generated article ===")
        print(json.dumps(content, ensure_ascii=False, indent=2))
        print(f"\nWrote {article_path}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
