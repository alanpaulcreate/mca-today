import os, logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

from timetable import (
    get_classes_for_day, get_free_slots_for_day, format_classes, format_all_faculty,
    get_live_session_info, sanitize_offset, sanitize_day, sanitize_chat_id, sanitize_text,
    get_ist_now, load_store, save_store
)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    print("⚠️ TELEGRAM_TOKEN not set — Telegram bot exiting.")
    import sys; sys.exit(0)

REMINDERS_FILE = "reminders.json"
USER_REMINDERS = load_store(REMINDERS_FILE)
SENT_REMINDERS = set()

async def reply(update: Update, text: str, markup=None):
    if update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=markup, parse_mode="Markdown")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("📅 Today", callback_data='today'), InlineKeyboardButton("📅 Tomorrow", callback_data='tomorrow')],
        [InlineKeyboardButton("🗓️ This Week", callback_data='week'), InlineKeyboardButton("🕒 What's Now?", callback_data='now')],
        [InlineKeyboardButton("⏭️ Next Class", callback_data='next'), InlineKeyboardButton("☕ Free Slots", callback_data='free')],
        [InlineKeyboardButton("👨‍🏫 Faculty & Courses", callback_data='faculty')]
    ]
    txt = ("Hey! I'm your Timetable Bot 📅\n\nCommands:\n"
           "/today, /tomorrow, /week, /now, /next, /free, /faculty\n"
           "/remind_on [mins] - e.g. `/remind_on 10`\n"
           "/remind_off, /remind_status\nOr use /mon, /tue, etc.")
    await reply(update, txt, InlineKeyboardMarkup(kb))

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = get_ist_now().strftime("%a").lower()
    await reply(update, f"📅 **Today**:\n{format_classes(get_classes_for_day(d))}")

async def tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = (get_ist_now() + timedelta(days=1)).strftime("%a").lower()
    await reply(update, f"📅 **Tomorrow**:\n{format_classes(get_classes_for_day(d))}")

async def day_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clean = sanitize_day((update.message.text or "").lstrip("/").strip())
    if clean: await reply(update, f"📅 **{clean.upper()}**:\n{format_classes(get_classes_for_day(clean))}")

async def now_class(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c = get_live_session_info().get('ongoing')
    if c:
        venue = f" @ {c['Venue']}" if c.get('Venue') and c['Venue'] != '-' else ""
        fac = f"\n👤 Faculty: {c['Faculty']}" if c.get('Faculty') else ""
        await reply(update, f"🟢 **Ongoing:**\n\n**{c.get('FullName') or c['Subject']}**{venue}{fac}\nEnds in {c['mins_left']} mins ({c['End']})")
    else:
        await reply(update, "No class is currently ongoing. 🎉")

async def next_class(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c = get_live_session_info().get('next')
    if c:
        venue = f"📍 {c['Venue']} @ " if c.get('Venue') and c['Venue'] != '-' else ""
        fac = f"\n👤 Faculty: {c['Faculty']}" if c.get('Faculty') else ""
        await reply(update, f"⏭️ Next: **{c.get('FullName') or c['Subject']}** in {c['mins_until']} min\n{venue}{c['Start']}{fac}")
    else:
        await reply(update, "No more classes today 🎉")

async def free_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    slots = get_free_slots_for_day(get_ist_now().strftime("%a").lower())
    await reply(update, "🏖️ **Free Slots Today:**\n" + "\n".join([f"☕ {s['Start']} - {s['End']}" for s in slots]) if slots else "No designated free slots today! 💪")

async def faculty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, format_all_faculty())

async def week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = ["🗓️ **Weekly Timetable**\n"]
    for d in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]:
        cls = get_classes_for_day(d)
        if cls: res.append(f"*{d.capitalize()}*:\n{format_classes(cls)}\n")
    await reply(update, "\n".join(res))

async def remind_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = sanitize_chat_id(update.effective_chat.id if update.effective_chat else "")
    if not cid: return
    offset = sanitize_offset(context.args[0] if context.args else 10)
    USER_REMINDERS[cid] = offset
    save_store(REMINDERS_FILE, USER_REMINDERS)
    await reply(update, f"✅ Reminders ON! I'll alert you **{offset} minutes** before class.")

async def remind_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = sanitize_chat_id(update.effective_chat.id if update.effective_chat else "")
    if cid in USER_REMINDERS:
        del USER_REMINDERS[cid]
        save_store(REMINDERS_FILE, USER_REMINDERS)
        await reply(update, "🔕 Reminders OFF")
    else: await reply(update, "ℹ️ Reminders are already disabled.")

async def remind_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = sanitize_chat_id(update.effective_chat.id if update.effective_chat else "")
    offset = USER_REMINDERS.get(cid)
    await reply(update, f"🔔 Reminders are **ON** ({offset}m before class).\nUse `/remind_on <mins>` or `/remind_off`." if offset else "🔕 Reminders are **OFF**.\nUse `/remind_on [mins]` to activate.")

ACTION_MAP = {'today': today, 'tomorrow': tomorrow, 'week': week, 'next': next_class, 'now': now_class, 'free': free_slots, 'faculty': faculty}

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    fn = ACTION_MAP.get(sanitize_text(update.callback_query.data, 20))
    if fn: await fn(update, context)

async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    global SENT_REMINDERS
    now = get_ist_now()
    today_str = now.strftime("%Y-%m-%d")
    classes = get_classes_for_day(now.strftime("%a").lower())
    
    for cid, offset in list(USER_REMINDERS.items()):
        for c in classes:
            try:
                c_dt = datetime.strptime(c['Start'], "%H:%M").replace(year=now.year, month=now.month, day=now.day, second=0, microsecond=0)
                diff = (c_dt - now).total_seconds()
                key = (today_str, c['Start'], str(cid))
                if 0 <= (int(offset) * 60 - diff) <= 60 and diff > 0 and key not in SENT_REMINDERS:
                    venue = f"\n📍 Venue: {c['Venue']}" if c.get('Venue') and c['Venue'] != '-' else ""
                    fac = f"\n👤 Faculty: {c['Faculty']}" if c.get('Faculty') else ""
                    await context.bot.send_message(cid, f"⏰ Reminder: **{c.get('FullName') or c['Subject']}** starts in {offset} min!{venue}{fac}", parse_mode="Markdown")
                    SENT_REMINDERS.add(key)
            except Exception as e: print(f"Reminder error for {cid}: {e}")
                
    if len(SENT_REMINDERS) > 500: SENT_REMINDERS = {k for k in SENT_REMINDERS if k[0] == today_str}

def main():
    app = Application.builder().token(TOKEN).build()
    for cmd, fn in [("start", start), ("today", today), ("tomorrow", tomorrow), ("week", week), ("now", now_class), ("next", next_class), ("free", free_slots), ("faculty", faculty), ("remind_on", remind_on), ("remind_off", remind_off), ("remind_status", remind_status)]:
        app.add_handler(CommandHandler(cmd, fn))
    for d in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]:
        app.add_handler(CommandHandler(d, day_cmd))
    app.add_handler(CallbackQueryHandler(button))

    if app.job_queue: app.job_queue.run_repeating(reminder_job, interval=60, first=10)
    print("🤖 Telegram Bot running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()