from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select

from database.models import CityState, Inventory, MarketOffer, MarketPurchase, User
from database.session import SessionFactory
from services.game_service import (
    GameError,
    buy_shield,
    create_alliance,
    ensure_user,
    get_user,
    join_alliance,
    register_night_action,
)

router = Router(name="private")
router.message.filter(F.chat.type == "private")


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌑 عملیات شبانه", callback_data="menu:ops"), InlineKeyboardButton(text="🕶 پرونده من", callback_data="menu:profile")],
        [InlineKeyboardButton(text="🛡 خرید سپر", callback_data="buy:shield"), InlineKeyboardButton(text="🛒 بازار سیاه", callback_data="menu:market")],
        [InlineKeyboardButton(text="🤝 اتحاد", callback_data="menu:alliance")],
    ])


@router.message(Command("start"))
async def private_start(message: Message) -> None:
    async with SessionFactory.begin() as session:
        await ensure_user(session, message.from_user, private_started=True)
    await message.answer("🌒 <b>به پایتخت سایه خوش آمدی.</b>\nاینجا یا نقشه می‌کشی، یا سوژه نقشه بقیه می‌شی. بعد از بازشدن ثبت‌نام، داخل گروه /join بزن.", parse_mode="HTML", reply_markup=main_menu())


@router.callback_query(F.data == "menu:profile")
async def private_profile(callback: CallbackQuery) -> None:
    async with SessionFactory() as session:
        user = await get_user(session, callback.from_user.id)
        text = "هنوز عضو فصل نیستی." if not user or not user.season_id else f"🕶 {escape(user.game_name)}\n💵 {user.clean_cash:,} تمیز | 💸 {user.dirty_cash:,} کثیف | 🔐 {user.vault:,}\n⛏ تونل {user.tunnel_progress}٪ | 🎩 نفوذ {user.influence}"
    await callback.message.edit_text(text, reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "menu:ops")
