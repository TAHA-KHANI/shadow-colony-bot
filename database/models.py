from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Season(Base, TimestampMixin):
    __tablename__ = "seasons"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[int] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(String(20), default="registration", index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    winner_user_id: Mapped[int | None] = mapped_column(BigInteger)
    winner_alliance_id: Mapped[int | None] = mapped_column(BigInteger)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(128))
    alias: Mapped[str | None] = mapped_column(String(64))
    private_started: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    clean_cash: Mapped[int] = mapped_column(BigInteger, default=0)
    dirty_cash: Mapped[int] = mapped_column(BigInteger, default=0)
    vault: Mapped[int] = mapped_column(BigInteger, default=0)
    strength: Mapped[int] = mapped_column(Integer, default=5)
    defense: Mapped[int] = mapped_column(Integer, default=5)
    speed: Mapped[int] = mapped_column(Integer, default=5)
    hack_power: Mapped[int] = mapped_column(Integer, default=1)
    firewall_level: Mapped[int] = mapped_column(Integer, default=1)
    influence: Mapped[int] = mapped_column(Integer, default=0)
    tunnel_progress: Mapped[int] = mapped_column(Integer, default=0)
    heat: Mapped[int] = mapped_column(Integer, default=0)
    jailed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shield_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alliance_id: Mapped[int | None] = mapped_column(ForeignKey("alliances.id", ondelete="SET NULL"), index=True)
    alliance_role: Mapped[str | None] = mapped_column(String(20))
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id"), index=True)
    last_action_day: Mapped[date | None] = mapped_column(Date)
    properties: Mapped[list[Property]] = relationship(back_populates="owner")

    @property
    def game_name(self) -> str:
        return self.alias or self.display_name


class Alliance(Base, TimestampMixin):
    __tablename__ = "alliances"
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(12), unique=True)
    leader_id: Mapped[int] = mapped_column(BigInteger)
    treasury: Mapped[int] = mapped_column(BigInteger, default=0)
    security_level: Mapped[int] = mapped_column(Integer, default=1)
    score: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("season_id", "name", name="uq_alliance_name_season"),)


class CityState(Base, TimestampMixin):
    __tablename__ = "city_state"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id"))
    day_number: Mapped[int] = mapped_column(Integer, default=0)
    phase: Mapped[str] = mapped_column(String(32), default="registration")
    generator_energy: Mapped[int] = mapped_column(Integer, default=100)
    city_treasury: Mapped[int] = mapped_column(BigInteger, default=0)
    mayor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    market_days: Mapped[list[int]] = mapped_column(JSON, default=list)
    market_week: Mapped[str | None] = mapped_column(String(16))
    newspaper_text: Mapped[str | None] = mapped_column(Text)
    upgrade_discount_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Property(Base, TimestampMixin):
    __tablename__ = "properties"
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    base_income: Mapped[int] = mapped_column(Integer)
    base_price: Mapped[int] = mapped_column(Integer)
    toll: Mapped[int] = mapped_column(Integer)
    laundering_limit: Mapped[int] = mapped_column(Integer, default=1200)
    disabled_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auction_open: Mapped[bool] = mapped_column(Boolean, default=False)
    owner: Mapped[User | None] = relationship(back_populates="properties")


class PropertyBid(Base, TimestampMixin):
    __tablename__ = "property_bids"
    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (UniqueConstraint("property_id", "user_id", name="uq_property_bid_user"),)


class Ledger(Base):
    __tablename__ = "ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    currency: Mapped[str] = mapped_column(String(16))
    amount: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(100))
    reference: Mapped[str | None] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GameTick(Base):
    __tablename__ = "game_ticks"
    id: Mapped[int] = mapped_column(primary_key=True)
    tick_key: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NightAction(Base, TimestampMixin):
    __tablename__ = "night_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    game_day: Mapped[int] = mapped_column(Integer, index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    target_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id"))
    action_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_text: Mapped[str | None] = mapped_column(Text)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("season_id", "game_day", "actor_id", name="uq_one_night_action"),)


class MayorBid(Base, TimestampMixin):
    __tablename__ = "mayor_bids"
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    game_day: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (UniqueConstraint("season_id", "game_day", "user_id", name="uq_daily_mayor_bid"),)


class Bill(Base, TimestampMixin):
    __tablename__ = "bills"
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    game_day: Mapped[int] = mapped_column(Integer)
    mayor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(100))
    bill_type: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    target_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="voting")
    vetoed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Vote(Base):
    __tablename__ = "votes"
    id: Mapped[int] = mapped_column(primary_key=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("bills.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    choice: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("bill_id", "user_id", name="uq_bill_vote"),)


class Bounty(Base, TimestampMixin):
    __tablename__ = "bounties"
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    game_day: Mapped[int] = mapped_column(Integer)
    assassin_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    target_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    trigger_type: Mapped[str] = mapped_column(String(20))
    trigger_value: Mapped[str | None] = mapped_column(String(100))
    reward: Mapped[int] = mapped_column(Integer, default=700)
    status: Mapped[str] = mapped_column(String(20), default="active")


class Infection(Base, TimestampMixin):
    __tablename__ = "infections"
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    infected_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    immune_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Fight(Base, TimestampMixin):
    __tablename__ = "fights"
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    game_day: Mapped[int] = mapped_column(Integer)
    fighter_one_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    fighter_two_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    winner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="betting")
    narration: Mapped[str | None] = mapped_column(Text)


class Bet(Base, TimestampMixin):
    __tablename__ = "bets"
    id: Mapped[int] = mapped_column(primary_key=True)
    fight_id: Mapped[int] = mapped_column(ForeignKey("fights.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    fighter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[int] = mapped_column(Integer)
    paid: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("fight_id", "user_id", name="uq_fight_bet"),)


class Loan(Base, TimestampMixin):
    __tablename__ = "loans"
    id: Mapped[int] = mapped_column(primary_key=True)
    lender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    borrower_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    principal: Mapped[int] = mapped_column(BigInteger)
    interest_percent: Mapped[int] = mapped_column(Integer)
    remaining: Mapped[int] = mapped_column(BigInteger)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    collateral_property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id"))
    status: Mapped[str] = mapped_column(String(20), default="offered")


class Dossier(Base, TimestampMixin):
    __tablename__ = "dossiers"
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="sealed")


class DeadManSwitch(Base, TimestampMixin):
    __tablename__ = "dead_man_switches"
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    effect: Mapped[str] = mapped_column(String(24))
    triggered: Mapped[bool] = mapped_column(Boolean, default=False)


class RouletteDuel(Base, TimestampMixin):
    __tablename__ = "roulette_duels"
    id: Mapped[int] = mapped_column(primary_key=True)
    challenger_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    opponent_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    wager: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="offered")
    loser_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class MarketOffer(Base, TimestampMixin):
    __tablename__ = "market_offers"
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    game_day: Mapped[int] = mapped_column(Integer)
    item_code: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(100))
    price_dirty: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MarketPurchase(Base):
    __tablename__ = "market_purchases"
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    game_day: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    offer_id: Mapped[int] = mapped_column(ForeignKey("market_offers.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("season_id", "game_day", "user_id", name="uq_market_purchase_per_opening"),)


class Inventory(Base, TimestampMixin):
    __tablename__ = "inventory"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    item_code: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint("user_id", "item_code", name="uq_inventory_item"),)


class NewsEntry(Base):
    __tablename__ = "news_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    game_day: Mapped[int] = mapped_column(Integer, index=True)
    category: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    public: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdminLog(Base):
    __tablename__ = "admin_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    admin_telegram_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(100))
    details: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

