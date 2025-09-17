#!/usr/bin/env python3
"""
簡單的SNMP測試腳本 - 使用不同的方法測試SNMP連接
"""

import os
import sys
import logging
import subprocess
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_with_snmpget():
    """使用系統的snmpget命令測試"""
    host = os.getenv('TNMS_HOST')
    community = os.getenv('SNMP_COMMUNITY')

    if not host or not community:
        logger.error("請確認.env檔案中設定了TNMS_HOST和SNMP_COMMUNITY")
        return False

    logger.info(f"使用snmpget測試SNMP連接")
    logger.info(f"目標主機: {host}")
    logger.info(f"社群字串: {community}")

    # 測試系統描述 OID
    oids_to_test = [
        ('1.3.6.1.2.1.1.1.0', '系統描述 (sysDescr)'),
        ('1.3.6.1.2.1.1.5.0', '系統名稱 (sysName)'),
        ('1.3.6.1.2.1.1.3.0', '系統運行時間 (sysUpTime)')
    ]

    success_count = 0

    for oid, description in oids_to_test:
        logger.info(f"\n測試 {description}")
        logger.info(f"OID: {oid}")

        try:
            # 構建snmpget命令
            cmd = [
                'snmpget',
                '-v2c',
                f'-c{community}',
                '-t', '5',  # 5秒超時
                '-r', '3',  # 重試3次
                f'{host}:50161',  # 使用正確的埠口
                oid
            ]

            # 執行命令
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15
            )

            if result.returncode == 0:
                logger.info(f"✓ 成功: {result.stdout.strip()}")
                success_count += 1
            else:
                logger.error(f"✗ 失敗: {result.stderr.strip()}")

        except subprocess.TimeoutExpired:
            logger.error(f"✗ 超時：命令執行超過15秒")
        except FileNotFoundError:
            logger.error("✗ 系統未安裝snmp-utils，嘗試安裝：sudo apt install snmp snmp-utils")
            return False
        except Exception as e:
            logger.error(f"✗ 錯誤: {e}")

    logger.info(f"\n基本測試結果: {success_count}/{len(oids_to_test)} 個OID測試成功")
    return success_count > 0

def test_tnms_oids():
    """測試TNMS特定的OID"""
    host = os.getenv('TNMS_HOST')
    community = os.getenv('SNMP_COMMUNITY')

    logger.info("=== TNMS特定OID測試 ===")

    # TNMS OID定義 (使用更新後的正確路徑)
    tnms_oids = [
        ('1.3.6.1.4.1.42229.6.22.1.1.1.3.35', 'TNMS網路元素名稱'),
        ('1.3.6.1.4.1.42229.6.22.1.1.1.2.35', 'TNMS設備類型'),
        ('1.3.6.1.4.1.42229.6.22.3.1.1.1.1', 'TNMS告警ID')
    ]

    success_count = 0

    for oid, description in tnms_oids:
        logger.info(f"\n測試 {description}")
        logger.info(f"OID: {oid}")

        try:
            cmd = [
                'snmpget',
                '-v2c',
                f'-c{community}',
                '-t', '5',
                '-r', '3',
                f'{host}:50161',  # 使用正確的埠口
                oid
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15
            )

            if result.returncode == 0:
                logger.info(f"✓ 成功: {result.stdout.strip()}")
                success_count += 1
            else:
                logger.info(f"! 無資料或無權限: {result.stderr.strip()}")

        except Exception as e:
            logger.error(f"✗ 錯誤: {e}")

    logger.info(f"\nTNMS OID測試結果: {success_count}/{len(tnms_oids)} 個OID有回應")
    return success_count

def test_snmp_walk():
    """使用snmpwalk測試表格遍歷"""
    host = os.getenv('TNMS_HOST')
    community = os.getenv('SNMP_COMMUNITY')

    logger.info("=== SNMP Walk測試 ===")

    # 測試一些基本的MIB表格
    walk_oids = [
        ('1.3.6.1.2.1.1', '系統資訊 (system)'),
        ('1.3.6.1.4.1.42229.6.22.1.1.1', 'TNMS網路元素表格'),
        ('1.3.6.1.4.1.42229.6.22.3.1.1.1', 'TNMS告警表格')
    ]

    for oid, description in walk_oids:
        logger.info(f"\n遍歷 {description}")
        logger.info(f"基礎OID: {oid}")

        try:
            cmd = [
                'snmpwalk',
                '-v2c',
                f'-c{community}',
                '-t', '5',
                '-r', '2',
                f'{host}:50161',  # 使用正確的埠口
                oid
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if lines and lines[0]:
                    logger.info(f"✓ 找到 {len(lines)} 個項目")
                    # 顯示前3個結果
                    for i, line in enumerate(lines[:3]):
                        logger.info(f"  [{i+1}] {line}")
                    if len(lines) > 3:
                        logger.info(f"  ... 還有 {len(lines)-3} 個項目")
                else:
                    logger.info("! 表格為空")
            else:
                logger.info(f"! 無法存取: {result.stderr.strip()}")

        except Exception as e:
            logger.error(f"✗ 錯誤: {e}")

def main():
    """主函數"""
    print("TNMS SNMP 連接測試工具")
    print("=" * 50)

    logger.info("開始SNMP連接測試...")

    # 檢查是否有snmp工具
    try:
        subprocess.run(['snmpget', '--version'], capture_output=True, check=True)
        logger.info("✓ 系統已安裝SNMP工具")
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.error("✗ 系統未安裝SNMP工具")
        logger.info("請安裝: sudo apt update && sudo apt install snmp snmp-utils")
        return

    # 基本連接測試
    logger.info("\n=== 基本SNMP連接測試 ===")
    if not test_with_snmpget():
        logger.error("基本SNMP測試失敗，請檢查：")
        logger.error("1. 網路連接是否正常")
        logger.error("2. TNMS主機地址是否正確")
        logger.error("3. SNMP社群字串是否正確")
        logger.error("4. 目標主機是否啟用SNMP服務")
        return

    # TNMS特定測試
    logger.info("\n")
    tnms_success = test_tnms_oids()

    # 表格遍歷測試
    logger.info("\n")
    test_snmp_walk()

    # 總結
    logger.info("\n=== 測試總結 ===")
    logger.info("✓ 基本SNMP連接正常")
    if tnms_success > 0:
        logger.info(f"✓ TNMS特定OID部分可用 ({tnms_success} 個)")
    else:
        logger.info("! TNMS特定OID無回應（可能是權限或資料問題）")

    logger.info("\n建議下一步：")
    logger.info("1. 如果基本測試成功，可以運行完整的監控程式")
    logger.info("2. 如果TNMS OID無回應，請檢查SNMP社群權限設定")
    logger.info("3. 確認目標設備確實是TNMS系統")

if __name__ == '__main__':
    main()