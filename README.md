# پایتخت سایه: کلونی تبهکاران

ربات گروهی فارسی برای ۵ تا ۱۵ بازیکن، ساخته‌شده با Python، aiogram 3، PostgreSQL، SQLAlchemy Async و APScheduler. بازی با Long Polling اجرا می‌شود و به دامنه یا Webhook نیاز ندارد.

## امکانات

- فصل‌های ۲۱ روزه با قهرمان فردی و اتحاد برتر
- پول تمیز، پول کثیف، گاوصندوق، پول‌شویی و دفتر تراکنش‌ها
- ۱۰ منطقه شهری، مزایده، سود، ارتقا، عوارض و ژنراتور مشترک
- مزایده شهردار، لایحه، رأی و وتو
- هک، DDoS، اسکن، دزدی، کمین، تونل، مخبری و پاکسازی
- فایت‌کلاب و شرط‌بندی
- مأموریت ترور کلامی و ویروس گروهی
- بازار سیاه زنده در دو شب تصادفی هفته
- رولت روسی دوستانه، وام، پرونده باج‌گیری و ماشه مرد مرده
- اتحاد رسمی، خزانه مشترک، امتیاز اتحاد و خیانت
- روزنامه صبحگاهی با افشای نیمه‌محرمانه
- بسته لحن رفاقتی بسیار بی‌پرده با طنز سیاه؛ بدون توهین ناموسی، خانوادگی، قومی یا نژادی
- بکاپ رمزگذاری‌شده و بازیابی برای انتقال بین سرویس‌ها
- پنل ادمین بدون نمایش عملیات مخفی بازیکنان

## ساخت ربات تلگرام

1. در `@BotFather` یک ربات بسازید و Token را بگیرید.
2. با `/setprivacy` حالت Privacy را خاموش کنید.
3. ربات را ادمین گروه کنید تا همه پیام‌ها و واکنش‌ها را دریافت کند.
4. همه بازیکنان باید ابتدا در پی‌وی ربات `/start` بزنند.

## متغیرهای Railway

یک PostgreSQL به پروژه اضافه کنید و این متغیرها را در سرویس ربات قرار دهید:

```env
BOT_TOKEN=توکن ربات
DATABASE_URL=${{Postgres.DATABASE_URL}}
GROUP_ID=-100xxxxxxxxxx
ADMIN_IDS=telegram_id_1,telegram_id_2
GAME_SECRET=یک رشته تصادفی طولانی
BACKUP_SECRET=یک رشته تصادفی طولانی دیگر
LOG_LEVEL=INFO
```

`GROUP_ID` شناسه عددی گروه است. `ADMIN_IDS` فقط برای شروع، توقف، بکاپ و بازیابی استفاده می‌شود. ادمین از داخل ربات به عملیات مخفی دسترسی ندارد.

## دیپلوی Railway

1. پروژه را در GitHub قرار دهید.
2. در Railway گزینه Deploy from GitHub را انتخاب کنید.
3. یک PostgreSQL به همان Project اضافه کنید.
4. متغیرهای بالا را ثبت کنید.
5. Railway به‌صورت خودکار Dockerfile را اجرا می‌کند.

ربات در شروع، جداول جدید را ایجاد می‌کند. برای ارتقای نسخه‌های بعدی می‌توان قبل از استارت دستور زیر را اجرا کرد:

```bash
alembic upgrade head
```

## شروع فصل

ترتیب دستورات:

1. ادمین در گروه: `/newseason`
2. هر بازیکن در پی‌وی: `/start`
3. هر بازیکن در گروه: `/join`
4. پس از رسیدن تعداد به ۵ تا ۱۵ نفر، ادمین: `/startseason`

## دستورات مهم

### عمومی

- `/help` راهنمای دستورها
- `/rules` قوانین و برنامه زمانی بازی
- `/players` فهرست بازیکنان و شناسه‌ها
- `/me` پرونده بازیکن
- `/properties` املاک شهر
- `/fund_generator 400` کمک به ژنراتور
- `/bid 1200` پیشنهاد شهرداری
- `/veto BILL_ID` وتوی لایحه
- `/propertybid PROPERTY_ID AMOUNT` پیشنهاد خرید ملک
- `/upgrade PROPERTY_ID` ارتقای ملک
- `/visit PROPERTY_ID` ورود و پرداخت عوارض
- `/vault deposit 1000` و `/vault withdraw 1000`
- `/launder PROPERTY_ID AMOUNT` پول‌شویی

### مالی و اجتماعی

- `/loan TELEGRAM_ID AMOUNT INTEREST DAYS`
- `/acceptloan LOAN_ID`
- `/repay LOAN_ID AMOUNT`
- `/alliance create NAME`
- `/alliance join CODE`
- `/alliancefund AMOUNT`
- `/deadman TELEGRAM_ID burn_dirty`

### سرگرمی و بازار سیاه

- `/roulette TELEGRAM_ID AMOUNT`
- `/acceptroulette DUEL_ID`
- `/bet FIGHT_ID FIGHTER_TELEGRAM_ID AMOUNT`
- `/dossier TELEGRAM_ID`
- `/answerdossier ID ANSWER`
- `/leak ID`
- `/use antidote`، `/use tunnel_kit` یا `/use ghost`

عملیات شبانه، خرید سپر و بازار سیاه از منوی دکمه‌ای پی‌وی انجام می‌شوند.

### ادمین

- `/newseason`
- `/startseason`
- `/pausegame`
- `/resumegame`
- `/backup`
- ارسال فایل بکاپ با کپشن `/restore`
- `/adminlog`

تمام تغییرات ادمینی حیاتی در `/adminlog` ثبت می‌شوند.

## اجرای محلی

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

## تست

```bash
pytest -q
python -m compileall .
```

زمان‌بندی‌ها همگی روی `Asia/Tehran` هستند. نتایج تصادفی با کلید رویداد و `GAME_SECRET` تولید می‌شوند، بنابراین ری‌استارت باعث تغییر نتیجه یا دوباره تاس‌انداختن نمی‌شود.
