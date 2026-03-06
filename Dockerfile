FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install wheel setuptools pip --upgrade
WORKDIR /usr/src/
COPY requirements.txt .
RUN pip install -r requirements.txt
ENV PYTHONUNBUFFERED=1
COPY . .

# Expose port (5000 = API + Console endpoint)
EXPOSE 5000

# Jalankan dengan Gunicorn (2 workers, 4 threads, timeout 120 detik untuk ML load)
CMD ["gunicorn", "-w", "2", "--threads", "4", "--timeout", "120", "-b", "0.0.0.0:5000", "run:app"]