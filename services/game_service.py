from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Alliance,
    CityState,
    Ledger,
    NightAction,
    Property,
    Season,
    User,
)
from game.constants import (
    GENERATOR_CASH_UNIT,
    GENERATOR_ENERGY_UNIT,
    GENERATOR_MAX,
    MAX_PLAYERS,
    PROPERTY_BLUEPRINTS,
    SHIELD_HOURS,
    SHIELD_PRICE,
    START_CLEAN_CASH,
    START_DIRTY_CASH,
    START_FIREWALL,
    START_HACK,
    START_STAT,
)
from game.tone import say


class GameError(ValueError):
    pass


async def city(session: AsyncSession, lock: bool = False) -> CityState:
    stmt = select(CityState).where(CityState.id == 1)
    if lock:
        stmt = stmt.with_for_update()
    state = await session.scalar(stmt)
    if not state:
        state = CityState(id=1)
        session.add(state)
        await session.flush()
    return state


async def active_season(session: AsyncSession) -> Season | None:
    return await session.scalar(select(Season).where(Season.status.in_(("registration", "active", "paused"))).order_by(Season.id.desc()))


async def get_user(session: AsyncSession, telegram_id: int, lock: bool = False) -> User | None:
    stmt = select(User).where(User.telegram_id == telegram_id)
    if lock:
        stmt = stmt.with_for_update()
    return await session.scalar(stmt)


async def ensure_user(session: AsyncSession, telegram_user, private_started: bool = False) -> User:
    user = await get_user(session, telegram_user.id, lock=True)
    name = telegram_user.full_name[:128]
    if not user:
        user = User(telegram_id=telegram_user.id, username=telegram_user.username, display_name=name, private_started=private_started)
        session.add(user)
        await session.flush()
    else:
        user.username = telegram_user.username
        user.display_name = name
        user.private_started = user.private_started or private_started
    return user


async def join_registration(session: AsyncSession, user: User) -> None:
    season = await active_season(session)
    if not season or season.status != "registration":
        raise GameError("فعلاً ثبت‌نام فصل باز نیست.")
    if not user.private_started:
        raise GameError("اول یک‌بار در پی‌وی ربات /start بزن، بعد برگرد ثبت‌نام کن.")
    count = await session.scalar(select(func.count(User.id)).where(User.season_id == season.id, User.is_active.is_(True)))
    if user.season_id == season.id:
        raise GameError("قبلاً برای همین فصل ثبت‌نام کردی، عجله نکن خلافکار!")
    if count >= MAX_PLAYERS:
        raise GameError("شهر پر شده؛ سقف این فصل ۱۵ خلافکار است.")
    user.season_id = season.id
    user.is_active = True
    user.clean_cash = START_CLEAN_CASH
    user.dirty_cash = START_DIRTY_CASH
    user.vault = 0
    user.strength = user.defense = user.speed = START_STAT
    user.hack_power = START_HACK
    user.firewall_level = START_FIREWALL
    user.influence = user.tunnel_progress = user.heat = 0
    user.alliance_id = None
    user.alliance_role = None


async def change_money(session: AsyncSession, user: User, currency: str, amount: int, reason: str, reference: str | None = None) -> None:
    if currency not in {"clean", "dirty", "vault"}:
        raise GameError("نوع پول نامعتبر است.")
    attr = {"clean": "clean_cash", "dirty": "dirty_cash", "vault": "vault"}[currency]
    value = getattr(user, attr) + amount
    if value < 0:
        raise GameError(say("no_money", f"{user.id}:{currency}:{reason}"))
    setattr(user, attr, value)
    session.add(Ledger(user_id=user.id, currency=currency, amount=amount, reason=reason, reference=reference))


