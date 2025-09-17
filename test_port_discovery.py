#!/usr/bin/env python3
"""
使用GETNEXT/GETBULK在enmsPortTable中查出NEId/PortId
然後用這些真實的組合作為PM request的FilterValue
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
        }
    }
    return config

def discover_ports_with_getnext():
    """使用GETNEXT/GETBULK在enmsPortTable中發現Port"""
    logger.info("=== 使用GETNEXT/GETBULK發現Port ===")

    config = create_test_config()
    collector = TNMSSNMPCollector(config)

    # enmsPortTable的各個可能OID
    port_table_oids = [
        '1.3.6.1.4.1.42229.6.22.2.3.1',     # enmsPortEntry
        '1.3.6.1.4.1.42229.6.22.2.3.1.1',   # enmsPortId
        '1.3.6.1.4.1.42229.6.22.2.3.1.2',   # enmsPortName
        '1.3.6.1.4.1.42229.6.22.2.3.1.3',   # enmsPortType
        '1.3.6.1.4.1.42229.6.22.2.3.1.4',   # enmsPortState
        '1.3.6.1.4.1.42229.6.22.2.3',       # enmsPortTable
    ]

    found_ports = {}

    for base_oid in port_table_oids:
        logger.info(f"\\n--- 測試 OID: {base_oid} ---")

        try:
            # 使用bulkCmd進行GETBULK操作
            port_data = collector.walk_table(base_oid)

            if port_data:
                logger.info(f"在 {base_oid} 找到 {len(port_data)} 個項目")

                # 解析Port資料，提取NEId和PortId
                temp_ports = {}
                for oid, value in port_data.items():
                    # 從OID中提取索引 (NEId, PortId)
                    # 格式應該是: base_oid.field.neId.portId
                    oid_suffix = oid.replace(f"{base_oid}.", "")
                    parts = oid_suffix.split(".")

                    if len(parts) >= 2:
                        # 假設最後兩個部分是NEId和PortId
                        ne_id = parts[-2]
                        port_id = parts[-1]
                        port_key = f"{ne_id}|{port_id}"

                        if port_key not in temp_ports:
                            temp_ports[port_key] = {
                                'ne_id': ne_id,
                                'port_id': port_id,
                                'port_key': port_key
                            }

                        # 根據field類型儲存資訊
                        if len(parts) >= 3:
                            field_id = parts[-3]
                            if field_id == '2' and value:  # Port Name
                                temp_ports[port_key]['port_name'] = str(value)
                            elif field_id == '3' and value:  # Port Type
                                temp_ports[port_key]['port_type'] = str(value)
                            elif field_id == '4' and value:  # Port State
                                temp_ports[port_key]['port_state'] = str(value)

                # 顯示找到的Port資訊
                valid_ports = {k: v for k, v in temp_ports.items() if len(v) > 3}  # 有額外資訊的Port
                if valid_ports:
                    logger.info(f"找到 {len(valid_ports)} 個有效Port:")
                    for i, (port_key, port_info) in enumerate(list(valid_ports.items())[:5]):
                        logger.info(f"  Port {i+1}: {port_key}")
                        logger.info(f"    名稱: {port_info.get('port_name', 'N/A')}")
                        logger.info(f"    類型: {port_info.get('port_type', 'N/A')}")
                        logger.info(f"    狀態: {port_info.get('port_state', 'N/A')}")

                    found_ports.update(valid_ports)
                    break  # 找到有效資料就停止
                else:
                    # 顯示原始資料以便分析
                    logger.info("原始資料範例:")
                    for i, (oid, value) in enumerate(list(port_data.items())[:5]):
                        logger.info(f"  {oid} = {value}")
                    if len(port_data) > 5:
                        logger.info(f"  ... 還有 {len(port_data)-5} 個項目")
            else:
                logger.info(f"在 {base_oid} 沒有找到資料")

        except Exception as e:
            logger.error(f"查詢 {base_oid} 時發生錯誤: {e}")
            continue

    return found_ports

def discover_ports_systematic():
    """系統性地搜索Port表格"""
    logger.info("=== 系統性搜索Port表格 ===")

    config = create_test_config()
    collector = TNMSSNMPCollector(config)

    # 先確認已知的NE
    ne_ids = ['35', '41', '81', '125', '143']  # 從之前發現的NE

    found_ports = {}

    # 測試不同的Port表格結構
    port_base_oids = [
        '1.3.6.1.4.1.42229.6.22.2.3.1',
        '1.3.6.1.4.1.42229.6.22.2.4.1',
        '1.3.6.1.4.1.42229.6.22.2.5.1',
        '1.3.6.1.4.1.42229.6.22.7.1',
        '1.3.6.1.4.1.42229.6.22.8.1',
    ]

    for base_oid in port_base_oids:
        logger.info(f"\\n--- 測試Port基礎OID: {base_oid} ---")

        # 先測試是否有任何資料
        data = collector.walk_table(base_oid)
        if data:
            logger.info(f"找到 {len(data)} 個項目")

            # 分析OID結構
            sample_oids = list(data.keys())[:10]
            logger.info("OID結構分析:")
            for oid in sample_oids:
                suffix = oid.replace(f"{base_oid}.", "")
                parts = suffix.split(".")
                logger.info(f"  {oid} -> 後綴: {suffix} (部分數: {len(parts)})")

            # 嘗試解析為Port資料
            ports = parse_port_data(data, base_oid)
            if ports:
                logger.info(f"解析出 {len(ports)} 個Port")
                found_ports.update(ports)
                return found_ports  # 找到有效資料就返回
        else:
            logger.info("沒有資料")

    return found_ports

def parse_port_data(raw_data, base_oid):
    """解析Port原始資料"""
    ports = {}

    for oid, value in raw_data.items():
        suffix = oid.replace(f"{base_oid}.", "")
        parts = suffix.split(".")

        # 嘗試不同的索引結構
        if len(parts) == 2:
            # 格式: field.index 或 neId.portId
            ne_id, port_id = parts[0], parts[1]
            port_key = f"{ne_id}|{port_id}"
        elif len(parts) == 3:
            # 格式: field.neId.portId
            field_id, ne_id, port_id = parts[0], parts[1], parts[2]
            port_key = f"{ne_id}|{port_id}"
        elif len(parts) >= 4:
            # 更複雜的結構，取最後兩個作為neId.portId
            ne_id, port_id = parts[-2], parts[-1]
            port_key = f"{ne_id}|{port_id}"
        else:
            continue

        if port_key not in ports:
            ports[port_key] = {
                'ne_id': ne_id,
                'port_id': port_id,
                'port_key': port_key
            }

        # 儲存值（如果有意義的話）
        if value and str(value).strip():
            if 'values' not in ports[port_key]:
                ports[port_key]['values'] = []
            ports[port_key]['values'].append(str(value))

    return ports

def test_pm_with_real_ports(discovered_ports):
    """使用發現的真實Port測試PM Request"""
    logger.info("=== 使用真實Port測試PM Request ===")

    if not discovered_ports:
        logger.error("沒有發現Port，無法測試PM Request")
        return False

    config = create_test_config()
    pm_manager = PMRequestManager(config)

    # 選擇前3個Port進行測試
    test_ports = list(discovered_ports.items())[:3]
    test_port_keys = [port_key for port_key, _ in test_ports]

    logger.info(f"使用以下Port進行PM Request測試:")
    for port_key, port_info in test_ports:
        logger.info(f"  {port_key}: {port_info.get('port_name', 'N/A')}")

    try:
        # 建立PM Request
        request_name = f"Real_Port_Test_{len(test_port_keys)}ports_{int(time.time())}"
        filter_value = ','.join(test_port_keys)  # 使用真實的NEId|PortId組合

        logger.info(f"PM Request FilterValue: {filter_value}")

        request_id = pm_manager.create_pm_request(
            request_name=request_name,
            filter_value=filter_value,
            request_type=PMRequestType.PM_CURRENT,
            filter_type=FilterType.PORT_OBJECT  # 使用PORT_OBJECT篩選
        )

        if request_id is None:
            logger.error("PM Request建立失敗")
            return False

        logger.info(f"PM Request建立成功: ID={request_id}")

        # 執行PM Request
        logger.info("執行PM Request...")
        success = pm_manager.execute_pm_request(
            request_id,
            timeout=60,
            max_retries=2
        )

        if success:
            logger.info("PM Request執行成功，查詢結果...")

            # 查詢PMP和數值結果
            pmp_results, value_results = pm_manager.get_pm_results(request_id)

            logger.info(f"PM結果: {len(pmp_results)} 個PMP, {len(value_results)} 個數值")

            # 分析介面流量數值
            if value_results:
                analyze_traffic_values(pmp_results, value_results, dict(test_ports))
            else:
                logger.warning("沒有取得數值結果")

        else:
            logger.error("PM Request執行失敗")
            error_info = pm_manager.get_request_info(request_id)
            if error_info:
                logger.error(f"錯誤資訊: {error_info}")

        # 清理
        pm_manager.delete_pm_request(request_id)
        return success

    except Exception as e:
        logger.error(f"PM Request測試發生錯誤: {e}", exc_info=True)
        if 'request_id' in locals() and request_id:
            try:
                pm_manager.delete_pm_request(request_id)
            except:
                pass
        return False

def analyze_traffic_values(pmp_results, value_results, port_dict):
    """分析介面流量數值"""
    logger.info("=== 介面流量數值分析 ===")

    # 建立PMP到Port的對應
    pmp_to_port = {}
    for pmp in pmp_results:
        pmp_number = pmp.get('pmp_number')
        ne_id = pmp.get('ne_id')
        port_id = pmp.get('port_id')

        if ne_id and port_id:
            port_key = f"{ne_id}|{port_id}"
            pmp_to_port[pmp_number] = {
                'port_key': port_key,
                'pmp_name': pmp.get('pmp_name', ''),
                'direction': pmp.get('direction', ''),
                'ne_name': pmp.get('ne_name', '')
            }

    logger.info(f"PMP到Port對應: {len(pmp_to_port)} 個PMP")

    # 按PMP分組流量數值
    traffic_by_pmp = {}
    for value in value_results:
        pmp_number = value.get('pmp_number')
        param_name = value.get('param_name', '')
        param_value = value.get('param_value', '0')
        unit = value.get('unit', '')

        if pmp_number not in traffic_by_pmp:
            traffic_by_pmp[pmp_number] = []

        traffic_by_pmp[pmp_number].append({
            'param': param_name,
            'value': param_value,
            'unit': unit
        })

    # 分析每個PMP的流量數據
    logger.info("\\n流量數據詳細分析:")
    for pmp_number, pmp_info in pmp_to_port.items():
        port_key = pmp_info['port_key']
        port_name = port_dict.get(port_key, {}).get('port_name', 'Unknown')

        logger.info(f"\\nPort {port_key} ({port_name}) - PMP {pmp_number}:")
        logger.info(f"  PMP名稱: {pmp_info['pmp_name']}")
        logger.info(f"  方向: {pmp_info['direction']}")
        logger.info(f"  NE名稱: {pmp_info['ne_name']}")

        if pmp_number in traffic_by_pmp:
            values = traffic_by_pmp[pmp_number]
            logger.info(f"  流量數據 ({len(values)} 個參數):")

            # 分類流量數據
            bytes_data = []
            packets_data = []
            errors_data = []
            other_data = []

            for v in values:
                param_lower = v['param'].lower()
                if any(x in param_lower for x in ['byte', 'octet']):
                    bytes_data.append(v)
                elif any(x in param_lower for x in ['packet', 'frame']):
                    packets_data.append(v)
                elif 'error' in param_lower:
                    errors_data.append(v)
                else:
                    other_data.append(v)

            # 顯示分類的數據
            if bytes_data:
                logger.info("    位元組/八位元組數據:")
                for v in bytes_data:
                    logger.info(f"      {v['param']}: {v['value']} {v['unit']}")

            if packets_data:
                logger.info("    封包/幀數據:")
                for v in packets_data:
                    logger.info(f"      {v['param']}: {v['value']} {v['unit']}")

            if errors_data:
                logger.info("    錯誤數據:")
                for v in errors_data:
                    logger.info(f"      {v['param']}: {v['value']} {v['unit']}")

            if other_data:
                logger.info("    其他數據:")
                for v in other_data[:3]:  # 只顯示前3個
                    logger.info(f"      {v['param']}: {v['value']} {v['unit']}")
        else:
            logger.info("  沒有找到對應的數值資料")

def main():
    """主函數"""
    logger.info("TNMS Port發現與PM Request測試")
    logger.info("=" * 60)

    # 檢查環境變數
    if not os.getenv('TNMS_HOST') or not os.getenv('SNMP_COMMUNITY'):
        logger.error("請確認.env檔案中設定了TNMS_HOST和SNMP_COMMUNITY")
        return

    try:
        # 步驟1: 使用GETNEXT/GETBULK發現Port
        logger.info("步驟1: 使用GETNEXT/GETBULK發現enmsPortTable中的Port")
        discovered_ports = discover_ports_with_getnext()

        if not discovered_ports:
            logger.info("標準方法沒找到Port，嘗試系統性搜索...")
            discovered_ports = discover_ports_systematic()

        if not discovered_ports:
            logger.error("無法發現任何Port，測試終止")
            return

        logger.info(f"\\n✓ 成功發現 {len(discovered_ports)} 個Port")

        # 步驟2: 使用發現的真實Port進行PM Request測試
        logger.info("\\n步驟2: 使用發現的真實Port測試PM Request")
        pm_success = test_pm_with_real_ports(discovered_ports)

        # 總結
        logger.info("\\n" + "=" * 60)
        logger.info("測試完成總結:")
        logger.info(f"發現Port數量: {len(discovered_ports)}")
        logger.info(f"PM Request測試: {'✓ 成功' if pm_success else '✗ 失敗'}")

        if pm_success:
            logger.info("\\n🎉 完整流程驗證成功！")
            logger.info("流程: GETBULK發現Port → 建立PM Request → 執行 → 查PMP → 查數值 → 分析流量")
            logger.info("系統已能從TNMS Server抓取真實的介面流量數值！")

    except KeyboardInterrupt:
        logger.info("測試被用戶中斷")
    except Exception as e:
        logger.error(f"測試過程發生錯誤: {e}", exc_info=True)

if __name__ == '__main__':
    main()