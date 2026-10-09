FROM python:3.11-slim

WORKDIR /app

# System dependencies for psycopg2 and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY backend/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application files
COPY . .

ENV PORT=8000
EXPOSE 8000

CMD ["python", "backend/server.py"]
