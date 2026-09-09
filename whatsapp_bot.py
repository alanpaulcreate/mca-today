import os, threading, time, asyncio, logging
from datetime import datetime, timedelta
from flask import Flask, request, render_template, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from dotenv import load_dotenv

from timetable import (
    get_classes_for_day, get_free_slots_for_day, format_classes, format_all_faculty,
    get_all_courses, get_live_session_info, sanitize_phone_number, sanitize_offset,
    sanitize_day, sanitize_text, get_ist_now, load_store, save_store
)

load_dotenv()
app = Flask(__name__)
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")

twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    try:
        twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    except Exception as e:
        logging.warning(f"Twilio init warning: {e}")

REMINDERS_FILE = "whatsapp_reminders.json"
reminders_lock = threading.Lock()

# ---------- WhatsApp reminder worker ----------
def reminder_worker():
    sent = set()
    while True:
        try:
            now = get_ist_now()
            today_str = now.strftime("%Y-%m-%d")
            classes = get_classes_for_day(now.strftime("%a").lower())
            with reminders_lock:
                reminders = load_store(REMINDERS_FILE)
            for phone, offset in reminders.items():
                for c in classes:
                    try:
                        c_dt = datetime.strptime(c["Start"], "%H:%M").replace(
                            year=now.year, month=now.month, day=now.day, second=0, microsecond=0)
                        diff = (c_dt - now).total_seconds()
                        key = (today_str, c["Start"], phone)
                        if 0 <= (offset * 60 - diff) <= 45 and diff > 0 and key not in sent:
                            if twilio_client:
                                venue = f"Venue: {c['Venue']}\n" if c.get("Venue") and c["Venue"] != "-" else ""
                                fac   = f"Faculty: {c['Faculty']}\n" if c.get("Faculty") else ""
                                twilio_client.messages.create(
                                    from_=TWILIO_WHATSAPP_NUMBER, to=phone,
                                    body=f"Reminder: {c.get('FullName') or c['Subject']} starts in {offset} min!\n{c['Start']}\n{venue}{fac}".strip()
                                )
                            sent.add(key)
                    except Exception as err:
                        logging.error(f"WA class reminder error: {err}")
            if len(sent) > 500:
                sent = {k for k in sent if k[0] == today_str}
        except Exception as e:
            logging.error(f"WhatsApp worker error: {e}")
        time.sleep(30)

threading.Thread(target=reminder_worker, daemon=True).start()

