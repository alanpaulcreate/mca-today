import re

def sanitize_phone_number(raw_phone: str) -> str:
    """
    Validate and sanitize phone number.
    Accepts Twilio whatsapp format: whatsapp:+[1-9][0-9]{6,14}
    or standard E.164 phone number.
    Returns cleaned string or empty string if invalid.
    """
    if not raw_phone or not isinstance(raw_phone, str):
        return ""
    
    cleaned = raw_phone.strip()
    is_whatsapp = cleaned.startswith("whatsapp:")
    phone_part = cleaned[9:] if is_whatsapp else cleaned
    
    # E.164 format check: optional '+' followed by 7-15 digits
    if re.fullmatch(r"\+?[1-9]\d{6,14}", phone_part):
        return f"whatsapp:{phone_part}" if is_whatsapp else phone_part
    return ""

def sanitize_text(text: str, max_length: int = 150) -> str:
    """
    Sanitize incoming user text:
    - Strip whitespace
    - Limit length to prevent buffer/memory exhaustion or regex DOS
    - Strip control and null characters
    """
    if not text or not isinstance(text, str):
        return ""
    
    # Remove null bytes and non-printable control characters (except newline)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    cleaned = cleaned.strip()[:max_length]
    return cleaned

def sanitize_offset(raw_val, default: int = 10, min_val: int = 1, max_val: int = 120) -> int:
    """Validate and clamp reminder offset minutes."""
    try:
        val = int(raw_val)
        return max(min_val, min(max_val, val))
    except (ValueError, TypeError):
        return default

def sanitize_day(day_str: str) -> str:
    """Validate and normalize a 3-letter day input."""
    cleaned = sanitize_text(day_str, max_length=10).lower()
    valid_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
    return cleaned if cleaned in valid_days else ""

def sanitize_csv_field(val: str, max_length: int = 100) -> str:
    """Sanitize CSV timetable cell content and neutralize CSV formula injection."""
    if not val:
        return ""
    cleaned = str(val).strip()[:max_length]
    # Neutralize spreadsheet formula injection characters (=, +, -, @, tab, CR)
    if cleaned and cleaned[0] in ('=', '+', '-', '@', '\t', '\r'):
        cleaned = "'" + cleaned
    return cleaned

def get_ist_now():
    """
    Get current datetime explicitly in Indian Standard Time (IST: UTC+5:30).
    Guarantees accurate class timing on cloud servers (like Render/Heroku/AWS)
    regardless of host system timezone.
    """
    from datetime import datetime, timezone, timedelta
    ist_offset = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist_offset).replace(tzinfo=None)

