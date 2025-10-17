# -----------------------------
# 1️⃣ Base image
# -----------------------------
FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# -----------------------------
# 2️⃣ Install system dependencies
# -----------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    ca-certificates \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------
# 3️⃣ Copy project files
# -----------------------------
COPY main.py .
COPY Dockerfile .
# COPY other required files (requirements.txt, attachments, etc.)

# -----------------------------
# 4️⃣ Install Python dependencies
# -----------------------------
RUN pip install --no-cache-dir \
    fastapi[standard] \
    uvicorn \
    httpx \
    aiofiles \
    gradio 

# -----------------------------
# 5️⃣ Optional: Set default Git config
# -----------------------------
RUN git config --global user.email "taylorfryhector@gmail.com" \
    && git config --global user.name "taylorfryhector-arch"

# -----------------------------
# 6️⃣ Environment & permissions
# -----------------------------
ENV PORT=7860
RUN mkdir -p /tmp && chmod 777 /tmp
EXPOSE $PORT

# -----------------------------
# 7️⃣ Run FastAPI
# -----------------------------
CMD ["bash", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]
