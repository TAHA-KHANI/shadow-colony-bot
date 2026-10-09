from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message
from sqlalchemy import func, select

from config import settings
from database.models import AdminLog, Season, User
from database.session import SessionFactory
from game.constants import MAX_PLAYERS, MIN_PLAYERS, SEASON_DAYS
from game.randomizer import roll
from services.backup import create_backup, restore_backup
from services.game_service import (
    active_season,
    city,
    initial_property_count,
    seed_properties,
)

router = Router(name="admin")


def allowed(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in settings.admin_ids)


async def deny(message: Message) -> bool:
    if allowed(message):
        return False
    await message.reply("این دکمه برای رئیس شهره؛ تو فعلاً برو عوارضتو بده.")
    return True


async def log_admin(session, message: Message, action: str, details: str) -> None:
    session.add(AdminLog(admin_telegram_id=message.from_user.id, action=action, details=details))


@router.message(Command("newseason"))
async def new_season(message: Message) -> None:
    if await deny(message):
        return
    async with SessionFactory.begin() as session:
        current = await active_season(session)
        if current:
            text = "یک فصل باز یا فعال وجود دارد؛ اول همان را تمام کن."
        else:
            number = (await session.scalar(select(func.max(Season.number)))) or 0
            season = Season(number=number + 1, status="registration")
            session.add(season)
            await session.flush()
            state = await city(session, lock=True)
            state.season_id = season.id
            state.day_number = 0
            state.phase = "registration"
            state.generator_energy = 100
            state.city_treasury = 0
            state.paused = False
            await log_admin(session, message, "newseason", f"فصل {season.number} ساخته شد")
            text = f"📝 ثبت‌نام فصل {season.number} باز شد. همه اول در پی‌وی /start و بعد اینجا /join بزنند."
    await message.bot.send_message(settings.group_id, text)


@router.message(Command("startseason"))
async def start_season(message: Message) -> None:
    if await deny(message):
        return
    async with SessionFactory.begin() as session:
        season = await active_season(session)
        if not season or season.status != "registration":
            text = "فصل در حالت ثبت‌نام نیست."
        else:
            users = list((await session.scalars(select(User).where(User.season_id == season.id, User.is_active.is_(True)).order_by(User.id).with_for_update())).all())
            if not MIN_PLAYERS <= len(users) <= MAX_PLAYERS:
                text = f"برای شروع بین {MIN_PLAYERS} تا {MAX_PLAYERS} بازیکن لازم است؛ الآن {len(users)} نفرند."
            else:
                now = datetime.now(timezone.utc)
                season.status = "active"
                season.starts_at = now
                season.ends_at = now + timedelta(days=SEASON_DAYS)
                state = await city(session, lock=True)
                state.phase = "day"
                properties = await seed_properties(session, season.id)
                count = initial_property_count(len(users))
                selected: set[int] = set()
                for i in range(count):
                    available = [u for u in users if u.id not in selected]
                    winner = available[roll(f"initial-property:{season.id}:{i}", len(available))]
                    selected.add(winner.id)
                    properties[i].owner_id = winner.id
                for user in users:
                    if user.id not in selected:
                        user.clean_cash += 500
                for prop in properties[count:]:
                    prop.auction_open = True
                await log_admin(session, message, "startseason", f"فصل {season.number} با {len(users)} بازیکن شروع شد")
                text = f"🌑 فصل {season.number} با {len(users)} خلافکار شروع شد!\n{count} ملک ضعیف قرعه‌کشی شد و بقیه به‌زودی وارد مزایده می‌شوند. خدا به رفاقت‌هاتون رحم کنه."
    await message.bot.send_message(settings.group_id, text)


@router.message(Command("pausegame"))
async def pause_game(message: Message) -> None:
    if await deny(message):
        return
    async with SessionFactory.begin() as session:
        state = await city(session, lock=True)
        state.paused = True
        await log_admin(session, message, "pause", "بازی متوقف شد")
    await message.bot.send_message(settings.group_id, "⏸ بازی به‌دلیل کار فنی متوقف شد. هیچ عملیات و درآمدی در این فاصله حساب نمی‌شود.")


@router.message(Command("resumegame"))
async def resume_game(message: Message) -> None:
    if await deny(message):
        return
    async with SessionFactory.begin() as session:
        state = await city(session, lock=True)
        state.paused = False
        await log_admin(session, message, "resume", "بازی ادامه یافت")
    await message.bot.send_message(settings.group_id, "▶️ شهر دوباره روشن شد؛ به کثافت‌کاری‌هاتون ادامه بدید.")


@router.message(Command("backup"))
async def backup(message: Message) -> None:
    if await deny(message):
        return
    blob = await create_backup()
    filename = f"shadow-colony-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.scbackup"
    await message.answer_document(BufferedInputFile(blob, filename=filename), caption="🔐 بکاپ رمزگذاری‌شده کامل بازی. این فایل با همان BACKUP_SECRET قابل بازیابی است.")


@router.message(F.document, F.caption.startswith("/restore"))
async def restore(message: Message) -> None:
    if await deny(message):
        return
    stream = BytesIO()
    await message.bot.download(message.document, destination=stream)
    try:
        counts = await restore_backup(stream.getvalue())
        async with SessionFactory.begin() as session:
            await log_admin(session, message, "restore", f"بکاپ با {sum(counts.values())} رکورد بازیابی شد")
        await message.answer(f"✅ بازیابی کامل شد؛ {sum(counts.values()):,} رکورد برگشت.")
    except ValueError as exc:
        await message.answer(f"❌ {exc}")


@router.message(Command("adminlog"))
async def admin_log(message: Message) -> None:
    async with SessionFactory() as session:
        logs = list((await session.scalars(select(AdminLog).order_by(AdminLog.id.desc()).limit(10))).all())
    if not logs:
        await message.reply("هنوز هیچ حرکت ادمینی ثبت نشده.")
        return
    lines = ["🧾 ده حرکت آخر ادمین:"] + [f"• {x.action}: {x.details}" for x in logs]
    await message.reply("\n".join(lines))

