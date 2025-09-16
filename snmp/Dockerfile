FROM python:3.11-slim

WORKDIR /app

# 安裝系統依賴
RUN apt-get update && apt-get install -y \
    gcc \
    libsnmp-dev \
    snmp \
    && rm -rf /var/lib/apt/lists/*

# 複製requirements檔案並安裝Python套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式碼
COPY src/ ./src/
COPY config.yaml .

# 建立MIB目錄
RUN mkdir -p /app/mib

# 設定環境變數
ENV PYTHONPATH=/app/src
ENV MIBS=ALL

# 健康檢查
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=5)" || exit 1

# 執行主程式
CMD ["python", "src/main.py"]