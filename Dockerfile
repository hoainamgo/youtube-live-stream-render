FROM python:3.11-slim

# Cài đặt ffmpeg, curl và các thư viện cần thiết
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cài đặt Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ mã nguồn
COPY . .

# Port mặc định của Render là 10000
ENV PORT=10000
EXPOSE 10000

CMD ["python", "app.py"]
