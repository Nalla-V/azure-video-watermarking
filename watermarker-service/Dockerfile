FROM python:3.10-slim

RUN apt-get update &&     apt-get install -y ffmpeg pkg-config libavformat-dev libavcodec-dev libavdevice-dev                        libavutil-dev libswscale-dev libavfilter-dev &&     apt-get clean &&     rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "app.py"]