from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message, ReactionTypeEmoji
from sqlalchemy import select

from config import settings
from database.models import (
    Bill,
    Bounty,
    CityState,
    Dossier,
    Infection,
    Loan,
    MayorBid,
    Property,
    User,
    Vote,
)
from database.session import SessionFactory
from game.constants import (
    BILL_TEMPLATES,
    MAX_LOAN_DAYS,
    MAX_LOAN_INTEREST,
    MIN_LOAN_DAYS,
)
from game.randomizer import chance
from services.game_service import (
    GameError,
    ensure_user,
    fund_generator,
    get_user,
    join_registration,
)

router = Router(name="group")
router.message.filter(F.chat.id == settings.group_id)


@router.message(Command("join"))
async def join_game(message: Message) -> None:
    async with SessionFactory.begin() as session:
        user = await ensure_user(session, message.from_user)
        try:
            await join_registration(session, user)
            text = f"✅ {escape(user.game_name)} وارد پایتخت سایه شد. هنوز فرصت داری فرار کنی؛ ولی خب مغز نداری."
        except GameError as exc:
            text = f"❌ {escape(str(exc))}"
    await message.reply(text, parse_mode="HTML")


@router.message(Command("me"))
async def profile(message: Message) -> None:
    async with SessionFactory() as session:
        user = await get_user(session, message.from_user.id)
        if not user or not user.season_id:
            await message.reply("هنوز عضو فصل نیستی. اول پی‌وی /start و بعد اینجا /join بزن.")
            return
        props = list((await session.scalars(select(Property).where(Property.owner_id == user.id))).all())
        jailed = "آره، آب خنک بخور" if user.jailed_until and user.jailed_until > datetime.now(timezone.utc) else "نه"
        text = (
            f"🕶 <b>پرونده {escape(user.game_name)}</b>\n\n"
            f"💵 تمیز: <code>{user.clean_cash:,}</code>\n💸 کثیف: <code>{user.dirty_cash:,}</code>\n"
            f"🔐 گاوصندوق: <code>{user.vault:,}</code>\n🏢 املاک: {len(props)}\n"
            f"💪 قدرت {user.strength} | 🛡 دفاع {user.defense} | ⚡ سرعت {user.speed}\n"
            f"💻 هک {user.hack_power} | 🔥 فایروال {user.firewall_level}\n"
            f"🎩 نفوذ: {user.influence} | ⛏ تونل: {user.tunnel_progress}٪\n"
            f"🚔 زندانی: {jailed}"
        )
    await message.reply(text, parse_mode="HTML")


@router.message(Command("properties"))
async def properties(message: Message) -> None:
    async with SessionFactory() as session:
        state = await session.get(CityState, 1)
        if not state or not state.season_id:
            await message.reply("فعلاً شهری وجود ندارد.")
            return
        props = list((await session.scalars(select(Property).where(Property.season_id == state.season_id).order_by(Property.id))).all())
        owners = {u.id: u.game_name for u in (await session.scalars(select(User).where(User.season_id == state.season_id))).all()}
        lines = ["🏙 <b>نقشه املاک شهر</b>"]
        for p in props:
            lines.append(f"\n<b>{p.id}. {escape(p.name)}</b> — سطح {p.level}\nمالک: {escape(owners.get(p.owner_id, 'بی‌صاحب'))} | سود: {p.base_income * p.level:,}")
    await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(Command("fund_generator"))
async def generator_fund(message: Message, command: CommandObject) -> None:
    try:
        amount = int((command.args or "0").strip())
    except ValueError:
        amount = 0
    async with SessionFactory.begin() as session:
        user = await get_user(session, message.from_user.id, lock=True)
        if not user:
            text = "اول عضو بازی شو."
        else:
            try:
                energy = await fund_generator(session, user, amount)
                text = f"⚡ {escape(user.game_name)} با {amount:,} پول، {energy} واحد جان به ژنراتور داد. قهرمان برق منطقه!"
            except GameError as exc:
                text = f"❌ {escape(str(exc))}\nنمونه: <code>/fund_generator 400</code>"
    await message.reply(text, parse_mode="HTML")