# ---------- Telegram bot (background thread — works with gunicorn) ----------
def start_telegram_bot():
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    if not token:
        logging.warning("TELEGRAM_TOKEN not set — Telegram bot disabled.")
        return
    try:
        from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
    except ImportError:
        logging.error("python-telegram-bot not installed — Telegram bot disabled.")
        return

    TG_REMINDERS_FILE = "reminders.json"
    USER_REMINDERS = load_store(TG_REMINDERS_FILE)
    SENT_REMINDERS = set()

    async def reply(update, text, markup=None):
        if not update.effective_message:
            return
        try:
            await update.effective_message.reply_text(text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            await update.effective_message.reply_text(text, reply_markup=markup)

    async def start(update, context):
        kb = [
            [InlineKeyboardButton("Today", callback_data="today"), InlineKeyboardButton("Tomorrow", callback_data="tomorrow")],
            [InlineKeyboardButton("This Week", callback_data="week"), InlineKeyboardButton("What's Now?", callback_data="now")],
            [InlineKeyboardButton("Next Class", callback_data="next"), InlineKeyboardButton("Free Slots", callback_data="free")],
            [InlineKeyboardButton("Faculty & Courses", callback_data="faculty")]
        ]
        txt = (
            "<b>MCA Timetable Bot (Batch A)</b>\n\n"
            "Commands:\n"
            "/today  /tomorrow  /week\n"
            "/now  /next  /free  /faculty\n"
            "/remind_on [mins]  /remind_off  /remind_status\n"
            "Or: /mon  /tue  /wed  /thu  /fri"
        )
        await reply(update, txt, InlineKeyboardMarkup(kb))

    async def today_cmd(update, context):
        d = get_ist_now().strftime("%a").lower()
        await reply(update, f"<b>Today ({d.upper()}):</b>\n\n{format_classes(get_classes_for_day(d))}")

    async def tomorrow_cmd(update, context):
        d = (get_ist_now() + timedelta(days=1)).strftime("%a").lower()
        await reply(update, f"<b>Tomorrow ({d.upper()}):</b>\n\n{format_classes(get_classes_for_day(d))}")

    async def day_cmd(update, context):
        clean = sanitize_day((update.message.text or "").lstrip("/").strip())
        if clean:
            await reply(update, f"<b>{clean.upper()}:</b>\n\n{format_classes(get_classes_for_day(clean))}")

    async def now_class(update, context):
        c = get_live_session_info().get("ongoing")
        if c:
            venue = f" @ {c['Venue']}" if c.get("Venue") and c["Venue"] != "-" else ""
            fac   = f"\nFaculty: {c['Faculty']}" if c.get("Faculty") else ""
            await reply(update, f"<b>Ongoing:</b>\n<b>{c.get('FullName') or c['Subject']}</b>{venue}{fac}\nEnds in {c['mins_left']} mins ({c['End']})")
        else:
            await reply(update, "No class is currently ongoing.")

    async def next_class(update, context):
        c = get_live_session_info().get("next")
        if c:
            venue = f" @ {c['Venue']}" if c.get("Venue") and c["Venue"] != "-" else ""
            fac   = f"\nFaculty: {c['Faculty']}" if c.get("Faculty") else ""
            await reply(update, f"<b>Next:</b>\n<b>{c.get('FullName') or c['Subject']}</b> in {c['mins_until']} min\nStarts at {c['Start']}{venue}{fac}")
        else:
            await reply(update, "No more classes scheduled for today.")

    async def free_slots(update, context):
        slots = get_free_slots_for_day(get_ist_now().strftime("%a").lower())
        text = "<b>Free Slots Today:</b>\n\n" + "\n".join([f"* {s['Start']} - {s['End']}" for s in slots]) if slots else "No designated free slots today."
        await reply(update, text)

    async def faculty_cmd(update, context):
        await reply(update, format_all_faculty())

    async def week_cmd(update, context):
        res = ["<b>Weekly Timetable:</b>\n"]
        for d in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]:
            cls = get_classes_for_day(d)
            if cls:
                res.append(f"\n<b>{d.upper()}</b>:\n{format_classes(cls)}")
        await reply(update, "\n".join(res))

    async def remind_on(update, context):
        cid = sanitize_chat_id(update.effective_chat.id if update.effective_chat else "")
        if not cid:
            return
        offset = sanitize_offset(context.args[0] if context.args else 10)
        USER_REMINDERS[cid] = offset
        save_store(TG_REMINDERS_FILE, USER_REMINDERS)
        await reply(update, f"Reminders enabled! You will be alerted <b>{offset} minutes</b> before each class.")

    async def remind_off(update, context):
        cid = sanitize_chat_id(update.effective_chat.id if update.effective_chat else "")
        if cid in USER_REMINDERS:
            del USER_REMINDERS[cid]
            save_store(TG_REMINDERS_FILE, USER_REMINDERS)
            await reply(update, "Class reminders disabled.")
        else:
            await reply(update, "Reminders are already disabled.")

    async def remind_status(update, context):
        cid = sanitize_chat_id(update.effective_chat.id if update.effective_chat else "")
        offset = USER_REMINDERS.get(cid)
        if offset:
            await reply(update, f"Reminders active (<b>{offset} min</b> before class).\nUse /remind_on [mins] or /remind_off.")
        else:
            await reply(update, "Reminders disabled. Use /remind_on [mins] to activate.")

    ACTION_MAP = {
        "today": today_cmd, "tomorrow": tomorrow_cmd, "week": week_cmd,
        "next": next_class, "now": now_class, "free": free_slots, "faculty": faculty_cmd
    }

    async def button(update, context):
        await update.callback_query.answer()
        fn = ACTION_MAP.get(sanitize_text(update.callback_query.data, 20))
        if fn:
            await fn(update, context)

    async def reminder_job(context):
        nonlocal SENT_REMINDERS
        now = get_ist_now()
        today_str = now.strftime("%Y-%m-%d")
        classes = get_classes_for_day(now.strftime("%a").lower())
        for cid, offset in list(USER_REMINDERS.items()):
            for c in classes:
                try:
                    c_dt = datetime.strptime(c["Start"], "%H:%M").replace(
                        year=now.year, month=now.month, day=now.day, second=0, microsecond=0)
                    diff = (c_dt - now).total_seconds()
                    key = (today_str, c["Start"], str(cid))
                    if 0 <= (int(offset) * 60 - diff) <= 60 and diff > 0 and key not in SENT_REMINDERS:
                        venue = f"\nVenue: {c['Venue']}" if c.get("Venue") and c["Venue"] != "-" else ""
                        fac   = f"\nFaculty: {c['Faculty']}" if c.get("Faculty") else ""
                        await context.bot.send_message(
                            cid,
                            f"<b>Reminder:</b>\n<b>{c.get('FullName') or c['Subject']}</b> starts in {offset} min!{venue}{fac}",
                            parse_mode="HTML"
                        )
                        SENT_REMINDERS.add(key)
                except Exception as e:
                    logging.error(f"TG reminder error for {cid}: {e}")
        if len(SENT_REMINDERS) > 500:
            SENT_REMINDERS = {k for k in SENT_REMINDERS if k[0] == today_str}

    from timetable import sanitize_chat_id

    async def run_bot():
        tg_app = Application.builder().token(token).build()
        cmds = [
            ("start", start), ("today", today_cmd), ("tomorrow", tomorrow_cmd),
            ("week", week_cmd), ("now", now_class), ("next", next_class),
            ("free", free_slots), ("faculty", faculty_cmd),
            ("remind_on", remind_on), ("remind_off", remind_off), ("remind_status", remind_status)
        ]
        for cmd, fn in cmds:
            tg_app.add_handler(CommandHandler(cmd, fn))
        for d in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]:
            tg_app.add_handler(CommandHandler(d, day_cmd))
        tg_app.add_handler(CallbackQueryHandler(button))
        if tg_app.job_queue:
            tg_app.job_queue.run_repeating(reminder_job, interval=60, first=10)
        logging.info("Telegram bot polling started.")
        await tg_app.run_polling(drop_pending_updates=True)

    def _thread_runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while True:
            try:
                loop.run_until_complete(run_bot())
            except Exception as e:
                logging.error(f"Telegram bot crashed: {e}. Restarting in 10s...")
                time.sleep(10)

    threading.Thread(target=_thread_runner, daemon=True, name="telegram-bot").start()
    logging.info("Telegram bot thread launched.")

