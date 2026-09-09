import csv, re, json, os
from datetime import datetime, timezone, timedelta

CSV_TIMETABLE = "MCA_I_Semester_Batch_A_Timetable.csv"
CSV_COURSES = "courses.csv"
TIME_REGEX = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
COURSES_CACHE = None

# --- Sanitization & IST Helpers (Combined from sanitizer) --- #
def get_ist_now():
    """Current datetime in Indian Standard Time (IST, UTC+5:30)."""
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).replace(tzinfo=None)

def sanitize_text(text: str, max_length: int = 150) -> str:
    if not text or not isinstance(text, str): return ""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text).strip()[:max_length]

def sanitize_phone_number(raw: str) -> str:
    if not raw or not isinstance(raw, str): return ""
    clean = raw.strip()
    is_wa = clean.startswith("whatsapp:")
    phone = clean[9:] if is_wa else clean
    return f"whatsapp:{phone}" if (is_wa and re.fullmatch(r"\+?[1-9]\d{6,14}", phone)) else (phone if re.fullmatch(r"\+?[1-9]\d{6,14}", phone) else "")

def sanitize_offset(raw, default=10, min_v=1, max_v=120) -> int:
    try: return max(min_v, min(max_v, int(raw)))
    except (ValueError, TypeError): return default

def sanitize_day(day_str: str) -> str:
    s = sanitize_text(day_str, 10).lower()
    return s if s in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"} else ""

def sanitize_chat_id(raw_id) -> str:
    s = str(raw_id).strip()
    return s if re.fullmatch(r"-?\d{1,20}", s) else ""

# --- JSON File Store Helper --- #
def load_store(file_path: str) -> dict:
    if not os.path.exists(file_path): return {}
    try:
        with open(file_path, 'r') as f:
            d = json.load(f)
            if isinstance(d, dict): return {k: sanitize_offset(v) for k, v in d.items() if k}
            return {x: 10 for x in d if x}
    except Exception: return {}

def save_store(file_path: str, data: dict):
    try:
        with open(file_path, 'w') as f: json.dump(data, f, indent=2)
    except Exception as e: print(f"Error saving {file_path}: {e}")

# --- Course & Timetable Logic --- #
def get_all_courses():
    global COURSES_CACHE
    if COURSES_CACHE is not None: return COURSES_CACHE
    courses = []
    try:
        with open(CSV_COURSES, mode='r', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                courses.append({
                    "code": str(r.get("Course Code", "")).strip(),
                    "short": str(r.get("Subject Code", "")).strip().upper(),
                    "name": str(r.get("Course Name", "")).strip(),
                    "faculty": str(r.get("Faculty", "")).strip()
                })
    except Exception as e: print(f"Courses read error: {e}")
    COURSES_CACHE = courses
    return courses

def get_course_info(subj):
    if not subj: return None
    s = subj.upper().strip()
    for c in get_all_courses():
        if c["short"] == s or c["name"].upper() == s: return c
    clean = re.sub(r"\b(TUTORIAL|TUT)\b", "", s).strip()
    if clean:
        for c in get_all_courses():
            if c["short"] == clean or c["name"].upper() == clean: return c
    for c in sorted(get_all_courses(), key=lambda x: len(x["short"]), reverse=True):
        if re.search(r"\b" + re.escape(c["short"]) + r"\b", s): return c
    return None

def is_free_slot(c):
    return "free slot" in str(c.get("Subject", "")).lower() or str(c.get("Venue", "")).strip() == "-"

def get_all_classes(include_free=False):
    classes = []
    try:
        with open(CSV_TIMETABLE, mode='r', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                day, start, end = str(r.get("Day", "")).strip().lower(), str(r.get("Start", "")).strip(), str(r.get("End", "")).strip()
                if not (TIME_REGEX.match(start) and TIME_REGEX.match(end) and day in {"mon","tue","wed","thu","fri","sat","sun"}):
                    continue
                subj = str(r.get("Subject", "")).strip()
                info = get_course_info(subj)
                entry = {
                    "Day": day.capitalize(), "Start": start, "End": end, "Subject": subj or "Unknown",
                    "Venue": str(r.get("Venue", "")).strip() or "-",
                    "Faculty": info["faculty"] if info else "",
                    "FullName": info["name"] if info else subj
                }
                if not include_free and is_free_slot(entry): continue
                classes.append(entry)
    except Exception as e: print(f"Timetable CSV error: {e}")
    return classes

def get_classes_for_day(day, include_free=False):
    clean = sanitize_day(day)
    return [r for r in get_all_classes(include_free) if r["Day"].lower() == clean] if clean else []

def get_free_slots_for_day(day):
    clean = sanitize_day(day)
    return [r for r in get_all_classes(include_free=True) if r["Day"].lower() == clean and is_free_slot(r)] if clean else []

def format_classes(classes):
    if not classes: return "No classes scheduled 🎉"
    res = []
    for c in classes:
        venue = f" @ {c['Venue']}" if c.get('Venue') and c['Venue'] != '-' else ""
        fac = f" ({c['Faculty']})" if c.get('Faculty') else ""
        res.append(f"• {c['Start']}-{c['End']} : *{c.get('FullName') or c['Subject']}*{venue}{fac}")
    return "\n".join(res)

def format_all_faculty():
    courses = get_all_courses()
    if not courses: return "No faculty details available."
    return "👨‍🏫 *Faculty & Courses:*\n\n" + "\n".join([f"• *{c['short']}* ({c['code']}): {c['name']}\n  👤 *{c['faculty']}*\n" for c in courses])

# --- Shared Live Session Telemetry (Used by Telegram, Web API & WhatsApp) --- #
def get_live_session_info():
    now = get_ist_now()
    day = now.strftime("%a").lower()
    classes = get_classes_for_day(day, include_free=False)
    ongoing, next_up = None, None

    for c in classes:
        try:
            s_dt = datetime.strptime(c['Start'], "%H:%M").replace(year=now.year, month=now.month, day=now.day)
            e_dt = datetime.strptime(c['End'], "%H:%M").replace(year=now.year, month=now.month, day=now.day)
            if s_dt <= now < e_dt and ongoing is None:
                ongoing = {**c, "mins_left": max(1, int(round((e_dt - now).total_seconds() / 60)))}
            elif s_dt > now and next_up is None:
                next_up = {**c, "mins_until": max(1, int(round((s_dt - now).total_seconds() / 60)))}
        except Exception: pass

    return {"now": now.strftime("%H:%M:%S"), "day": day, "ongoing": ongoing, "next": next_up}
