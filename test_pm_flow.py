#!/usr/bin/env python3
"""
TNMS PM Request 流程測試腳本
演示完整的 PM Request → 啟動 → 查 PMP → 查數值流程

根據 PTN TNMS SNMP NBI PDF 規格實作
"""

import os
import sys
import time
import logging
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# 添加src目錄到路徑
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'snmp', 'src'))

from pm_request_manager import PMRequestManager, PMRequestType, FilterType
from snmp_collector import TNMSSNMPCollector

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_test_config():
    """建立測試配置"""
    config = {
        'snmp': {
            'host': os.getenv('TNMS_HOST'),
            'port': 50161,
            'community': os.getenv('SNMP_COMMUNITY'),
            'version': '2c',
            'timeout': 5,
            'retries': 3,
            'max_repetitions': 25
        },
        'pm_collection': {
            'enabled': True,
            'interval': 60,
            'request_timeout': 60,
            'max_retries': 2
        }
    }
    return config

def test_port_discovery():
    """測試Port探索功能"""
    logger.info("=== Port 探索測試 ===")

    config = create_test_config()
    collector = TNMSSNMPCollector(config)

    # 測試SNMP連接
    if not collector.test_connection():
        logger.error("SNMP連接測試失敗")
        return None

    # 探索Port（使用Port表格OID）
    port_table_oid = '1.3.6.1.4.1.42229.6.22.2.3'
    logger.info(f"探索Port表格: {port_table_oid}")

    port_data = collector.walk_table(port_table_oid)

    if not port_data:
        logger.warning("沒有找到Port資料")
        return None

    # 解析Port資料
    ports = {}
    for oid, value in port_data.items():
        parts = oid.replace(f"{port_table_oid}.", "").split(".")
        if len(parts) >= 3:
            field_id = parts[0]
            ne_id = parts[1]
            port_id = parts[2]

            port_key = f"{ne_id}|{port_id}"

            if port_key not in ports:
                ports[port_key] = {
                    'ne_id': ne_id,
                    'port_id': port_id,
                    'port_key': port_key
                }

            # Port Name (field_id = 2)
            if field_id == '2':
                ports[port_key]['port_name'] = str(value)

    # 只保留有名稱的Port
    valid_ports = {k: v for k, v in ports.items() if 'port_name' in v}

    logger.info(f"發現 {len(valid_ports)} 個有效Port")

    # 顯示前10個Port
    for i, (port_key, port_info) in enumerate(list(valid_ports.items())[:10]):
        logger.info(f"  Port {i+1}: {port_key} - {port_info.get('port_name', 'N/A')}")

    return valid_ports

def test_pm_request_flow(test_ports):
    """測試完整的PM Request流程"""
    logger.info("=== PM Request 流程測試 ===")

    if not test_ports:
        logger.error("沒有可測試的Port")
        return False

    config = create_test_config()
    pm_manager = PMRequestManager(config)

    # 選擇前3個Port進行測試
    test_port_keys = list(test_ports.keys())[:3]
    filter_value = ','.join(test_port_keys)

    logger.info(f"測試Port: {test_port_keys}")

    try:
        # 步驟1: 建立PM Request
        logger.info("步驟1: 建立PM Request")
        request_name = f"Test_PM_Request_{int(time.time())}"

        request_id = pm_manager.create_pm_request(
            request_name=request_name,
            filter_value=filter_value,
            request_type=PMRequestType.PM_CURRENT,  # 使用當前PM資料
            filter_type=FilterType.PORT_OBJECT
        )

        if request_id is None:
            logger.error("PM Request 建立失敗")
            return False

        logger.info(f"PM Request 建立成功: ID={request_id}")

        # 步驟2: 執行PM Request
        logger.info("步驟2: 執行PM Request")
        success = pm_manager.execute_pm_request(
            request_id,
            timeout=60,
            max_retries=2
        )

        if not success:
            logger.error(f"PM Request {request_id} 執行失敗")
            # 清理失敗的Request
            pm_manager.delete_pm_request(request_id)
            return False

        logger.info(f"PM Request {request_id} 執行成功")

        # 步驟3: 查詢PMP和數值結果
        logger.info("步驟3: 查詢PM結果")
        pmp_results, value_results = pm_manager.get_pm_results(request_id)

        logger.info(f"查詢結果: {len(pmp_results)} 個PMP, {len(value_results)} 個數值")

        # 步驟4: 分析結果
        logger.info("步驟4: 分析PM結果")
        analyze_pm_results(pmp_results, value_results, test_ports)

        # 步驟5: 清理PM Request
        logger.info("步驟5: 清理PM Request")
        pm_manager.delete_pm_request(request_id)
        logger.info(f"PM Request {request_id} 已清理")

        return True

    except Exception as e:
        logger.error(f"PM Request流程測試發生錯誤: {e}", exc_info=True)
        # 確保清理Request
        if 'request_id' in locals() and request_id:
            try:
                pm_manager.delete_pm_request(request_id)
            except:
                pass
        return False

