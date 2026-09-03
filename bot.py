import os
import json
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

from timetable import get_classes_for_day, get_free_slots_for_day, format_classes, format_all_faculty
from sanitizer import sanitize_offset, sanitize_day, sanitize_text, get_ist_now

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    print("⚠️  TELEGRAM_TOKEN not set — Telegram bot will not start.")
    import sys; sys.exit(0)
REMINDERS_FILE = "reminders.json"

# Stored as dict: { str(chat_id): offset_minutes }
USER_REMINDERS = {}

def sanitize_chat_id(raw_id) -> str:
    """Validate that chat_id is a numeric integer string (Telegram chat ID)."""
    s = str(raw_id).strip()
    return s if re.fullmatch(r"-?\d{1,20}", s) else ""

def load_reminders():
    global USER_REMINDERS
    sanitized = {}
    if os.path.exists(REMINDERS_FILE):
        try:
            with open(REMINDERS_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, list):
                    for uid in data:
                        clean_id = sanitize_chat_id(uid)
                        if clean_id:
                            sanitized[clean_id] = 10
                elif isinstance(data, dict):
                    for k, v in data.items():
                        clean_id = sanitize_chat_id(k)
                        if clean_id:
                            sanitized[clean_id] = sanitize_offset(v)
            USER_REMINDERS = sanitized
        except Exception as e:
            print(f"Error loading reminders: {e}")

def save_reminders():
    try:
        with open(REMINDERS_FILE, 'w') as f:
            json.dump(USER_REMINDERS, f, indent=2)
    except Exception as e:
        print(f"Error saving reminders: {e}")

load_reminders()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📅 Today", callback_data='today'),
         InlineKeyboardButton("📅 Tomorrow", callback_data='tomorrow')],
        [InlineKeyboardButton("🗓️ This Week", callback_data='week'),
         InlineKeyboardButton("🕒 What's Now?", callback_data='now')],
        [InlineKeyboardButton("⏭️ Next Class", callback_data='next'),
         InlineKeyboardButton("☕ Free Slots", callback_data='free')],
        [InlineKeyboardButton("👨‍🏫 Faculty & Courses", callback_data='faculty')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        "Hey! I'm your Timetable Bot 📅\n\n"
        "Use the buttons below or commands:\n"
        "/today - Today's classes\n"
        "/tomorrow - Tomorrow's classes\n"
        "/week - Entire week's timetable\n"
        "/now - Currently ongoing class\n"
        "/next - Next class\n"
        "/free - Today's free slots\n"
        "/faculty - Course codes & teachers\n"
        "/remind_on [mins] - e.g. `/remind_on 15` (default 10m)\n"
        "/remind_off - Stop reminders\n"
        "/remind_status - Check reminder status\n"
        "You can also use /mon, /tue, etc."
    )
    if update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    clean_data = sanitize_text(query.data, max_length=20)
    
    if clean_data == 'today':
        await today(update, context)
    elif clean_data == 'tomorrow':
        await tomorrow(update, context)
    elif clean_data == 'week':
        await week(update, context)
    elif clean_data == 'next':
        await next_class(update, context)
    elif clean_data == 'now':
        await now_class(update, context)
    elif clean_data == 'free':
        await free_slots(update, context)
    elif clean_data == 'faculty':
        await faculty(update, context)

async def faculty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = format_all_faculty()
    if update.effective_message:
        await update.effective_message.reply_text(text, parse_mode="Markdown")

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    day = get_ist_now().strftime("%a").lower()
    classes = get_classes_for_day(day, include_free=False)
    if update.effective_message:
        await update.effective_message.reply_text(f"📅 Today:\n{format_classes(classes)}", parse_mode="Markdown")

async def tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    day = (get_ist_now() + timedelta(days=1)).strftime("%a").lower()
    classes = get_classes_for_day(day, include_free=False)
    if update.effective_message:
        await update.effective_message.reply_text(f"📅 Tomorrow:\n{format_classes(classes)}", parse_mode="Markdown")

async def day_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text if update.message else ""
    raw_day = raw_text.lstrip("/").strip()
    clean_day = sanitize_day(raw_day)
    if not clean_day:
        return
        
    classes = get_classes_for_day(clean_day, include_free=False)
    if update.effective_message:
        await update.effective_message.reply_text(f"📅 {clean_day.upper()}:\n{format_classes(classes)}", parse_mode="Markdown")

