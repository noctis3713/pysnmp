# TNMS SNMP 監控系統

基於 Docker Compose 的 TNMS SNMP 資料收集與監控解決方案，使用 Python + InfluxDB + Grafana 架構。

## 系統架構

```
TNMS Server ──SNMP──> Python Collector ──HTTP API──> InfluxDB ──Query──> Grafana
```

## 功能特色

- **SNMP 資料收集**: 支援 SNMP v2c/v3，使用 pysnmp 函式庫
- **TNMS MIB 支援**: 使用官方 TNMS-NBI-MIB 定義
- **時序資料庫**: InfluxDB 2.7 儲存監控資料
- **視覺化儀表板**: Grafana 提供豐富的監控視圖
- **容器化部署**: Docker Compose 一鍵部署
- **健康檢查**: 內建服務健康監控
- **自動重連**: 網路中斷自動重新連接

## 快速開始

### 1. 環境設定

複製並編輯環境變數檔案：
```bash
cp .env.example .env
vim .env
```

設定以下參數：
```bash
# TNMS SNMP 設定
TNMS_HOST=10.0.0.1              # TNMS 伺服器 IP
SNMP_COMMUNITY=public           # SNMP Community String

# InfluxDB 設定
INFLUXDB_USERNAME=admin
INFLUXDB_PASSWORD=password123
INFLUXDB_ORG=tnms-monitoring
INFLUXDB_TOKEN=tnms-token-change-me

# Grafana 設定
GRAFANA_USER=admin
GRAFANA_PASSWORD=admin123
```

### 2. 啟動系統

```bash
# 啟動所有服務（推薦）
docker compose up -d

# 查看服務狀態
docker compose ps

# 查看日誌
docker compose logs -f snmp

# 停止所有服務
docker compose down
```

### 3. 存取介面

- **Grafana 儀表板**: http://localhost:3000 (admin/admin123)
- **InfluxDB UI**: http://localhost:8086 (admin/password123)
- **健康檢查**: http://localhost:8080/health

## 專案結構

```
pysnmp/
├── docker-compose.yml          # Docker Compose 設定
├── .env                        # 環境變數
├── mib/                        # SNMP MIB 檔案
│   └── TNMS-NBI-MIB.my        # TNMS 官方 MIB
├── snmp/                       # Python SNMP 收集器
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── config.yaml
│   └── src/
│       ├── main.py            # 主程式
│       ├── snmp_collector.py  # SNMP 收集模組
│       └── influxdb_writer.py # InfluxDB 寫入模組
├── grafana/                   # Grafana 設定
│   ├── provisioning/          # 自動配置
│   │   ├── datasources/       # 資料源設定
│   │   └── dashboards/        # 儀表板設定
│   └── dashboards/            # 預設儀表板
└── influxdb/                  # InfluxDB 資料目錄
    └── data/
```

## 監控項目

系統預設監控以下 TNMS 資料：

### 1. 網路元件 (Network Elements)
- 設備名稱與類型
- 設備狀態
- 設備位置資訊

### 2. 告警資訊 (Alarms)
- 告警ID與類型
- 告警嚴重度
- 告警時間與描述

### 3. 埠口狀態 (Ports)
- 埠口名稱與類型
- 管理狀態
- 運作狀態

## 設定說明

### SNMP 設定 (config.yaml)

```yaml
snmp:
  host: "${TNMS_HOST}"           # TNMS 伺服器位址
  port: 161                      # SNMP 埠口
  community: "${SNMP_COMMUNITY}" # Community String
  version: "2c"                  # SNMP 版本
  timeout: 5                     # 超時時間 (秒)
  retries: 3                     # 重試次數

collection:
  interval: 60                   # 收集間隔 (秒)
  startup_delay: 30              # 啟動延遲 (秒)
```

### 自訂 OID 監控

在 `config.yaml` 中新增自訂 OID：

```yaml
oids:
  custom_metric:
    name: "customTable"
    oid: "1.3.6.1.4.1.42229.6.22.x.x"
    measurement: "tnms_custom"
    fields:
      - name: "customField"
        oid: "1.3.6.1.4.1.42229.6.22.x.x.x"
        type: "integer"
```

## 疑難排解

### 檢查服務狀態
```bash
# 查看所有容器狀態
docker compose ps

# 查看特定服務日誌
docker compose logs snmp
docker compose logs influxdb
docker compose logs grafana
```

### SNMP 連接問題
```bash
# 進入收集器容器除錯
docker compose exec snmp bash

# 測試 SNMP 連接
snmpget -v2c -c public TNMS_HOST 1.3.6.1.2.1.1.1.0

# 檢查健康狀態
curl http://localhost:8080/health
```

### InfluxDB 資料檢查
```bash
# 進入 InfluxDB 容器
docker compose exec influxdb bash

# 使用 influx CLI 查詢
influx query 'from(bucket:"tnms_data") |> range(start:-1h)'
```

## 自訂與擴展

### 新增監控項目

1. 在 MIB 檔案中找到要監控的 OID
2. 在 `config.yaml` 中新增 OID 定義
3. 重啟收集器服務

### 新增 Grafana 儀表板

1. 在 Grafana UI 中建立儀表板
2. 匯出 JSON 檔案
3. 放入 `grafana/dashboards/` 目錄
4. 重啟 Grafana 服務

## 效能調校

### 收集器效能

- 調整 `collection.interval` 來控制收集頻率
- 設定 `max_repetitions` 來優化 SNMP bulk 操作
- 調整 `batch_size` 來控制 InfluxDB 寫入批次大小

### InfluxDB 效能

- 設定適當的資料保留策略
- 調整 `flush_interval` 來平衡寫入效能與記憶體使用

## 安全考量

1. **修改預設密碼**: 變更 `.env` 中的所有預設密碼
2. **SNMP Community**: 使用強複雜度的 Community String
3. **網路存取控制**: 限制容器網路存取範圍
4. **資料加密**: 生產環境建議使用 SNMP v3

## 授權條款

本專案基於 MIT 授權條款發佈。