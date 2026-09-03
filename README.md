# MCA Timetable & Reminder Bot 📅

Automated Telegram & WhatsApp timetable bot with custom class reminders and free-slot filtering.

## 🚀 Features

- **Multi-Platform**: Works with Telegram Bot API & Twilio WhatsApp Sandbox/Production.
- **Dynamic Timetable Queries**:
  - `today` / `/today`: Today's classes
  - `tomorrow` / `/tomorrow`: Tomorrow's schedule
  - `now` / `/now`: Currently ongoing class + time remaining
  - `next` / `/next`: Next upcoming lecture + countdown
  - `week` / `/week`: Full 7-day schedule
  - `free` / `/free`: Free periods today
  - Individual day queries: `mon`, `tue`, `wed`, etc.
- **Proactive Notifications**: Set custom alerts before classes begin (e.g. 5, 10, 15, or 30 minutes prior).
- **Free Slot Filtering**: Clean views that hide non-classes by default, with dedicated free-slot inspection.
- **Security & Data Sanitization**: Strict input validation against command injection, memory exhaustion, and spreadsheet formula attacks.
- **Docker & Cloud Ready**: Out-of-the-box support for Docker Compose, Render, and Railway.

---

## ⚙️ Configuration (`.env`)

Create a `.env` file in the root directory (based on `.env.example`):

```env
TELEGRAM_TOKEN=your_telegram_bot_token_here
TWILIO_ACCOUNT_SID=your_twilio_sid_here
TWILIO_AUTH_TOKEN=your_twilio_auth_token_here
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
```

---

## 🏃 Running Locally

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Telegram Bot
```bash
python bot.py
```

### 3. Run WhatsApp Bot
```bash
python whatsapp_bot.py
```

---

## 🐳 Docker Setup

Run both bots 24/7 with restart protection:

```bash
docker-compose up -d --build
```

---

## ⏰ 24/7 Free Cloud Hosting (Prevent Sleep)

Render's free tier spins down web services after 15 minutes of inactivity. Use the built-in `/ping` endpoint with a free uptime pinger (like [cron-job.org](https://cron-job.org) or [UptimeRobot](https://uptimerobot.com)):

- **Target URL**: `https://<your-render-app>.onrender.com/ping`
- **Schedule**: Every 10 or 14 minutes
- **HTTP Method**: `GET`

