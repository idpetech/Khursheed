FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persist this directory with a Railway volume. The file is not in the image.
ENV PYTHONUNBUFFERED=1
ENV KHURSHEED_DB_PATH=/data/khursheed.db

EXPOSE 8080

CMD ["sh", "-c", "streamlit run hey_eman_app.py --server.address=0.0.0.0 --server.port=${PORT:-8080} --server.headless=true --server.enableCORS=false --server.enableXsrfProtection=true --browser.gatherUsageStats=false"]