async def fund_generator(session: AsyncSession, user: User, amount: int) -> int:
    if amount < GENERATOR_CASH_UNIT or amount % GENERATOR_CASH_UNIT:
        raise GameError(f"مبلغ باید مضربی از {GENERATOR_CASH_UNIT} باشد.")
    state = await city(session, lock=True)
    room = GENERATOR_MAX - state.generator_energy
    energy = min(room, amount // GENERATOR_CASH_UNIT * GENERATOR_ENERGY_UNIT)
    if energy <= 0:
        raise GameError("ژنراتور تا خرخره پر است.")
    actual = energy // GENERATOR_ENERGY_UNIT * GENERATOR_CASH_UNIT
    await change_money(session, user, "clean", -actual, "کمک به ژنراتور")
    state.generator_energy += energy
    return energy


async def buy_shield(session: AsyncSession, user: User) -> datetime:
    now = datetime.now(timezone.utc)
    if user.shield_until and user.shield_until > now:
        raise GameError("همین حالا سپر داری؛ پولت را آتش نزن.")
    await change_money(session, user, "clean", -SHIELD_PRICE, "خرید سپر شبانه")
    user.shield_until = now + timedelta(hours=SHIELD_HOURS)
    return user.shield_until


async def register_night_action(session: AsyncSession, user: User, action_type: str, target_id: int | None = None, property_id: int | None = None) -> NightAction:
    state = await city(session)
    season = await active_season(session)
    if not season or season.status != "active" or state.paused:
        raise GameError("بازی الآن برای عملیات شبانه باز نیست.")
    allowed = {"hack", "ddos", "scan", "steal", "dig", "inform", "ambush", "cleanup", "dawn_raid", "betray"}
    if action_type not in allowed:
        raise GameError("عملیات ناشناخته است.")
    existing = await session.scalar(select(NightAction).where(NightAction.season_id == season.id, NightAction.game_day == state.day_number, NightAction.actor_id == user.id))
    if existing:
        raise GameError("امشب یک نقشه ثبت کردی؛ شهر با دکمه‌زدن بیشتر گول نمی‌خورد.")
    if target_id == user.id:
        raise GameError("نمی‌توانی خودت را بزنی؛ خودزنی امتیاز ندارد.")
    action = NightAction(season_id=season.id, game_day=state.day_number, actor_id=user.id, target_id=target_id, property_id=property_id, action_type=action_type)
    session.add(action)
    user.last_action_day = datetime.now(timezone.utc).date()
    await session.flush()
    return action


def alliance_limit(player_count: int) -> int:
    return max(2, min(5, player_count // 3))


async def create_alliance(session: AsyncSession, user: User, name: str) -> Alliance:
    if user.alliance_id:
        raise GameError("اول از اتحاد فعلی بیرون بیا.")
    season = await active_season(session)
    if not season or season.status != "active":
        raise GameError("فصل فعال نیست.")
    if len(name.strip()) < 3 or len(name) > 32:
        raise GameError("نام اتحاد باید بین ۳ تا ۳۲ کاراکتر باشد.")
    code = secrets.token_hex(3).upper()
    alliance = Alliance(season_id=season.id, name=name.strip(), code=code, leader_id=user.id)
    session.add(alliance)
    await session.flush()
    user.alliance_id = alliance.id
    user.alliance_role = "leader"
    return alliance


async def join_alliance(session: AsyncSession, user: User, code: str) -> Alliance:
    if user.alliance_id:
        raise GameError("هم‌زمان در دو باند؟ زیادی فیلم دیدی.")
    alliance = await session.scalar(select(Alliance).where(Alliance.code == code.upper()).with_for_update())
    if not alliance:
        raise GameError("کد اتحاد پیدا نشد.")
    player_count = await session.scalar(select(func.count(User.id)).where(User.season_id == alliance.season_id))
    member_count = await session.scalar(select(func.count(User.id)).where(User.alliance_id == alliance.id))
    if member_count >= alliance_limit(player_count):
        raise GameError("این باند دیگر جا ندارد.")
    user.alliance_id = alliance.id
    user.alliance_role = "member"
    return alliance


def initial_property_count(players: int) -> int:
    if players <= 7:
        return 2
    if players <= 11:
        return 3
    return 4


async def seed_properties(session: AsyncSession, season_id: int) -> list[Property]:
    items = []
    for name, income, price, toll in PROPERTY_BLUEPRINTS:
        item = Property(season_id=season_id, name=name, base_income=income, base_price=price, toll=toll, laundering_limit=income * 2)
        session.add(item)
        items.append(item)
    await session.flush()
    return items

