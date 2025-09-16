#!/usr/bin/env python3
import os
import sys
import time
import logging
import signal
import yaml
import schedule
from datetime import datetime
from flask import Flask, jsonify
import threading
from typing import Dict, Any

from snmp_collector import TNMSSNMPCollector
from influxdb_writer import InfluxDBWriter
from port_traffic_collector import PortTrafficCollector

class TNMSMonitor:
    def __init__(self, config_path: str = 'config.yaml'):
        self.config = self._load_config(config_path)
        self._setup_logging()

        self.logger = logging.getLogger(__name__)
        self.running = False

        # 初始化元件
        self.snmp_collector = None
        self.influxdb_writer = None
        self.traffic_collector = None

        # Flask健康檢查服務
        self.app = Flask(__name__)
        self._setup_health_endpoint()

        # 統計資訊
        self.stats = {
            'start_time': datetime.now(),
            'collections_count': 0,
            'last_collection': None,
            'last_error': None,
            'records_collected': 0,
            'records_written': 0,
            'pm_collections_count': 0,
            'last_pm_collection': None,
            'pm_records_collected': 0
        }

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """載入配置檔案"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            # 替換環境變數
            config = self._substitute_env_vars(config)

            # 驗證配置
            self._validate_config(config)

            # 設定預設值
            config = self._set_defaults(config)

            return config
        except Exception as e:
            print(f"載入配置檔案錯誤: {e}")
            sys.exit(1)

    def _validate_config(self, config: dict):
        """驗證配置檔案"""
        required_sections = ['snmp', 'influxdb', 'oids']
        for section in required_sections:
            if section not in config:
                raise ValueError(f"配置檔案缺少必要區塊: {section}")

        # 驗證SNMP設定
        snmp_config = config['snmp']
        required_snmp = ['host', 'community']
        for key in required_snmp:
            if not snmp_config.get(key):
                raise ValueError(f"SNMP設定缺少必要參數: {key}")

        # 驗證InfluxDB設定
        influxdb_config = config['influxdb']
        required_influxdb = ['url', 'token', 'org', 'bucket']
        for key in required_influxdb:
            if not influxdb_config.get(key):
                raise ValueError(f"InfluxDB設定缺少必要參數: {key}")

        # 驗證OID設定
        if not config['oids'] or not isinstance(config['oids'], dict):
            raise ValueError("OID設定不能為空且必須是字典格式")

    def _set_defaults(self, config: dict) -> dict:
        """設定預設值"""
        # SNMP預設值
        snmp_defaults = {
            'port': 161,
            'version': '2c',
            'timeout': 5,
            'retries': 3,
            'max_repetitions': 25
        }
        for key, default_value in snmp_defaults.items():
            config['snmp'].setdefault(key, default_value)

        # InfluxDB預設值
        influxdb_defaults = {
            'batch_size': 100,
            'flush_interval': 10
        }
        for key, default_value in influxdb_defaults.items():
            config['influxdb'].setdefault(key, default_value)

        # 收集設定預設值
        config.setdefault('collection', {})
        collection_defaults = {
            'interval': 60,
            'startup_delay': 30
        }
        for key, default_value in collection_defaults.items():
            config['collection'].setdefault(key, default_value)

        # 日誌設定預設值
        config.setdefault('logging', {})
        logging_defaults = {
            'level': 'INFO',
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        }
        for key, default_value in logging_defaults.items():
            config['logging'].setdefault(key, default_value)

        return config

    def _substitute_env_vars(self, obj):
        """遞歸替換配置中的環境變數"""
        if isinstance(obj, dict):
            return {k: self._substitute_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._substitute_env_vars(v) for v in obj]
        elif isinstance(obj, str) and obj.startswith('${') and obj.endswith('}'):
            env_var = obj[2:-1]
            default_value = None
            if ':' in env_var:
                env_var, default_value = env_var.split(':', 1)
            return os.getenv(env_var, default_value or obj)
        else:
            return obj

    def _setup_logging(self):
        """設定日誌"""
        logging_config = self.config.get('logging', {})
        level = getattr(logging, logging_config.get('level', 'INFO').upper())
        format_str = logging_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        logging.basicConfig(
            level=level,
            format=format_str,
            handlers=[
                logging.StreamHandler(sys.stdout)
            ]
        )

    def _setup_health_endpoint(self):
        """設定健康檢查端點"""
        @self.app.route('/health', methods=['GET'])
        def health_check():
            health_status = {
                'status': 'healthy' if self.running else 'unhealthy',
                'timestamp': datetime.now().isoformat(),
                'uptime': str(datetime.now() - self.stats['start_time']),
                'stats': self.stats.copy()
            }

            # 檢查元件狀態
            if self.snmp_collector:
                health_status['snmp_initialized'] = True
            if self.influxdb_writer:
                influx_stats = self.influxdb_writer.get_stats()
                health_status['influxdb_connected'] = influx_stats['connected']
                health_status['buffer_size'] = influx_stats['buffer_size']
            if self.traffic_collector:
                port_stats = self.traffic_collector.get_port_statistics()
                health_status['pm_collection_enabled'] = True
                health_status['port_statistics'] = port_stats

            return jsonify(health_status)

        @self.app.route('/stats', methods=['GET'])
        def get_stats():
            return jsonify(self.stats)

    def initialize_components(self):
        """初始化SNMP收集器和InfluxDB寫入器"""
        try:
            # 初始化SNMP收集器
            self.logger.info("初始化SNMP收集器...")
            self.snmp_collector = TNMSSNMPCollector(self.config)

            # 測試SNMP連接
            if not self.snmp_collector.test_connection():
                self.logger.error("SNMP連接測試失敗，請檢查TNMS主機設定")
                return False

            # 初始化InfluxDB寫入器
            self.logger.info("初始化InfluxDB寫入器...")
            self.influxdb_writer = InfluxDBWriter(self.config)

            # 測試InfluxDB連接
            if not self.influxdb_writer.test_connection():
                self.logger.error("InfluxDB連接測試失敗，請檢查資料庫設定")
                return False

            # 初始化流量收集器（如果啟用）
            pm_config = self.config.get('pm_collection', {})
            if pm_config.get('enabled', False):
                self.logger.info("初始化Port流量收集器...")
                self.traffic_collector = PortTrafficCollector(self.config)
                self.logger.info("Port流量收集器初始化完成")

            self.logger.info("所有元件初始化成功")
            return True

        except Exception as e:
            self.logger.error(f"初始化元件錯誤: {e}", exc_info=True)
            # 清理已建立的資源
            if self.influxdb_writer:
                try:
                    self.influxdb_writer.close()
                except:
                    pass
            return False

    def collect_and_store_data(self):
        """收集SNMP資料並儲存到InfluxDB"""
        try:
            self.logger.info("開始資料收集...")
            start_time = time.time()

            # 收集SNMP資料
            records = self.snmp_collector.collect_all_data()

            if not records:
                self.logger.warning("沒有收集到任何資料")
                return

            # 寫入InfluxDB
            self.influxdb_writer.add_records(records)

            # 更新統計
            collection_time = time.time() - start_time
            self.stats['collections_count'] += 1
            self.stats['last_collection'] = datetime.now()
            self.stats['records_collected'] += len(records)
            self.stats['records_written'] += len(records)

            self.logger.info(f"資料收集完成：收集 {len(records)} 筆記錄，耗時 {collection_time:.2f} 秒")

        except Exception as e:
            error_msg = f"資料收集錯誤: {e}"
            self.logger.error(error_msg, exc_info=True)
            self.stats['last_error'] = {
                'message': error_msg,
                'timestamp': datetime.now(),
                'type': type(e).__name__
            }

    def collect_and_store_pm_data(self):
        """收集PM流量資料並儲存到InfluxDB"""
        if not self.traffic_collector:
            return

        try:
            self.logger.info("開始PM流量資料收集...")
            start_time = time.time()

            # 收集流量資料
            traffic_records = self.traffic_collector.collect_port_traffic()

            if not traffic_records:
                self.logger.info("沒有收集到流量資料")
                return

            # 寫入InfluxDB
            self.influxdb_writer.add_records(traffic_records)

            # 更新統計
            collection_time = time.time() - start_time
            self.stats['pm_collections_count'] += 1
            self.stats['last_pm_collection'] = datetime.now()
            self.stats['pm_records_collected'] += len(traffic_records)
            self.stats['records_written'] += len(traffic_records)

            # 清理舊資料
            cleanup_config = self.config.get('pm_collection', {}).get('cleanup', {})
            self.traffic_collector.cleanup_old_counters(
                cleanup_config.get('old_counters_ttl', 3600)
            )
            self.traffic_collector.pm_manager.cleanup_old_requests(
                cleanup_config.get('old_requests_ttl', 1800)
            )

            self.logger.info(f"PM流量資料收集完成：收集 {len(traffic_records)} 筆記錄，耗時 {collection_time:.2f} 秒")

        except Exception as e:
            error_msg = f"PM流量資料收集錯誤: {e}"
            self.logger.error(error_msg, exc_info=True)
            self.stats['last_error'] = {
                'message': error_msg,
                'timestamp': datetime.now(),
                'type': type(e).__name__
            }

    def start_scheduler(self):
        """啟動排程器"""
        # 基本 SNMP 收集排程
        interval = self.config.get('collection', {}).get('interval', 60)
        self.logger.info(f"設定基本收集間隔: {interval} 秒")
        schedule.every(interval).seconds.do(self.collect_and_store_data)

        # PM 流量收集排程（如果啟用）
        if self.traffic_collector:
            pm_config = self.config.get('pm_collection', {})
            pm_interval = pm_config.get('interval', 60)
            self.logger.info(f"設定PM收集間隔: {pm_interval} 秒")
            schedule.every(pm_interval).seconds.do(self.collect_and_store_pm_data)

        # 啟動排程執行緒
        def run_scheduler():
            while self.running:
                try:
                    schedule.run_pending()
                    time.sleep(1)
                except Exception as e:
                    self.logger.error(f"排程器錯誤: {e}")

        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()

        return scheduler_thread

    def start_health_server(self):
        """啟動健康檢查伺服器"""
        def run_server():
            self.app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)

        health_thread = threading.Thread(target=run_server, daemon=True)
        health_thread.start()
        self.logger.info("健康檢查伺服器已啟動在埠口 8080")
        return health_thread

    def signal_handler(self, signum, frame):
        """處理終止信號"""
        self.logger.info(f"收到信號 {signum}，正在關閉...")
        self.stop()

    def start(self):
        """啟動監控系統"""
        self.logger.info("啟動TNMS SNMP監控系統...")

        # 註冊信號處理器
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        # 初始化元件
        if not self.initialize_components():
            self.logger.critical("元件初始化失敗，系統無法啟動")
            self.logger.info("請檢查以下設定：")
            self.logger.info("1. TNMS主機位址是否正確")
            self.logger.info("2. SNMP Community是否正確")
            self.logger.info("3. InfluxDB連接設定是否正確")
            self.logger.info("4. 網路連接是否正常")
            sys.exit(1)

        self.running = True

        # 啟動健康檢查伺服器
        health_thread = self.start_health_server()

        # 等待啟動延遲
        startup_delay = self.config.get('collection', {}).get('startup_delay', 30)
        if startup_delay > 0:
            self.logger.info(f"啟動延遲 {startup_delay} 秒...")
            time.sleep(startup_delay)

        # 執行第一次收集
        self.collect_and_store_data()

        # 啟動排程器
        scheduler_thread = self.start_scheduler()

        self.logger.info("監控系統已啟動")

        try:
            # 保持主執行緒運行
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("收到中斷信號")
        finally:
            self.stop()

    def stop(self):
        """停止監控系統"""
        if not self.running:
            return

        self.logger.info("正在關閉監控系統...")
        self.running = False

        # 最後一次flush
        if self.influxdb_writer:
            self.influxdb_writer.flush()
            self.influxdb_writer.close()

        self.logger.info("監控系統已關閉")


def main():
    """主函數"""
    config_path = os.environ.get('CONFIG_PATH', 'config.yaml')

    monitor = TNMSMonitor(config_path)
    monitor.start()


if __name__ == '__main__':
    main()