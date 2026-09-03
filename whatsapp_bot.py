import os
import json
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, request, render_template, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from dotenv import load_dotenv

from timetable import get_classes_for_day, get_free_slots_for_day, format_classes, format_all_faculty, get_all_courses
from sanitizer import sanitize_text, sanitize_phone_number, sanitize_offset, sanitize_day

load_dotenv()

app = Flask(__name__)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")

twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    try:
        twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    except Exception as e:
        print(f"Twilio client init warning: {e}")

WHATSAPP_REMINDERS_FILE = "whatsapp_reminders.json"
reminders_lock = threading.Lock()

def load_whatsapp_reminders():
    """Load and sanitize phone number to offset minutes mapping."""
    sanitized_map = {}
    if os.path.exists(WHATSAPP_REMINDERS_FILE):
        try:
            with open(WHATSAPP_REMINDERS_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        clean_phone = sanitize_phone_number(item)
                        if clean_phone:
                            sanitized_map[clean_phone] = 10
                elif isinstance(data, dict):
                    for k, v in data.items():
                        clean_phone = sanitize_phone_number(k)
                        if clean_phone:
                            sanitized_map[clean_phone] = sanitize_offset(v)
        except Exception as e:
            print(f"Error loading WhatsApp reminders: {e}")
    return sanitized_map

def save_whatsapp_reminders(reminders_dict):
    """Save sanitized phone number to offset minutes mapping."""
    try:
        with open(WHATSAPP_REMINDERS_FILE, 'w') as f:
            json.dump(reminders_dict, f, indent=2)
    except Exception as e:
        print(f"Error saving WhatsApp reminders: {e}")

def reminder_worker():
    """Background daemon checking for upcoming classes and sending reminders."""
    sent_reminders = set()
    
    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            day_abbr = now.strftime("%a").lower()
            classes = get_classes_for_day(day_abbr, include_free=False)
            
            with reminders_lock:
                current_reminders = load_whatsapp_reminders()

            for phone_number, offset_mins in current_reminders.items():
                offset = sanitize_offset(offset_mins)
                for c in classes:
                    try:
                        class_dt = datetime.strptime(c['Start'], "%H:%M").replace(
                            year=now.year, month=now.month, day=now.day, second=0, microsecond=0
                        )
                        diff_seconds = (class_dt - now).total_seconds()
                        target_seconds = offset * 60
                        key = (today_str, c['Start'], phone_number)
                        
                        if 0 <= (target_seconds - diff_seconds) <= 45 and diff_seconds > 0:
                            if key not in sent_reminders:
                                if twilio_client:
                                    venue_text = f"📍 {c['Venue']}" if c.get('Venue') and c['Venue'] != '-' else ""
                                    msg_body = (
                                        f"⏰ *Reminder:* *{c['Subject']}* starts in {offset} min!\n"
                                        f"🕒 Start Time: {c['Start']}\n"
                                        f"{venue_text}"
                                    )
                                    twilio_client.messages.create(
                                        from_=TWILIO_WHATSAPP_NUMBER,
                                        to=phone_number,
                                        body=msg_body
                                    )
                                    sent_reminders.add(key)
                    except Exception as err:
                        print(f"Error checking class {c}: {err}")
                        
            if len(sent_reminders) > 500:
                sent_reminders = {k for k in sent_reminders if k[0] == today_str}
                
        except Exception as e:
            print(f"Error in WhatsApp reminder worker: {e}")
            
        time.sleep(30)

threading.Thread(target=reminder_worker, daemon=True).start()

# ----------------- Web Dashboard & API Endpoints ----------------- #

@app.route("/", methods=['GET'])
def index():
    """Interactive Web Dashboard."""
    return render_template("index.html")

@app.route("/api/live_status", methods=['GET'])
def api_live_status():
    """Return currently ongoing class and next upcoming class."""
    now = datetime.now()
    day = now.strftime("%a").lower()
    classes = get_classes_for_day(day, include_free=False)
    
    ongoing = None
    next_up = None
    
    for c in classes:
        try:
            start_dt = datetime.strptime(c['Start'], "%H:%M").replace(year=now.year, month=now.month, day=now.day)
            end_dt = datetime.strptime(c['End'], "%H:%M").replace(year=now.year, month=now.month, day=now.day)
            
            if start_dt <= now <= end_dt:
                mins_left = int((end_dt - now).total_seconds() / 60)
                ongoing = {**c, "mins_left": mins_left}
            elif start_dt > now and next_up is None:
                mins_until = int((start_dt - now).total_seconds() / 60)
                next_up = {**c, "mins_until": mins_until}
        except Exception:
            pass
            
    return jsonify({
        "now": now.strftime("%H:%M:%S"),
        "day": day,
        "ongoing": ongoing,
        "next": next_up
    })

@app.route("/api/classes", methods=['GET'])
def api_classes():
    """Return schedule for a specific day or 'today'."""
    raw_day = request.args.get('day', 'today').strip().lower()
    if raw_day in ['today', 'tdy']:
        day = datetime.now().strftime("%a").lower()
    else:
        day = sanitize_day(raw_day) or datetime.now().strftime("%a").lower()
        
    classes = get_classes_for_day(day, include_free=False)
    return jsonify({"day": day, "classes": classes})

@app.route("/api/faculty", methods=['GET'])
def api_faculty():
    """Return full faculty & course directory."""
    return jsonify({"courses": get_all_courses()})

# ----------------- Twilio WhatsApp Webhook ----------------- #

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    """Respond to incoming messages with sanitized input validation."""
    raw_sender = request.values.get('From', '')
    raw_body = request.values.get('Body', '')
    
    # 1. Sanitize outside inputs
    sender = sanitize_phone_number(raw_sender)
    clean_msg = sanitize_text(raw_body).lower()
    
    resp = MessagingResponse()
    msg = resp.message()
    
    if not sender:
        msg.body("⚠️ Invalid sender identification.")
        return str(resp), 400

    # 2. Reminders Management
    if clean_msg.startswith("remind on") or clean_msg == "remind":
        parts = clean_msg.split()
        offset = 10
        if len(parts) >= 3:
            offset = sanitize_offset(parts[2])
        elif len(parts) >= 2:
            offset = sanitize_offset(parts[1])
            
        with reminders_lock:
            data = load_whatsapp_reminders()
            data[sender] = offset
            save_whatsapp_reminders(data)
            
        msg.body(f"✅ *Reminders Activated!* You will receive WhatsApp alerts *{offset} minutes* before each class.\n\nTip: You can change the offset anytime using `remind on 15` or stop using `remind off`.")
        return str(resp)

    elif clean_msg in ["remind off", "stop reminders", "remind cancel"]:
        with reminders_lock:
            data = load_whatsapp_reminders()
            if sender in data:
                del data[sender]
                save_whatsapp_reminders(data)
                msg.body("🔕 *Reminders Disabled.* You will no longer receive automated class alerts.")
            else:
                msg.body("ℹ️ You do not currently have reminders enabled.")
        return str(resp)

    elif clean_msg in ["remind status", "reminder status", "reminders"]:
        with reminders_lock:
            data = load_whatsapp_reminders()
            if sender in data:
                offset = data[sender]
                msg.body(f"🔔 *Reminders are ON* ({offset} minutes before class).\nSend `remind on <mins>` to change or `remind off` to disable.")
            else:
                msg.body("🔕 *Reminders are OFF*.\nSend `remind on` or `remind on 15` to enable alerts.")
        return str(resp)

    # 3. Free Slots
    elif clean_msg in ["free", "freeslot", "freeslots", "free slots"]:
        day = datetime.now().strftime("%a").lower()
        free_slots = get_free_slots_for_day(day)
        if free_slots:
            text = "🏖️ *Free Slots Today:*\n"
            for s in free_slots:
                text += f"☕ {s['Start']} - {s['End']}\n"
            msg.body(text)
        else:
            msg.body("No designated free slots today! Stay strong 💪")
        return str(resp)

    # 4. Schedule Queries
    elif clean_msg in ['today', 'tdy']:
        day = datetime.now().strftime("%a").lower()
        classes = get_classes_for_day(day, include_free=False)
        msg.body(f"📅 *Today:*\n{format_classes(classes)}")
        
    elif clean_msg in ['tomorrow', 'tmr']:
        day = (datetime.now() + timedelta(days=1)).strftime("%a").lower()
        classes = get_classes_for_day(day, include_free=False)
        msg.body(f"📅 *Tomorrow:*\n{format_classes(classes)}")
        
    elif clean_msg == 'week':
        days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        text = "🗓️ *Weekly Timetable*\n\n"
        for day in days:
            classes = get_classes_for_day(day, include_free=False)
            if classes:
                text += f"*{day.capitalize()}*:\n{format_classes(classes)}\n"
        msg.body(text)
        
    elif clean_msg == 'now':
        now = datetime.now()
        day = now.strftime("%a").lower()
        classes = get_classes_for_day(day, include_free=False)
        found = False
        for c in classes:
            try:
                start_time = datetime.strptime(c['Start'], "%H:%M").replace(year=now.year, month=now.month, day=now.day)
                end_time = datetime.strptime(c['End'], "%H:%M").replace(year=now.year, month=now.month, day=now.day)
                if start_time <= now <= end_time:
                    mins_left = int((end_time - now).total_seconds() / 60)
                    venue_text = f" @ {c['Venue']}" if c.get('Venue') and c['Venue'] != '-' else ""
                    msg.body(f"🟢 *Currently Ongoing:*\n\n*{c['Subject']}*{venue_text}\nEnds in {mins_left} mins ({c['End']})")
                    found = True
                    break
            except Exception:
                pass
        if not found:
            msg.body("No class is currently ongoing. 🎉")
            
    elif clean_msg == 'next':
        now = datetime.now()
        day = now.strftime("%a").lower()
        classes = get_classes_for_day(day, include_free=False)
        found = False
        for c in classes:
            try:
                start_time = datetime.strptime(c['Start'], "%H:%M").replace(year=now.year, month=now.month, day=now.day)
                if start_time > now:
                    mins = int((start_time - now).total_seconds() / 60)
                    venue_text = f"📍 {c['Venue']}" if c.get('Venue') and c['Venue'] != '-' else ""
                    msg.body(f"⏭️ Next: *{c['Subject']}* in {mins} min\n{venue_text} @ {c['Start']}")
                    found = True
                    break
            except Exception:
                pass
        if not found:
            msg.body("No more classes today 🎉")
            
    elif sanitize_day(clean_msg):
        valid_day = sanitize_day(clean_msg)
        classes = get_classes_for_day(valid_day, include_free=False)
        msg.body(f"📅 *{valid_day.upper()}:*\n{format_classes(classes)}")
        
    elif clean_msg in ['faculty', 'teachers', 'professors', 'staff', 'courses']:
        msg.body(format_all_faculty().replace("**", "*"))
        return str(resp)

    else:
        msg.body(
            "Hey! I'm your Timetable Bot 📅\n\n"
            "Reply with any of these commands:\n"
            "• *today* - Today's schedule\n"
            "• *tomorrow* - Tomorrow's schedule\n"
            "• *now* - Current class\n"
            "• *next* - Next upcoming class\n"
            "• *week* - Full week timetable\n"
            "• *free* - Free slots today\n"
            "• *faculty* - Course codes & teachers\n"
            "• *mon*, *tue*, *wed*, etc.\n\n"
            "🔔 *Reminders:*\n"
            "• *remind on [mins]* - e.g. `remind on 15`\n"
            "• *remind off* - Stop alerts\n"
            "• *remind status* - Check settings"
        )

    return str(resp)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