def analyze_pm_results(pmp_results, value_results, ports):
    """分析PM結果"""
    logger.info("=== PM 結果分析 ===")

    if not pmp_results:
        logger.warning("沒有PMP結果")
        return

    # 建立PMP資訊對應
    pmp_info = {}
    for pmp in pmp_results:
        pmp_number = pmp.get('pmp_number')
        pmp_info[pmp_number] = pmp

        logger.info(f"PMP {pmp_number}:")
        logger.info(f"  NE ID: {pmp.get('ne_id', 'N/A')}")
        logger.info(f"  Port ID: {pmp.get('port_id', 'N/A')}")
        logger.info(f"  PMP名稱: {pmp.get('pmp_name', 'N/A')}")
        logger.info(f"  方向: {pmp.get('direction', 'N/A')}")
        logger.info(f"  NE名稱: {pmp.get('ne_name', 'N/A')}")

    if not value_results:
        logger.warning("沒有數值結果")
        return

    # 按PMP分組數值
    pmp_values = {}
    for value in value_results:
        pmp_number = value.get('pmp_number')
        if pmp_number not in pmp_values:
            pmp_values[pmp_number] = []
        pmp_values[pmp_number].append(value)

    # 分析每個PMP的流量數據
    logger.info("=== 流量數據分析 ===")
    for pmp_number, values in pmp_values.items():
        pmp = pmp_info.get(pmp_number, {})
        port_key = f"{pmp.get('ne_id', '')}|{pmp.get('port_id', '')}"
        port_name = ports.get(port_key, {}).get('port_name', 'Unknown')

        logger.info(f"\nPMP {pmp_number} ({port_name}) 的流量數據:")

        traffic_data = {}
        for value in values:
            param_name = value.get('param_name', '')
            param_value = value.get('param_value', '0')
            unit = value.get('unit', '')

            # 分類流量參數
            param_lower = param_name.lower() if param_name else ''

            if 'byte' in param_lower or 'octet' in param_lower:
                direction = 'in' if any(x in param_lower for x in ['in', 'rx', 'receive']) else 'out'
                traffic_data[f'bytes_{direction}'] = param_value
            elif 'packet' in param_lower or 'frame' in param_lower:
                direction = 'in' if any(x in param_lower for x in ['in', 'rx', 'receive']) else 'out'
                traffic_data[f'packets_{direction}'] = param_value
            elif 'error' in param_lower:
                direction = 'in' if any(x in param_lower for x in ['in', 'rx', 'receive']) else 'out'
                traffic_data[f'errors_{direction}'] = param_value

            logger.info(f"  {param_name}: {param_value} {unit}")

        # 顯示整理後的流量統計
        if traffic_data:
            logger.info(f"  整理後的流量統計:")
            for key, value in traffic_data.items():
                logger.info(f"    {key}: {value}")

def main():
    """主函數"""
    logger.info("TNMS PM Request 流程測試開始")
    logger.info("=" * 50)

    # 檢查環境變數
    if not os.getenv('TNMS_HOST') or not os.getenv('SNMP_COMMUNITY'):
        logger.error("請確認.env檔案中設定了TNMS_HOST和SNMP_COMMUNITY")
        return

    try:
        # 步驟1: 探索Port
        test_ports = test_port_discovery()

        if not test_ports:
            logger.error("Port探索失敗，無法進行PM測試")
            return

        # 步驟2: 測試PM Request流程
        success = test_pm_request_flow(test_ports)

        # 總結
        logger.info("\n" + "=" * 50)
        if success:
            logger.info("✓ PM Request 流程測試成功!")
            logger.info("完整流程: PM Request建立 → 執行 → 查PMP → 查數值 → 清理")
        else:
            logger.error("✗ PM Request 流程測試失敗")

    except KeyboardInterrupt:
        logger.info("測試被用戶中斷")
    except Exception as e:
        logger.error(f"測試過程發生錯誤: {e}", exc_info=True)

if __name__ == '__main__':
    main()