import os, subprocess, sys, time
from dotenv import load_dotenv

load_dotenv()
os.environ["PYTHONUNBUFFERED"] = "1"

def start_cmd(cmd, name):
    print(f"🚀 Starting {name}...")
    return subprocess.Popen(cmd)

def run():
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    port = os.getenv("PORT", "5000")
    
    tg_cmd = [sys.executable, "-u", "bot.py"] if token else None
    web_cmd = [sys.executable, "-u", "whatsapp_bot.py"] if sys.platform.startswith("win") else [
        "gunicorn", "--bind", f"0.0.0.0:{port}", "--workers", "1", "--threads", "4", "whatsapp_bot:app"
    ]
    
    tg_proc = start_cmd(tg_cmd, f"Telegram Bot (@Mcatimetablebot)") if tg_cmd else (print("⚠️ TELEGRAM_TOKEN not set in environment!") or None)
    web_proc = start_cmd(web_cmd, f"Web Server on port {port}")

    try:
        while True:
            time.sleep(5)
            if tg_cmd and (not tg_proc or tg_proc.poll() is not None):
                print(f"⚠️ Telegram bot exited ({tg_proc.poll() if tg_proc else 'N/A'}). Restarting in 5s...")
                time.sleep(5)
                tg_proc = start_cmd(tg_cmd, "Telegram Bot")
            if web_proc.poll() is not None:
                print(f"🚨 Web server stopped ({web_proc.poll()}). Exiting.")
                break
    except KeyboardInterrupt:
        if tg_proc: tg_proc.terminate()
        web_proc.terminate()

if __name__ == "__main__":
    run()
