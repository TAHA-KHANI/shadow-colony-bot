from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select

from database.models import (
    Alliance,
    Bet,
    CityState,
    DeadManSwitch,
    Dossier,
    Fight,
    Infection,
    Inventory,
    Loan,
    Property,
    PropertyBid,
    RouletteDuel,
    User,
)
from database.session import SessionFactory
from game.constants import DOSSIER_QUESTIONS, LAUNDER_FEE_PERCENT, VAULT_FEE_PERCENT
from game.randomizer import pick_index, roll
from game.tone import say
from services.game_service import GameError, change_money, get_user

router = Router(name="economy")


@router.message(Command("vault"))
async def vault(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    if len(parts) != 2 or parts[0] not in {"deposit", "withdraw"}:
        await message.reply("واریز: <code>/vault deposit 1000</code>\nبرداشت: <code>/vault withdraw 1000</code>", parse_mode="HTML")
        return
    try:
        amount = int(parts[1])
    except ValueError:
        amount = 0
    if amount < 100:
        await message.reply("مبلغ باید حداقل ۱۰۰ باشد.")
        return
    async with SessionFactory.begin() as session:
        user = await get_user(session, message.from_user.id, lock=True)
        if not user:
            text = "عضو بازی نیستی."
        else:
            fee = amount * VAULT_FEE_PERCENT // 100
            try:
                if parts[0] == "deposit":
                    await change_money(session, user, "clean", -(amount + fee), "واریز گاوصندوق")
                    await change_money(session, user, "vault", amount, "واریز گاوصندوق")
                    text = f"🔐 {amount:,} داخل گاوصندوق رفت و {fee:,} کارمزد دود شد."
                else:
                    await change_money(session, user, "vault", -amount, "برداشت گاوصندوق")
                    await change_money(session, user, "clean", amount - fee, "برداشت گاوصندوق")
                    text = f"💵 {amount - fee:,} دستت رسید؛ {fee:,} هم سهم زالوهای بانک."
            except GameError as exc:
                text = f"❌ {exc}"
    await message.reply(text)


@router.message(Command("launder"))
async def launder(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    if len(parts) != 2:
        await message.reply("فرمت: <code>/launder PROPERTY_ID مبلغ</code>", parse_mode="HTML")
        return
    try:
        prop_id, amount = map(int, parts)
    except ValueError:
        prop_id = amount = 0
    async with SessionFactory.begin() as session:
        user = await get_user(session, message.from_user.id, lock=True)
        prop = await session.get(Property, prop_id, with_for_update=True)
        if not user or not prop or prop.owner_id != user.id:
            text = "این ملک مال تو نیست؛ پول‌شویی در خشکشویی همسایه نداریم."
        elif amount < 100 or amount > prop.laundering_limit * prop.level:
            text = f"مبلغ نامعتبر است؛ سقف فعلی این ملک {prop.laundering_limit * prop.level:,} است."
        elif user.dirty_cash < amount:
            text = "این‌قدر پول کثیف نداری."
        else:
            clean = amount * (100 - LAUNDER_FEE_PERCENT) // 100
            user.dirty_cash -= amount
            user.clean_cash += clean
            text = f"🧼 {say('launder', f'{user.id}:{prop.id}:{amount}', dirty=amount, clean=clean)}"
    await message.reply(text)


@router.message(Command("upgrade"))
async def upgrade(message: Message, command: CommandObject) -> None:
    try:
        prop_id = int(command.args or "0")
    except ValueError:
        prop_id = 0
    async with SessionFactory.begin() as session:
        user = await get_user(session, message.from_user.id, lock=True)
        prop = await session.get(Property, prop_id, with_for_update=True)
        if not user or not prop or prop.owner_id != user.id:
            text = "ملک معتبر و متعلق به تو نیست."
        elif prop.level >= 3:
            text = "ملک به آخر خط ارتقا رسیده. برج خلیفه که نمی‌سازیم."
        else:
            cost = prop.base_price * prop.level * 70 // 100
            state = await session.get(CityState, 1)
            if state and state.upgrade_discount_until and state.upgrade_discount_until > datetime.now(timezone.utc):
                cost = cost * 80 // 100
            if user.clean_cash < cost:
                text = f"برای ارتقا {cost:,} پول تمیز لازم داری."
            else:
                user.clean_cash -= cost
                prop.level += 1
                text = f"🏗 {say('upgrade', f'{prop.id}:{prop.level}', property=prop.name, level=prop.level)}"
    await message.reply(text)


@router.message(Command("propertybid"))
async def property_bid(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    try:
        prop_id, amount = map(int, parts)
    except (ValueError, TypeError):
        await message.reply("فرمت: <code>/propertybid PROPERTY_ID مبلغ</code>", parse_mode="HTML")
        return
    async with SessionFactory.begin() as session:
        user = await get_user(session, message.from_user.id)
        prop = await session.get(Property, prop_id)
        if not user or not prop or not prop.auction_open or prop.owner_id:
            text = "این ملک در مزایده نیست."
        elif amount < prop.base_price or amount > user.clean_cash:
            text = f"پیشنهاد باید حداقل {prop.base_price:,} و در حد جیب خودت باشد."
        else:
            bid = await session.scalar(select(PropertyBid).where(PropertyBid.property_id == prop.id, PropertyBid.user_id == user.id).with_for_update())
            if bid:
                bid.amount = amount
            else:
                session.add(PropertyBid(property_id=prop.id, user_id=user.id, amount=amount))
            text = f"🏢 پیشنهاد {amount:,} برای {prop.name} مخفیانه ثبت شد."
    await message.reply(text)


@router.message(Command("visit"))
async def visit(message: Message, command: CommandObject) -> None:
    try:
        prop_id = int(command.args or "0")
    except ValueError:
        prop_id = 0
    async with SessionFactory.begin() as session:
        visitor = await get_user(session, message.from_user.id, lock=True)
        prop = await session.get(Property, prop_id, with_for_update=True)
        owner = await session.get(User, prop.owner_id, with_for_update=True) if prop and prop.owner_id else None
        if not visitor or not prop:
            text = "منطقه پیدا نشد."
        elif owner and owner.id != visitor.id:
            toll = min(prop.toll, visitor.clean_cash)
            visitor.clean_cash -= toll
            owner.clean_cash += toll
            text = f"🚕 وارد {prop.name} شدی و {toll:,} عوارض به {owner.game_name} دادی. خوش‌آمدی، بدبخت."
        else:
            text = f"🚶 در {prop.name} قدم زدی؛ کسی هم جیبت را نزد. عجیب بود."
    await message.reply(text)


@router.message(Command("repay"))
async def repay(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    try:
        loan_id, amount = map(int, parts)
    except (ValueError, TypeError):
        await message.reply("فرمت: <code>/repay LOAN_ID مبلغ</code>", parse_mode="HTML")
        return
    async with SessionFactory.begin() as session:
        borrower = await get_user(session, message.from_user.id, lock=True)
        loan = await session.get(Loan, loan_id, with_for_update=True)
        if not borrower or not loan or loan.borrower_id != borrower.id or loan.status != "active":
            text = "وام فعال پیدا نشد."
        else:
            lender = await session.get(User, loan.lender_id, with_for_update=True)
            payment = min(amount, loan.remaining)
            if payment < 1 or borrower.clean_cash < payment:
                text = "مبلغ پرداخت معتبر نیست یا پول نداری."
            else:
                borrower.clean_cash -= payment
                lender.clean_cash += payment
                loan.remaining -= payment
                if loan.remaining == 0:
                    loan.status = "paid"
                text = f"💳 {payment:,} پرداخت شد؛ مانده بدهی {loan.remaining:,}."
    await message.reply(text)


@router.message(Command("bet"))
async def bet(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    try:
        fight_id, fighter_tg, amount = map(int, parts)
    except (ValueError, TypeError):
        await message.reply("فرمت: <code>/bet FIGHT_ID TELEGRAM_ID مبلغ</code>", parse_mode="HTML")
        return
    async with SessionFactory.begin() as session:
        user = await get_user(session, message.from_user.id, lock=True)
        fighter = await get_user(session, fighter_tg)
        fight = await session.get(Fight, fight_id, with_for_update=True)
        if not user or not fighter or not fight or fight.status != "betting" or fighter.id not in {fight.fighter_one_id, fight.fighter_two_id}:
            text = "مبارزه یا فایتر معتبر نیست."
        elif user.id in {fight.fighter_one_id, fight.fighter_two_id}:
            text = "فایتر روی دعوای خودش شرط نمی‌بندد؛ خیلی تابلوئه."
        elif amount < 100 or user.clean_cash < amount:
            text = "شرط حداقل ۱۰۰ است و باید پولش را داشته باشی."
        else:
            existing = await session.scalar(select(Bet).where(Bet.fight_id == fight.id, Bet.user_id == user.id))
            if existing:
                text = "برای این مبارزه قبلاً شرط بستی."
            else:
                user.clean_cash -= amount
                session.add(Bet(fight_id=fight.id, user_id=user.id, fighter_id=fighter.id, amount=amount))
                text = f"🎰 {amount:,} روی {fighter.game_name} رفت. اگر کتک خورد، پولت هم همراهش می‌رود."
    await message.reply(text)


@router.message(Command("roulette"))
async def roulette(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    try:
        target_tg, wager = map(int, parts)
    except (ValueError, TypeError):
        await message.reply("فرمت: <code>/roulette TELEGRAM_ID مبلغ</code>", parse_mode="HTML")
        return
    async with SessionFactory.begin() as session:
        challenger = await get_user(session, message.from_user.id)
        opponent = await get_user(session, target_tg)
        if not challenger or not opponent or wager < 100 or challenger.dirty_cash < wager:
            text = "دعوت معتبر نیست یا پول کثیفت کافی نیست."
        else:
            duel = RouletteDuel(challenger_id=challenger.id, opponent_id=opponent.id, wager=wager)
            session.add(duel)
            await session.flush()
            text = f"🔫 دوئل #{duel.id} برای {opponent.game_name} ثبت شد. قبول: /acceptroulette {duel.id}"
    await message.reply(text)


@router.message(Command("acceptroulette"))
async def accept_roulette(message: Message, command: CommandObject) -> None:
    try:
        duel_id = int(command.args or "0")
    except ValueError:
        duel_id = 0
    async with SessionFactory.begin() as session:
        opponent = await get_user(session, message.from_user.id, lock=True)
        duel = await session.get(RouletteDuel, duel_id, with_for_update=True)
        if not opponent or not duel or duel.opponent_id != opponent.id or duel.status != "offered":
            text = "دوئل معتبر نیست."
        else:
            challenger = await session.get(User, duel.challenger_id, with_for_update=True)
            if challenger.dirty_cash < duel.wager or opponent.dirty_cash < duel.wager:
                duel.status = "cancelled"
                text = "یکی از دو نفر تا لحظه قبول پولش را خورده؛ دوئل لغو شد."
            else:
                loser = challenger if roll(f"roulette:{duel.id}", 2) == 0 else opponent
                winner = opponent if loser is challenger else challenger
                loser.dirty_cash -= duel.wager
                winner.dirty_cash += duel.wager
                loser.jailed_until = datetime.now(timezone.utc) + timedelta(hours=4)
                duel.loser_id = loser.id
                duel.status = "resolved"
                text = f"🔫 {say('roulette', str(duel.id), loser=loser.game_name, winner=winner.game_name, amount=duel.wager)}"
    await message.reply(text)


@router.message(Command("dossier"))
async def dossier(message: Message, command: CommandObject) -> None:
    try:
        target_tg = int(command.args or "0")
    except ValueError:
        target_tg = 0
    async with SessionFactory.begin() as session:
        owner = await get_user(session, message.from_user.id)
        subject = await get_user(session, target_tg)
        if not owner or not subject or owner.dirty_cash < 800:
            text = "هدف معتبر نیست یا ۸۰۰ پول کثیف نداری."
        else:
            owner.dirty_cash -= 800
            question = DOSSIER_QUESTIONS[pick_index(f"dossier:{owner.id}:{subject.id}:{datetime.now(timezone.utc).date()}", len(DOSSIER_QUESTIONS))]
            item = Dossier(season_id=owner.season_id, owner_id=owner.id, subject_id=subject.id, question=question)
            session.add(item)
            await session.flush()
            text = f"📁 پرونده #{item.id} باز شد. سؤال برای {subject.game_name}:\n{question}\nاو می‌تواند در پی‌وی با /answerdossier {item.id} پاسخ بدهد یا رد کند."
            try:
                await message.bot.send_message(subject.telegram_id, text)
            except TelegramAPIError:
                text += "\n⚠️ هدف هنوز پی‌وی ربات را باز نکرده و سؤال به او نرسید."
    await message.reply(text)


@router.message(Command("answerdossier"))
async def answer_dossier(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.reply("فرمت: /answerdossier ID پاسخ — برای ردکردن پاسخ بنویس: رد")
        return
    try:
        dossier_id = int(parts[0])
    except ValueError:
        return
    async with SessionFactory.begin() as session:
        user = await get_user(session, message.from_user.id, lock=True)
        item = await session.get(Dossier, dossier_id, with_for_update=True)
        if not user or not item or item.subject_id != user.id or item.status != "sealed":
            text = "پرونده معتبر نیست."
        elif parts[1].strip() == "رد":
            fine = min(400, user.clean_cash)
            user.clean_cash -= fine
            item.answer = "هدف پاسخ را رد کرد و جریمه داد."
            item.status = "answered"
            text = f"پاسخ رد شد و {fine:,} جریمه دادی."
        else:
            item.answer = parts[1][:1000]
            item.status = "answered"
            text = "پاسخ مهروموم شد و فقط صاحب پرونده می‌تواند افشایش کند."
    await message.reply(text)


@router.message(Command("leak"))
async def leak(message: Message, command: CommandObject) -> None:
    try:
        dossier_id = int(command.args or "0")
    except ValueError:
        dossier_id = 0
    async with SessionFactory.begin() as session:
        owner = await get_user(session, message.from_user.id)
        item = await session.get(Dossier, dossier_id, with_for_update=True)
        if not owner or not item or item.owner_id != owner.id or item.status != "answered":
            text = "پرونده آماده افشا نیست."
        else:
            subject = await session.get(User, item.subject_id)
            item.status = "leaked"
            text = f"📢 افشای پرونده {subject.game_name}\n\nسؤال: {item.question}\nپاسخ: {item.answer}"
    await message.bot.send_message(message.chat.id, text)


@router.message(Command("use"))
async def use_item(message: Message, command: CommandObject) -> None:
    code = (command.args or "").strip().lower()
    async with SessionFactory.begin() as session:
        user = await get_user(session, message.from_user.id, lock=True)
        item = await session.scalar(select(Inventory).where(Inventory.user_id == user.id, Inventory.item_code == code).with_for_update()) if user else None
        if not user or not item or item.quantity < 1:
            text = "این آیتم را نداری."
        elif code == "antidote":
            infection = await session.scalar(select(Infection).where(Infection.user_id == user.id, Infection.active.is_(True)).with_for_update())
            if not infection:
                text = "ویروسی نیستی؛ پادتن را الکی نخور نابغه."
            else:
                infection.active = False
                infection.immune_until = datetime.now(timezone.utc) + timedelta(days=2)
                item.quantity -= 1
                text = "💉 پادتن زدی؛ دو روز از این سیرک ویروسی مصونی."
        elif code == "tunnel_kit":
            user.tunnel_progress = min(100, user.tunnel_progress + 8)
            item.quantity -= 1
            text = "⛏ دریل بی‌صدا ۸٪ تونلت را جلو برد. همسایه پایین رسماً شاکی است."
        elif code == "ghost":
            user.heat = max(0, user.heat - 4)
            item.quantity -= 1
            text = "👻 بخشی از ردپاهایت پاک شد. پلیس فعلاً دنبال یک بدبخت دیگر رفت."
        else:
            text = "این آیتم مصرف مستقیم ندارد."
    await message.reply(text)


@router.message(Command("alliancefund"))
async def alliance_fund(message: Message, command: CommandObject) -> None:
    try:
        amount = int(command.args or "0")
    except ValueError:
        amount = 0
    async with SessionFactory.begin() as session:
        user = await get_user(session, message.from_user.id, lock=True)
        alliance = await session.get(Alliance, user.alliance_id, with_for_update=True) if user and user.alliance_id else None
        if not alliance or amount < 100 or user.clean_cash < amount:
            text = "اتحاد نداری یا مبلغ معتبر نیست."
        else:
            user.clean_cash -= amount
            alliance.treasury += amount
            alliance.score += amount // 10
            text = f"🤝 {amount:,} به خزانه {alliance.name} رفت. امیدوارم رهبرت مار نباشه."
    await message.reply(text)


@router.message(Command("deadman"))
async def deadman(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    if len(parts) != 2 or parts[1] not in {"burn_dirty", "heat"}:
        await message.reply("فرمت: <code>/deadman TELEGRAM_ID burn_dirty</code> یا <code>heat</code>", parse_mode="HTML")
        return
    try:
        target_tg = int(parts[0])
    except ValueError:
        return
    async with SessionFactory.begin() as session:
        owner = await get_user(session, message.from_user.id)
        target = await get_user(session, target_tg)
        if not owner or not target or owner.id == target.id:
            text = "هدف معتبر نیست."
        else:
            switch = await session.scalar(select(DeadManSwitch).where(DeadManSwitch.owner_id == owner.id).with_for_update())
            if switch:
                switch.target_id = target.id
                switch.effect = parts[1]
                switch.triggered = False
            else:
                session.add(DeadManSwitch(season_id=owner.season_id, owner_id=owner.id, target_id=target.id, effect=parts[1]))
            text = "💀 ماشه مرد مرده تنظیم شد. امیدواریم هیچ‌وقت آن‌قدر بدبخت نشوی که فعال شود."
    await message.reply(text)
