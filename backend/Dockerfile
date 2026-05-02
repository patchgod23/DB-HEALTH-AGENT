# ── Base image: Python 3.12 slim (Debian Bookworm)
FROM python:3.12-slim

LABEL maintainer="db-health-agent"
LABEL description="Autonomous multi-database health monitoring agent"

# ── Install system dependencies + Microsoft ODBC Driver 17 for SQL Server
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        gnupg2 \
        unixodbc \
        unixodbc-dev \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list \
        -o /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
        msodbcsql17 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory
WORKDIR /app

# ── Install Python dependencies (layer-cached separately from source code)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Copy application source
COPY . .

# ── Create logs directory
RUN mkdir -p logs

# ── Default: single scan run
# Override with: docker-compose run agent python main.py --loop
CMD ["python", "main.py"]
