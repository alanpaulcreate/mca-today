import csv
import re
from sanitizer import sanitize_day, sanitize_csv_field

CSV_FILE_PATH = "MCA_I_Semester_Batch_A_Timetable.csv"
TIME_REGEX = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

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
    
    # Must have valid time format HH:MM
    if not TIME_REGEX.match(start) or not TIME_REGEX.match(end):
        return None
    if day not in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}:
        return None
        
    return {
        "Day": day.capitalize(),
        "Start": start,
        "End": end,
        "Subject": subject or "Unknown",
        "Venue": venue or "-"
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

def format_classes(classes):
    if not classes:
        return "No classes 🎉"
    text = ""
    for c in classes:
        if is_free_slot(c):
            text += f"☕ {c['Start']}-{c['End']} : *Free Slot* 🏖️\n"
        else:
            venue = f" @ {c['Venue']}" if c.get('Venue') and c['Venue'] != '-' else ""
            text += f"⏰ {c['Start']}-{c['End']} : **{c['Subject']}**{venue}\n"
    return text
