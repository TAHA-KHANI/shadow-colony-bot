from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from config import settings
from database.models import (
    Alliance,
    Bet,
    Bill,
    Bounty,
    CityState,
    DeadManSwitch,
    Fight,
    GameTick,
    Infection,
    MarketOffer,
    MayorBid,
    NewsEntry,
    Property,
    PropertyBid,
    Season,
    User,
    Vote,
)
from database.session import SessionFactory
from game.constants import (
    BILL_TEMPLATES,
    BOUNTY_WORDS,
    GENERATOR_DAILY_DRAIN,
    SEASON_DAYS,
)
from game.randomizer import pick_index, roll
from game.tone import say
from services.game_service import change_money
from services.resolution_engine import resolve_night


def local_now() -> datetime:
    return datetime.now(settings.timezone)


async def claim_tick(key: str) -> bool:
    async with SessionFactory.begin() as session:
        session.add(GameTick(tick_key=key))
        try:
            await session.flush()
            return True
        except IntegrityError:
            return False


async def complete_tick(key: str, result: dict | None = None) -> None:
    async with SessionFactory.begin() as session:
        tick = await session.scalar(select(GameTick).where(GameTick.tick_key == key).with_for_update())
        if tick:
            tick.status = "completed"
            tick.result = result or {}
            tick.completed_at = datetime.now(timezone.utc)


async def morning_cycle(bot: Bot) -> None:
    today = local_now().date().isoformat()
    key = f"morning:{today}"
    if not await claim_tick(key):
        return
    lines = ["🗞 <b>روزنامه پایتخت سایه</b>", ""]
    async with SessionFactory.begin() as session:
        state = await session.scalar(select(CityState).where(CityState.id == 1).with_for_update())
        if not state or state.paused or not state.season_id:
            await complete_tick(key, {"skipped": True})
            return
        season = await session.get(Season, state.season_id, with_for_update=True)
        if not season or season.status != "active":
            return
        state.day_number += 1
        state.phase = "mayor_auction"
        state.generator_energy = max(0, state.generator_energy - GENERATOR_DAILY_DRAIN)
        users = {u.id: u for u in (await session.scalars(select(User).where(User.season_id == season.id, User.is_active.is_(True)).with_for_update())).all()}
        properties = list((await session.scalars(select(Property).where(Property.season_id == season.id).with_for_update())).all())
        if state.day_number == 3:
            for prop in properties:
                if not prop.auction_open or prop.owner_id:
                    continue
                bid = await session.scalar(select(PropertyBid).where(PropertyBid.property_id == prop.id).order_by(PropertyBid.amount.desc(), PropertyBid.created_at.asc()).with_for_update())
                if bid:
                    bidder = users.get(bid.user_id)
                    if bidder and bidder.clean_cash >= bid.amount:
                        await change_money(session, bidder, "clean", -bid.amount, f"خرید {prop.name}", f"property-win:{prop.id}")
                        prop.owner_id = bidder.id
                        state.city_treasury += bid.amount
                prop.auction_open = False
        lines.append(f"📆 روز {state.day_number} از {SEASON_DAYS}")
        lines.append(f"⚡ انرژی ژنراتور: {state.generator_energy}/100")
        for user in users.values():
            owns = any(p.owner_id == user.id for p in properties)
            if user.clean_cash + user.dirty_cash + user.vault <= 0 and not owns:
                switch = await session.scalar(select(DeadManSwitch).where(DeadManSwitch.owner_id == user.id, DeadManSwitch.triggered.is_(False)).with_for_update())
                if switch:
                    target = users.get(switch.target_id)
                    if target:
                        if switch.effect == "burn_dirty":
                            target.dirty_cash = max(0, target.dirty_cash - 500)
                        elif switch.effect == "heat":
                            target.heat += 3
                        lines.append(f"💀 ماشه مرد مرده‌ی {user.game_name} فعال شد و یقه {target.game_name} را گرفت.")
                    switch.triggered = True
                user.clean_cash = 1000
                user.dirty_cash = 300
                lines.append(f"🛟 {say('bankrupt', f'{season.id}:{state.day_number}:{user.id}', name=user.game_name)}")
        if state.generator_energy == 0:
            lines.append(f"🏚 {say('generator_dead', f'{season.id}:{state.day_number}')}")
        else:
            paid = 0
            now = datetime.now(timezone.utc)
            for prop in properties:
                if prop.owner_id and prop.owner_id in users and (not prop.disabled_until or prop.disabled_until <= now):
                    income = prop.base_income * prop.level
                    await change_money(session, users[prop.owner_id], "clean", income, f"سود {prop.name}", f"income:{season.id}:{state.day_number}:{prop.id}")
                    paid += income
            lines.append(f"🏢 مجموع {paid:,} پول تمیز از دودکش املاک بیرون آمد.")
        news = list((await session.scalars(select(NewsEntry).where(NewsEntry.season_id == season.id, NewsEntry.game_day == state.day_number - 1, NewsEntry.public.is_(True)).order_by(NewsEntry.id))).all())
        if news:
            lines.extend(["", "🌑 <b>گندکاری‌های شب گذشته:</b>"] + [entry.text for entry in news[-12:]])
        lines.extend(["", "🏛 مزایده شهرداری تا ساعت ۱۱:۳۰ باز است. با <code>/bid مبلغ</code> پیشنهاد بدهید."])
        state.newspaper_text = "\n".join(lines)
        if state.day_number > SEASON_DAYS:
            await finish_season_locked(session, state, season, lines)
    await bot.send_message(settings.group_id, "\n".join(lines), parse_mode="HTML")
    await complete_tick(key, {"lines": len(lines)})


