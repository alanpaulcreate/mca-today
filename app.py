import os, threading, time, asyncio, logging
from datetime import datetime, timedelta
from flask import Flask, request, render_template, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from dotenv import load_dotenv
from timetable import (
    get_classes_for_day, get_free_slots_for_day, format_classes, format_all_faculty,
    get_all_courses, get_live_session_info, sanitize_phone_number, sanitize_offset,
    sanitize_day, sanitize_chat_id, sanitize_text, get_ist_now, load_store, save_store
)

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
app = Flask(__name__)

# ── Twilio setup ──────────────────────────────────────────────────────────────
SID   = os.getenv("TWILIO_ACCOUNT_SID")
TAUTH = os.getenv("TWILIO_AUTH_TOKEN")
WA_FROM = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")
twilio = Client(SID, TAUTH) if SID and TAUTH else None

WA_FILE = "whatsapp_reminders.json"
wa_lock = threading.Lock()

# ── WhatsApp reminder thread ──────────────────────────────────────────────────
def wa_reminder_loop():
    sent = set()
    while True:
        now = get_ist_now()
        today = now.strftime("%Y-%m-%d")
        classes = get_classes_for_day(now.strftime("%a").lower())
        with wa_lock:
            reminders = load_store(WA_FILE)
        for phone, offset in reminders.items():
            for c in classes:
                try:
                    start_dt = datetime.strptime(c["Start"], "%H:%M").replace(
                        year=now.year, month=now.month, day=now.day)
                    diff = (start_dt - now).total_seconds()
                    key = (today, c["Start"], phone)
                    if 0 <= (offset * 60 - diff) <= 45 and diff > 0 and key not in sent:
                        if twilio:
                            twilio.messages.create(
                                from_=WA_FROM, to=phone,
                                body=f"Reminder: {c.get('FullName') or c['Subject']} in {offset} min ({c['Start']})"
                            )
                        sent.add(key)
                except Exception as e:
                    logging.error(f"WA reminder: {e}")
        if len(sent) > 500:
            sent = {k for k in sent if k[0] == today}
        time.sleep(30)

