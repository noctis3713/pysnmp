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
            try:
                name_filter = self.pm_config.get('ports', {}).get('filter')
                ports = self.discover_ports(name_filter)
            except Exception as e:
                self.logger.error(f"探索 Port 時發生錯誤: {e}")
                return []

        if not ports:
            self.logger.warning("沒有可收集的 Port")
            return []

        # 分批處理 Port，避免一次處理太多
        batch_size = self.pm_config.get('batch_size', 50)
        all_records = []
        failed_batches = 0

        port_items = list(ports.items())
        total_batches = (len(port_items) + batch_size - 1) // batch_size

        self.logger.info(f"開始收集 {len(ports)} 個 Port 的流量資料，分為 {total_batches} 批處理")

        for batch_index in range(0, len(port_items), batch_size):
            batch_ports = dict(port_items[batch_index:batch_index + batch_size])
            batch_num = batch_index // batch_size + 1

            try:
                self.logger.debug(f"處理第 {batch_num}/{total_batches} 批 ({len(batch_ports)} 個 Port)")

                # 建立批次 PM Request
                filter_value = ','.join(batch_ports.keys())
                request_id = self.pm_manager.create_pm_request(
                    request_name=f"Port_Traffic_Batch_{batch_num}_{int(time.time())}",
                    filter_value=filter_value,
                    request_type=PMRequestType.PM_CURRENT,
                    filter_type=FilterType.PORT_OBJECT
                )

                if request_id is None:
                    self.logger.error(f"無法建立第 {batch_num} 批的 PM Request")
                    failed_batches += 1
                    continue

                # 執行 Request（增加重試次數）
                timeout = self.pm_config.get('request_timeout', 60)
                max_retries = self.pm_config.get('max_retries', 3)

                if not self.pm_manager.execute_pm_request(request_id, timeout=timeout, max_retries=max_retries):
                    self.logger.error(f"第 {batch_num} 批的 PM Request {request_id} 執行失敗")
                    # 嘗試清理失敗的 Request
                    try:
                        self.pm_manager.delete_pm_request(request_id)
                    except Exception as cleanup_e:
                        self.logger.warning(f"清理失敗的 PM Request {request_id} 時發生錯誤: {cleanup_e}")
                    failed_batches += 1
                    continue

                # 取得結果
                try:
                    pmp_results, value_results = self.pm_manager.get_pm_results(request_id)

                    if not pmp_results and not value_results:
                        self.logger.warning(f"第 {batch_num} 批沒有取得任何結果資料")
                    else:
                        # 處理結果資料
                        batch_records = self._process_pm_results(pmp_results, value_results, batch_ports)
                        all_records.extend(batch_records)
                        self.logger.debug(f"第 {batch_num} 批成功收集 {len(batch_records)} 筆記錄")

                except Exception as process_e:
                    self.logger.error(f"處理第 {batch_num} 批結果時發生錯誤: {process_e}")
                    failed_batches += 1

                # 清理 Request
                try:
                    self.pm_manager.delete_pm_request(request_id)
                except Exception as cleanup_e:
                    self.logger.warning(f"清理 PM Request {request_id} 時發生錯誤: {cleanup_e}")

                # 批次間稍微延遲，避免對 TNMS 造成過大負載
                if batch_num < total_batches:
                    time.sleep(1)

            except Exception as e:
                self.logger.error(f"處理第 {batch_num} 批時發生未預期的錯誤: {e}", exc_info=True)
                failed_batches += 1
                continue

        # 記錄收集結果統計
        success_batches = total_batches - failed_batches
        self.logger.info(f"流量收集完成: 成功 {success_batches}/{total_batches} 批，收集 {len(all_records)} 筆記錄")

        if failed_batches > 0:
            self.logger.warning(f"有 {failed_batches} 批處理失敗，可能影響部分 Port 的資料收集")

        return all_records

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
                # 從 PMP 結果取得 NE ID 和 Port ID（根據 MIB 確認的欄位）
                ne_id = pmp.get('ne_id')
                port_id = pmp.get('port_id')

                # 記錄額外的 PMP 資訊以供除錯
                pmp_name = pmp.get('pmp_name', '')
                obj_location = pmp.get('obj_location', '')
                direction = pmp.get('direction', '')

                if ne_id and port_id:
                    port_key = f"{ne_id}|{port_id}"
                    if port_key in ports:
                        pmp_to_port[pmp_number] = {
                            'port_key': port_key,
                            'port_info': ports[port_key],
                            'pmp_info': {
                                'pmp_name': pmp_name,
                                'obj_location': obj_location,
                                'direction': direction,
                                'ne_name': pmp.get('ne_name', ''),
                                'location': pmp.get('location', ''),
                                'native_location': pmp.get('native_location', '')
                            }
                        }
                        self.logger.debug(f"PMP {pmp_number} 對應到 Port {port_key}: {pmp_name} ({direction})")
                    else:
                        # 記錄找不到對應 Port 的情況，便於除錯
                        self.logger.debug(f"找不到對應的 Port: {port_key} (PMP: {pmp_number}, 名稱: {pmp_name})")
                else:
                    # 記錄缺少關鍵欄位的情況
                    self.logger.debug(f"PMP {pmp_number} 缺少 NE ID 或 Port ID: ne_id={ne_id}, port_id={port_id}")

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

                # 建立記錄，包含更多 PMP 資訊
                pmp_info = port_mapping.get('pmp_info', {})
                record = {
                    'measurement': 'port_traffic',
                    'tags': {
                        'ne_id': port_info['ne_id'],
                        'port_id': port_info['port_id'],
                        'port_name': port_info.get('port_name', ''),
                        'port_type': port_info.get('port_type', ''),
                        'pmp_name': pmp_info.get('pmp_name', ''),
                        'pmp_direction': pmp_info.get('direction', ''),
                        'pmp_location': pmp_info.get('location', ''),
                        'ne_name': pmp_info.get('ne_name', ''),
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
            # 使用根據 MIB 確認的欄位名稱
            param = value.get('param_name', '')
            val = value.get('param_value', '0')
            unit = value.get('unit', '')
            status = value.get('status', '')

            try:
                # 嘗試轉換為數字，支援不同的數字格式
                if isinstance(val, (int, float)):
                    numeric_value = int(val)
                elif isinstance(val, str):
                    if val.isdigit():
                        numeric_value = int(val)
                    else:
                        # 嘗試處理科學記號或其他格式
                        try:
                            numeric_value = int(float(val))
                        except (ValueError, TypeError):
                            self.logger.debug(f"無法解析數值: {val} (參數: {param}, 單位: {unit})")
                            continue
                else:
                    continue

                # 根據參數名稱對應到計數器欄位
                param_lower = param.lower() if param else ''

                # 更詳細的參數名稱對應邏輯，包含常見的 TNMS 參數名稱
                # 位元組/八位元組相關
                if any(x in param_lower for x in ['bytes', 'octets', 'byte']):
                    if any(x in param_lower for x in ['in', 'rx', 'receive', 'ingress', 'input']):
                        counter.bytes_in = numeric_value
                        self.logger.debug(f"設定 bytes_in: {param} = {numeric_value}")
                    elif any(x in param_lower for x in ['out', 'tx', 'transmit', 'egress', 'output']):
                        counter.bytes_out = numeric_value
                        self.logger.debug(f"設定 bytes_out: {param} = {numeric_value}")
                # 封包/框架相關
                elif any(x in param_lower for x in ['packets', 'frames', 'pkts', 'pkt', 'frame']):
                    if any(x in param_lower for x in ['in', 'rx', 'receive', 'ingress', 'input']):
                        counter.packets_in = numeric_value
                        self.logger.debug(f"設定 packets_in: {param} = {numeric_value}")
                    elif any(x in param_lower for x in ['out', 'tx', 'transmit', 'egress', 'output']):
                        counter.packets_out = numeric_value
                        self.logger.debug(f"設定 packets_out: {param} = {numeric_value}")
                # 錯誤相關
                elif 'error' in param_lower:
                    if any(x in param_lower for x in ['in', 'rx', 'receive', 'ingress', 'input']):
                        counter.errors_in = numeric_value
                        self.logger.debug(f"設定 errors_in: {param} = {numeric_value}")
                    elif any(x in param_lower for x in ['out', 'tx', 'transmit', 'egress', 'output']):
                        counter.errors_out = numeric_value
                        self.logger.debug(f"設定 errors_out: {param} = {numeric_value}")
                # 丟棄相關
                elif any(x in param_lower for x in ['discard', 'drop', 'dropped']):
                    if any(x in param_lower for x in ['in', 'rx', 'receive', 'ingress', 'input']):
                        counter.discards_in = numeric_value
                        self.logger.debug(f"設定 discards_in: {param} = {numeric_value}")
                    elif any(x in param_lower for x in ['out', 'tx', 'transmit', 'egress', 'output']):
                        counter.discards_out = numeric_value
                        self.logger.debug(f"設定 discards_out: {param} = {numeric_value}")
                else:
                    # 記錄未識別的參數，包含單位資訊
                    self.logger.debug(f"未識別的參數: {param} = {val} ({unit}) [狀態: {status}]")

            except (ValueError, TypeError) as e:
                self.logger.debug(f"解析參數值時發生錯誤: {param} = {val}, 錯誤: {e}")
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

    def cleanup_old_counters(self, max_age: int = 3600, max_counters: int = 1000) -> Dict[str, int]:
        """清理舊的計數器資料"""
        current_time = time.time()
        cleanup_stats = {
            'expired_counters': 0,
            'excess_counters': 0,
            'total_cleaned': 0,
            'remaining_counters': 0
        }

        # 1. 清理過期的計數器
        expired_ports = []
        for port_key, counter in self.previous_counters.items():
            if current_time - counter.timestamp > max_age:
                expired_ports.append(port_key)

        for port_key in expired_ports:
            del self.previous_counters[port_key]
        cleanup_stats['expired_counters'] = len(expired_ports)

        # 2. 如果計數器數量仍然過多，清理最舊的
        if len(self.previous_counters) > max_counters:
            # 按時間戳排序，保留最新的
            sorted_counters = sorted(
                self.previous_counters.items(),
                key=lambda x: x[1].timestamp,
                reverse=True
            )

            # 保留最新的 max_counters 個
            to_keep = sorted_counters[:max_counters]
            to_remove = sorted_counters[max_counters:]

            # 重建字典
            self.previous_counters = dict(to_keep)
            cleanup_stats['excess_counters'] = len(to_remove)

            if to_remove:
                oldest_time = to_remove[-1][1].timestamp
                newest_time = to_remove[0][1].timestamp
                self.logger.info(f"因數量超限清理了 {len(to_remove)} 個計數器 "
                               f"(時間範圍: {time.ctime(oldest_time)} 到 {time.ctime(newest_time)})")

        cleanup_stats['total_cleaned'] = cleanup_stats['expired_counters'] + cleanup_stats['excess_counters']
        cleanup_stats['remaining_counters'] = len(self.previous_counters)

        # 記錄清理結果
        if cleanup_stats['total_cleaned'] > 0:
            self.logger.info(f"計數器清理完成: "
                           f"過期 {cleanup_stats['expired_counters']} 個, "
                           f"超量 {cleanup_stats['excess_counters']} 個, "
                           f"剩餘 {cleanup_stats['remaining_counters']} 個")

        return cleanup_stats