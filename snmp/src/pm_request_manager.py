import logging
import time
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
from pysnmp.hlapi import *
from pysnmp.proto.rfc1902 import Counter32, Counter64, Gauge32, Integer32


class PMRequestState(Enum):
    """PM Request 狀態枚舉"""
    CREATED = 1
    PENDING = 2
    STARTED = 3
    FINISHED = 4
    FAILED = 5
    CANCELLING = 6
    CANCELLED = 7


class PMRequestType(Enum):
    """PM Request 類型枚舉"""
    PM_HISTORY = 1
    PM_CURRENT = 2
    PM_POINTS = 3


class FilterType(Enum):
    """過濾器類型枚舉"""
    TP_OBJECT = 1
    PORT_OBJECT = 2
    NE_OBJECT = 3
    SNC_OBJECT = 4
    ETHERNET_PATH_OBJECT = 5
    MODULE_OBJECT = 6
    EQUIP_HOLDER_OBJECT = 7


class PMRequestManager:
    """PM Request 管理器"""

    # SNMP OID 定義
    OID_PM_REQUEST_NEXT_ID = '1.3.6.1.4.1.42229.6.22.10.1.0'
    OID_PM_REQUEST_TABLE = '1.3.6.1.4.1.42229.6.22.10.2.1'
    OID_PM_REQUEST_ROW_STATUS = '1.3.6.1.4.1.42229.6.22.10.2.1.3'
    OID_PM_REQUEST_STATE = '1.3.6.1.4.1.42229.6.22.10.2.1.4'
    OID_PM_REQUEST_NAME = '1.3.6.1.4.1.42229.6.22.10.2.1.2'
    OID_PM_REQUEST_TYPE = '1.3.6.1.4.1.42229.6.22.10.2.1.7'
    OID_PM_REQUEST_FILTER_TYPE = '1.3.6.1.4.1.42229.6.22.10.2.1.10'
    OID_PM_REQUEST_FILTER_VALUE = '1.3.6.1.4.1.42229.6.22.10.2.1.11'
    OID_PM_REQUEST_INFO = '1.3.6.1.4.1.42229.6.22.10.2.1.6'

    # PM 結果表格 OID
    OID_PM_RESULT_PMP_TABLE = '1.3.6.1.4.1.42229.6.22.10.3.1'
    OID_PM_RESULT_VALUE_TABLE = '1.3.6.1.4.1.42229.6.22.10.4.1'

    def __init__(self, config: dict):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.snmp_config = config['snmp']

        # SNMP 連線設定
        self.timeout = self.snmp_config.get('timeout', 5)
        self.retries = self.snmp_config.get('retries', 3)

        # SNMP 引擎設定
        self.snmp_engine = SnmpEngine()
        self.target = UdpTransportTarget(
            (self.snmp_config['host'], self.snmp_config['port']),
            timeout=self.timeout,
            retries=self.retries
        )
        self.community = CommunityData(self.snmp_config['community'])
        self.context = ContextData()

        # 活動的 requests 追蹤
        self.active_requests: Dict[int, Dict[str, Any]] = {}

    def get_next_request_id(self) -> Optional[int]:
        """取得下一個可用的 Request ID"""
        try:
            for (errorIndication, errorStatus, errorIndex, varBinds) in getCmd(
                self.snmp_engine,
                self.community,
                self.target,
                self.context,
                ObjectType(ObjectIdentity(self.OID_PM_REQUEST_NEXT_ID))
            ):
                if errorIndication:
                    self.logger.error(f"取得 Request ID 錯誤: {errorIndication}")
                    return None
                elif errorStatus:
                    self.logger.error(f"取得 Request ID 錯誤: {errorStatus.prettyPrint()}")
                    return None
                else:
                    for varBind in varBinds:
                        return int(varBind[1])
            return None
        except Exception as e:
            self.logger.error(f"取得 Request ID 時發生錯誤: {e}")
            return None

    def create_pm_request(self, request_name: str, filter_value: str,
                         request_type: PMRequestType = PMRequestType.PM_CURRENT,
                         filter_type: FilterType = FilterType.PORT_OBJECT) -> Optional[int]:
        """建立新的 PM Request"""
        try:
            # 取得 Request ID
            request_id = self.get_next_request_id()
            if request_id is None:
                self.logger.error("無法取得 Request ID")
                return None

            self.logger.info(f"建立 PM Request {request_id}: {request_name}")

            # 建立 PM Request
            for (errorIndication, errorStatus, errorIndex, varBinds) in setCmd(
                self.snmp_engine,
                self.community,
                self.target,
                self.context,
                ObjectType(
                    ObjectIdentity(f"{self.OID_PM_REQUEST_NAME}.{request_id}"),
                    OctetString(request_name)
                ),
                ObjectType(
                    ObjectIdentity(f"{self.OID_PM_REQUEST_TYPE}.{request_id}"),
                    Integer32(request_type.value)
                ),
                ObjectType(
                    ObjectIdentity(f"{self.OID_PM_REQUEST_FILTER_TYPE}.{request_id}"),
                    Integer32(filter_type.value)
                ),
                ObjectType(
                    ObjectIdentity(f"{self.OID_PM_REQUEST_FILTER_VALUE}.{request_id}"),
                    OctetString(filter_value)
                ),
                ObjectType(
                    ObjectIdentity(f"{self.OID_PM_REQUEST_ROW_STATUS}.{request_id}"),
                    Integer32(4)  # createAndGo
                )
            ):
                if errorIndication:
                    self.logger.error(f"建立 PM Request 錯誤: {errorIndication}")
                    return None
                elif errorStatus:
                    self.logger.error(f"建立 PM Request 錯誤: {errorStatus.prettyPrint()}")
                    return None

            # 記錄建立的 request
            self.active_requests[request_id] = {
                'name': request_name,
                'filter_value': filter_value,
                'request_type': request_type,
                'filter_type': filter_type,
                'created_time': time.time(),
                'state': PMRequestState.CREATED
            }

            self.logger.info(f"PM Request {request_id} 建立成功")
            return request_id

        except Exception as e:
            self.logger.error(f"建立 PM Request 時發生錯誤: {e}")
            return None

    def execute_pm_request(self, request_id: int, timeout: int = 30) -> bool:
        """執行 PM Request 並等待完成"""
        try:
            self.logger.info(f"執行 PM Request {request_id}")

            # 啟動 Request
            for (errorIndication, errorStatus, errorIndex, varBinds) in setCmd(
                self.snmp_engine,
                self.community,
                self.target,
                self.context,
                ObjectType(
                    ObjectIdentity(f"{self.OID_PM_REQUEST_STATE}.{request_id}"),
                    Integer32(3)  # started
                )
            ):
                if errorIndication:
                    self.logger.error(f"啟動 PM Request 錯誤: {errorIndication}")
                    return False
                elif errorStatus:
                    self.logger.error(f"啟動 PM Request 錯誤: {errorStatus.prettyPrint()}")
                    return False

            # 等待完成
            start_time = time.time()
            while time.time() - start_time < timeout:
                state = self.get_request_state(request_id)
                if state is None:
                    self.logger.error(f"無法取得 Request {request_id} 狀態")
                    return False

                if state == PMRequestState.FINISHED:
                    self.logger.info(f"PM Request {request_id} 執行完成")
                    if request_id in self.active_requests:
                        self.active_requests[request_id]['state'] = state
                    return True
                elif state == PMRequestState.FAILED:
                    error_info = self.get_request_info(request_id)
                    self.logger.error(f"PM Request {request_id} 執行失敗: {error_info}")
                    if request_id in self.active_requests:
                        self.active_requests[request_id]['state'] = state
                    return False

                time.sleep(1)

            self.logger.error(f"PM Request {request_id} 執行超時")
            return False

        except Exception as e:
            self.logger.error(f"執行 PM Request 時發生錯誤: {e}")
            return False

    def get_request_state(self, request_id: int) -> Optional[PMRequestState]:
        """取得 PM Request 狀態"""
        try:
            for (errorIndication, errorStatus, errorIndex, varBinds) in getCmd(
                self.snmp_engine,
                self.community,
                self.target,
                self.context,
                ObjectType(ObjectIdentity(f"{self.OID_PM_REQUEST_STATE}.{request_id}"))
            ):
                if errorIndication or errorStatus:
                    return None
                else:
                    for varBind in varBinds:
                        state_value = int(varBind[1])
                        return PMRequestState(state_value)
            return None
        except Exception as e:
            self.logger.error(f"取得 Request 狀態時發生錯誤: {e}")
            return None

    def get_request_info(self, request_id: int) -> str:
        """取得 PM Request 資訊"""
        try:
            for (errorIndication, errorStatus, errorIndex, varBinds) in getCmd(
                self.snmp_engine,
                self.community,
                self.target,
                self.context,
                ObjectType(ObjectIdentity(f"{self.OID_PM_REQUEST_INFO}.{request_id}"))
            ):
                if errorIndication or errorStatus:
                    return ""
                else:
                    for varBind in varBinds:
                        return str(varBind[1])
            return ""
        except Exception as e:
            self.logger.error(f"取得 Request 資訊時發生錯誤: {e}")
            return ""

    def get_pm_results(self, request_id: int) -> Tuple[List[Dict], List[Dict]]:
        """取得 PM 結果資料"""
        try:
            # 取得 PMP 資料
            pmp_results = self._get_pmp_results(request_id)
            # 取得數值資料
            value_results = self._get_value_results(request_id)

            return pmp_results, value_results

        except Exception as e:
            self.logger.error(f"取得 PM 結果時發生錯誤: {e}")
            return [], []

    def _get_pmp_results(self, request_id: int) -> List[Dict]:
        """取得 PMP 結果"""
        results = []
        try:
            # 遍歷 PMP 表格
            for (errorIndication, errorStatus, errorIndex, varBinds) in bulkCmd(
                self.snmp_engine,
                self.community,
                self.target,
                self.context,
                0, 25,  # max_repetitions
                ObjectType(ObjectIdentity(self.OID_PM_RESULT_PMP_TABLE)),
                lexicographicMode=False,
                maxRows=1000
            ):
                if errorIndication or errorStatus:
                    break

                for varBind in varBinds:
                    oid = str(varBind[0])
                    value = varBind[1]

                    # 解析 OID 取得欄位資訊
                    parts = oid.replace(f"{self.OID_PM_RESULT_PMP_TABLE}.", "").split(".")
                    if len(parts) >= 3:
                        field_id = parts[0]
                        req_id = int(parts[1])
                        pmp_number = int(parts[2])

                        # 只取得符合 request_id 的結果
                        if req_id == request_id:
                            # 找到或建立對應的 PMP 記錄
                            pmp_record = None
                            for record in results:
                                if record['pmp_number'] == pmp_number:
                                    pmp_record = record
                                    break

                            if pmp_record is None:
                                pmp_record = {
                                    'request_id': req_id,
                                    'pmp_number': pmp_number
                                }
                                results.append(pmp_record)

                            # 根據欄位 ID 設定對應的值
                            pmp_record[f"field_{field_id}"] = value

        except Exception as e:
            self.logger.error(f"取得 PMP 結果時發生錯誤: {e}")

        return results

    def _get_value_results(self, request_id: int) -> List[Dict]:
        """取得數值結果"""
        results = []
        try:
            # 遍歷數值表格
            for (errorIndication, errorStatus, errorIndex, varBinds) in bulkCmd(
                self.snmp_engine,
                self.community,
                self.target,
                self.context,
                0, 25,
                ObjectType(ObjectIdentity(self.OID_PM_RESULT_VALUE_TABLE)),
                lexicographicMode=False,
                maxRows=1000
            ):
                if errorIndication or errorStatus:
                    break

                for varBind in varBinds:
                    oid = str(varBind[0])
                    value = varBind[1]

                    parts = oid.replace(f"{self.OID_PM_RESULT_VALUE_TABLE}.", "").split(".")
                    if len(parts) >= 4:
                        field_id = parts[0]
                        req_id = int(parts[1])
                        pmp_number = int(parts[2])
                        value_number = int(parts[3])

                        if req_id == request_id:
                            value_record = {
                                'request_id': req_id,
                                'pmp_number': pmp_number,
                                'value_number': value_number,
                                f"field_{field_id}": value
                            }
                            results.append(value_record)

        except Exception as e:
            self.logger.error(f"取得數值結果時發生錯誤: {e}")

        return results

    def delete_pm_request(self, request_id: int) -> bool:
        """刪除 PM Request"""
        try:
            self.logger.info(f"刪除 PM Request {request_id}")

            for (errorIndication, errorStatus, errorIndex, varBinds) in setCmd(
                self.snmp_engine,
                self.community,
                self.target,
                self.context,
                ObjectType(
                    ObjectIdentity(f"{self.OID_PM_REQUEST_ROW_STATUS}.{request_id}"),
                    Integer32(6)  # destroy
                )
            ):
                if errorIndication:
                    self.logger.error(f"刪除 PM Request 錯誤: {errorIndication}")
                    return False
                elif errorStatus:
                    self.logger.error(f"刪除 PM Request 錯誤: {errorStatus.prettyPrint()}")
                    return False

            # 從追蹤清單移除
            if request_id in self.active_requests:
                del self.active_requests[request_id]

            self.logger.info(f"PM Request {request_id} 刪除成功")
            return True

        except Exception as e:
            self.logger.error(f"刪除 PM Request 時發生錯誤: {e}")
            return False

    def cleanup_old_requests(self, max_age: int = 3600) -> None:
        """清理舊的 PM Requests"""
        current_time = time.time()
        to_delete = []

        for request_id, info in self.active_requests.items():
            age = current_time - info.get('created_time', current_time)
            if age > max_age:
                to_delete.append(request_id)

        for request_id in to_delete:
            self.delete_pm_request(request_id)