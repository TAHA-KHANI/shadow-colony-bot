from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select

from database.models import (
    Alliance,
    CityState,
    NewsEntry,
    NightAction,
    Property,
    Season,
    User,
)
from database.session import SessionFactory
from game.randomizer import chance, roll
from game.tone import say
from services.game_service import change_money


async def resolve_night(bot: Bot) -> list[str]:
    public_news: list[str] = []
    async with SessionFactory.begin() as session:
        state = await session.scalar(select(CityState).where(CityState.id == 1).with_for_update())
        if not state or not state.season_id or state.paused:
            return []
        actions = list((await session.scalars(select(NightAction).where(NightAction.season_id == state.season_id, NightAction.game_day == state.day_number, NightAction.status == "pending").order_by(NightAction.id).with_for_update())).all())
        users = {u.id: u for u in (await session.scalars(select(User).where(User.season_id == state.season_id).with_for_update())).all()}
        ambushers = {a.actor_id for a in actions if a.action_type == "ambush"}
        informers = [a for a in actions if a.action_type == "inform"]

        for action in actions:
            actor = users.get(action.actor_id)
            target = users.get(action.target_id) if action.target_id else None
            if not actor:
                action.status = "failed"
                continue
            key = f"night:{action.season_id}:{action.game_day}:{action.id}"
            shielded = bool(target and target.shield_until and target.shield_until > datetime.now(timezone.utc))
            text = ""
            public = False
            if action.action_type == "dig":
                gain = 8 + roll(key, 8)
                actor.tunnel_progress = min(100, actor.tunnel_progress + gain)
                text = f"⛏ {say('dig_success', key, gain=gain)}\nپیشرفت کل: {actor.tunnel_progress}٪"
                if actor.tunnel_progress >= 100:
                    season = await session.get(Season, action.season_id, with_for_update=True)
                    if season and season.status == "active":
                        season.status = "finished"
                        season.winner_user_id = actor.id
                        season.ends_at = datetime.now(timezone.utc)
                        state.phase = "finished"
                        text += "\n🏁 تونل کامل شد؛ از شهر فرار کردی و قهرمان فصل شدی!"
                        public = True
            elif action.action_type == "cleanup":
                cost = min(500, actor.dirty_cash)
                await change_money(session, actor, "dirty", -cost, "رشوه به رفتگر", f"cleanup:{action.id}")
                actor.heat = max(0, actor.heat - 3)
                text = f"🧹 {say('cleanup', key)}"
            elif action.action_type in {"hack", "ddos", "scan", "steal", "dawn_raid"} and target:
                if shielded:
                    text = f"🛡 {say('shield_block', key)}"
                elif target.id in ambushers and action.action_type != "scan":
                    actor.heat += 2
                    text = f"🪤 {say('ambush_block', key)}"
                    public = chance(key + ":expose", 45)
                else:
                    base = 52 + (actor.hack_power - target.firewall_level) * 9
                    if action.action_type in {"steal", "dawn_raid"}:
                        base = 58 + actor.speed * 2 - target.defense * 2
                    if action.action_type == "dawn_raid" and chance(key + ":police", 50):
                        actor.jailed_until = datetime.now(timezone.utc) + timedelta(hours=6)
                        actor.heat += 3
                        text = f"🚔 {say('police', key)}"
                        public = True
                    elif chance(key, max(15, min(85, base))):
                        if action.action_type == "scan":
                            text = f"🔎 {say('scan_success', key)}\nتمیز {target.clean_cash:,} | کثیف {target.dirty_cash:,} | هک {target.hack_power} | فایروال {target.firewall_level}"
                        elif action.action_type == "ddos":
                            prop = await session.scalar(select(Property).where(Property.owner_id == target.id).order_by(Property.id).with_for_update())
                            if prop:
                                prop.disabled_until = datetime.now(timezone.utc) + timedelta(hours=18)
                                text = f"⚡ {say('ddos_success', key, property=prop.name)}"
                            else:
                                text = "⚡ DDoS موفق بود، ولی هدف ملکی نداشت که خاموش شود؛ کابل هوا را زدی."
                        else:
                            cap = 650 if action.action_type == "dawn_raid" else 350
                            stolen = min(target.dirty_cash, 100 + roll(key + ":loot", cap))
                            await change_money(session, target, "dirty", -stolen, "سرقت شبانه", f"victim:{action.id}")
                            await change_money(session, actor, "dirty", stolen, "غنیمت شبانه", f"actor:{action.id}")
                            actor.heat += 2 if action.action_type == "dawn_raid" else 1
                            text = f"💰 {say('theft_success', key, amount=stolen)}"
                        public = chance(key + ":expose", 25 + actor.heat * 5)
                    else:
                        actor.heat += 1
                        text = f"💥 {say('operation_fail', key)}"
                        public = chance(key + ":expose", 35)
            elif action.action_type == "ambush":
                text = "🪤 تمام شب کمین کردی؛ اگر کسی آمده باشد صبح جنازه غرورش پیدا می‌شود."
            elif action.action_type == "betray":
                if actor.alliance_id and chance(key, 45 + actor.influence * 3):
                    alliance = await session.get(Alliance, actor.alliance_id, with_for_update=True)
                    loot = min(alliance.treasury // 5, 1200) if alliance else 0
                    if alliance:
                        alliance.treasury -= loot
                        alliance.score = max(0, alliance.score - 200)
                    actor.dirty_cash += loot
                    text = f"🐍 {say('betray_success', key, amount=loot)}"
                    actor.influence += 2
                else:
                    text = f"🐍 {say('betray_fail', key)}"
                    public = True
            else:
                text = "عملیات به هدف معتبری نرسید."
            action.status = "resolved"
            action.result_text = text
            action.is_public = public
            if public:
                line = f"• {actor.game_name}: {text}"
                public_news.append(line)
                session.add(NewsEntry(season_id=state.season_id, game_day=state.day_number, category="night", text=line))
            try:
                await bot.send_message(actor.telegram_id, f"🌑 نتیجه عملیات شبانه\n\n{text}")
            except TelegramAPIError:
                action.payload = {**action.payload, "delivery_failed": True}

        for report in informers:
            reporter = users.get(report.actor_id)
            suspect = users.get(report.target_id) if report.target_id else None
            if not reporter or not suspect:
                continue
            dug = any(a.actor_id == suspect.id and a.action_type == "dig" for a in actions)
            key = f"inform:{report.id}"
            if dug:
                damage = suspect.tunnel_progress // 2
                suspect.tunnel_progress -= damage
                await change_money(session, reporter, "clean", 500, "پاداش مخبری", f"inform:{report.id}")
                report.result_text = f"📞 گزارش درست بود؛ {damage}٪ از تونل متهم ریخت."
            else:
                fine = min(250, reporter.clean_cash)
                await change_money(session, reporter, "clean", -fine, "گزارش دروغ", f"false-inform:{report.id}")
                report.result_text = "☎️ گزارش کشکی بود و خودت جریمه شدی."
                if chance(key, 50):
                    public_news.append(f"• یک مخبر ناشی گزارش الکی داد و خودش را ضایع کرد: {reporter.game_name}")
    return public_news

