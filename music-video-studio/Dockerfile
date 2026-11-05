FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY music-video-studio/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY music-video-studio/ .
ENV PYTHONUNBUFFERED=1
CMD ["sh","-c","uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000}"]
