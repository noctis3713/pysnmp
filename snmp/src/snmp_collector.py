import logging
import time
from typing import Dict, List, Any, Optional
from pysnmp.hlapi import *
from pysnmp.proto.rfc1902 import Counter32, Counter64, Gauge32, Integer32

class TNMSSNMPCollector:
    def __init__(self, config: dict):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.snmp_config = config['snmp']

        # 設定超時和重試
        self.timeout = self.snmp_config.get('timeout', 5)
        self.retries = self.snmp_config.get('retries', 3)
        self.max_repetitions = self.snmp_config.get('max_repetitions', 25)

        # SNMP 引擎設定 - 重用單一實例
        self.snmp_engine = SnmpEngine()
        self.target = UdpTransportTarget(
            (self.snmp_config['host'], self.snmp_config['port']),
            timeout=self.timeout,
            retries=self.retries
        )
        self.community = CommunityData(self.snmp_config['community'])
        self.context = ContextData()

    def _convert_snmp_value(self, value, value_type: str) -> Any:
        """轉換SNMP值為適當的Python型別"""
        try:
            if value_type == 'string':
                return str(value)
            elif value_type == 'integer':
                if isinstance(value, (Counter32, Counter64, Gauge32, Integer32)):
                    return int(value)
                return int(value)
            elif value_type == 'counter':
                return int(value)
            elif value_type == 'gauge':
                return float(value)
            else:
                return str(value)
        except (ValueError, TypeError) as e:
            self.logger.warning(f"無法轉換值 {value} 為 {value_type}: {e}")
            return str(value)

    def get_single_value(self, oid: str) -> Optional[Any]:
        """獲取單一OID值"""
        try:
            for (errorIndication, errorStatus, errorIndex, varBinds) in getCmd(
                self.snmp_engine,
                self.community,
                self.target,
                self.context,
                ObjectType(ObjectIdentity(oid))
            ):
                if errorIndication:
                    self.logger.error(f"SNMP錯誤: {errorIndication}")
                    return None
                elif errorStatus:
                    self.logger.error(f"SNMP錯誤: {errorStatus.prettyPrint()} at {errorIndex and varBinds[int(errorIndex) - 1][0] or '?'}")
                    return None
                else:
                    for varBind in varBinds:
                        return varBind[1]
            return None
        except Exception as e:
            self.logger.error(f"獲取單一值時發生錯誤 {oid}: {e}")
            return None

    def walk_table(self, base_oid: str) -> Dict[str, Any]:
        """遍歷SNMP表格"""
        results = {}
        try:
            for (errorIndication, errorStatus, errorIndex, varBinds) in bulkCmd(
                self.snmp_engine,
                self.community,
                self.target,
                self.context,
                0, self.max_repetitions,
                ObjectType(ObjectIdentity(base_oid)),
                lexicographicMode=False,
                maxRows=1000
            ):
                if errorIndication:
                    self.logger.error(f"SNMP Walk錯誤: {errorIndication}")
                    break
                elif errorStatus:
                    self.logger.error(f"SNMP Walk錯誤: {errorStatus.prettyPrint()}")
                    break
                else:
                    for varBind in varBinds:
                        oid = str(varBind[0])
                        value = varBind[1]

                        # 檢查是否還在我們要的表格範圍內
                        if not oid.startswith(base_oid):
                            return results

                        results[oid] = value

        except Exception as e:
            self.logger.error(f"遍歷表格時發生錯誤 {base_oid}: {e}")

        return results

    def collect_oid_data(self, oid_config: dict) -> List[Dict[str, Any]]:
        """根據OID配置收集資料"""
        oid_name = oid_config['name']
        base_oid = oid_config['oid']
        measurement = oid_config['measurement']
        fields = oid_config['fields']

        self.logger.info(f"開始收集 {oid_name} 資料")

        # 遍歷表格獲取所有資料
        raw_data = self.walk_table(base_oid)

        if not raw_data:
            self.logger.warning(f"沒有從 {oid_name} 獲取到資料")
            return []

        # 組織資料為記錄格式
        records = []
        indices = set()

        # 提取所有索引
        for oid in raw_data.keys():
            # 從OID中提取表格索引
            if base_oid in oid:
                parts = oid.replace(base_oid + '.', '').split('.')
                if len(parts) >= 2:
                    field_oid = parts[0]
                    index = '.'.join(parts[1:])
                    indices.add(index)

        # 為每個索引建立記錄
        for index in indices:
            record = {
                'measurement': measurement,
                'tags': {'index': index},
                'fields': {},
                'timestamp': int(time.time() * 1000000000)  # nanoseconds
            }

            # 為每個欄位收集值
            for field in fields:
                field_name = field['name']
                field_oid = field['oid']
                field_type = field['type']

                # 建構完整的OID (field_oid + index)
                full_oid = f"{field_oid}.{index}"

                if full_oid in raw_data:
                    raw_value = raw_data[full_oid]
                    converted_value = self._convert_snmp_value(raw_value, field_type)

                    if field_type == 'string' and field_name in ['neName', 'neLocation', 'portName']:
                        # 字串欄位作為標籤
                        record['tags'][field_name] = converted_value
                    else:
                        record['fields'][field_name] = converted_value

            # 只有當記錄有資料時才加入
            if record['fields'] or len(record['tags']) > 1:
                records.append(record)

        self.logger.info(f"從 {oid_name} 收集到 {len(records)} 筆記錄")
        return records

    def collect_all_data(self) -> List[Dict[str, Any]]:
        """收集所有配置的OID資料"""
        all_records = []
        oids_config = self.config.get('oids', {})

        for oid_key, oid_config in oids_config.items():
            try:
                records = self.collect_oid_data(oid_config)
                all_records.extend(records)
            except Exception as e:
                self.logger.error(f"收集 {oid_key} 資料時發生錯誤: {e}")
                continue

        return all_records

    def test_connection(self) -> bool:
        """測試SNMP連線"""
        try:
            # 測試 TNMS 特定 OID (第一個網路元素的名稱)
            test_oid = '1.3.6.1.4.1.42229.6.22.1.1.1.3.35'
            result = self.get_single_value(test_oid)
            if result:
                self.logger.info(f"TNMS SNMP連線測試成功，找到網路元素: {result}")
                return True
            else:
                # 如果特定設備不存在，嘗試測試基礎表格
                base_test_oid = '1.3.6.1.4.1.42229.6.22.1.1.1.1'
                base_result = self.get_single_value(base_test_oid + '.35')
                if base_result:
                    self.logger.info(f"TNMS SNMP連線測試成功，基礎表格可用")
                    return True
                else:
                    self.logger.error("TNMS SNMP連線測試失敗：無法連接到TNMS系統或無資料")
                    return False
        except Exception as e:
            self.logger.error(f"SNMP連線測試錯誤: {e}")
            return False