@router.message(Command("bid"))
async def mayor_bid(message: Message, command: CommandObject) -> None:
    try:
        amount = int((command.args or "0").strip())
    except ValueError:
        amount = 0
    if amount < 100:
        await message.reply("کمتر از ۱۰۰؟ با پول آدامس می‌خوای شهردار شی؟ نمونه: /bid 1200")
        return
    async with SessionFactory.begin() as session:
        state = await session.get(CityState, 1)
        user = await get_user(session, message.from_user.id, lock=True)
        if not state or state.phase != "mayor_auction" or not user:
            text = "مزایده الآن باز نیست."
        elif user.clean_cash < amount:
            text = "پولش را نداری؛ عدد درشت نوشتن که ثروت حساب نمی‌شود."
        else:
            bid = await session.scalar(select(MayorBid).where(MayorBid.season_id == state.season_id, MayorBid.game_day == state.day_number, MayorBid.user_id == user.id).with_for_update())
            if bid:
                bid.amount = amount
            else:
                session.add(MayorBid(season_id=state.season_id, game_day=state.day_number, user_id=user.id, amount=amount))
            text = f"🎩 پیشنهاد {amount:,} ثبت شد. تا پایان مزایده کسی مبلغت را نمی‌بیند."
    await message.reply(text)


@router.callback_query(F.data.startswith("vote:"))
async def vote_bill(callback: CallbackQuery) -> None:
    _, bill_id, choice = callback.data.split(":")
    async with SessionFactory.begin() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            text = "عضو بازی نیستی."
        else:
            vote = await session.scalar(select(Vote).where(Vote.bill_id == int(bill_id), Vote.user_id == user.id).with_for_update())
            if vote:
                vote.choice = choice == "1"
            else:
                session.add(Vote(bill_id=int(bill_id), user_id=user.id, choice=choice == "1"))
            text = "رأیت ثبت شد؛ امیدوارم فردا از انتخابت خجالت نکشی."
    await callback.answer(text, show_alert=True)


@router.callback_query(F.data.startswith("billpick:"))
async def pick_bill(callback: CallbackQuery) -> None:
    idx = int(callback.data.split(":")[1])
    async with SessionFactory.begin() as session:
        state = await session.get(CityState, 1, with_for_update=True)
        user = await get_user(session, callback.from_user.id)
        existing = await session.scalar(select(Bill).where(Bill.season_id == state.season_id, Bill.game_day == state.day_number)) if state else None
        if not state or not user or state.mayor_user_id != user.id:
            await callback.answer("تو شهردار نیستی؛ دستت را از قانون بکش.", show_alert=True)
            return
        if existing:
            await callback.answer("لایحه امروز قبلاً انتخاب شده.", show_alert=True)
            return
        template = BILL_TEMPLATES[idx]
        bill = Bill(season_id=state.season_id, game_day=state.day_number, mayor_id=user.id, title=template[0], bill_type=template[1], description=template[2])
        session.add(bill)
        await session.flush()
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ موافق", callback_data=f"vote:{bill.id}:1"), InlineKeyboardButton(text="❌ مخالف", callback_data=f"vote:{bill.id}:0")]])
        await callback.message.edit_text(f"📜 شهردار لایحه «{bill.title}» را انداخت وسط.\n{bill.description}\n\nتا ساعت ۱۳ رأی بدهید.", reply_markup=markup)
    await callback.answer("لایحه ثبت شد.")


@router.message(Command("veto"))
async def veto_bill(message: Message, command: CommandObject) -> None:
    try:
        bill_id = int(command.args or "0")
    except ValueError:
        bill_id = 0
    async with SessionFactory.begin() as session:
        user = await get_user(session, message.from_user.id, lock=True)
        bill = await session.get(Bill, bill_id, with_for_update=True)
        dossier = await session.scalar(select(Dossier).where(Dossier.owner_id == user.id, Dossier.status == "answered").with_for_update()) if user else None
        if not user or not bill or bill.status != "voting" or bill.vetoed_by_id:
            text = "لایحه قابل وتو نیست."
        elif user.influence >= 3:
            user.influence -= 3
            bill.vetoed_by_id = user.id
            text = f"🛑 {user.game_name} سه نفوذ خرج کرد و لایحه را فرستاد ته چاه."
        elif dossier:
            dossier.status = "spent"
            bill.vetoed_by_id = user.id
            text = f"📁 {user.game_name} یک پرونده رو کرد و لایحه وتو شد. چه توی پرونده بود؟ فضولی نکن."
        else:
            text = "برای وتو سه نفوذ یا یک پرونده آماده لازم داری."
    await message.reply(text)


