import os, threading, time
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

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")

twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    try: twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    except Exception as e: print(f"Twilio warning: {e}")

REMINDERS_FILE = "whatsapp_reminders.json"
reminders_lock = threading.Lock()

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
                        c_dt = datetime.strptime(c['Start'], "%H:%M").replace(year=now.year, month=now.month, day=now.day, second=0, microsecond=0)
                        diff = (c_dt - now).total_seconds()
                        key = (today_str, c['Start'], phone)
                        if 0 <= (offset * 60 - diff) <= 45 and diff > 0 and key not in sent:
                            if twilio_client:
                                venue = f"📍 {c['Venue']}\n" if c.get('Venue') and c['Venue'] != '-' else ""
                                fac = f"👤 Faculty: {c['Faculty']}\n" if c.get('Faculty') else ""
                                twilio_client.messages.create(
                                    from_=TWILIO_WHATSAPP_NUMBER, to=phone,
                                    body=f"⏰ *Reminder:* *{c.get('FullName') or c['Subject']}* starts in {offset} min!\n🕒 {c['Start']}\n{venue}{fac}".strip()
                                )
                                sent.add(key)
                    except Exception as err: print(f"Class reminder error: {err}")

            if len(sent) > 500: sent = {k for k in sent if k[0] == today_str}
        except Exception as e: print(f"WhatsApp worker error: {e}")
        time.sleep(30)

threading.Thread(target=reminder_worker, daemon=True).start()

# --- Web Endpoints --- #
@app.route("/", methods=['GET'])
def index():
    return render_template("index.html")

@app.route("/api/live_status", methods=['GET'])
def api_live_status():
    return jsonify(get_live_session_info())

@app.route("/api/classes", methods=['GET'])
def api_classes():
    raw_day = request.args.get('day', 'today').strip().lower()
    day = get_ist_now().strftime("%a").lower() if raw_day in ['today', 'tdy'] else (sanitize_day(raw_day) or get_ist_now().strftime("%a").lower())
    return jsonify({"day": day, "classes": get_classes_for_day(day)})

@app.route("/api/faculty", methods=['GET'])
def api_faculty():
    return jsonify({"courses": get_all_courses()})

@app.route("/ping", methods=['GET'])
@app.route("/health", methods=['GET'])
def ping():
    return jsonify({"status": "healthy", "service": "mca-bot-server", "timestamp": datetime.now().isoformat()}), 200

# --- WhatsApp Webhook --- #
@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    sender = sanitize_phone_number(request.values.get('From', ''))
    clean = sanitize_text(request.values.get('Body', '')).lower()
    resp = MessagingResponse()
    msg = resp.message()

    if not sender:
        msg.body("⚠️ Invalid sender identification.")
        return str(resp), 400

    if clean.startswith("remind on") or clean == "remind":
        parts = clean.split()
        offset = sanitize_offset(parts[2] if len(parts) >= 3 else (parts[1] if len(parts) >= 2 else 10))
        with reminders_lock:
            data = load_store(REMINDERS_FILE)
            data[sender] = offset
            save_store(REMINDERS_FILE, data)
        msg.body(f"🔔 *Reminders Set ({offset}m):*\nFor reliable free alerts, launch Telegram Bot: https://t.me/Mcatimetablebot")
        return str(resp)

    if clean in ["remind off", "stop reminders", "remind cancel"]:
        with reminders_lock:
            data = load_store(REMINDERS_FILE)
            if sender in data: del data[sender]; save_store(REMINDERS_FILE, data)
        msg.body("🔕 Class alerts disabled.")
        return str(resp)

    if clean in ["free", "freeslot", "freeslots", "free slots"]:
        slots = get_free_slots_for_day(get_ist_now().strftime("%a").lower())
        msg.body("🏖️ *Free Slots Today:*\n" + "\n".join([f"☕ {s['Start']} - {s['End']}" for s in slots]) if slots else "No designated free slots today! 💪")
        return str(resp)

    if clean in ['today', 'tdy', 'tomorrow', 'tmr'] or sanitize_day(clean):
        day = get_ist_now().strftime("%a").lower() if clean in ['today', 'tdy'] else ((get_ist_now() + timedelta(days=1)).strftime("%a").lower() if clean in ['tomorrow', 'tmr'] else sanitize_day(clean))
        msg.body(f"📅 *{day.upper()}:*\n{format_classes(get_classes_for_day(day))}")
        return str(resp)

    if clean == 'week':
        txt = ["🗓️ *Weekly Timetable*\n"]
        for d in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]:
            c = get_classes_for_day(d)
            if c: txt.append(f"*{d.capitalize()}*:\n{format_classes(c)}\n")
        msg.body("\n".join(txt))
        return str(resp)

    if clean in ['now', 'next']:
        info = get_live_session_info()
        c = info.get('ongoing' if clean == 'now' else 'next')
        if c:
            venue = f"📍 {c['Venue']} " if c.get('Venue') and c['Venue'] != '-' else ""
            timing = f"Ends in {c['mins_left']} mins" if clean == 'now' else f"in {c['mins_until']} min @ {c['Start']}"
            msg.body(f"{'🟢 Ongoing:' if clean == 'now' else '⏭️ Next:'} *{c.get('FullName') or c['Subject']}*\n{venue}{timing}")
        else: msg.body("No class currently ongoing." if clean == 'now' else "No more classes today 🎉")
        return str(resp)

    if clean in ['faculty', 'teachers', 'professors', 'staff', 'courses']:
        msg.body(format_all_faculty().replace("**", "*"))
        return str(resp)

    msg.body("Hey! I'm your Timetable Bot 📅\n\nCommands:\n• *today*, *tomorrow*, *week*, *now*, *next*, *free*, *faculty*\n• *mon*, *tue*, *wed*, etc.\n• *remind on [mins]*, *remind off*")
    return str(resp)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
