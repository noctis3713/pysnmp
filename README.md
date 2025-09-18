# TNMS SNMP 監控系統

基於 Docker Compose 的 TNMS SNMP 資料收集與監控解決方案，使用 Python + InfluxDB + Grafana 架構。

## 專案概述

這是一個客製化的監控解決方案，旨在從 TNMS 伺服器收集、儲存並視覺化網路設備數據。系統設計支援兩種模式：

1. **基本監控模式**（目前可用）：使用 SNMP GET 指令收集網路元件狀態和告警資訊
2. **進階流量監控模式**（暫時無法使用）：透過包含 GET 與 SET 指令的有狀態多步驟 PM Request 交易流程，擷取介面流量計數器並計算即時速率

收集到的數據會格式化為 InfluxDB Line Protocol，透過 HTTP API 寫入時序資料庫。Grafana 儀表板連接 InfluxDB，使用 Flux 查詢生成互動式圖表，完成從數據採集到視覺呈現的完整流程。

## 系統架構

```
TNMS Server
    ↓ (SNMP GET/SET)
Python Collector (pysnmp)
    ↓ (計算速率)
InfluxDB Writer
    ↓ (HTTP API + Line Protocol)
InfluxDB Database
    ↓ (Flux Query)
Grafana Dashboard
    ↓
Interactive Charts
```

**技術說明**：
- SNMP 支援 GET（唯讀）和 SET（寫入）操作
- 基本監控僅使用 GET 指令收集 NE 狀態和告警
- PM Request 管理需要 SET 指令（目前因 TNMS 端問題無法使用）
- 速率計算在 Python 層進行，支援計數器溢位處理
- 使用 Line Protocol 格式批次寫入時序資料庫

## 功能狀態

✅ **可用功能**：
- 網路元素(NE)監控 - 49個設備狀態追蹤
- 告警監控 - 即時告警收集（1137筆告警）
- 基本SNMP查詢和資料視覺化
- Docker容器化部署

⏸️ **暫時無法使用**：
- PM流量監控（TNMS端PM功能未啟用）
- Port資訊收集（Port表格無資料）

📋 **已知限制**：
- PM Request功能（OID 1.3.6.1.4.1.42229.6.22.10.1.0）回傳 NoSuchObject
- OperationalState值與MIB定義不完全一致

## 快速開始

### 1. 環境設定
複製並編輯環境變數：
```bash
cp .env.example .env
# 設定 TNMS_HOST 和 SNMP_COMMUNITY
```

### 2. 啟動系統
```bash
docker compose up -d           # 啟動所有服務
docker compose logs -f snmp    # 查看收集器日誌
```

### 3. 存取介面
| 服務 | 網址 | 帳號/密碼 |
|------|------|-----------|
| Grafana 儀表板 | http://localhost:3000 | admin/admin123 |
| InfluxDB UI | http://localhost:8086 | admin/password123 |
| 健康檢查 API | http://localhost:8080/health | - |

## 監控項目

### 目前可用的監控功能

| 監控項目 | 資料表 | 狀態 | 說明 |
|----------|--------|------|------|
| 網路元件(NE) | `tnms_network_elements` | ✅ 正常 | 49個設備的名稱、類型、狀態 |
| 告警資訊 | `tnms_alarms` | ✅ 正常 | 1137筆告警的即時監控 |
| 埠口狀態 | `tnms_ports` | ❌ 無資料 | Port表格暫時無法取得資料 |
| PM流量統計 | `port_traffic` | ❌ 無法使用 | PM Request功能未啟用 |

### 測試腳本

專案包含多個測試腳本：
- `simple_snmp_test.py` - 基本SNMP連線測試
- `test_pm_direct.py` - PM Request直接測試
- `test_pm_real_data.py` - 真實資料PM測試
- `test_pm_flow.py` - 完整PM流程測試

## 設定檔案

主要設定檔案位於 `snmp/config.yaml`，包含：

### 基本SNMP設定
```yaml
snmp:
  host: "${TNMS_HOST}"
  community: "${SNMP_COMMUNITY}"
  timeout: 5
  retries: 3
```

### 資料收集設定
```yaml
collection:
  interval: 60              # 收集間隔(秒)

pm_collection:
  enabled: true             # PM功能(目前無法使用)
  interval: 60
```

詳細設定請參考 `snmp/config.yaml` 檔案。

## 疑難排解

### 常用指令
```bash
# 查看服務狀態
docker compose ps

# 查看收集器日誌
docker compose logs -f snmp

# 檢查健康狀態
curl http://localhost:8080/health

# 測試SNMP連線
python simple_snmp_test.py
```

### 常見問題

**Q: 沒有收集到資料**
```bash
# 檢查SNMP連接
docker compose logs snmp | grep -i error

# 確認.env設定正確
cat .env
```

**Q: PM功能無法使用**
A: 目前TNMS端PM功能未啟用，這是已知限制。

**Q: Grafana無法連接InfluxDB**
A: 確認所有容器都正常啟動：`docker compose ps`

## 專案結構
```
pysnmp/
├── docker-compose.yml     # Docker服務定義
├── .env                   # 環境變數設定
├── snmp/                  # SNMP收集器
│   ├── config.yaml        # 主要設定檔
│   └── src/               # Python源碼
├── grafana/               # Grafana設定
└── influxdb/              # InfluxDB資料目錄
```