# TNMS SNMP 監控系統

基於 Docker Compose 的 TNMS SNMP 資料收集與監控解決方案，使用 Python + InfluxDB + Grafana 架構。支援基本 SNMP 資料收集和進階 PM（Performance Monitoring）流量監控。

## 系統架構

```
TNMS Server ──SNMP──> Python Collector ──HTTP API──> InfluxDB ──Query──> Grafana
                        │                      │
                        ├── SNMP Collector     ├── Basic Data Storage
                        │   (Network Elements, │   (Elements, Alarms, Ports)
                        │    Alarms, Ports)    │
                        │                      │
                        └── PM Traffic Collector
                            (Port Performance)
                            - PM Request Manager
                            - Port Discovery
                            - Traffic Counter
```

## 功能特色

- **基本 SNMP 收集**: 支援 SNMP v2c/v3，使用 pysnmp 函式庫收集網路元件、告警、埠口狀態
- **PM 流量監控**: 進階 Performance Monitoring 功能，即時收集埠口流量統計
- **TNMS MIB 支援**: 使用官方 TNMS-NBI-MIB 定義
- **時序資料庫**: InfluxDB 2.7 儲存監控資料
- **視覺化儀表板**: Grafana 提供豐富的監控視圖
- **容器化部署**: Docker Compose 一鍵部署
- **健康檢查**: 內建服務健康監控和統計 API
- **自動重連**: 網路中斷自動重新連接
- **PM Request 管理**: 智能管理 PM 請求生命週期
- **流量速率計算**: 支援計數器溢位處理和速率計算

## 快速開始

### 1. Python 環境設定

本專案使用 Python 3.11，建議使用虛擬環境：

```bash
# 建立虛擬環境
python3 -m venv .venv

# 啟用虛擬環境
source .venv/bin/activate

# 安裝依賴套件
pip install -r requirements.txt
```

### 2. 環境設定

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

### 3. 啟動系統

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
- **健康檢查 API**: http://localhost:8080/health
- **系統統計 API**: http://localhost:8080/stats

#### 健康檢查 API 回應範例
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00.000Z",
  "uptime": "1:23:45",
  "stats": {
    "collections_count": 123,
    "pm_collections_count": 45,
    "records_collected": 5678,
    "records_written": 5678
  },
  "snmp_initialized": true,
  "influxdb_connected": true,
  "buffer_size": 0,
  "pm_collection_enabled": true,
  "port_statistics": {
    "total_ports": 24,
    "ports_with_traffic_data": 12
  }
}
```

## 專案結構

```
pysnmp/
├── .venv/                         # Python 虛擬環境
├── requirements.txt               # Python 依賴套件
├── docker-compose.yml             # Docker Compose 設定
├── .env                           # 環境變數
├── .gitignore                     # Git 忽略檔案
├── test_traffic_collection.py     # PM 流量測試腳本
├── mib/                           # SNMP MIB 檔案
│   └── TNMS-NBI-MIB.my           # TNMS 官方 MIB
├── snmp/                          # Python SNMP 收集器
│   ├── Dockerfile
│   ├── requirements.txt           # 容器專用依賴套件
│   ├── config.yaml               # 系統設定檔案
│   └── src/
│       ├── main.py               # 主程式（TNMSMonitor）
│       ├── snmp_collector.py     # SNMP 基本收集模組
│       ├── influxdb_writer.py    # InfluxDB 寫入模組
│       ├── port_traffic_collector.py  # PM 流量收集模組
│       └── pm_request_manager.py      # PM Request 管理模組
├── grafana/                       # Grafana 設定
│   ├── provisioning/              # 自動配置
│   │   ├── datasources/           # 資料源設定
│   │   │   └── influxdb.yml
│   │   └── dashboards/            # 儀表板設定
│   │       └── dashboards.yml
│   └── dashboards/                # 預設儀表板
└── influxdb/                      # InfluxDB 資料目錄
    └── data/
