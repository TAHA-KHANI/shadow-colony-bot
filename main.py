import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from database.session import close_db, init_db
from handlers import admin, economy, group_chat, info, private_ops
from services.scheduler import build_scheduler, catch_up, weekly_market_days


async def main() -> None:
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    await init_db()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()
    dispatcher.include_router(admin.router)
    dispatcher.include_router(info.router)
    dispatcher.include_router(private_ops.router)
    dispatcher.include_router(economy.router)
    dispatcher.include_router(group_chat.router)
    scheduler = build_scheduler(bot)
    await weekly_market_days()
    await catch_up(bot)
    scheduler.start()
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