async def finish_season_locked(session, state: CityState, season: Season, lines: list[str]) -> None:
    users = list((await session.scalars(select(User).where(User.season_id == season.id))).all())
    properties = list((await session.scalars(select(Property).where(Property.season_id == season.id))).all())
    prop_count = {u.id: 0 for u in users}
    for prop in properties:
        if prop.owner_id:
            prop_count[prop.owner_id] = prop_count.get(prop.owner_id, 0) + prop.level
    ranked = sorted(users, key=lambda u: (u.clean_cash + u.dirty_cash + u.vault) * 40 + prop_count.get(u.id, 0) * 5000 + u.influence * 1500 + (u.strength + u.defense + u.speed + u.hack_power) * 500, reverse=True)
    if ranked:
        season.winner_user_id = ranked[0].id
        lines.append(f"\n👑 قهرمان فردی فصل: <b>{ranked[0].game_name}</b>")
    alliances = list((await session.scalars(select(Alliance).where(Alliance.season_id == season.id))).all())
    if alliances:
        for alliance in alliances:
            members = [u for u in users if u.alliance_id == alliance.id]
            alliance.score += alliance.treasury + sum(u.influence * 500 + prop_count.get(u.id, 0) * 1200 for u in members)
        winner_alliance = max(alliances, key=lambda x: x.score)
        season.winner_alliance_id = winner_alliance.id
        lines.append(f"🤝 اتحاد برتر فصل: <b>{winner_alliance.name}</b> با {winner_alliance.score:,} امتیاز")
    season.status = "finished"
    season.ends_at = datetime.now(timezone.utc)
    state.phase = "finished"


