FROM python:3.10-slim

# Tối ưu cài đặt ffmpeg siêu tốc, không tải file thừa
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860
CMD ["python", "main.py"]
