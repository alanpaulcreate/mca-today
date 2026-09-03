import os
import subprocess
import sys
import time

def run():
    print("🚀 Starting Unified MCA Bot Manager...")
    
    # 1. Start Telegram Bot process if TELEGRAM_TOKEN exists
    telegram_proc = None
    if os.getenv("TELEGRAM_TOKEN"):
        print("🤖 Starting Telegram Bot...")
        telegram_proc = subprocess.Popen([sys.executable, "bot.py"])
    else:
        print("⚠️ TELEGRAM_TOKEN not found. Skipping Telegram Bot.")

    # 2. Start WhatsApp Flask Webhook & Dashboard via Gunicorn
    port = os.getenv("PORT", "5000")
    print(f"🌐 Starting Web & WhatsApp server on port {port}...")
    web_cmd = [
        "gunicorn",
        "--bind", f"0.0.0.0:{port}",
        "--workers", "1",
        "--threads", "4",
        "whatsapp_bot:app"
    ]
    
    try:
        web_proc = subprocess.Popen(web_cmd)
        
        # Monitor processes
        while True:
            time.sleep(5)
            if telegram_proc and telegram_proc.poll() is not None:
                print("⚠️ Telegram bot exited unexpectedly! Restarting...")
                telegram_proc = subprocess.Popen([sys.executable, "bot.py"])
            if web_proc.poll() is not None:
                print("🚨 Web server stopped! Exiting runner.")
                break
    except KeyboardInterrupt:
        print("Stopping bots...")
        if telegram_proc:
            telegram_proc.terminate()
        web_proc.terminate()

if __name__ == "__main__":
    run()