# Launch Telegram bot when module loads (gunicorn-compatible)
start_telegram_bot()

# ---------- Web Endpoints ----------
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/api/live_status", methods=["GET"])
def api_live_status():
    return jsonify(get_live_session_info())

@app.route("/api/classes", methods=["GET"])
def api_classes():
    raw_day = request.args.get("day", "today").strip().lower()
    day = (get_ist_now().strftime("%a").lower() if raw_day in ["today", "tdy"]
           else (sanitize_day(raw_day) or get_ist_now().strftime("%a").lower()))
    return jsonify({"day": day, "classes": get_classes_for_day(day)})

@app.route("/api/faculty", methods=["GET"])
def api_faculty():
    return jsonify({"courses": get_all_courses()})

@app.route("/ping", methods=["GET"])
@app.route("/health", methods=["GET"])
def ping():
    return jsonify({"status": "healthy", "service": "mca-bot-server",
                    "timestamp": datetime.now().isoformat()}), 200

# ---------- WhatsApp Webhook ----------
@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    sender = sanitize_phone_number(request.values.get("From", ""))
    clean  = sanitize_text(request.values.get("Body", "")).lower()
    resp   = MessagingResponse()
    msg    = resp.message()

    if not sender:
        msg.body("Invalid sender identification.")
        return str(resp), 400

    if clean.startswith("remind on") or clean == "remind":
        parts  = clean.split()
        offset = sanitize_offset(parts[2] if len(parts) >= 3 else (parts[1] if len(parts) >= 2 else 10))
        with reminders_lock:
            data = load_store(REMINDERS_FILE)
            data[sender] = offset
            save_store(REMINDERS_FILE, data)
        msg.body(f"Reminders Set ({offset}m).\nFor reliable alerts use Telegram: https://t.me/Mcatimetablebot")
        return str(resp)

    if clean in ["remind off", "stop reminders", "remind cancel"]:
        with reminders_lock:
            data = load_store(REMINDERS_FILE)
            if sender in data:
                del data[sender]
                save_store(REMINDERS_FILE, data)
        msg.body("Class alerts disabled.")
        return str(resp)

    if clean in ["free", "freeslot", "freeslots", "free slots"]:
        slots = get_free_slots_for_day(get_ist_now().strftime("%a").lower())
        msg.body("Free Slots Today:\n" + "\n".join([f"* {s['Start']} - {s['End']}" for s in slots]) if slots else "No free slots today!")
        return str(resp)

    if clean in ["today", "tdy", "tomorrow", "tmr"] or sanitize_day(clean):
        if clean in ["today", "tdy"]:
            day = get_ist_now().strftime("%a").lower()
        elif clean in ["tomorrow", "tmr"]:
            day = (get_ist_now() + timedelta(days=1)).strftime("%a").lower()
        else:
            day = sanitize_day(clean)
        msg.body(f"{day.upper()}:\n{format_classes(get_classes_for_day(day))}")
        return str(resp)

    if clean == "week":
        txt = ["Weekly Timetable\n"]
        for d in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]:
            c = get_classes_for_day(d)
            if c:
                txt.append(f"{d.capitalize()}:\n{format_classes(c)}\n")
        msg.body("\n".join(txt))
        return str(resp)

    if clean in ["now", "next"]:
        info = get_live_session_info()
        c = info.get("ongoing" if clean == "now" else "next")
        if c:
            venue  = f" @ {c['Venue']}" if c.get("Venue") and c["Venue"] != "-" else ""
            timing = f"Ends in {c['mins_left']} mins" if clean == "now" else f"in {c['mins_until']} min @ {c['Start']}"
            msg.body(f"{'Ongoing:' if clean == 'now' else 'Next:'} {c.get('FullName') or c['Subject']}{venue} {timing}")
        else:
            msg.body("No class currently ongoing." if clean == "now" else "No more classes today!")
        return str(resp)

    if clean in ["faculty", "teachers", "professors", "staff", "courses"]:
        msg.body(format_all_faculty().replace("<b>", "").replace("</b>", ""))
        return str(resp)

    msg.body("Timetable Bot!\n\nCommands:\ntoday, tomorrow, week, now, next, free, faculty\nmon, tue, wed, etc.\nremind on [mins], remind off")
    return str(resp)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
