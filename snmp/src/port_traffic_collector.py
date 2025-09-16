import logging
import time
import re
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from pysnmp.hlapi import *
from snmp_collector import TNMSSNMPCollector
from pm_request_manager import PMRequestManager, FilterType, PMRequestType


class TrafficCounter:
    """流量計數器資料結構"""
    def __init__(self, timestamp: float = None):
        self.timestamp = timestamp or time.time()
        self.bytes_in = 0
        self.bytes_out = 0
        self.packets_in = 0
        self.packets_out = 0
        self.errors_in = 0
        self.errors_out = 0
        self.discards_in = 0
        self.discards_out = 0

    def __repr__(self):
        return f"TrafficCounter(bytes_in={self.bytes_in}, bytes_out={self.bytes_out}, timestamp={self.timestamp})"


class PortTrafficCollector(TNMSSNMPCollector):
    """Port 流量收集器"""

    # Port 表格 OID
    OID_PORT_TABLE = '1.3.6.1.4.1.42229.6.22.2.3'
    OID_PORT_NAME = '1.3.6.1.4.1.42229.6.22.2.3.1.2'

    def __init__(self, config: dict):
        super().__init__(config)

        # PM 設定
        self.pm_config = config.get('pm_collection', {})
        self.pm_enabled = self.pm_config.get('enabled', False)
        self.pm_interval = self.pm_config.get('interval', 60)

        # 初始化 PM Request Manager
        self.pm_manager = PMRequestManager(config)

        # 前次計數器值儲存
        self.previous_counters: Dict[str, TrafficCounter] = {}

        # Port 快取
        self.port_cache: Dict[str, Dict] = {}
        self.port_cache_time = 0
        self.port_cache_ttl = 300  # 5 分鐘

    def discover_ports(self, name_filter: str = None) -> Dict[str, Dict]:
        """探索可用的 Port"""
        current_time = time.time()

        # 檢查快取是否有效
        if current_time - self.port_cache_time < self.port_cache_ttl and self.port_cache:
            self.logger.debug("使用快取的 Port 資料")
            return self._filter_ports(self.port_cache, name_filter)

        self.logger.info("探索網路 Port...")
        ports = {}

        try:
            # 遍歷 Port 表格
            raw_data = self.walk_table(self.OID_PORT_TABLE)

            if not raw_data:
                self.logger.warning("沒有找到任何 Port 資料")
                return ports

            # 解析 Port 資料
            port_data = {}
            for oid, value in raw_data.items():
                # 從 OID 解析 NEId, PortId 和欄位
                if self.OID_PORT_TABLE in oid:
                    parts = oid.replace(f"{self.OID_PORT_TABLE}.", "").split(".")
                    if len(parts) >= 3:
                        field_id = parts[0]
                        ne_id = parts[1]
                        port_id = parts[2]

                        port_key = f"{ne_id}|{port_id}"

                        if port_key not in port_data:
                            port_data[port_key] = {
                                'ne_id': ne_id,
                                'port_id': port_id,
                                'port_key': port_key
                            }

                        # 根據欄位 ID 設定對應的值
                        if field_id == '2':  # Port Name
                            port_data[port_key]['port_name'] = str(value)
                        elif field_id == '3':  # Port Type
                            port_data[port_key]['port_type'] = str(value)
                        elif field_id == '7':  # Bandwidth
                            port_data[port_key]['bandwidth'] = int(value) if value else 0
                        elif field_id == '15':  # OpState TX
                            port_data[port_key]['op_state_tx'] = int(value) if value else 0
                        elif field_id == '16':  # OpState RX
                            port_data[port_key]['op_state_rx'] = int(value) if value else 0

            # 轉換為最終格式
            for port_key, port_info in port_data.items():
                if 'port_name' in port_info:  # 確保有 Port 名稱
                    ports[port_key] = port_info

            # 更新快取
            self.port_cache = ports
            self.port_cache_time = current_time

            self.logger.info(f"發現 {len(ports)} 個 Port")

        except Exception as e:
            self.logger.error(f"探索 Port 時發生錯誤: {e}")

        return self._filter_ports(ports, name_filter)

    def _filter_ports(self, ports: Dict[str, Dict], name_filter: str = None) -> Dict[str, Dict]:
        """根據名稱篩選器過濾 Port"""
        if not name_filter:
            return ports

        filtered_ports = {}
        try:
            pattern = re.compile(name_filter, re.IGNORECASE)
            for port_key, port_info in ports.items():
                port_name = port_info.get('port_name', '')
                if pattern.search(port_name):
                    filtered_ports[port_key] = port_info
        except re.error as e:
            self.logger.warning(f"無效的篩選器正則表達式 '{name_filter}': {e}")
            return ports

        self.logger.info(f"篩選後剩餘 {len(filtered_ports)} 個 Port")
        return filtered_ports

    def collect_port_traffic(self, ports: Dict[str, Dict] = None) -> List[Dict[str, Any]]:
        """收集 Port 流量資料"""
        if not self.pm_enabled:
            self.logger.debug("PM 收集功能未啟用")
            return []

        if ports is None:
            name_filter = self.pm_config.get('ports', {}).get('filter')
            ports = self.discover_ports(name_filter)

        if not ports:
            self.logger.warning("沒有可收集的 Port")
            return []

        self.logger.info(f"開始收集 {len(ports)} 個 Port 的流量資料")

        try:
            # 建立批次 PM Request
            filter_value = ','.join(ports.keys())
            request_id = self.pm_manager.create_pm_request(
                request_name=f"Port_Traffic_{int(time.time())}",
                filter_value=filter_value,
                request_type=PMRequestType.PM_CURRENT,
                filter_type=FilterType.PORT_OBJECT
            )

            if request_id is None:
                self.logger.error("無法建立 PM Request")
                return []

            # 執行 Request
            if not self.pm_manager.execute_pm_request(request_id, timeout=60):
                self.logger.error(f"PM Request {request_id} 執行失敗")
                self.pm_manager.delete_pm_request(request_id)
                return []

            # 取得結果
            pmp_results, value_results = self.pm_manager.get_pm_results(request_id)

            # 處理結果資料
            records = self._process_pm_results(pmp_results, value_results, ports)

            # 清理 Request
            self.pm_manager.delete_pm_request(request_id)

            self.logger.info(f"成功收集 {len(records)} 筆流量記錄")
            return records

        except Exception as e:
            self.logger.error(f"收集 Port 流量時發生錯誤: {e}")
            return []

    def _process_pm_results(self, pmp_results: List[Dict], value_results: List[Dict],
                           ports: Dict[str, Dict]) -> List[Dict[str, Any]]:
        """處理 PM 結果資料"""
        records = []
        current_time = time.time()
        timestamp_ns = int(current_time * 1000000000)

        try:
            # 建立 PMP 到 Port 的對應
            pmp_to_port = {}
            for pmp in pmp_results:
                pmp_number = pmp.get('pmp_number')
                # 從 PMP 結果取得 NE ID 和 Port ID
                ne_id = pmp.get('field_3')  # 假設欄位 3 是 NE ID
                port_id = pmp.get('field_4')  # 假設欄位 4 是 Port ID

                if ne_id and port_id:
                    port_key = f"{ne_id}|{port_id}"
                    if port_key in ports:
                        pmp_to_port[pmp_number] = {
                            'port_key': port_key,
                            'port_info': ports[port_key]
                        }

            # 按 PMP 分組數值
            pmp_values = {}
            for value in value_results:
                pmp_number = value.get('pmp_number')
                if pmp_number not in pmp_values:
                    pmp_values[pmp_number] = []
                pmp_values[pmp_number].append(value)

            # 處理每個 PMP 的資料
            for pmp_number, port_mapping in pmp_to_port.items():
                port_key = port_mapping['port_key']
                port_info = port_mapping['port_info']

                if pmp_number not in pmp_values:
                    continue

                # 解析計數器值
                current_counter = self._parse_counter_values(pmp_values[pmp_number])
                current_counter.timestamp = current_time

                # 計算速率（如果有前次數據）
                rates = self._calculate_rates(port_key, current_counter)

                # 建立記錄
                record = {
                    'measurement': 'port_traffic',
                    'tags': {
                        'ne_id': port_info['ne_id'],
                        'port_id': port_info['port_id'],
                        'port_name': port_info.get('port_name', ''),
                        'port_type': port_info.get('port_type', ''),
                    },
                    'fields': {
                        # 計數器值
                        'bytes_in_total': current_counter.bytes_in,
                        'bytes_out_total': current_counter.bytes_out,
                        'packets_in_total': current_counter.packets_in,
                        'packets_out_total': current_counter.packets_out,
                        'errors_in_total': current_counter.errors_in,
                        'errors_out_total': current_counter.errors_out,
                        'discards_in_total': current_counter.discards_in,
                        'discards_out_total': current_counter.discards_out,
                        # 速率值
                        **rates
                    },
                    'timestamp': timestamp_ns
                }

                # 添加頻寬資訊
                if 'bandwidth' in port_info:
                    record['fields']['bandwidth'] = port_info['bandwidth']

                records.append(record)

                # 更新前次計數器值
                self.previous_counters[port_key] = current_counter

        except Exception as e:
            self.logger.error(f"處理 PM 結果時發生錯誤: {e}")

        return records

    def _parse_counter_values(self, values: List[Dict]) -> TrafficCounter:
        """解析計數器值"""
        counter = TrafficCounter()

        for value in values:
            param = value.get('field_4', '')  # 假設欄位 4 是參數名稱
            val = value.get('field_5', '0')   # 假設欄位 5 是數值

            try:
                numeric_value = int(val) if val.isdigit() else 0

                # 根據參數名稱對應到計數器欄位
                param_lower = param.lower() if param else ''

                if 'bytes' in param_lower or 'octets' in param_lower:
                    if 'in' in param_lower or 'rx' in param_lower:
                        counter.bytes_in = numeric_value
                    elif 'out' in param_lower or 'tx' in param_lower:
                        counter.bytes_out = numeric_value
                elif 'packets' in param_lower or 'frames' in param_lower:
                    if 'in' in param_lower or 'rx' in param_lower:
                        counter.packets_in = numeric_value
                    elif 'out' in param_lower or 'tx' in param_lower:
                        counter.packets_out = numeric_value
                elif 'error' in param_lower:
                    if 'in' in param_lower or 'rx' in param_lower:
                        counter.errors_in = numeric_value
                    elif 'out' in param_lower or 'tx' in param_lower:
                        counter.errors_out = numeric_value
                elif 'discard' in param_lower or 'drop' in param_lower:
                    if 'in' in param_lower or 'rx' in param_lower:
                        counter.discards_in = numeric_value
                    elif 'out' in param_lower or 'tx' in param_lower:
                        counter.discards_out = numeric_value

            except (ValueError, TypeError):
                continue

        return counter

    def _calculate_rates(self, port_key: str, current_counter: TrafficCounter) -> Dict[str, float]:
        """計算流量速率"""
        rates = {
            'bytes_in_rate': 0.0,
            'bytes_out_rate': 0.0,
            'packets_in_rate': 0.0,
            'packets_out_rate': 0.0,
            'bits_in_rate': 0.0,
            'bits_out_rate': 0.0
        }

        if port_key not in self.previous_counters:
            return rates

        previous_counter = self.previous_counters[port_key]
        time_diff = current_counter.timestamp - previous_counter.timestamp

        if time_diff <= 0:
            return rates

        try:
            # 計算位元組速率
            rates['bytes_in_rate'] = self._calculate_counter_rate(
                current_counter.bytes_in, previous_counter.bytes_in, time_diff)
            rates['bytes_out_rate'] = self._calculate_counter_rate(
                current_counter.bytes_out, previous_counter.bytes_out, time_diff)

            # 計算封包速率
            rates['packets_in_rate'] = self._calculate_counter_rate(
                current_counter.packets_in, previous_counter.packets_in, time_diff)
            rates['packets_out_rate'] = self._calculate_counter_rate(
                current_counter.packets_out, previous_counter.packets_out, time_diff)

            # 計算位元速率 (bytes * 8)
            rates['bits_in_rate'] = rates['bytes_in_rate'] * 8
            rates['bits_out_rate'] = rates['bytes_out_rate'] * 8

        except Exception as e:
            self.logger.warning(f"計算速率時發生錯誤 {port_key}: {e}")

        return rates

    def _calculate_counter_rate(self, current: int, previous: int, time_diff: float) -> float:
        """計算計數器速率，處理溢位情況"""
        if current >= previous:
            return (current - previous) / time_diff
        else:
            # 處理 32-bit 計數器溢位
            max_32bit = 2**32
            if current + max_32bit - previous < max_32bit / 2:
                return (current + max_32bit - previous) / time_diff
            else:
                # 計數器可能重置，回傳 0
                return 0.0

    def get_port_statistics(self) -> Dict[str, Any]:
        """取得 Port 統計資訊"""
        ports = self.discover_ports()

        stats = {
            'total_ports': len(ports),
            'ports_with_traffic_data': len(self.previous_counters),
            'last_collection_time': None
        }

        if self.previous_counters:
            latest_time = max(counter.timestamp for counter in self.previous_counters.values())
            stats['last_collection_time'] = datetime.fromtimestamp(latest_time).isoformat()

        return stats

    def cleanup_old_counters(self, max_age: int = 3600):
        """清理舊的計數器資料"""
        current_time = time.time()
        to_remove = []

        for port_key, counter in self.previous_counters.items():
            if current_time - counter.timestamp > max_age:
                to_remove.append(port_key)

        for port_key in to_remove:
            del self.previous_counters[port_key]

        if to_remove:
            self.logger.info(f"清理了 {len(to_remove)} 個過期的計數器記錄")