async def operation_menu(callback: CallbackQuery) -> None:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💻 هک", callback_data="optype:hack"), InlineKeyboardButton(text="⚡ DDoS", callback_data="optype:ddos")],
        [InlineKeyboardButton(text="🔎 اسکن", callback_data="optype:scan"), InlineKeyboardButton(text="💰 دزدی", callback_data="optype:steal")],
        [InlineKeyboardButton(text="⛏ حفر تونل", callback_data="opnow:dig"), InlineKeyboardButton(text="🪤 کمین", callback_data="opnow:ambush")],
        [InlineKeyboardButton(text="☎️ مخبری", callback_data="optype:inform"), InlineKeyboardButton(text="🧹 پاکسازی", callback_data="opnow:cleanup")],
        [InlineKeyboardButton(text="◀️ برگشت", callback_data="menu:back")],
    ])
    await callback.message.edit_text("🌑 نقشه امشب را انتخاب کن. فقط یک عملیات اصلی داری:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("optype:"))
async def choose_target(callback: CallbackQuery) -> None:
    action = callback.data.split(":", 1)[1]
    async with SessionFactory() as session:
        me = await get_user(session, callback.from_user.id)
        users = list((await session.scalars(select(User).where(User.season_id == me.season_id, User.is_active.is_(True), User.id != me.id))).all()) if me and me.season_id else []
    rows = [[InlineKeyboardButton(text=u.game_name[:25], callback_data=f"optarget:{action}:{u.id}")] for u in users]
    rows.append([InlineKeyboardButton(text="◀️ برگشت", callback_data="menu:ops")])
    await callback.message.edit_text("قربانی خوش‌شانس را انتخاب کن:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("optarget:"))
async def target_operation(callback: CallbackQuery) -> None:
    _, action, target_id = callback.data.split(":")
    async with SessionFactory.begin() as session:
        user = await get_user(session, callback.from_user.id, lock=True)
        try:
            if not user:
                raise GameError("عضو بازی نیستی.")
            await register_night_action(session, user, action, int(target_id))
            text = "✅ نقشه ثبت شد. تا صبح دهانت را ببند که خودت لو نروی."
        except GameError as exc:
            text = f"❌ {exc}"
    await callback.answer(text, show_alert=True)


@router.callback_query(F.data.startswith("opnow:"))
async def direct_operation(callback: CallbackQuery) -> None:
    action = callback.data.split(":", 1)[1]
    async with SessionFactory.begin() as session:
        user = await get_user(session, callback.from_user.id, lock=True)
        try:
            if not user:
                raise GameError("عضو بازی نیستی.")
            await register_night_action(session, user, action)
            text = "✅ عملیات ثبت شد. حالا برو بخواب، خلافکار خسته."
        except GameError as exc:
            text = f"❌ {exc}"
    await callback.answer(text, show_alert=True)


@router.callback_query(F.data == "buy:shield")
async def shield(callback: CallbackQuery) -> None:
    async with SessionFactory.begin() as session:
        user = await get_user(session, callback.from_user.id, lock=True)
        try:
            if not user:
                raise GameError("عضو بازی نیستی.")
            await buy_shield(session, user)
            text = "🛡 سپر تا پایان شب فعال شد. حالا می‌تونی با ترس کمتری بخوابی."
        except GameError as exc:
            text = f"❌ {exc}"
    await callback.answer(text, show_alert=True)


@router.callback_query(F.data == "menu:market")
async def market(callback: CallbackQuery) -> None:
    async with SessionFactory() as session:
        state = await session.get(CityState, 1)
        offers = list((await session.scalars(select(MarketOffer).where(MarketOffer.season_id == state.season_id, MarketOffer.game_day == state.day_number, MarketOffer.active.is_(True), MarketOffer.stock > 0))).all()) if state and state.phase == "black_market" else []
    if not offers:
        await callback.answer("بازار بسته است؛ قاچاقچی‌ها هم خواب دارند.", show_alert=True)
        return
    rows = [[InlineKeyboardButton(text=f"{o.title} — {o.price_dirty:,}💸 ({o.stock})", callback_data=f"marketbuy:{o.id}")] for o in offers]
    await callback.message.edit_text("🛒 بازار سیاه؛ جنس را بقاپ قبل از اینکه رفیقت بخرد:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("marketbuy:"))
async def market_buy(callback: CallbackQuery) -> None:
    offer_id = int(callback.data.split(":")[1])
    async with SessionFactory.begin() as session:
        user = await get_user(session, callback.from_user.id, lock=True)
        offer = await session.get(MarketOffer, offer_id, with_for_update=True)
        if not user or not offer or not offer.active or offer.stock < 1:
            text = "یکی زودتر قاپیدش."
        elif user.dirty_cash < offer.price_dirty:
            text = "پول کثیفت نمی‌رسد؛ قاچاقچی نسیه نمی‌دهد."
        else:
            previous = await session.scalar(select(MarketPurchase).where(MarketPurchase.season_id == offer.season_id, MarketPurchase.game_day == offer.game_day, MarketPurchase.user_id == user.id))
            if previous:
                await callback.answer("سهم امشبت را خریدی؛ قاچاقچی عمده‌فروش بابات نیست.", show_alert=True)
                return
            user.dirty_cash -= offer.price_dirty
            offer.stock -= 1
            session.add(MarketPurchase(season_id=offer.season_id, game_day=offer.game_day, user_id=user.id, offer_id=offer.id))
            item = await session.scalar(select(Inventory).where(Inventory.user_id == user.id, Inventory.item_code == offer.item_code).with_for_update())
            if item:
                item.quantity += 1
            else:
                session.add(Inventory(user_id=user.id, item_code=offer.item_code, quantity=1))
            text = f"✅ {offer.title} مال تو شد. صدایش را درنیاور."
    await callback.answer(text, show_alert=True)


@router.message(Command("alliance"))
async def alliance_command(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) != 2 or parts[0] not in {"create", "join"}:
        await message.answer("ساخت اتحاد: <code>/alliance create نام</code>\nعضویت: <code>/alliance join CODE</code>", parse_mode="HTML")
        return
    async with SessionFactory.begin() as session:
        user = await get_user(session, message.from_user.id, lock=True)
        try:
            if not user:
                raise GameError("عضو بازی نیستی.")
            alliance = await (create_alliance(session, user, parts[1]) if parts[0] == "create" else join_alliance(session, user, parts[1]))
            text = f"🤝 وارد اتحاد {escape(alliance.name)} شدی. کد دعوت: <code>{alliance.code}</code>"
        except GameError as exc:
            text = f"❌ {escape(str(exc))}"
    await message.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "menu:alliance")
async def alliance_help(callback: CallbackQuery) -> None:
    await callback.message.edit_text("🤝 ساخت اتحاد:\n/alliance create نام\n\nعضویت با کد:\n/alliance join CODE\n\nخیانت شبانه از بخش عملیات باز می‌شود.", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "menu:back")
async def back(callback: CallbackQuery) -> None:
    await callback.message.edit_text("یکی را انتخاب کن، رئیس:", reply_markup=main_menu())
    await callback.answer()

