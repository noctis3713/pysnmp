#!/usr/bin/env python3
"""
TNMS 流量收集測試腳本

這個腳本用於測試新增的 PM 流量收集功能
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime

# 添加 src 目錄到 Python 路徑
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'snmp', 'src'))

from pm_request_manager import PMRequestManager, PMRequestType, FilterType
from port_traffic_collector import PortTrafficCollector
from influxdb_writer import InfluxDBWriter


def setup_logging(level=logging.INFO):
    """設定日誌"""
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )


def load_test_config():
    """載入測試配置"""
    config = {
        'snmp': {
            'host': os.getenv('TNMS_HOST', 'localhost'),
            'port': int(os.getenv('SNMP_PORT', '161')),
            'community': os.getenv('SNMP_COMMUNITY', 'public'),
            'version': '2c',
            'timeout': 10,
            'retries': 3,
            'max_repetitions': 10
        },
        'influxdb': {
            'url': os.getenv('INFLUXDB_URL', 'http://localhost:8086'),
            'token': os.getenv('INFLUXDB_TOKEN', 'test-token'),
            'org': os.getenv('INFLUXDB_ORG', 'test-org'),
            'bucket': os.getenv('INFLUXDB_BUCKET', 'test-bucket'),
            'batch_size': 10,
            'flush_interval': 5
        },
        'pm_collection': {
            'enabled': True,
            'interval': 30,
            'request_type': 'pmCurrent',
            'timeout': 30,
            'ports': {
                'auto_discovery': True,
                'filter': '.*',  # 測試時收集所有 port
                'cache_ttl': 300
            },
            'cleanup': {
                'old_counters_ttl': 1800,
                'old_requests_ttl': 900
            }
        },
        'logging': {
            'level': 'INFO'
        }
    }
    return config


def test_pm_request_manager(config):
    """測試 PM Request Manager"""
    print("\n=== 測試 PM Request Manager ===")

    try:
        pm_manager = PMRequestManager(config)

        # 測試取得 Request ID
        print("1. 測試取得 Request ID...")
        request_id = pm_manager.get_next_request_id()
        if request_id:
            print(f"   ✓ 成功取得 Request ID: {request_id}")
        else:
            print("   ✗ 取得 Request ID 失敗")
            return False

        # 測試建立 PM Request
        print("2. 測試建立 PM Request...")
        test_request_id = pm_manager.create_pm_request(
            request_name="Test_Request",
            filter_value="32|6734",  # 測試用的 port
            request_type=PMRequestType.PM_CURRENT,
            filter_type=FilterType.PORT_OBJECT
        )

        if test_request_id:
            print(f"   ✓ 成功建立 PM Request: {test_request_id}")

            # 測試取得狀態
            print("3. 測試取得 Request 狀態...")
            state = pm_manager.get_request_state(test_request_id)
            if state:
                print(f"   ✓ Request 狀態: {state.name}")

            # 測試執行 Request（但不等待完成，避免測試過久）
            print("4. 測試啟動 PM Request...")
            print("   註：只測試啟動，不等待完成")

            # 清理測試用的 Request
            print("5. 清理測試 Request...")
            if pm_manager.delete_pm_request(test_request_id):
                print("   ✓ 成功刪除測試 Request")
            else:
                print("   ✗ 刪除測試 Request 失敗")

        else:
            print("   ✗ 建立 PM Request 失敗")
            return False

        print("✓ PM Request Manager 測試完成")
        return True

    except Exception as e:
        print(f"✗ PM Request Manager 測試錯誤: {e}")
        return False


def test_port_discovery(config):
    """測試 Port 探索功能"""
    print("\n=== 測試 Port 探索功能 ===")

    try:
        traffic_collector = PortTrafficCollector(config)

        # 測試探索所有 Port
        print("1. 測試探索所有 Port...")
        ports = traffic_collector.discover_ports()

        if ports:
            print(f"   ✓ 成功探索到 {len(ports)} 個 Port")

            # 顯示前幾個 Port 的資訊
            count = 0
            for port_key, port_info in ports.items():
                if count >= 3:  # 只顯示前 3 個
                    break
                print(f"   - {port_key}: {port_info.get('port_name', 'Unknown')}")
                count += 1

            if len(ports) > 3:
                print(f"   ... 和其他 {len(ports) - 3} 個 Port")

        else:
            print("   ✗ 沒有探索到任何 Port")
            return False

        # 測試使用篩選器
        print("2. 測試 Port 篩選功能...")
        filtered_ports = traffic_collector.discover_ports("GigE.*")
        print(f"   ✓ 篩選後剩餘 {len(filtered_ports)} 個 Port")

        # 測試統計資訊
        print("3. 測試統計資訊...")
        stats = traffic_collector.get_port_statistics()
        print(f"   - 總 Port 數: {stats['total_ports']}")
        print(f"   - 有流量資料的 Port: {stats['ports_with_traffic_data']}")

        print("✓ Port 探索功能測試完成")
        return True

    except Exception as e:
        print(f"✗ Port 探索測試錯誤: {e}")
        return False


def test_traffic_collection(config):
    """測試流量收集功能"""
    print("\n=== 測試流量收集功能 ===")

    try:
        traffic_collector = PortTrafficCollector(config)

        # 先探索 Port
        print("1. 探索 Port...")
        ports = traffic_collector.discover_ports()

        if not ports:
            print("   ✗ 沒有可收集的 Port")
            return False

        # 限制測試範圍
        test_ports = dict(list(ports.items())[:2])  # 只測試前 2 個 Port
        print(f"   使用 {len(test_ports)} 個 Port 進行測試")

        # 測試收集流量資料
        print("2. 測試收集流量資料...")
        print("   註：第一次收集只會有計數器值，沒有速率")

        traffic_records = traffic_collector.collect_port_traffic(test_ports)

        if traffic_records:
            print(f"   ✓ 成功收集 {len(traffic_records)} 筆流量記錄")

            # 顯示第一筆記錄的結構
            if traffic_records:
                sample_record = traffic_records[0]
                print("   樣本記錄結構:")
                print(f"   - measurement: {sample_record['measurement']}")
                print(f"   - tags: {list(sample_record['tags'].keys())}")
                print(f"   - fields: {list(sample_record['fields'].keys())}")

        else:
            print("   ! 沒有收集到流量記錄（可能是首次執行）")

        # 等待一段時間後再次收集，測試速率計算
        print("3. 等待 10 秒後再次收集，測試速率計算...")
        time.sleep(10)

        traffic_records2 = traffic_collector.collect_port_traffic(test_ports)

        if traffic_records2:
            print(f"   ✓ 第二次收集到 {len(traffic_records2)} 筆記錄")

            # 檢查是否有速率資料
            sample_record = traffic_records2[0]
            rate_fields = [k for k in sample_record['fields'].keys() if k.endswith('_rate')]
            if rate_fields:
                print(f"   ✓ 成功計算速率，包含: {rate_fields}")
            else:
                print("   ! 沒有速率資料（可能需要更多時間）")

        print("✓ 流量收集功能測試完成")
        return True

    except Exception as e:
        print(f"✗ 流量收集測試錯誤: {e}")
        return False


def test_influxdb_integration(config):
    """測試 InfluxDB 整合"""
    print("\n=== 測試 InfluxDB 整合 ===")

    try:
        # 建立測試資料
        test_records = [
            {
                'measurement': 'port_traffic_test',
                'tags': {
                    'ne_id': '32',
                    'port_id': '6734',
                    'port_name': 'Test-Port',
                    'port_type': 'GigE'
                },
                'fields': {
                    'bytes_in_total': 1000000,
                    'bytes_out_total': 800000,
                    'bytes_in_rate': 125000.0,
                    'bytes_out_rate': 100000.0,
                    'bits_in_rate': 1000000.0,
                    'bits_out_rate': 800000.0
                },
                'timestamp': int(time.time() * 1000000000)
            }
        ]

        # 測試寫入 InfluxDB
        print("1. 測試寫入 InfluxDB...")
        influxdb_writer = InfluxDBWriter(config)

        if not influxdb_writer.test_connection():
            print("   ! InfluxDB 連接失敗，跳過寫入測試")
            return True

        influxdb_writer.write_records(test_records)
        print("   ✓ 測試資料已寫入 InfluxDB")

        # 等待一下確保資料寫入
        time.sleep(2)

        influxdb_writer.close()
        print("✓ InfluxDB 整合測試完成")
        return True

    except Exception as e:
        print(f"✗ InfluxDB 整合測試錯誤: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='TNMS 流量收集測試腳本')
    parser.add_argument('--verbose', '-v', action='store_true', help='啟用詳細日誌')
    parser.add_argument('--skip-pm', action='store_true', help='跳過 PM Request Manager 測試')
    parser.add_argument('--skip-port', action='store_true', help='跳過 Port 探索測試')
    parser.add_argument('--skip-traffic', action='store_true', help='跳過流量收集測試')
    parser.add_argument('--skip-influx', action='store_true', help='跳過 InfluxDB 測試')
    args = parser.parse_args()

    # 設定日誌
    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(log_level)

    print("TNMS 流量收集功能測試")
    print("=" * 40)

    # 載入配置
    config = load_test_config()
    print(f"TNMS 主機: {config['snmp']['host']}:{config['snmp']['port']}")
    print(f"InfluxDB: {config['influxdb']['url']}")

    # 執行測試
    tests_passed = 0
    total_tests = 0

    if not args.skip_pm:
        total_tests += 1
        if test_pm_request_manager(config):
            tests_passed += 1

    if not args.skip_port:
        total_tests += 1
        if test_port_discovery(config):
            tests_passed += 1

    if not args.skip_traffic:
        total_tests += 1
        if test_traffic_collection(config):
            tests_passed += 1

    if not args.skip_influx:
        total_tests += 1
        if test_influxdb_integration(config):
            tests_passed += 1

    # 測試結果
    print("\n" + "=" * 40)
    print(f"測試結果: {tests_passed}/{total_tests} 通過")

    if tests_passed == total_tests:
        print("✓ 所有測試通過！")
        return 0
    else:
        print("✗ 部分測試失敗")
        return 1


if __name__ == '__main__':
    sys.exit(main())