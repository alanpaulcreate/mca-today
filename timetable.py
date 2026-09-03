import csv
import re
from sanitizer import sanitize_day, sanitize_csv_field

CSV_FILE_PATH = "MCA_I_Semester_Batch_A_Timetable.csv"
COURSES_FILE_PATH = "courses.csv"
TIME_REGEX = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

COURSES_CACHE = None

def get_all_courses():
    """Load and cache course codes, full course names, and faculties."""
    global COURSES_CACHE
    if COURSES_CACHE is not None:
        return COURSES_CACHE
        
    courses = []
    try:
        with open(COURSES_FILE_PATH, mode='r', encoding='utf-8-sig') as file:
            reader = csv.DictReader(file)
            for row in reader:
                courses.append({
                    "code": str(row.get("Course Code", "")).strip(),
                    "short": str(row.get("Subject Code", "")).strip().upper(),
                    "name": str(row.get("Course Name", "")).strip(),
                    "faculty": str(row.get("Faculty", "")).strip()
                })
    except Exception as e:
        print(f"Error reading courses: {e}")
        
    COURSES_CACHE = courses
    return courses

def get_course_info(subject_text):
    """Fuzzy match a subject string to find its course details and faculty."""
    if not subject_text:
        return None
        
    courses = get_all_courses()
    s_upper = subject_text.upper().strip()
    
    # Exact or sub-match against short code or full name
    for c in courses:
        if c["short"] == s_upper or c["short"] in s_upper:
            return c
        if c["name"].upper() in s_upper or s_upper in c["name"].upper():
            return c
            
    # Check individual words like MFC, SE, PP, DSA
    for c in courses:
        words = re.findall(r"[A-Za-z0-9]+", s_upper)
        if c["short"] in words:
            return c
            
    return None

def format_all_faculty():
    """Format full list of faculty and subjects."""
    courses = get_all_courses()
    if not courses:
        return "No faculty details available."
    
    lines = ["👨‍🏫 **Faculty & Courses Directory:**\n"]
    for c in courses:
        lines.append(f"• **{c['short']}** ({c['code']})\n  📖 {c['name']}\n  👤 Faculty: *{c['faculty']}*\n")
    return "\n".join(lines)

def is_free_slot(class_entry):
    """Check if a timetable entry represents a free period."""
    subject = str(class_entry.get("Subject", "")).strip().lower()
    venue = str(class_entry.get("Venue", "")).strip()
    return "free slot" in subject or venue == "-"

def validate_timetable_row(row):
    """Sanitize and validate an individual timetable row."""
    if not isinstance(row, dict):
        return None
        
    day = str(row.get("Day", "")).strip().lower()
    start = str(row.get("Start", "")).strip()
    end = str(row.get("End", "")).strip()
    subject = sanitize_csv_field(row.get("Subject", ""))
    venue = sanitize_csv_field(row.get("Venue", ""))
    
    if not TIME_REGEX.match(start) or not TIME_REGEX.match(end):
        return None
    if day not in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}:
        return None
        
    # Enrich with faculty info
    info = get_course_info(subject)
    faculty = info["faculty"] if info else ""
    full_name = info["name"] if info else ""
        
    return {
        "Day": day.capitalize(),
        "Start": start,
        "End": end,
        "Subject": subject or "Unknown",
        "Venue": venue or "-",
        "Faculty": faculty,
        "FullName": full_name
    }

def get_all_classes(include_free=False):
    classes = []
    try:
        with open(CSV_FILE_PATH, mode='r', encoding='utf-8-sig') as file:
            reader = csv.DictReader(file)
            for raw_row in reader:
                validated = validate_timetable_row(raw_row)
                if not validated:
                    continue
                if not include_free and is_free_slot(validated):
                    continue
                classes.append(validated)
    except Exception as e:
        print(f"Error reading from CSV: {e}")
    return classes

def get_classes_for_day(day, include_free=False):
    clean_day = sanitize_day(day)
    if not clean_day:
        return []
    data = get_all_classes(include_free=include_free)
    return [r for r in data if str(r.get("Day", "")).lower() == clean_day]

def get_free_slots_for_day(day):
    clean_day = sanitize_day(day)
    if not clean_day:
        return []
    data = get_all_classes(include_free=True)
    return [r for r in data if str(r.get("Day", "")).lower() == clean_day and is_free_slot(r)]

def format_classes(classes, show_faculty=False):
    if not classes:
        return "No classes 🎉"
    text = ""
    for c in classes:
        if is_free_slot(c):
            text += f"☕ {c['Start']}-{c['End']} : *Free Slot* 🏖️\n"
        else:
            venue = f" @ {c['Venue']}" if c.get('Venue') and c['Venue'] != '-' else ""
            faculty = f"\n   👤 {c['Faculty']}" if (show_faculty and c.get('Faculty')) else ""
            text += f"⏰ {c['Start']}-{c['End']} : **{c['Subject']}**{venue}{faculty}\n"
    return text