```

## 監控項目

系統支援兩種資料收集模式：

### 基本 SNMP 收集

#### 1. 網路元件 (Network Elements)
- 設備名稱與類型 (neName, neType)
- 設備狀態 (neState)
- 設備位置資訊 (neLocation)
- 測量名稱：`tnms_network_elements`

#### 2. 告警資訊 (Alarms)
- 告警ID與類型 (alarmId, alarmType)
- 告警嚴重度 (alarmSeverity)
- 告警時間與描述 (alarmTime, alarmText)
- 測量名稱：`tnms_alarms`

#### 3. 埠口狀態 (Ports)
- 埠口名稱與類型 (portName, portType)
- 管理狀態 (portAdminState)
- 運作狀態 (portOperState)
- 測量名稱：`tnms_ports`

### PM 流量監控 (Performance Monitoring)

#### 4. 埠口流量統計
- **計數器值**: 總位元組、封包、錯誤、丟棄計數
  - bytes_in_total / bytes_out_total
  - packets_in_total / packets_out_total
  - errors_in_total / errors_out_total
  - discards_in_total / discards_out_total

- **即時速率**: 每秒速率計算
  - bytes_in_rate / bytes_out_rate (位元組/秒)
  - bits_in_rate / bits_out_rate (位元/秒)
  - packets_in_rate / packets_out_rate (封包/秒)

- **埠口資訊**: 頻寬、狀態資訊
  - bandwidth (頻寬)
  - 埠口類型和狀態標籤

- 測量名稱：`port_traffic`
- 支援正則表達式篩選埠口（如：`GigE.*|10GE.*`）

## 設定說明

### 完整設定檔範例 (config.yaml)

```yaml
snmp:
  host: "${TNMS_HOST}"           # TNMS 伺服器位址
  port: 161                      # SNMP 埠口
  community: "${SNMP_COMMUNITY}" # Community String
  version: "2c"                  # SNMP 版本
  timeout: 5                     # 超時時間 (秒)
  retries: 3                     # 重試次數
  max_repetitions: 25            # SNMP Bulk 操作最大重複數

influxdb:
  url: "${INFLUXDB_URL}"         # InfluxDB 連線 URL
  token: "${INFLUXDB_TOKEN}"     # InfluxDB Token
  org: "${INFLUXDB_ORG}"         # InfluxDB 組織名稱
  bucket: "${INFLUXDB_BUCKET}"   # InfluxDB Bucket 名稱
  batch_size: 100                # 批次寫入大小
  flush_interval: 10             # 寫入間隔 (秒)

# 基本收集設定
collection:
  interval: 60                   # 收集間隔 (秒)
  startup_delay: 30              # 啟動延遲 (秒)

# PM 流量監控設定
pm_collection:
  enabled: true                  # 啟用 PM 收集
  interval: 60                   # PM 收集間隔 (秒)
  request_type: "pmCurrent"      # PM 請求類型
  timeout: 60                    # PM 請求超時 (秒)

  # 埠口篩選設定
  ports:
    auto_discovery: true         # 自動探索埠口
    filter: "GigE.*|10GE.*"      # 埠口名稱正則表達式篩選
    cache_ttl: 300              # 埠口清單快取時間 (秒)

  # 清理設定
  cleanup:
    old_counters_ttl: 3600      # 舊計數器資料保留時間
    old_requests_ttl: 1800      # 舊 PM 請求清理時間
```

### PM 流量監控進階設定

#### 1. 埠口篩選器
支援使用正則表達式篩選要監控的埠口：

```yaml
pm_collection:
  ports:
    filter: "GigE.*|10GE.*"       # 只監控 GigE 和 10GE 埠口
    # filter: ".*"                # 監控所有埠口
    # filter: "GigE0/1/[1-4]"     # 監控特定埠口範圍
```

#### 2. PM Request 生命週期
PM 收集採用以下步驟：
1. 探索可用埠口並快取 (5分鐘快取)
2. 建立 PM Request 並設定篩選條件
3. 執行 PM Request 並等待完成
4. 收集 PMP 和數值結果
5. 計算流量速率（處理計數器溢位）
6. 清理 PM Request 和舊資料

#### 3. 自訂 OID 監控
在 `config.yaml` 中新增自訂基本 SNMP 收集：

```yaml
oids:
  custom_metric:
    name: "customTable"
    oid: "1.3.6.1.4.1.42229.6.22.x.x"
    measurement: "tnms_custom"
    fields:
      - name: "customField"
        oid: "1.3.6.1.4.1.42229.6.22.x.x.x"
        type: "integer"  # 支援: string, integer, counter, gauge
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

