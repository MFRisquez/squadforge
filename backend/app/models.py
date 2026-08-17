"""Database tables for SquadForge MVP."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Club(Base):
    __tablename__ = "clubs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    # FPL bootstrap teams[].code — used for shirt_{code}-66.webp artwork
    kit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # FPL bootstrap teams[].id — fixtures API uses this
    fpl_team_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    # API-Football teams[].id for league 39 (advanced defensive/create stats)
    api_football_team_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)


class Fixture(Base):
    """Premier League fixtures (from FPL) for FDR + live scores."""

    __tablename__ = "fixtures"
    __table_args__ = (UniqueConstraint("fpl_id", name="uq_fixture_fpl"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fpl_id: Mapped[int] = mapped_column(Integer, index=True)
    gameweek_number: Mapped[int] = mapped_column(Integer, index=True, default=0)
    home_club_code: Mapped[str] = mapped_column(String(8), index=True)
    away_club_code: Mapped[str] = mapped_column(String(8), index=True)
    # FPL team_h_difficulty / team_a_difficulty (1 easiest … 5 hardest)
    home_difficulty: Mapped[int] = mapped_column(Integer, default=3)
    away_difficulty: Mapped[int] = mapped_column(Integer, default=3)
    kickoff_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    started: Mapped[int] = mapped_column(Integer, default=0)
    finished: Mapped[int] = mapped_column(Integer, default=0)
    home_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    away_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Raw FPL stats blob (goals_scored / assists / …) for match detail later
    stats_json: Mapped[str] = mapped_column(Text, default="[]")


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    position: Mapped[str] = mapped_column(String(8), index=True)  # GK|DEF|MID|ATT
    team_code: Mapped[str] = mapped_column(String(8), default="", index=True)
    price: Mapped[float] = mapped_column(Float, default=5.0)
    # FPL availability: a=available, d=doubtful, i=injured, s=suspended, u=unavailable
    status: Mapped[str] = mapped_column(String(8), default="a")
    chance_of_playing: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    news: Mapped[str] = mapped_column(String(255), default="")
    # FPL photo code e.g. "80201.jpg" → CDN headshot
    photo: Mapped[str] = mapped_column(String(64), default="")
    # Season KPIs from FPL bootstrap (JSON) — total_points, minutes, goals, form, …
    season_stats_json: Mapped[str] = mapped_column(Text, default="{}")


class Gameweek(Base):
    __tablename__ = "gameweeks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[int] = mapped_column(Integer, unique=True)
    status: Mapped[str] = mapped_column(String(24), default="upcoming")
    name: Mapped[str] = mapped_column(String(64), default="")
    is_current: Mapped[int] = mapped_column(Integer, default=0)
    # ISO timestamp from FPL events[].deadline_time
    deadline_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class League(Base):
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80))
    invite_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    # classic = FPL-style cumulative table · h2h = weekly head-to-head (best with even members)
    league_type: Mapped[str] = mapped_column(String(16), default="classic")
    # Creator / admin — nullable so existing leagues keep working until backfilled.
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("managers.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="league")


class Manager(Base):
    __tablename__ = "managers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    display_name: Mapped[str] = mapped_column(String(80), unique=True)
    # Legacy PIN (pre-password accounts). New accounts use password_hash.
    pin: Mapped[str] = mapped_column(String(16), default="")
    email: Mapped[str] = mapped_column(String(120), default="", index=True)
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    team_name: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="manager")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("league_id", "manager_id", name="uq_membership"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), index=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"), index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    league: Mapped[League] = relationship(back_populates="memberships")
    manager: Mapped[Manager] = relationship(back_populates="memberships")


class SquadPick(Base):
    """Lineup for a gameweek — subset of the manager's owned 15."""

    __tablename__ = "squad_picks"
    __table_args__ = (UniqueConstraint("manager_id", "gameweek_id", "player_id", name="uq_pick"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"), index=True)
    gameweek_id: Mapped[int] = mapped_column(ForeignKey("gameweeks.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    is_captain: Mapped[int] = mapped_column(Integer, default=0)
    is_vice_captain: Mapped[int] = mapped_column(Integer, default=0)
    is_starter: Mapped[int] = mapped_column(Integer, default=1)
    bench_order: Mapped[int] = mapped_column(Integer, default=0)
    # 1 = was captain when their club's GW fixture kicked off (keeps ×2 after mid-GW C change)
    captain_armed: Mapped[int] = mapped_column(Integer, default=0)


class OwnedPlayer(Base):
    """Current 15-man squad ownership (not formation)."""

    __tablename__ = "owned_players"
    __table_args__ = (UniqueConstraint("manager_id", "player_id", name="uq_owned"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    acquired_gw: Mapped[int] = mapped_column(Integer, default=1)


class TransferState(Base):
    __tablename__ = "transfer_states"
    __table_args__ = (UniqueConstraint("manager_id", name="uq_ft_manager"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"), index=True)
    free_transfers: Mapped[int] = mapped_column(Integer, default=1)
    last_banked_gw: Mapped[int] = mapped_column(Integer, default=1)
    has_squad: Mapped[int] = mapped_column(Integer, default=0)


class TransferLog(Base):
    __tablename__ = "transfer_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"), index=True)
    gameweek_id: Mapped[int] = mapped_column(ForeignKey("gameweeks.id"), index=True)
    player_out_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    player_in_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    free_transfers_after: Mapped[int] = mapped_column(Integer, default=0)
    is_hit: Mapped[int] = mapped_column(Integer, default=0)  # 1 = −4 points that GW
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TechnicalDirectorPick(Base):
    __tablename__ = "td_picks"
    __table_args__ = (UniqueConstraint("manager_id", "start_gw", name="uq_td_block"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"), index=True)
    club_code: Mapped[str] = mapped_column(String(8))
    start_gw: Mapped[int] = mapped_column(Integer)  # block starts at this GW number
    end_gw: Mapped[int] = mapped_column(Integer)  # inclusive, start+2


class ChipState(Base):
    """Remaining chips for a manager in a league/season."""

    __tablename__ = "chip_states"
    __table_args__ = (UniqueConstraint("manager_id", name="uq_chip_manager"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"), index=True)
    wildcard_remaining: Mapped[int] = mapped_column(Integer, default=2)
    free_hit_remaining: Mapped[int] = mapped_column(Integer, default=1)
    bench_boost_remaining: Mapped[int] = mapped_column(Integer, default=1)
    triple_captain_remaining: Mapped[int] = mapped_column(Integer, default=1)
    super_sub_remaining: Mapped[int] = mapped_column(Integer, default=1)
    wildcards_unlocked: Mapped[int] = mapped_column(Integer, default=1)  # 2nd at GW20


class ChipPlay(Base):
    __tablename__ = "chip_plays"
    __table_args__ = (UniqueConstraint("manager_id", "gameweek_id", name="uq_chip_gw"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"), index=True)
    gameweek_id: Mapped[int] = mapped_column(ForeignKey("gameweeks.id"), index=True)
    chip: Mapped[str] = mapped_column(String(32))  # wildcard|free_hit|bench_boost|triple_captain|super_sub
    meta_json: Mapped[str] = mapped_column(Text, default="{}")  # e.g. super_sub player id


class MatchEvent(Base):
    __tablename__ = "match_events"
    __table_args__ = (UniqueConstraint("gameweek_id", "player_id", "metric", name="uq_event"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gameweek_id: Mapped[int] = mapped_column(ForeignKey("gameweeks.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    metric: Mapped[str] = mapped_column(String(64))
    value: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str] = mapped_column(String(64), default="manual")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PlayerPoints(Base):
    __tablename__ = "player_points"
    __table_args__ = (UniqueConstraint("gameweek_id", "player_id", "formula_version", name="uq_points"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gameweek_id: Mapped[int] = mapped_column(ForeignKey("gameweeks.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    total: Mapped[float] = mapped_column(Float, default=0)
    breakdown_json: Mapped[str] = mapped_column(Text, default="{}")
    formula_version: Mapped[str] = mapped_column(String(32), default="v0.2.1-cameo")


class ManagerGameweekScore(Base):
    __tablename__ = "manager_gw_scores"
    __table_args__ = (UniqueConstraint("manager_id", "gameweek_id", name="uq_mgr_gw"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"), index=True)
    gameweek_id: Mapped[int] = mapped_column(ForeignKey("gameweeks.id"), index=True)
    squad_points: Mapped[float] = mapped_column(Float, default=0)
    td_points: Mapped[float] = mapped_column(Float, default=0)
    total: Mapped[float] = mapped_column(Float, default=0)
    breakdown_json: Mapped[str] = mapped_column(Text, default="{}")


class ClubResult(Base):
    """Real club result for Technical Director scoring."""

    __tablename__ = "club_results"
    __table_args__ = (UniqueConstraint("gameweek_id", "club_code", "fixture_index", name="uq_club_result"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gameweek_id: Mapped[int] = mapped_column(ForeignKey("gameweeks.id"), index=True)
    club_code: Mapped[str] = mapped_column(String(8), index=True)
    fixture_index: Mapped[int] = mapped_column(Integer, default=0)  # 0,1 for DGW
    result: Mapped[str] = mapped_column(String(8))  # W|D|L


class H2HMatch(Base):
    """Weekly head-to-head pairing inside an H2H league."""

    __tablename__ = "h2h_matches"
    __table_args__ = (UniqueConstraint("league_id", "gameweek_id", "home_manager_id", name="uq_h2h"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), index=True)
    gameweek_id: Mapped[int] = mapped_column(ForeignKey("gameweeks.id"), index=True)
    home_manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    away_manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    home_points: Mapped[float] = mapped_column(Float, default=0)
    away_points: Mapped[float] = mapped_column(Float, default=0)
    # pending | home | away | draw
    result: Mapped[str] = mapped_column(String(16), default="pending")

