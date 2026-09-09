import os, sys
from dotenv import load_dotenv

load_dotenv()
os.environ["PYTHONUNBUFFERED"] = "1"

port = os.getenv("PORT", "5000")

# On Windows use Flask dev server; on Linux (Render/Docker) use gunicorn.
# Telegram bot starts automatically as a background thread inside whatsapp_bot.py.
if sys.platform.startswith("win"):
    from whatsapp_bot import app
    app.run(host="0.0.0.0", port=int(port), debug=False)
else:
    import subprocess
    subprocess.run([
        "gunicorn", "--bind", f"0.0.0.0:{port}",
        "--workers", "1", "--threads", "4",
        "whatsapp_bot:app"
    ])
