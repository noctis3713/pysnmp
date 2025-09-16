import logging
import time
from typing import List, Dict, Any
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS, ASYNCHRONOUS
from influxdb_client.client.exceptions import InfluxDBError
import threading
from concurrent.futures import ThreadPoolExecutor

class InfluxDBWriter:
    def __init__(self, config: dict):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.influxdb_config = config['influxdb']

        # InfluxDB 客戶端設定
        self.client = None
        self.write_api = None
        self.connected = False

        # 批次寫入設定
        self.batch_size = self.influxdb_config.get('batch_size', 100)
        self.flush_interval = self.influxdb_config.get('flush_interval', 10)

        # 資料緩衝區
        self.buffer = []
        self.buffer_lock = threading.Lock()

        # 背景寫入執行緒
        self.write_thread = None
        self.stop_event = threading.Event()

        # 執行緒池用於批次寫入
        self.thread_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="influxdb-writer")

        self._connect()

    def _connect(self):
        """建立InfluxDB連線"""
        try:
            self.client = InfluxDBClient(
                url=self.influxdb_config['url'],
                token=self.influxdb_config['token'],
                org=self.influxdb_config['org']
            )

            # 測試連線
            health = self.client.health()
            if health.status == "pass":
                self.logger.info("成功連接到InfluxDB")
                self.connected = True

                # 建立寫入API
                self.write_api = self.client.write_api(write_options=ASYNCHRONOUS)

                # 啟動背景寫入執行緒
                self._start_background_writer()
            else:
                self.logger.error(f"InfluxDB健康檢查失敗: {health.status}")
                self.connected = False

        except Exception as e:
            self.logger.error(f"連接InfluxDB失敗: {e}")
            self.connected = False

    def _start_background_writer(self):
        """啟動背景寫入執行緒"""
        if self.write_thread is None or not self.write_thread.is_alive():
            self.stop_event.clear()
            self.write_thread = threading.Thread(target=self._background_writer, daemon=True)
            self.write_thread.start()
            self.logger.info("背景寫入執行緒已啟動")

    def _background_writer(self):
        """背景執行緒：定期將緩衝區資料寫入InfluxDB"""
        while not self.stop_event.is_set():
            try:
                # 等待flush間隔時間或停止信號
                if self.stop_event.wait(self.flush_interval):
                    break

                # 檢查緩衝區是否有資料需要寫入
                with self.buffer_lock:
                    if self.buffer:
                        batch = self.buffer.copy()
                        self.buffer.clear()
                    else:
                        continue

                # 寫入資料
                if batch:
                    self._write_batch(batch)

            except Exception as e:
                self.logger.error(f"背景寫入執行緒錯誤: {e}")

    def _convert_to_point(self, record: Dict[str, Any]) -> Point:
        """將記錄轉換為InfluxDB Point"""
        point = Point(record['measurement'])

        # 新增標籤
        for tag_key, tag_value in record.get('tags', {}).items():
            if tag_value is not None and str(tag_value).strip():
                point = point.tag(tag_key, str(tag_value))

        # 新增欄位
        for field_key, field_value in record.get('fields', {}).items():
            if field_value is not None:
                if isinstance(field_value, bool):
                    point = point.field(field_key, field_value)
                elif isinstance(field_value, (int, float)):
                    # 確保數值是有效的（不是 NaN 或無限大）
                    if field_key.endswith('_rate'):
                        # 對於速率欄位，確保是正數並且合理
                        field_value = max(0.0, float(field_value))
                        if field_value > 1e12:  # 防止過大的值
                            field_value = 0.0
                    point = point.field(field_key, field_value)
                else:
                    point = point.field(field_key, str(field_value))

        # 設定時間戳記
        if 'timestamp' in record:
            point = point.time(record['timestamp'])

        return point

    def _write_batch(self, batch: List[Dict[str, Any]]):
        """批次寫入資料到InfluxDB"""
        if not self.connected or not self.write_api:
            self.logger.warning("InfluxDB未連接，跳過寫入")
            return

        try:
            # 轉換為Points
            points = []
            for record in batch:
                try:
                    point = self._convert_to_point(record)
                    points.append(point)
                except Exception as e:
                    self.logger.warning(f"轉換記錄為Point失敗: {e}")
                    continue

            if not points:
                self.logger.warning("沒有有效的Points可寫入")
                return

            # 寫入到InfluxDB
            self.write_api.write(
                bucket=self.influxdb_config['bucket'],
                org=self.influxdb_config['org'],
                record=points
            )

            self.logger.info(f"成功寫入 {len(points)} 個資料點到InfluxDB")

        except InfluxDBError as e:
            self.logger.error(f"InfluxDB寫入錯誤: {e}")
            # 記錄詳細錯誤資訊
            if hasattr(e, 'response') and e.response:
                self.logger.error(f"InfluxDB錯誤詳情: {e.response.text}")
        except Exception as e:
            self.logger.error(f"批次寫入錯誤: {e}", exc_info=True)

    def add_records(self, records: List[Dict[str, Any]]):
        """新增記錄到緩衝區"""
        if not records:
            return

        with self.buffer_lock:
            self.buffer.extend(records)

            # 如果緩衝區達到批次大小，立即寫入
            if len(self.buffer) >= self.batch_size:
                batch = self.buffer.copy()
                self.buffer.clear()
                # 使用執行緒池寫入以避免阻塞並控制併發
                self.thread_pool.submit(self._write_batch, batch)

    def write_records(self, records: List[Dict[str, Any]]):
        """立即寫入記錄（同步）"""
        if not records:
            return

        self._write_batch(records)

    def flush(self):
        """強制寫入緩衝區中的所有資料"""
        with self.buffer_lock:
            if self.buffer:
                batch = self.buffer.copy()
                self.buffer.clear()
                self._write_batch(batch)

    def test_connection(self) -> bool:
        """測試InfluxDB連接"""
        try:
            if not self.client:
                return False

            health = self.client.health()
            is_healthy = health.status == "pass"
            self.logger.info(f"InfluxDB連接測試: {'成功' if is_healthy else '失敗'}")
            return is_healthy

        except Exception as e:
            self.logger.error(f"InfluxDB連接測試錯誤: {e}")
            return False

    def close(self):
        """關閉InfluxDB連接和清理資源"""
        self.logger.info("關閉InfluxDB連接...")

        # 停止背景寫入執行緒
        if self.write_thread and self.write_thread.is_alive():
            self.stop_event.set()
            self.write_thread.join(timeout=10)

        # 最後一次flush
        self.flush()

        # 關閉執行緒池
        if self.thread_pool:
            try:
                self.thread_pool.shutdown(wait=True, timeout=30)
                self.logger.info("執行緒池已關閉")
            except Exception as e:
                self.logger.error(f"關閉執行緒池時發生錯誤: {e}")

        # 關閉寫入API
        if self.write_api:
            try:
                self.write_api.close()
            except Exception as e:
                self.logger.warning(f"關閉寫入API時發生錯誤: {e}")

        # 關閉客戶端
        if self.client:
            try:
                self.client.close()
            except Exception as e:
                self.logger.warning(f"關閉客戶端時發生錯誤: {e}")

        self.connected = False
        self.logger.info("InfluxDB連接已關閉")

    def get_stats(self) -> Dict[str, Any]:
        """獲取寫入統計"""
        with self.buffer_lock:
            buffer_size = len(self.buffer)

        return {
            'connected': self.connected,
            'buffer_size': buffer_size,
            'batch_size': self.batch_size,
            'flush_interval': self.flush_interval
        }