# 即時查看收集器日誌
docker compose logs -f snmp
```

### SNMP 連接問題
```bash
# 進入收集器容器除錯
docker compose exec snmp bash

# 測試基本 SNMP 連接
snmpget -v2c -c public TNMS_HOST 1.3.6.1.2.1.1.1.0

# 測試 TNMS 特定 OID
snmpwalk -v2c -c public TNMS_HOST 1.3.6.1.4.1.42229.6.22.2.1

# 檢查健康狀態
curl http://localhost:8080/health | jq

# 檢查統計資訊
curl http://localhost:8080/stats | jq
```

### PM 流量收集問題
```bash
# 檢查 PM 收集是否啟用
curl http://localhost:8080/health | jq '.pm_collection_enabled'

# 檢查埠口探索結果
curl http://localhost:8080/health | jq '.port_statistics'

# 查看 PM 相關日誌
docker compose logs snmp | grep -i "pm\|traffic"

# 測試 PM Request 相關 OID (在容器內)
snmpget -v2c -c public TNMS_HOST 1.3.6.1.4.1.42229.6.22.10.1.0
```

### InfluxDB 資料檢查
```bash
# 進入 InfluxDB 容器
docker compose exec influxdb bash

# 使用 influx CLI 查詢
influx query 'from(bucket:"tnms_data") |> range(start:-1h)'
```

## 進階功能

### 流量速率計算
系統自動計算各項流量速率，支援：
- 32-bit 和 64-bit 計數器溢位處理
- 計數器重置偵測
- 異常數值過濾

### PM Request 管理
- 自動管理 PM Request 生命週期
- 支援並行多個 PM Request
- 自動清理過期的 Request
- 錯誤處理和重試機制

### 效能優化
- 埠口資訊快取機制 (TTL: 5分鐘)
- 批次資料寫入 InfluxDB
- 背景執行緒處理資料寫入
- SNMP 連線重用

## 自訂與擴展

### 新增基本監控項目
1. 在 MIB 檔案中找到要監控的 OID
2. 在 `config.yaml` 的 `oids` 區段新增定義
3. 重啟收集器服務

### 調整 PM 收集範圍
1. 修改 `config.yaml` 中的 `pm_collection.ports.filter`
2. 重啟服務讓新的篩選器生效

### 新增 Grafana 儀表板
1. 在 Grafana UI 中建立儀表板
2. 匯出 JSON 檔案
3. 放入 `grafana/dashboards/` 目錄
4. 重啟 Grafana 服務

### 擴展收集器功能
可以參考現有模組擴展功能：
- `snmp_collector.py`: 基本 SNMP 收集
- `port_traffic_collector.py`: PM 流量收集
- `pm_request_manager.py`: PM Request 管理
- `influxdb_writer.py`: 資料寫入

## 效能調校

### 基本收集器效能
- 調整 `collection.interval` 來控制基本收集頻率 (預設 60秒)
- 設定 `snmp.max_repetitions` 來優化 SNMP bulk 操作 (預設 25)
- 調整 `snmp.timeout` 和 `retries` 來適應網路環境

### PM 收集效能
- 調整 `pm_collection.interval` 來控制流量收集頻率 (預設 60秒)
- 使用 `pm_collection.ports.filter` 篩選需要的埠口以減少負載
- 設定 `pm_collection.ports.cache_ttl` 來控制埠口快取時間
- 調整 `pm_collection.cleanup` 參數來控制資料保留

### InfluxDB 寫入效能
- 調整 `influxdb.batch_size` 來控制寫入批次大小 (預設 100)
- 設定 `influxdb.flush_interval` 來平衡寫入效能與記憶體使用 (預設 10秒)
- 在 InfluxDB 中設定適當的資料保留策略

### 系統資源優化
- 監控容器記憶體和 CPU 使用率
- 根據埠口數量調整 Docker 容器資源限制
- 定期清理 InfluxDB 舊資料

## 安全考量

1. **修改預設密碼**: 變更 `.env` 中的所有預設密碼
2. **SNMP Community**: 使用強複雜度的 Community String
3. **網路存取控制**: 限制容器網路存取範圍
4. **資料加密**: 生產環境建議使用 SNMP v3

## 授權條款

本專案基於 MIT 授權條款發佈。