@router.message(Command("loan"))
async def offer_loan(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    if len(parts) != 4:
        await message.reply("فرمت: <code>/loan USER_ID مبلغ سود روز</code>\nمثال: <code>/loan 123456789 1000 15 3</code>", parse_mode="HTML")
        return
    try:
        target_tg, amount, interest, days = map(int, parts)
    except ValueError:
        await message.reply("همه مقدارها باید عدد باشند.")
        return
    if amount < 100 or not 0 <= interest <= MAX_LOAN_INTEREST or not MIN_LOAN_DAYS <= days <= MAX_LOAN_DAYS:
        await message.reply("مبلغ حداقل ۱۰۰، سود ۰ تا ۳۰٪ و مهلت ۱ تا ۷ روز است.")
        return
    async with SessionFactory.begin() as session:
        lender = await get_user(session, message.from_user.id)
        borrower = await get_user(session, target_tg)
        if not lender or not borrower or lender.season_id != borrower.season_id:
            text = "وام‌دهنده یا وام‌گیرنده عضو همین فصل نیست."
        elif lender.clean_cash < amount:
            text = "خودت پول نداری، بانک مرکزی بازی شدی؟"
        else:
            due = datetime.now(timezone.utc) + timedelta(days=days)
            loan = Loan(lender_id=lender.id, borrower_id=borrower.id, principal=amount, interest_percent=interest, remaining=amount * (100 + interest) // 100, due_at=due)
            session.add(loan)
            await session.flush()
            text = f"🤝 پیشنهاد وام #{loan.id} برای {borrower.game_name} ثبت شد. او باید با /acceptloan {loan.id} قبول کند."
    await message.reply(text)


@router.message(Command("acceptloan"))
async def accept_loan(message: Message, command: CommandObject) -> None:
    try:
        loan_id = int(command.args or "0")
    except ValueError:
        loan_id = 0
    async with SessionFactory.begin() as session:
        borrower = await get_user(session, message.from_user.id, lock=True)
        loan = await session.get(Loan, loan_id, with_for_update=True)
        if not borrower or not loan or loan.borrower_id != borrower.id or loan.status != "offered":
            text = "پیشنهاد معتبر نیست."
        else:
            lender = await session.get(User, loan.lender_id, with_for_update=True)
            if not lender or lender.clean_cash < loan.principal:
                text = "وام‌دهنده تا تو تصمیم بگیری پول‌ها را خورده؛ معامله لغو شد."
                loan.status = "cancelled"
            else:
                lender.clean_cash -= loan.principal
                borrower.clean_cash += loan.principal
                loan.status = "active"
                text = f"✅ وام #{loan.id} فعال شد؛ {loan.remaining:,} باید تا موعد پس بدهی."
    await message.reply(text)


@router.message(F.text | F.voice | F.sticker)
async def group_listener(message: Message) -> None:
    if message.text and message.text.startswith("/"):
        return
    announcements: list[str] = []
    async with SessionFactory.begin() as session:
        user = await get_user(session, message.from_user.id, lock=True)
        if not user or not user.season_id:
            return
        state = await session.get(CityState, 1)
        if not state:
            return
        bounties = list((await session.scalars(select(Bounty).where(Bounty.season_id == user.season_id, Bounty.game_day == state.day_number, Bounty.target_id == user.id, Bounty.status == "active").with_for_update())).all())
        text_lower = (message.text or message.caption or "").casefold()
        for bounty in bounties:
            hit = bounty.trigger_type == "keyword" and bounty.trigger_value and bounty.trigger_value.casefold() in text_lower
            if hit:
                assassin = await session.get(User, bounty.assassin_id, with_for_update=True)
                if assassin:
                    assassin.dirty_cash += bounty.reward
                    user.clean_cash = max(0, user.clean_cash - 200)
                    bounty.status = "completed"
                    announcements.append(f"🔪 {assassin.game_name} کاری کرد {user.game_name} کلمه ممنوعه را بگوید و {bounty.reward:,} پول کثیف گرفت!")

        infected = await session.scalar(select(Infection).where(Infection.user_id == user.id, Infection.active.is_(True)))
        reply_user_id = message.reply_to_message.from_user.id if message.reply_to_message and message.reply_to_message.from_user else None
        if reply_user_id:
            source = await get_user(session, reply_user_id)
            source_infected = await session.scalar(select(Infection).where(Infection.user_id == source.id, Infection.active.is_(True))) if source else None
            if source_infected and not infected and chance(f"infection:reply:{message.chat.id}:{message.message_id}", 40):
                session.add(Infection(season_id=user.season_id, user_id=user.id, infected_by_id=source.id))
                announcements.append(f"🦠 {user.game_name} با یک ریپلای ساده ویروسی شد. تبریک به سیستم ایمنی تعطیلش!")
        if infected and chance(f"clown:{message.message_id}", 35):
            try:
                await message.bot.set_message_reaction(message.chat.id, message.message_id, [ReactionTypeEmoji(emoji="🤡")])
            except TelegramAPIError:
                announcements.append(f"🤡 پیام {user.game_name} بوی ویروس می‌دهد؛ زیاد نزدیک نشوید.")
    for text in announcements:
        await message.reply(text)