async def next_class(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = get_ist_now()
    day = now.strftime("%a").lower()
    classes = get_classes_for_day(day, include_free=False)
    for c in classes:
        try:
            class_time = datetime.strptime(c['Start'], "%H:%M").replace(year=now.year, month=now.month, day=now.day)
            if class_time > now:
                mins = int((class_time - now).total_seconds() / 60)
                venue_text = f"📍 {c['Venue']} @ " if c.get('Venue') and c['Venue'] != '-' else ""
                if update.effective_message:
                    await update.effective_message.reply_text(f"⏭️ Next: **{c['Subject']}** in {mins} min\n{venue_text}{c['Start']}", parse_mode="Markdown")
                return
        except Exception:
            pass
    if update.effective_message:
        await update.effective_message.reply_text("No more classes today 🎉")

async def free_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    day = get_ist_now().strftime("%a").lower()
    slots = get_free_slots_for_day(day)
    if update.effective_message:
        if slots:
            text = "🏖️ **Free Slots Today:**\n"
            for s in slots:
                text += f"☕ {s['Start']} - {s['End']}\n"
            await update.effective_message.reply_text(text, parse_mode="Markdown")
        else:
            await update.effective_message.reply_text("No designated free slots today! 💪")

async def week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    text = "🗓️ **Weekly Timetable**\n\n"
    for day in days:
        classes = get_classes_for_day(day, include_free=False)
        if classes:
            text += f"*{day.capitalize()}*:\n{format_classes(classes)}\n"
    if update.effective_message:
        await update.effective_message.reply_text(text, parse_mode="Markdown")

async def now_class(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = get_ist_now()
    day = now.strftime("%a").lower()
    classes = get_classes_for_day(day, include_free=False)
    for c in classes:
        try:
            start_time = datetime.strptime(c['Start'], "%H:%M").replace(year=now.year, month=now.month, day=now.day)
            end_time = datetime.strptime(c['End'], "%H:%M").replace(year=now.year, month=now.month, day=now.day)
            if start_time <= now <= end_time:
                mins_left = int((end_time - now).total_seconds() / 60)
                venue_text = f" @ {c['Venue']}" if c.get('Venue') and c['Venue'] != '-' else ""
                if update.effective_message:
                    await update.effective_message.reply_text(f"🟢 **Currently Ongoing:**\n\n**{c['Subject']}**{venue_text}\nEnds in {mins_left} mins ({c['End']})", parse_mode="Markdown")
                return
        except Exception:
            pass
    if update.effective_message:
        await update.effective_message.reply_text("No class is currently ongoing. 🎉")

async def remind_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = sanitize_chat_id(update.effective_chat.id if update.effective_chat else "")
    if not chat_id:
        return
        
    raw_arg = context.args[0] if context.args else 10
    offset = sanitize_offset(raw_arg, default=10)
    
    USER_REMINDERS[chat_id] = offset
    save_reminders()
    if update.effective_message:
        await update.effective_message.reply_text(f"✅ Reminders ON! I'll ping you **{offset} minutes** before each class.")

async def remind_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = sanitize_chat_id(update.effective_chat.id if update.effective_chat else "")
    if not chat_id:
        return
        
    if chat_id in USER_REMINDERS:
        del USER_REMINDERS[chat_id]
        save_reminders()
        msg = "🔕 Reminders OFF"
    else:
        msg = "ℹ️ Reminders are already disabled."
    if update.effective_message:
        await update.effective_message.reply_text(msg)

async def remind_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = sanitize_chat_id(update.effective_chat.id if update.effective_chat else "")
    if not chat_id:
        return
        
    if chat_id in USER_REMINDERS:
        offset = USER_REMINDERS[chat_id]
        msg = f"🔔 Reminders are **ON** ({offset} minutes before class).\nUse `/remind_on <mins>` to change or `/remind_off` to disable."
    else:
        msg = "🔕 Reminders are **OFF**.\nUse `/remind_on [mins]` to activate alerts."
    if update.effective_message:
        await update.effective_message.reply_text(msg)

async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    now = get_ist_now()
    day = now.strftime("%a").lower()
    classes = get_classes_for_day(day, include_free=False)
    
    for chat_id, offset in USER_REMINDERS.items():
        check_time = (now + timedelta(minutes=int(offset))).strftime("%H:%M")
        for c in classes:
            if c['Start'] == check_time:
                venue_text = f"\n📍 {c['Venue']}" if c.get('Venue') and c['Venue'] != '-' else ""
                try:
                    await context.bot.send_message(
                        chat_id,
                        f"⏰ Reminder: **{c['Subject']}** starts in {offset} min{venue_text}",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"Failed to send reminder to {chat_id}: {e}")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("tomorrow", tomorrow))
    app.add_handler(CommandHandler("week", week))
    app.add_handler(CommandHandler("now", now_class))
    app.add_handler(CommandHandler("next", next_class))
    app.add_handler(CommandHandler("free", free_slots))
    app.add_handler(CommandHandler("faculty", faculty))
    app.add_handler(CommandHandler("remind_on", remind_on))
    app.add_handler(CommandHandler("remind_off", remind_off))
    app.add_handler(CommandHandler("remind_status", remind_status))
    for d in ["mon","tue","wed","thu","fri","sat","sun"]:
        app.add_handler(CommandHandler(d, day_cmd))
    
    if app.job_queue is not None:
        app.job_queue.run_repeating(reminder_job, interval=60, first=10)
    else:
        print("⚠️  job_queue unavailable (APScheduler not installed) — reminders disabled.")
    print("Telegram Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()