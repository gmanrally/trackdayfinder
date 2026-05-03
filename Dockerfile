FROM mcr.microsoft.com/playwright/python:v1.59.0-jammy

WORKDIR /app

# tzdata so APScheduler can resolve "Europe/London" via tzlocal/zoneinfo.
# Pre-set TZ + DEBIAN_FRONTEND so the apt install doesn't prompt for a region.
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/London
RUN ln -fs /usr/share/zoneinfo/Europe/London /etc/localtime \
    && echo "Europe/London" > /etc/timezone \
    && apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

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