# ── Telegram bot thread ───────────────────────────────────────────────────────
def tg_bot_loop():
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    if not token:
        logging.warning("TELEGRAM_TOKEN not set - Telegram disabled.")
        return
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.ext import Application, CommandHandler, CallbackQueryHandler
    except ImportError:
        logging.error("python-telegram-bot not installed.")
        return

    TG_FILE = "reminders.json"
    rems = load_store(TG_FILE)
    sent = set()

    async def send(update, text, kb=None):
        if not update.effective_message:
            return
        try:
            await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await update.effective_message.reply_text(text, reply_markup=kb)

    async def cmd_start(u, c):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Today",    callback_data="today"),
             InlineKeyboardButton("Tomorrow", callback_data="tomorrow")],
            [InlineKeyboardButton("Now",      callback_data="now"),
             InlineKeyboardButton("Next",     callback_data="next")],
            [InlineKeyboardButton("Free",     callback_data="free"),
             InlineKeyboardButton("Faculty",  callback_data="faculty")],
        ])
        await send(u, "<b>MCA Timetable Bot</b>\n/today /tomorrow /week /now /next /free /faculty\n/remind_on [mins] /remind_off /remind_status\n/mon /tue /wed /thu /fri", kb)

    async def cmd_today(u, c):
        d = get_ist_now().strftime("%a").lower()
        await send(u, f"<b>{d.upper()}:</b>\n{format_classes(get_classes_for_day(d))}")

    async def cmd_tomorrow(u, c):
        d = (get_ist_now() + timedelta(days=1)).strftime("%a").lower()
        await send(u, f"<b>{d.upper()}:</b>\n{format_classes(get_classes_for_day(d))}")

    async def cmd_week(u, c):
        lines = ["<b>Week:</b>"]
        for d in ["mon","tue","wed","thu","fri","sat","sun"]:
            cls = get_classes_for_day(d)
            if cls: lines.append(f"\n<b>{d.upper()}</b>\n{format_classes(cls)}")
        await send(u, "\n".join(lines))

    async def cmd_day(u, c):
        d = sanitize_day((u.message.text or "").lstrip("/").strip())
        if d: await send(u, f"<b>{d.upper()}:</b>\n{format_classes(get_classes_for_day(d))}")

    async def cmd_now(u, c):
        s = get_live_session_info().get("ongoing")
        if s: await send(u, f"<b>Ongoing:</b> {s.get('FullName') or s['Subject']}\nEnds at {s['End']} ({s['mins_left']} min left)")
        else: await send(u, "No class right now.")

    async def cmd_next(u, c):
        s = get_live_session_info().get("next")
        if s: await send(u, f"<b>Next:</b> {s.get('FullName') or s['Subject']}\nStarts at {s['Start']} (in {s['mins_until']} min)")
        else: await send(u, "No more classes today.")

    async def cmd_free(u, c):
        slots = get_free_slots_for_day(get_ist_now().strftime("%a").lower())
        await send(u, "<b>Free Slots:</b>\n" + "\n".join(f"{s['Start']}-{s['End']}" for s in slots) if slots else "No free slots today.")

    async def cmd_faculty(u, c):
        await send(u, format_all_faculty())

    async def cmd_remind_on(u, c):
        cid = sanitize_chat_id(u.effective_chat.id if u.effective_chat else "")
        if not cid: return
        offset = sanitize_offset(c.args[0] if c.args else 10)
        rems[cid] = offset
        save_store(TG_FILE, rems)
        await send(u, f"Reminders on: <b>{offset} min</b> before class.")

    async def cmd_remind_off(u, c):
        cid = sanitize_chat_id(u.effective_chat.id if u.effective_chat else "")
        if cid in rems:
            del rems[cid]; save_store(TG_FILE, rems)
            await send(u, "Reminders off.")
        else: await send(u, "Already off.")

    async def cmd_remind_status(u, c):
        cid = sanitize_chat_id(u.effective_chat.id if u.effective_chat else "")
        off = rems.get(cid)
        await send(u, f"Active: <b>{off} min</b> before class." if off else "Reminders off. Use /remind_on [mins].")

    ACTIONS = {"today": cmd_today, "tomorrow": cmd_tomorrow, "week": cmd_week,
               "now": cmd_now, "next": cmd_next, "free": cmd_free, "faculty": cmd_faculty}

    async def btn(u, c):
        await u.callback_query.answer()
        fn = ACTIONS.get(sanitize_text(u.callback_query.data, 20))
        if fn: await fn(u, c)

    async def reminder_job(ctx):
        nonlocal sent
        now = get_ist_now(); today = now.strftime("%Y-%m-%d")
        for cid, offset in list(rems.items()):
            for cls in get_classes_for_day(now.strftime("%a").lower()):
                try:
                    s_dt = datetime.strptime(cls["Start"], "%H:%M").replace(year=now.year, month=now.month, day=now.day)
                    diff = (s_dt - now).total_seconds()
                    key  = (today, cls["Start"], str(cid))
                    if 0 <= (int(offset)*60 - diff) <= 60 and diff > 0 and key not in sent:
                        await ctx.bot.send_message(cid,
                            f"<b>Reminder:</b> {cls.get('FullName') or cls['Subject']} in {offset} min ({cls['Start']})",
                            parse_mode="HTML")
                        sent.add(key)
                except Exception as e: logging.error(f"TG reminder: {e}")
        if len(sent) > 500: sent = {k for k in sent if k[0] == today}

    async def run():
        tg = Application.builder().token(token).build()
        for cmd, fn in [("start",cmd_start),("today",cmd_today),("tomorrow",cmd_tomorrow),
                         ("week",cmd_week),("now",cmd_now),("next",cmd_next),
                         ("free",cmd_free),("faculty",cmd_faculty),
                         ("remind_on",cmd_remind_on),("remind_off",cmd_remind_off),
                         ("remind_status",cmd_remind_status)]:
            tg.add_handler(CommandHandler(cmd, fn))
        for d in ["mon","tue","wed","thu","fri","sat","sun"]:
            tg.add_handler(CommandHandler(d, cmd_day))
        tg.add_handler(CallbackQueryHandler(btn))
        if tg.job_queue: tg.job_queue.run_repeating(reminder_job, interval=60, first=10)
        logging.info("Telegram bot started.")
        await tg.run_polling(drop_pending_updates=True)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while True:
        try: loop.run_until_complete(run())
        except Exception as e:
            logging.error(f"Telegram crashed: {e}. Retry in 10s.")
            time.sleep(10)

