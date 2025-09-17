#!/usr/bin/env python3
"""
直接測試PM Request流程，不依賴Port探索
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

def test_pm_request_basic():
    """測試基本PM Request功能"""
    logger.info("=== 基本PM Request測試 ===")

    config = create_test_config()
    pm_manager = PMRequestManager(config)

    try:
        # 步驟1: 取得下一個Request ID
        logger.info("步驟1: 取得下一個Request ID")
        request_id = pm_manager.get_next_request_id()

        if request_id is None:
            logger.error("無法取得Request ID")
            return False

        logger.info(f"下一個可用Request ID: {request_id}")

        # 步驟2: 建立PM Request（使用簡單的測試filter）
        logger.info("步驟2: 建立PM Request")
        request_name = f"Test_Basic_PM_{int(time.time())}"
        filter_value = "35"  # 使用我們知道存在的NE ID

        request_id = pm_manager.create_pm_request(
            request_name=request_name,
            filter_value=filter_value,
            request_type=PMRequestType.PM_CURRENT,
            filter_type=FilterType.NE_OBJECT  # 改用NE_OBJECT
        )

        if request_id is None:
            logger.error("PM Request建立失敗")
            return False

        logger.info(f"PM Request建立成功: ID={request_id}, 名稱={request_name}")

        # 步驟3: 查詢Request狀態
        logger.info("步驟3: 查詢Request狀態")
        state = pm_manager.get_request_state(request_id)
        logger.info(f"Request {request_id} 初始狀態: {state}")

        # 步驟4: 執行PM Request
        logger.info("步驟4: 執行PM Request")
        success = pm_manager.execute_pm_request(
            request_id,
            timeout=30,
            max_retries=1
        )

        if success:
            logger.info(f"PM Request {request_id} 執行成功")

            # 步驟5: 查詢結果
            logger.info("步驟5: 查詢PM結果")
            pmp_results, value_results = pm_manager.get_pm_results(request_id)

            logger.info(f"查詢結果: {len(pmp_results)} 個PMP, {len(value_results)} 個數值")

            # 顯示部分結果
            if pmp_results:
                logger.info("PMP結果範例:")
                for i, pmp in enumerate(pmp_results[:3]):
                    logger.info(f"  PMP {i+1}: {pmp}")

            if value_results:
                logger.info("數值結果範例:")
                for i, value in enumerate(value_results[:5]):
                    logger.info(f"  值 {i+1}: 參數={value.get('param_name')}, 值={value.get('param_value')}, 單位={value.get('unit')}")

        else:
            logger.error(f"PM Request {request_id} 執行失敗")
            # 取得錯誤資訊
            error_info = pm_manager.get_request_info(request_id)
            if error_info:
                logger.error(f"錯誤資訊: {error_info}")

        # 步驟6: 清理Request
        logger.info("步驟6: 清理Request")
        pm_manager.delete_pm_request(request_id)
        logger.info(f"Request {request_id} 已清理")

        return success

    except Exception as e:
        logger.error(f"PM Request測試發生錯誤: {e}", exc_info=True)
        return False

def test_pm_request_with_different_filters():
    """使用不同Filter類型測試PM Request"""
    logger.info("=== 不同Filter類型PM Request測試 ===")

    config = create_test_config()
    pm_manager = PMRequestManager(config)

    # 測試不同的filter類型和值
    test_cases = [
        (FilterType.NE_OBJECT, "35", "NE物件篩選"),
        (FilterType.PORT_OBJECT, "35|1", "Port物件篩選"),
        (FilterType.TP_OBJECT, "35", "TP物件篩選"),
    ]

    results = []

    for filter_type, filter_value, description in test_cases:
        logger.info(f"\n--- 測試 {description} ---")
        logger.info(f"Filter類型: {filter_type}, Filter值: {filter_value}")

        try:
            request_name = f"Test_{filter_type.name}_{int(time.time())}"

            request_id = pm_manager.create_pm_request(
                request_name=request_name,
                filter_value=filter_value,
                request_type=PMRequestType.PM_CURRENT,
                filter_type=filter_type
            )

            if request_id is None:
                logger.warning(f"{description} - Request建立失敗")
                results.append((description, False, "建立失敗"))
                continue

            logger.info(f"Request {request_id} 建立成功，開始執行...")

            success = pm_manager.execute_pm_request(
                request_id,
                timeout=30,
                max_retries=1
            )

            if success:
                pmp_results, value_results = pm_manager.get_pm_results(request_id)
                result_summary = f"{len(pmp_results)} PMP, {len(value_results)} 值"
                logger.info(f"{description} - 成功: {result_summary}")
                results.append((description, True, result_summary))
            else:
                error_info = pm_manager.get_request_info(request_id)
                logger.warning(f"{description} - 執行失敗: {error_info}")
                results.append((description, False, f"執行失敗: {error_info}"))

            # 清理
            pm_manager.delete_pm_request(request_id)

        except Exception as e:
            logger.error(f"{description} - 發生錯誤: {e}")
            results.append((description, False, f"異常: {e}"))

    # 總結結果
    logger.info("\n=== 測試結果總結 ===")
    for description, success, detail in results:
        status = "✓ 成功" if success else "✗ 失敗"
        logger.info(f"{status} - {description}: {detail}")

    return any(result[1] for result in results)

def main():
    """主函數"""
    logger.info("TNMS PM Request 直接測試開始")
    logger.info("=" * 50)

    # 檢查環境變數
    if not os.getenv('TNMS_HOST') or not os.getenv('SNMP_COMMUNITY'):
        logger.error("請確認環境變數TNMS_HOST和SNMP_COMMUNITY已設定")
        return

    try:
        # 基本功能測試
        basic_success = test_pm_request_basic()

        # 不同filter類型測試
        filter_success = test_pm_request_with_different_filters()

        # 總結
        logger.info("\n" + "=" * 50)
        logger.info("測試完成總結:")
        logger.info(f"基本PM Request測試: {'成功' if basic_success else '失敗'}")
        logger.info(f"Filter類型測試: {'成功' if filter_success else '失敗'}")

        if basic_success or filter_success:
            logger.info("✓ PM Request功能驗證成功！")
            logger.info("系統具備完整的 PM Request → 執行 → 查詢結果 → 清理 功能")
        else:
            logger.info("✗ PM Request功能測試失敗")
            logger.info("可能原因：")
            logger.info("1. TNMS系統PM功能未啟用")
            logger.info("2. 測試用的NE/Port不存在")
            logger.info("3. SNMP權限不足")

    except KeyboardInterrupt:
        logger.info("測試被用戶中斷")
    except Exception as e:
        logger.error(f"測試過程發生錯誤: {e}", exc_info=True)

if __name__ == '__main__':
    main()