async def close_mayor_auction(bot: Bot) -> None:
    key = f"mayor:{local_now().date().isoformat()}"
    if not await claim_tick(key):
        return
    message = "🏛 امروز هیچ‌کس حاضر نشد برای شهرداری پول دور بریزد."
    async with SessionFactory.begin() as session:
        state = await session.scalar(select(CityState).where(CityState.id == 1).with_for_update())
        if not state or not state.season_id:
            return
        bid = await session.scalar(select(MayorBid).where(MayorBid.season_id == state.season_id, MayorBid.game_day == state.day_number).order_by(MayorBid.amount.desc(), MayorBid.created_at.asc()).with_for_update())
        if bid:
            winner = await session.get(User, bid.user_id, with_for_update=True)
            if winner and winner.clean_cash >= bid.amount:
                await change_money(session, winner, "clean", -bid.amount, "برد مزایده شهرداری", f"mayor-win:{state.season_id}:{state.day_number}")
                state.city_treasury += bid.amount
                state.mayor_user_id = winner.id
                winner.influence += 2
                choices = []
                cursor = pick_index(f"bill-options:{state.season_id}:{state.day_number}", len(BILL_TEMPLATES))
                for offset in range(3):
                    idx = (cursor + offset) % len(BILL_TEMPLATES)
                    choices.append(idx)
                from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
                markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=BILL_TEMPLATES[idx][0], callback_data=f"billpick:{idx}")] for idx in choices])
                message = f"🎩 <b>{winner.game_name}</b> با پیشنهاد {bid.amount:,} شهردار شد.\nشهردار تا ساعت ۱۲ یکی از لایحه‌های زیر را انتخاب کند؛ وگرنه ربات به جایش تصمیم می‌گیرد."
            else:
                markup = None
        else:
            markup = None
        state.phase = "parliament"
    await bot.send_message(settings.group_id, message, parse_mode="HTML", reply_markup=markup)
    await complete_tick(key)


async def ensure_bill(bot: Bot) -> None:
    async with SessionFactory.begin() as session:
        state = await session.get(CityState, 1, with_for_update=True)
        if not state or not state.season_id or not state.mayor_user_id:
            return
        existing = await session.scalar(select(Bill).where(Bill.season_id == state.season_id, Bill.game_day == state.day_number))
        if existing:
            return
        idx = pick_index(f"default-bill:{state.season_id}:{state.day_number}", len(BILL_TEMPLATES))
        template = BILL_TEMPLATES[idx]
        bill = Bill(season_id=state.season_id, game_day=state.day_number, mayor_id=state.mayor_user_id, title=template[0], bill_type=template[1], description=template[2])
        session.add(bill)
        await session.flush()
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ موافق", callback_data=f"vote:{bill.id}:1"), InlineKeyboardButton(text="❌ مخالف", callback_data=f"vote:{bill.id}:0")]])
        text = f"📜 شهردار خواب ماند؛ ربات لایحه «{bill.title}» را انداخت وسط.\n{bill.description}"
    await bot.send_message(settings.group_id, text, reply_markup=markup)


async def resolve_bill(bot: Bot) -> None:
    key = f"bill:{local_now().date().isoformat()}"
    if not await claim_tick(key):
        return
    text = "📜 امروز لایحه‌ای روی میز نبود."
    async with SessionFactory.begin() as session:
        state = await session.scalar(select(CityState).where(CityState.id == 1).with_for_update())
        if not state or not state.season_id:
            return
        bill = await session.scalar(select(Bill).where(Bill.season_id == state.season_id, Bill.game_day == state.day_number).order_by(Bill.id.desc()).with_for_update())
        if bill:
            yes = await session.scalar(select(func.count(Vote.id)).where(Vote.bill_id == bill.id, Vote.choice.is_(True)))
            no = await session.scalar(select(func.count(Vote.id)).where(Vote.bill_id == bill.id, Vote.choice.is_(False)))
            passed = yes > no and not bill.vetoed_by_id
            bill.status = "passed" if passed else "rejected"
            text = f"📊 لایحه «{bill.title}» با {yes} موافق و {no} مخالف " + ("تصویب شد." if passed else "رفت داخل سطل زباله.")
            if passed:
                await apply_bill(session, state, bill)
        state.phase = "bounty"
    await bot.send_message(settings.group_id, text)
    await complete_tick(key)


