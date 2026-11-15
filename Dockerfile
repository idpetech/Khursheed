FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The database is not in the image. Attach a Railway volume at /data.
# TZ is the clock for the morning brief. Override it in the service variables.
ENV PYTHONUNBUFFERED=1
ENV KHURSHEED_DB_PATH=/data/khursheed.db
ENV TZ=America/New_York

EXPOSE 8080

CMD ["sh", "-c", "streamlit run hey_eman_app.py --server.address=0.0.0.0 --server.port=${PORT:-8080} --server.headless=true --server.enableCORS=false --server.enableXsrfProtection=true --browser.gatherUsageStats=false"]
