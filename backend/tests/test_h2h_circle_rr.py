"""Circle-method H2H round-robin: full opponent coverage + bye rotation."""

from __future__ import annotations

from itertools import combinations

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import Gameweek
from app.services import league as league_svc
from app.services import standings as standings_svc
from app.services.seed import seed_if_empty


def setup_module():
    settings.reset_db_on_startup = False
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()


def _pair_key(a: int, b: int) -> frozenset[int]:
    return frozenset((int(a), int(b)))


def test_h2h_circle_pairs_four_covers_all_combos_before_repeat():
    ids = [10, 20, 30, 40]
    # All unordered pairs among 4 managers = C(4,2) = 6 edges, but each round
    # plays 2 disjoint matches → 3 distinct round-configurations:
    # {AB,CD}, {AC,BD}, {AD,BC}.
    expected_rounds = {
        frozenset({_pair_key(10, 20), _pair_key(30, 40)}),
        frozenset({_pair_key(10, 30), _pair_key(20, 40)}),
        frozenset({_pair_key(10, 40), _pair_key(20, 30)}),
    }
    seen: list[frozenset[frozenset[int]]] = []
    for r in range(8):
        pairs = standings_svc.h2h_circle_pairs(ids, round_index=r)
        assert len(pairs) == 2
        cfg = frozenset(_pair_key(a, b) for a, b in pairs)
        seen.append(cfg)
        # Every manager appears exactly once per round.
        flat = [x for pair in pairs for x in pair]
        assert sorted(flat) == sorted(ids)

    # First 3 rounds are the full single round-robin; then it repeats.
    assert set(seen[:3]) == expected_rounds
    assert seen[3:6] == seen[:3]
    assert seen[6:8] == seen[:2]


def test_h2h_circle_pairs_five_bye_rotates_without_repeat_streak():
    ids = [1, 2, 3, 4, 5]
    byes: list[int] = []
    for r in range(10):  # > one full cycle of 5
        pairs = standings_svc.h2h_circle_pairs(ids, round_index=r)
        assert len(pairs) == 2  # 5 managers → 2 matches + 1 bye
        playing = {x for pair in pairs for x in pair}
        assert len(playing) == 4
        resting = set(ids) - playing
        assert len(resting) == 1
        byes.append(next(iter(resting)))

    # One full cycle: each manager byes exactly once.
    assert sorted(byes[:5]) == sorted(ids)
    # No manager rests two consecutive rounds before everyone else has byed.
    for i in range(4):
        assert byes[i] != byes[i + 1]
    # Cycle repeats.
    assert byes[5:10] == byes[:5]


def test_ensure_h2h_pairings_four_and_five_over_eight_gws():
    db = SessionLocal()
    try:
        # --- 4 managers ---
        owners4 = []
        for i in range(4):
            owners4.append(
                league_svc.register_manager(
                    db,
                    display_name=f"RR4_{i}",
                    password="secret12",
                    email=f"rr4_{i}@example.com",
                    team_name=f"RR4 Team {i}",
                )
            )
        league4 = league_svc.create_league(db, "RR Four", owners4[0], league_type="h2h")
        for m in owners4[1:]:
            league_svc.join_league(db, league4.invite_code, m)
        ids4 = sorted(int(m.id) for m in owners4)
        a, b, c, d = ids4
        expected_cfgs4 = {
            frozenset({_pair_key(a, b), _pair_key(c, d)}),
            frozenset({_pair_key(a, c), _pair_key(b, d)}),
            frozenset({_pair_key(a, d), _pair_key(b, c)}),
        }

        gws = db.query(Gameweek).order_by(Gameweek.number).limit(8).all()
        assert len(gws) >= 8
        cfgs4: list[frozenset[frozenset[int]]] = []
        for gw in gws[:8]:
            matches = standings_svc.ensure_h2h_pairings(db, league4, gw)
            assert len(matches) == 2
            cfg = frozenset(
                _pair_key(m.home_manager_id, m.away_manager_id) for m in matches
            )
            cfgs4.append(cfg)

        assert set(cfgs4[:3]) == expected_cfgs4
        assert cfgs4[3:6] == cfgs4[:3]
        # All 6 unordered pairs appear across a single cycle of 3 rounds.
        covered = set().union(*cfgs4[:3])
        assert covered == {_pair_key(x, y) for x, y in combinations(ids4, 2)}

        # --- 5 managers ---
        owners5 = []
        for i in range(5):
            owners5.append(
                league_svc.register_manager(
                    db,
                    display_name=f"RR5_{i}",
                    password="secret12",
                    email=f"rr5_{i}@example.com",
                    team_name=f"RR5 Team {i}",
                )
            )
        league5 = league_svc.create_league(db, "RR Five", owners5[0], league_type="h2h")
        for m in owners5[1:]:
            league_svc.join_league(db, league5.invite_code, m)
        # Odd H2H allowed via set_league_type / create.
        league_svc.set_league_type(db, league5, "h2h")
        ids5 = sorted(int(m.id) for m in owners5)

        byes5: list[int] = []
        for gw in gws[:8]:
            matches = standings_svc.ensure_h2h_pairings(db, league5, gw)
            assert len(matches) == 2
            playing = {
                int(m.home_manager_id) for m in matches
            } | {int(m.away_manager_id) for m in matches}
            resting = set(ids5) - playing
            assert len(resting) == 1
            byes5.append(next(iter(resting)))

        assert sorted(byes5[:5]) == sorted(ids5)
        for i in range(4):
            assert byes5[i] != byes5[i + 1]
        assert byes5[5:8] == byes5[:3]
    finally:
        db.close()


def test_set_league_type_allows_odd_h2h():
    db = SessionLocal()
    try:
        managers = []
        for i in range(3):
            managers.append(
                league_svc.register_manager(
                    db,
                    display_name=f"OddH2H{i}",
                    password="secret12",
                    email=f"oddh2h{i}@example.com",
                    team_name=f"Odd {i}",
                )
            )
        league = league_svc.create_league(db, "Odd Classic", managers[0])
        for m in managers[1:]:
            league_svc.join_league(db, league.invite_code, m)
        updated = league_svc.set_league_type(db, league, "h2h")
        assert updated.league_type == "h2h"
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        matches = standings_svc.ensure_h2h_pairings(db, league, gw)
        assert len(matches) == 1  # 3 managers → 1 match + 1 bye
    finally:
        db.close()