async def apply_bill(session, state: CityState, bill: Bill) -> None:
    users = list((await session.scalars(select(User).where(User.season_id == state.season_id, User.is_active.is_(True)).with_for_update())).all())
    if bill.bill_type == "rich_tax":
        for user in sorted(users, key=lambda x: x.clean_cash, reverse=True)[:3]:
            tax = user.clean_cash * 20 // 100
            await change_money(session, user, "clean", -tax, "مالیات لایحه")
            state.city_treasury += tax
    elif bill.bill_type == "poor_relief" and users:
        targets = sorted(users, key=lambda x: x.clean_cash)[:3]
        share = state.city_treasury // len(targets)
        for user in targets:
            await change_money(session, user, "clean", share, "کمک خزانه")
        state.city_treasury -= share * len(targets)
    elif bill.bill_type == "firewall_boost":
        for user in users:
            user.firewall_level += 1
    elif bill.bill_type == "property_freeze":
        props = list((await session.scalars(select(Property).where(Property.season_id == state.season_id, Property.owner_id.is_not(None)).with_for_update())).all())
        if props:
            prop = props[pick_index(f"freeze:{state.season_id}:{state.day_number}", len(props))]
            prop.disabled_until = datetime.now(timezone.utc) + timedelta(hours=24)
    elif bill.bill_type == "upgrade_discount":
        state.upgrade_discount_until = datetime.now(timezone.utc) + timedelta(hours=24)


