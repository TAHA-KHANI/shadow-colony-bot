from html import escape

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from database.models import CityState, User
from database.session import SessionFactory

router = Router(name="info")


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    if message.chat.type == "private":
        text = (
            "🕶 <b>راهنمای پی‌وی پایتخت سایه</b>\n\n"
            "از دکمه‌های زیر پیام اول برای عملیات شبانه، خرید سپر، بازار سیاه و دیدن پرونده استفاده کن.\n\n"
            "<b>دستورهای شخصی:</b>\n"
            "/vault — واریز یا برداشت گاوصندوق\n"
            "/launder — شستن پول کثیف با ملک\n"
            "/alliance — ساخت یا عضویت در اتحاد\n"
            "/alliancefund — کمک به خزانه اتحاد\n"
            "/dossier — خرید پرونده برای یک نفر\n"
            "/answerdossier — پاسخ به پرونده\n"
            "/use — مصرف آیتم بازار سیاه\n"
            "/deadman — تنظیم ماشه مرد مرده\n"
            "/players — فهرست بازیکن‌ها و شناسه‌ها\n"
            "/rules — قوانین و هدف بازی\n\n"
            "عملیات محرمانه را در گروه ننویس، کصخل؛ برای همین پی‌وی ساخته شده."
        )
    else:
        text = (
            "🏙 <b>راهنمای گروه پایتخت سایه</b>\n\n"
            "/join — ثبت‌نام فصل\n"
            "/me — پول، قدرت و وضعیت خودت\n"
            "/players — بازیکن‌ها و شناسه‌هایشان\n"
            "/properties — فهرست املاک شهر\n"
            "/fund_generator — شارژ ژنراتور\n"
            "/bid — پیشنهاد مزایده شهرداری\n"
            "/veto — وتوی لایحه\n"
            "/propertybid — پیشنهاد خرید ملک\n"
            "/upgrade — ارتقای ملک\n"
            "/visit — ورود به یک منطقه\n"
            "/loan و /acceptloan و /repay — وام\n"
            "/bet — شرط فایت‌کلاب\n"
            "/roulette و /acceptroulette — رولت روسی\n"
            "/leak — افشای یک پرونده\n"
            "/rules — قوانین و ساعت‌های بازی\n\n"
            "هک، تونل، مخبری، سپر و بازار سیاه از منوی پی‌وی انجام می‌شوند."
        )
    await message.reply(text)


@router.message(Command("rules"))
async def rules_command(message: Message) -> None:
    text = (
        "📕 <b>قوانین پایتخت سایه</b>\n\n"
        "• فصل ۲۱ روز است و کسی برای همیشه حذف نمی‌شود.\n"
        "• برنده فردی با ثروت، املاک، نفوذ و قدرت مشخص می‌شود؛ تکمیل تونل ۱۰۰٪ برد فوری است.\n"
        "• اتحادها جدول امتیاز جدا دارند، ولی اعضا می‌توانند به هم خیانت کنند.\n"
        "• پول کثیف را باید با ملک و ۱۵٪ کارمزد بشویی.\n"
        "• گاوصندوق امن‌تر است، ولی واریز و برداشت ۱۰٪ کارمزد دارد.\n"
        "• حمله آزاد است؛ سپر بخری، حمله همان شب به گه می‌رود.\n"
        "• ورشکستگی باعث حذف نمی‌شود و بسته برگشت می‌گیری.\n\n"
        "⏰ <b>برنامه روزانه تهران</b>\n"
        "۰۹:۰۰ روزنامه، سود املاک و شروع شهرداری\n"
        "۱۱:۳۰ تعیین شهردار\n"
        "۱۲:۰۰ تا ۱۳:۰۰ رأی‌گیری لایحه\n"
        "۱۳:۰۰ تا ۱۷:۰۰ ترور کلامی\n"
        "۱۷:۰۰ تا ۱۹:۳۰ فایت‌کلاب و شرط‌بندی\n"
        "۲۰:۰۰ تا ۰۱:۳۰ ثبت عملیات شبانه\n"
        "۰۲:۳۰ دو شب تصادفی در هفته بازار سیاه\n"
        "۰۷:۳۰ حل عملیات شبانه"
    )
    await message.reply(text)


@router.message(Command("players"))
async def players_command(message: Message) -> None:
    async with SessionFactory() as session:
        state = await session.get(CityState, 1)
        users = list((await session.scalars(select(User).where(User.season_id == state.season_id, User.is_active.is_(True)).order_by(User.id))).all()) if state and state.season_id else []
    if not users:
        await message.reply("هنوز هیچ خلافکاری برای این فصل ثبت‌نام نکرده.")
        return
    lines = ["👥 <b>بازیکنان این فصل</b>"]
    for index, user in enumerate(users, 1):
        username = f"@{escape(user.username)}" if user.username else "بدون یوزرنیم"
        lines.append(f"{index}. {escape(user.game_name)} — {username} — <code>{user.telegram_id}</code>")
    lines.append("\nبرای دستورهایی که هدف می‌خواهند، همین شناسه عددی را وارد کنید.")
    await message.reply("\n".join(lines))

