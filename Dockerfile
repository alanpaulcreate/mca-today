FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default command: runs Unified MCA Bot Manager (both Telegram & Web/WhatsApp)
ENV PYTHONUNBUFFERED=1
EXPOSE 5000
CMD ["python", "run.py"]