# ── Start background threads ──────────────────────────────────────────────────
threading.Thread(target=wa_reminder_loop, daemon=True).start()
threading.Thread(target=tg_bot_loop,      daemon=True).start()

# ── Flask routes ──────────────────────────────────────────────────────────────
@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/live_status")
def api_live_status(): return jsonify(get_live_session_info())

@app.route("/api/classes")
def api_classes():
    raw = request.args.get("day", "today").strip().lower()
    day = get_ist_now().strftime("%a").lower() if raw in ["today","tdy"] else (sanitize_day(raw) or get_ist_now().strftime("%a").lower())
    return jsonify({"day": day, "classes": get_classes_for_day(day)})

@app.route("/api/faculty")
def api_faculty(): return jsonify({"courses": get_all_courses()})

@app.route("/ping")
@app.route("/health")
def ping(): return jsonify({"status":"ok","ts":datetime.now().isoformat()})

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    sender = sanitize_phone_number(request.values.get("From",""))
    msg_in = sanitize_text(request.values.get("Body","")).lower()
    resp   = MessagingResponse()
    out    = resp.message()

    if not sender: out.body("Invalid sender."); return str(resp), 400

    if msg_in.startswith("remind on") or msg_in == "remind":
        parts  = msg_in.split()
        offset = sanitize_offset(parts[2] if len(parts)>=3 else 10)
        with wa_lock:
            d = load_store(WA_FILE); d[sender]=offset; save_store(WA_FILE, d)
        out.body(f"Reminders on ({offset}m). Use Telegram for best results: https://t.me/Mcatimetablebot")
        return str(resp)

    if msg_in in ["remind off","stop reminders","remind cancel"]:
        with wa_lock:
            d = load_store(WA_FILE)
            if sender in d: del d[sender]; save_store(WA_FILE, d)
        out.body("Reminders off."); return str(resp)

    if msg_in in ["free","freeslots","free slots"]:
        slots = get_free_slots_for_day(get_ist_now().strftime("%a").lower())
        out.body("Free: " + ", ".join(f"{s['Start']}-{s['End']}" for s in slots) if slots else "No free slots.")
        return str(resp)

    if msg_in in ["today","tdy","tomorrow","tmr"] or sanitize_day(msg_in):
        if   msg_in in ["today","tdy"]:     day = get_ist_now().strftime("%a").lower()
        elif msg_in in ["tomorrow","tmr"]:  day = (get_ist_now()+timedelta(days=1)).strftime("%a").lower()
        else:                               day = sanitize_day(msg_in)
        out.body(f"{day.upper()}:\n{format_classes(get_classes_for_day(day))}"); return str(resp)

    if msg_in == "week":
        lines = []
        for d in ["mon","tue","wed","thu","fri"]:
            c = get_classes_for_day(d)
            if c: lines.append(f"{d.upper()}:\n{format_classes(c)}")
        out.body("\n\n".join(lines)); return str(resp)

    if msg_in in ["now","next"]:
        s = get_live_session_info().get("ongoing" if msg_in=="now" else "next")
        if s: out.body(f"{s.get('FullName') or s['Subject']} — {'ends' if msg_in=='now' else 'starts'} {s.get('End') or s.get('Start')}")
        else:  out.body("No class." if msg_in=="now" else "No more classes today.")
        return str(resp)

    if msg_in in ["faculty","teachers","courses"]:
        out.body(format_all_faculty().replace("<b>","").replace("</b>","")); return str(resp)

    out.body("Commands: today, tomorrow, week, now, next, free, faculty, mon-fri\nremind on [mins], remind off")
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","5000")), threaded=True)