async def create_bounties(bot: Bot) -> None:
    async with SessionFactory.begin() as session:
        state = await session.get(CityState, 1)
        if not state or not state.season_id:
            return
        users = list((await session.scalars(select(User).where(User.season_id == state.season_id, User.is_active.is_(True)))).all())
        count = 1 if len(users) <= 7 else 2 if len(users) <= 11 else 3
        for i in range(min(count, len(users) // 2)):
            assassin = users[pick_index(f"assassin:{state.season_id}:{state.day_number}:{i}", len(users))]
            candidates = [u for u in users if u.id != assassin.id]
            target = candidates[pick_index(f"target:{state.season_id}:{state.day_number}:{i}", len(candidates))]
            word = BOUNTY_WORDS[pick_index(f"word:{state.season_id}:{state.day_number}:{i}", len(BOUNTY_WORDS))]
            bounty = Bounty(season_id=state.season_id, game_day=state.day_number, assassin_id=assassin.id, target_id=target.id, trigger_type="keyword", trigger_value=word)
            session.add(bounty)
            try:
                await bot.send_message(assassin.telegram_id, f"🔪 مأموریت ترور کلامی\nهدفت: {target.game_name}\nکاری کن تا قبل از ساعت ۱۷ کلمه «{word}» را در گروه بنویسد. لو نرو، نابغه!")
            except TelegramAPIError:
                bounty.status = "delivery_failed"


async def open_fight(bot: Bot) -> None:
    key = f"fight-open:{local_now().date().isoformat()}"
    if not await claim_tick(key):
        return
    async with SessionFactory.begin() as session:
        state = await session.get(CityState, 1)
        if not state or not state.season_id:
            return
        users = list((await session.scalars(select(User).where(User.season_id == state.season_id, User.is_active.is_(True)))).all())
        if len(users) < 2:
            return
        a = users[pick_index(f"fighter-a:{state.day_number}", len(users))]
        candidates = [u for u in users if u.id != a.id]
        b = candidates[pick_index(f"fighter-b:{state.day_number}", len(candidates))]
        fight = Fight(season_id=state.season_id, game_day=state.day_number, fighter_one_id=a.id, fighter_two_id=b.id)
        session.add(fight)
        await session.flush()
        text = f"🥊 فایت‌کلاب باز شد!\n#{fight.id}: {a.game_name} در برابر {b.game_name}\nشرط: /bet {fight.id} TELEGRAM_ID مبلغ\nشرط‌ها ساعت ۱۹:۲۵ بسته می‌شوند."
    await bot.send_message(settings.group_id, text)
    await complete_tick(key)


async def resolve_fight(bot: Bot) -> None:
    key = f"fight:{local_now().date().isoformat()}"
    if not await claim_tick(key):
        return
    async with SessionFactory.begin() as session:
        state = await session.get(CityState, 1)
        if not state or not state.season_id:
            return
        fight = await session.scalar(select(Fight).where(Fight.season_id == state.season_id, Fight.game_day == state.day_number, Fight.status == "betting").order_by(Fight.id.desc()).with_for_update())
        if not fight:
            return
        a = await session.get(User, fight.fighter_one_id, with_for_update=True)
        b = await session.get(User, fight.fighter_two_id, with_for_update=True)
        score_a = a.strength * 3 + a.defense * 2 + a.speed + roll(f"fight:{state.day_number}:a", 20)
        score_b = b.strength * 3 + b.defense * 2 + b.speed + roll(f"fight:{state.day_number}:b", 20)
        winner = a if score_a >= score_b else b
        loser = b if winner is a else a
        winner.influence += 1
        fight.winner_id = winner.id
        fight.status = "resolved"
        fight.narration = f"{winner.game_name} برنده شد"
        bets = list((await session.scalars(select(Bet).where(Bet.fight_id == fight.id).with_for_update())).all())
        winner_pool = sum(x.amount for x in bets if x.fighter_id == winner.id)
        total_pool = sum(x.amount for x in bets)
        for bet in bets:
            if bet.fighter_id == winner.id and winner_pool:
                bettor = await session.get(User, bet.user_id, with_for_update=True)
                payout = bet.amount * total_pool // winner_pool
                bettor.clean_cash += payout
                bet.paid = True
        text = f"🥊 <b>فایت‌کلاب امشب</b>\n\n{say('fight_win', f'{fight.id}', winner=winner.game_name, loser=loser.game_name)}"
    await bot.send_message(settings.group_id, text, parse_mode="HTML")
    await complete_tick(key)


async def market_warning(bot: Bot) -> None:
    now = local_now()
    async with SessionFactory() as session:
        state = await session.get(CityState, 1)
        if not state or now.weekday() not in (state.market_days or []):
            return
    await bot.send_message(settings.group_id, f"🚨 {say('market_warning', str(now.date()))}")


async def open_market(bot: Bot) -> None:
    now = local_now()
    async with SessionFactory.begin() as session:
        state = await session.get(CityState, 1)
        if not state or not state.season_id or now.weekday() not in (state.market_days or []):
            return
        existing = await session.scalar(select(MarketOffer).where(MarketOffer.season_id == state.season_id, MarketOffer.game_day == state.day_number, MarketOffer.active.is_(True)))
        if not existing:
            session.add_all([
                MarketOffer(season_id=state.season_id, game_day=state.day_number, item_code="antidote", title="پادتن ویروس", price_dirty=700, stock=3),
                MarketOffer(season_id=state.season_id, game_day=state.day_number, item_code="tunnel_kit", title="دریل بی‌صدا", price_dirty=1100, stock=2),
                MarketOffer(season_id=state.season_id, game_day=state.day_number, item_code="ghost", title="پاک‌کننده ردپا", price_dirty=900, stock=2),
            ])
        state.phase = "black_market"
    await bot.send_message(settings.group_id, "🛒 بازار سیاه باز شد! فقط ۱۵ دقیقه وقت دارید و هر کله فقط یک جنس انحصاری می‌برد.")


async def close_market(bot: Bot) -> None:
    async with SessionFactory.begin() as session:
        state = await session.get(CityState, 1, with_for_update=True)
        if not state or state.phase != "black_market":
            return
        offers = list((await session.scalars(select(MarketOffer).where(MarketOffer.season_id == state.season_id, MarketOffer.game_day == state.day_number, MarketOffer.active.is_(True)).with_for_update())).all())
        for offer in offers:
            offer.active = False
        state.phase = "underground"
    await bot.send_message(settings.group_id, "🔒 بازار سیاه بسته شد. جا موندی؟ دفعه بعد کمتر بخواب، شاهزاده.")


async def weekly_infection(bot: Bot) -> None:
    key = f"infection:{local_now().isocalendar().year}-{local_now().isocalendar().week}"
    if not await claim_tick(key):
        return
    async with SessionFactory.begin() as session:
        state = await session.get(CityState, 1)
        if not state or not state.season_id:
            return
        users = list((await session.scalars(select(User).where(User.season_id == state.season_id, User.is_active.is_(True)))).all())
        for infection in (await session.scalars(select(Infection).where(Infection.season_id == state.season_id, Infection.active.is_(True)).with_for_update())).all():
            infection.active = False
        count = 2 if len(users) >= 12 else 1
        chosen: set[int] = set()
        for i in range(min(count, len(users))):
            pool = [u for u in users if u.id not in chosen]
            patient = pool[pick_index(f"patient-zero:{key}:{i}", len(pool))]
            chosen.add(patient.id)
            session.add(Infection(season_id=state.season_id, user_id=patient.id))
            try:
                await bot.send_message(patient.telegram_id, "🦠 تبریک، بیمار صفر این هفته‌ای. ساکت باش و بگذار بقیه با ریپلای‌کردن به تو خودشان را بدبخت کنند.")
            except TelegramAPIError:
                infection.active = False
    await bot.send_message(settings.group_id, "🦠 ویروس تازه‌ای وارد شهر شده. بیمار صفر بین شماست و احتمالاً همین الآن دارد ادای آدم سالم درمی‌آورد.")
    await complete_tick(key)


async def weekly_market_days() -> None:
    now = local_now()
    week = f"{now.isocalendar().year}-{now.isocalendar().week}"
    async with SessionFactory.begin() as session:
        state = await session.scalar(select(CityState).where(CityState.id == 1).with_for_update())
        if not state or state.market_week == week:
            return
        first = roll(f"market:{week}:1", 7)
        second = roll(f"market:{week}:2", 6)
        if second >= first:
            second += 1
        state.market_days = sorted([first, second])
        state.market_week = week


def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.timezone, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600})
    jobs = [
        (morning_cycle, {"hour": 9, "minute": 0}, [bot], "morning"),
        (close_mayor_auction, {"hour": 11, "minute": 30}, [bot], "mayor"),
        (ensure_bill, {"hour": 12, "minute": 0}, [bot], "ensure_bill"),
        (resolve_bill, {"hour": 13, "minute": 0}, [bot], "bill"),
        (create_bounties, {"hour": 13, "minute": 5}, [bot], "bounties"),
        (open_fight, {"hour": 17, "minute": 0}, [bot], "fight_open"),
        (resolve_fight, {"hour": 19, "minute": 30}, [bot], "fight"),
        (market_warning, {"hour": 2, "minute": 20}, [bot], "market_warning"),
        (open_market, {"hour": 2, "minute": 30}, [bot], "market"),
        (close_market, {"hour": 2, "minute": 45}, [bot], "market_close"),
        (resolve_night, {"hour": 7, "minute": 30}, [bot], "night"),
        (weekly_market_days, {"day_of_week": "mon", "hour": 0, "minute": 5}, [], "market_days"),
        (weekly_infection, {"day_of_week": "mon", "hour": 9, "minute": 10}, [bot], "infection"),
    ]
    for func_, cron, args, job_id in jobs:
        scheduler.add_job(func_, CronTrigger(timezone=settings.timezone, **cron), args=args, id=job_id, replace_existing=True)
    return scheduler


async def catch_up(bot: Bot) -> None:
    now = local_now()
    minutes = now.hour * 60 + now.minute
    if minutes >= 7 * 60 + 30:
        await resolve_night(bot)
    if minutes >= 9 * 60:
        await morning_cycle(bot)
    if minutes >= 11 * 60 + 30:
        await close_mayor_auction(bot)
    if minutes >= 12 * 60:
        await ensure_bill(bot)
    if minutes >= 13 * 60:
        await resolve_bill(bot)
    if minutes >= 17 * 60:
        await open_fight(bot)
    if minutes >= 19 * 60 + 30:
        await resolve_fight(bot)
