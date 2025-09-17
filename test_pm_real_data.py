#!/usr/bin/env python3
"""
使用TNMS系統中實際存在的資料測試PM Request流程
基於真實的NE資料進行測試
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

def discover_real_network_elements():
    """探索TNMS系統中實際的網路元素"""
    logger.info("=== 探索實際網路元素 ===")

    config = create_test_config()
    collector = TNMSSNMPCollector(config)

    # 測試SNMP連接
    if not collector.test_connection():
        logger.error("SNMP連接測試失敗")
        return None

    # 探索網路元素表格
    ne_table_oid = '1.3.6.1.4.1.42229.6.22.1.1.1'
    logger.info(f"探索網路元素表格: {ne_table_oid}")

    ne_data = collector.walk_table(ne_table_oid)

    if not ne_data:
        logger.warning("沒有找到網路元素資料")
        return None

    # 解析NE資料
    ne_info = {}
    for oid, value in ne_data.items():
        parts = oid.replace(f"{ne_table_oid}.", "").split(".")
        if len(parts) >= 2:
            field_id = parts[0]
            ne_id = parts[1]

            if ne_id not in ne_info:
                ne_info[ne_id] = {'ne_id': ne_id}

            # NE名稱 (field 3)
            if field_id == '3':
                ne_info[ne_id]['ne_name'] = str(value)
            # NE類型 (field 2)
            elif field_id == '2':
                ne_info[ne_id]['ne_type'] = str(value)
            # NE狀態 (field 5)
            elif field_id == '5':
                ne_info[ne_id]['ne_state'] = str(value)

    # 只保留有名稱的NE
    valid_nes = {k: v for k, v in ne_info.items() if 'ne_name' in v}

    logger.info(f"發現 {len(valid_nes)} 個有效網路元素")

    # 顯示前5個NE
    for i, (ne_id, ne_info_item) in enumerate(list(valid_nes.items())[:5]):
        logger.info(f"  NE {i+1}: ID={ne_id}, 名稱={ne_info_item.get('ne_name', 'N/A')}, 類型={ne_info_item.get('ne_type', 'N/A')}")

    return valid_nes

def test_pm_request_with_real_ne(real_nes):
    """使用真實NE資料測試PM Request流程"""
    logger.info("=== 使用真實NE資料測試PM Request ===")

    if not real_nes:
        logger.error("沒有可測試的NE")
        return False

    config = create_test_config()
    pm_manager = PMRequestManager(config)

    # 選擇第一個NE進行測試
    test_ne_id, test_ne_info = list(real_nes.items())[0]
    logger.info(f"使用NE進行測試: ID={test_ne_id}, 名稱={test_ne_info.get('ne_name')}")

    try:
        # 步驟1: 建立PM Request
        logger.info("步驟1: 建立PM Request")
        request_name = f"Real_NE_Test_{test_ne_info.get('ne_name', 'Unknown')}_{int(time.time())}"

        request_id = pm_manager.create_pm_request(
            request_name=request_name,
            filter_value=test_ne_id,  # 使用真實的NE ID
            request_type=PMRequestType.PM_CURRENT,
            filter_type=FilterType.NE_OBJECT  # NE物件篩選
        )

        if request_id is None:
            logger.error("PM Request 建立失敗")
            return False

        logger.info(f"PM Request 建立成功: ID={request_id}")

        # 步驟2: 執行PM Request
        logger.info("步驟2: 執行PM Request")
        success = pm_manager.execute_pm_request(
            request_id,
            timeout=45,
            max_retries=2
        )

        if not success:
            logger.error(f"PM Request {request_id} 執行失敗")
            # 取得錯誤資訊
            error_info = pm_manager.get_request_info(request_id)
            if error_info:
                logger.error(f"錯誤資訊: {error_info}")
            # 清理失敗的Request
            pm_manager.delete_pm_request(request_id)
            return False

        logger.info(f"PM Request {request_id} 執行成功")

        # 步驟3: 查詢PMP和數值結果
        logger.info("步驟3: 查詢PM結果")
        pmp_results, value_results = pm_manager.get_pm_results(request_id)

        logger.info(f"查詢結果: {len(pmp_results)} 個PMP, {len(value_results)} 個數值")

        # 步驟4: 分析結果
        if pmp_results or value_results:
            logger.info("步驟4: 分析PM結果")
            analyze_real_pm_results(pmp_results, value_results, test_ne_info)

            # 步驟5: 清理PM Request
            logger.info("步驟5: 清理PM Request")
            pm_manager.delete_pm_request(request_id)
            logger.info(f"PM Request {request_id} 已清理")

            return True
        else:
            logger.warning("沒有取得任何PM結果")
            pm_manager.delete_pm_request(request_id)
            return False

    except Exception as e:
        logger.error(f"PM Request流程測試發生錯誤: {e}", exc_info=True)
        # 確保清理Request
        if 'request_id' in locals() and request_id:
            try:
                pm_manager.delete_pm_request(request_id)
            except:
                pass
        return False

def test_pm_request_with_multiple_nes(real_nes, max_nes=3):
    """使用多個真實NE測試PM Request"""
    logger.info(f"=== 使用多個NE測試PM Request (最多{max_nes}個) ===")

    if not real_nes:
        logger.error("沒有可測試的NE")
        return False

    config = create_test_config()
    pm_manager = PMRequestManager(config)

    # 選擇前幾個NE進行測試
    test_nes = list(real_nes.items())[:max_nes]
    test_ne_ids = [ne_id for ne_id, _ in test_nes]
    filter_value = ','.join(test_ne_ids)

    logger.info(f"使用NE進行測試: {[f'{ne_id}({info.get(\"ne_name\")})' for ne_id, info in test_nes]}")

    try:
        # 建立PM Request
        request_name = f"Multi_NE_Test_{len(test_nes)}NEs_{int(time.time())}"

        request_id = pm_manager.create_pm_request(
            request_name=request_name,
            filter_value=filter_value,  # 使用多個真實NE ID
            request_type=PMRequestType.PM_CURRENT,
            filter_type=FilterType.NE_OBJECT
        )

        if request_id is None:
            logger.error("多NE PM Request 建立失敗")
            return False

        logger.info(f"多NE PM Request 建立成功: ID={request_id}")

        # 執行PM Request
        success = pm_manager.execute_pm_request(
            request_id,
            timeout=60,  # 多個NE可能需要更長時間
            max_retries=2
        )

        if success:
            # 查詢結果
            pmp_results, value_results = pm_manager.get_pm_results(request_id)
            logger.info(f"多NE查詢結果: {len(pmp_results)} 個PMP, {len(value_results)} 個數值")

            if pmp_results or value_results:
                # 按NE分組分析結果
                analyze_multi_ne_results(pmp_results, value_results, dict(test_nes))

        # 清理
        pm_manager.delete_pm_request(request_id)
        return success

    except Exception as e:
        logger.error(f"多NE PM Request測試發生錯誤: {e}", exc_info=True)
        if 'request_id' in locals() and request_id:
            try:
                pm_manager.delete_pm_request(request_id)
            except:
                pass
        return False

def analyze_real_pm_results(pmp_results, value_results, ne_info):
    """分析真實的PM結果"""
    logger.info("=== 真實PM結果分析 ===")

    if pmp_results:
        logger.info(f"PMP結果 ({len(pmp_results)} 個):")
        for i, pmp in enumerate(pmp_results[:3]):  # 顯示前3個
            logger.info(f"  PMP {i+1}:")
            logger.info(f"    PMP編號: {pmp.get('pmp_number', 'N/A')}")
            logger.info(f"    NE ID: {pmp.get('ne_id', 'N/A')}")
            logger.info(f"    Port ID: {pmp.get('port_id', 'N/A')}")
            logger.info(f"    PMP名稱: {pmp.get('pmp_name', 'N/A')}")
            logger.info(f"    方向: {pmp.get('direction', 'N/A')}")
            logger.info(f"    位置: {pmp.get('location', 'N/A')}")

    if value_results:
        logger.info(f"\\n數值結果 ({len(value_results)} 個):")

        # 統計參數類型
        param_stats = {}
        for value in value_results:
            param_name = value.get('param_name', 'Unknown')
            param_stats[param_name] = param_stats.get(param_name, 0) + 1

        logger.info("參數類型統計:")
        for param, count in sorted(param_stats.items()):
            logger.info(f"  {param}: {count} 個")

        # 顯示一些具體數值
        logger.info("\\n數值範例:")
        traffic_values = []
        for i, value in enumerate(value_results[:10]):  # 顯示前10個
            param_name = value.get('param_name', '')
            param_value = value.get('param_value', '0')
            unit = value.get('unit', '')

            logger.info(f"  值 {i+1}: {param_name} = {param_value} {unit}")

            # 收集疑似流量相關的數值
            if any(keyword in param_name.lower() for keyword in ['byte', 'packet', 'frame', 'bit', 'octet']):
                traffic_values.append({
                    'name': param_name,
                    'value': param_value,
                    'unit': unit
                })

        if traffic_values:
            logger.info("\\n疑似流量相關數值:")
            for traffic in traffic_values[:5]:  # 顯示前5個流量數值
                logger.info(f"  {traffic['name']}: {traffic['value']} {traffic['unit']}")

def analyze_multi_ne_results(pmp_results, value_results, ne_dict):
    """分析多NE的PM結果"""
    logger.info("=== 多NE PM結果分析 ===")

    # 按NE分組PMP結果
    ne_pmp_count = {}
    for pmp in pmp_results:
        ne_id = pmp.get('ne_id', 'Unknown')
        ne_pmp_count[ne_id] = ne_pmp_count.get(ne_id, 0) + 1

    logger.info("各NE的PMP數量:")
    for ne_id, count in ne_pmp_count.items():
        ne_name = ne_dict.get(ne_id, {}).get('ne_name', 'Unknown')
        logger.info(f"  NE {ne_id} ({ne_name}): {count} 個PMP")

    # 按NE分組數值結果
    ne_value_count = {}
    for value in value_results:
        pmp_number = value.get('pmp_number')
        # 通過PMP找對應的NE
        for pmp in pmp_results:
            if pmp.get('pmp_number') == pmp_number:
                ne_id = pmp.get('ne_id', 'Unknown')
                ne_value_count[ne_id] = ne_value_count.get(ne_id, 0) + 1
                break

    logger.info("\\n各NE的數值數量:")
    for ne_id, count in ne_value_count.items():
        ne_name = ne_dict.get(ne_id, {}).get('ne_name', 'Unknown')
        logger.info(f"  NE {ne_id} ({ne_name}): {count} 個數值")

def main():
    """主函數"""
    logger.info("TNMS PM Request 真實資料測試開始")
    logger.info("=" * 60)

    # 檢查環境變數
    if not os.getenv('TNMS_HOST') or not os.getenv('SNMP_COMMUNITY'):
        logger.error("請確認.env檔案中設定了TNMS_HOST和SNMP_COMMUNITY")
        return

    try:
        # 步驟1: 探索真實NE
        real_nes = discover_real_network_elements()

        if not real_nes:
            logger.error("無法探索到真實NE資料，測試無法進行")
            return

        # 步驟2: 使用單個真實NE測試PM Request流程
        single_success = test_pm_request_with_real_ne(real_nes)

        # 步驟3: 使用多個真實NE測試PM Request流程
        multi_success = test_pm_request_with_multiple_nes(real_nes, max_nes=3)

        # 總結
        logger.info("\\n" + "=" * 60)
        logger.info("真實資料測試完成總結:")
        logger.info(f"發現網路元素數量: {len(real_nes)}")
        logger.info(f"單NE PM Request測試: {'✓ 成功' if single_success else '✗ 失敗'}")
        logger.info(f"多NE PM Request測試: {'✓ 成功' if multi_success else '✗ 失敗'}")

        if single_success or multi_success:
            logger.info("\\n🎉 PM Request流程驗證成功！")
            logger.info("完整流程: 探索真實NE → 建立PM Request → 執行 → 查詢PMP → 查詢數值 → 分析 → 清理")
            logger.info("系統已具備從TNMS Server抓取介面流量數值的完整功能！")
        else:
            logger.error("\\n❌ PM Request流程測試失敗")
            logger.info("可能原因:")
            logger.info("1. TNMS系統PM功能未完全啟用")
            logger.info("2. 測試NE沒有PM資料")
            logger.info("3. SNMP權限限制")

    except KeyboardInterrupt:
        logger.info("測試被用戶中斷")
    except Exception as e:
        logger.error(f"測試過程發生錯誤: {e}", exc_info=True)

if __name__ == '__main__':
    main()