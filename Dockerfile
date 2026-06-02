FROM python:3.10-slim

WORKDIR /app

# sistem dependency-lər (ntgcalls üçün vacibdir)
RUN apt-get update && apt-get install -y \
    git \
    ffmpeg \
    build-essential \
    cmake \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# pip upgrade
RUN pip install --no-cache-dir --upgrade pip

# requirements
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# kodu copy et
COPY . .

# start
CMD ["python", "main.py"]
