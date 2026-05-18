FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for OpenCV and fpdf
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0t64 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Set default env variables
ENV PORT=8000
ENV HOST=0.0.0.0

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host $HOST --port $PORT"]
