FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

WORKDIR /app

# Install Python deps first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY app ./app

# Persistent data lives in /data (mount a volume here)
ENV TRACKDAYFINDER_DATA=/data
RUN mkdir -p /data

EXPOSE 8766

# Bind to 0.0.0.0 so the container is reachable
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8766"]
