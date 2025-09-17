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

    # PMP 表格欄位定義 (enmsPerfMonResultPmpTable)
    # 根據 TNMS-NBI-MIB.my 確認的欄位對應
    PMP_FIELD_REQUEST_ID = '1'          # enmsPmResultPmpReqId - 請求 ID (索引)
    PMP_FIELD_PMP_NUMBER = '2'          # enmsPmResultPmpPmpNumber - PMP 編號 (索引)
    PMP_FIELD_NE_ID = '3'               # enmsPmResultPmpNeId - NE ID
    PMP_FIELD_PORT_ID = '4'             # enmsPmResultPmpPortId - Port ID
    PMP_FIELD_TP_ID_HIGH = '5'          # enmsPmResultPmpTPIdH - TP ID 高位
    PMP_FIELD_TP_ID_LOW = '6'           # enmsPmResultPmpTPIdL - TP ID 低位
    PMP_FIELD_NE_NAME = '7'             # enmsPmResultPmpNeIdName - NE 名稱
    PMP_FIELD_OBJ_LOCATION = '8'        # enmsPmResultPmpObjLocation - 物件位置
    PMP_FIELD_PMP_NAME = '9'            # enmsPmResultPmpName - PMP 名稱
    PMP_FIELD_LOCATION = '10'           # enmsPmResultPmpLocation - PMP 位置
    PMP_FIELD_DIRECTION = '11'          # enmsPmResultPmpDirection - PMP 方向
    PMP_FIELD_RETRIEVAL_TIME = '12'     # enmsPmResultPmpRetrievalTime - 擷取時間
    PMP_FIELD_PERIOD_END_TIME = '13'    # enmsPmResultPmpPeriodEndTime - 週期結束時間
    PMP_FIELD_MONITORED_TIME = '14'     # enmsPmResultPmpMonitoredTime - 監控時間
    PMP_FIELD_NUM_VALUES = '15'         # enmsPmResultPmpNumValues - 數值數量
    PMP_FIELD_RELATED_PATHS = '16'      # enmsPmResultPmpRelatedPaths - 相關路徑
    PMP_FIELD_RELATED_SERVICES = '17'   # enmsPmResultPmpRelatedServices - 相關服務
    PMP_FIELD_RELATED_SUBSCRIBERS = '18' # enmsPmResultPmpRelatedSubscribers - 相關訂閱者
    PMP_FIELD_NATIVE_LOCATION = '19'    # enmsPmResultPmpNativeLocation - 原生位置
    PMP_FIELD_MODULE_ID = '20'          # enmsPmResultPmpModuleId - 模組 ID
    PMP_FIELD_EQUIP_HOLDER_ID = '21'    # enmsPmResultPmpEquipHolderId - 設備持有者 ID

    # Value 表格欄位定義 (enmsPerfMonResultValueTable)
    # 根據 TNMS-NBI-MIB.my 確認的欄位對應
    VALUE_FIELD_REQUEST_ID = '1'        # enmsPmResultValReqId - 請求 ID (索引)
    VALUE_FIELD_PMP_NUMBER = '2'        # enmsPmResultValPmpNumber - PMP 編號 (索引)
    VALUE_FIELD_VALUE_NUMBER = '3'      # enmsPmResultValNumber - 數值編號 (索引)
    VALUE_FIELD_PARAM_NAME = '4'        # enmsPmResultValParam - 參數名稱
    VALUE_FIELD_PARAM_VALUE = '5'       # enmsPmResultValValue - 參數值
    VALUE_FIELD_UNIT = '6'              # enmsPmResultValUnit - 單位
    VALUE_FIELD_STATUS = '7'            # enmsPmResultValStatus - 狀態

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

    def execute_pm_request(self, request_id: int, timeout: int = 30, max_retries: int = 3) -> bool:
        """執行 PM Request 並等待完成"""
        last_error = None

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    self.logger.info(f"重試執行 PM Request {request_id} (第 {attempt + 1} 次)")
                    time.sleep(2 * attempt)  # 遞增延遲
                else:
                    self.logger.info(f"執行 PM Request {request_id}")

                # 啟動 Request
                start_success = False
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
                        last_error = f"啟動 PM Request 錯誤: {errorIndication}"
                        self.logger.warning(f"{last_error} (嘗試 {attempt + 1}/{max_retries})")
                        break
                    elif errorStatus:
                        last_error = f"啟動 PM Request 錯誤: {errorStatus.prettyPrint()}"
                        self.logger.warning(f"{last_error} (嘗試 {attempt + 1}/{max_retries})")
                        break
                    else:
                        start_success = True
                        break

                if not start_success:
                    continue

                # 等待完成
                start_time = time.time()
                check_interval = 1
                last_state = None
                state_change_time = start_time

                while time.time() - start_time < timeout:
                    state = self.get_request_state(request_id)
                    if state is None:
                        last_error = f"無法取得 Request {request_id} 狀態"
                        self.logger.warning(f"{last_error} (嘗試 {attempt + 1}/{max_retries})")
                        break

                    # 記錄狀態變化
                    if state != last_state:
                        self.logger.debug(f"PM Request {request_id} 狀態變化: {last_state} -> {state}")
                        last_state = state
                        state_change_time = time.time()

                    if state == PMRequestState.FINISHED:
                        self.logger.info(f"PM Request {request_id} 執行完成 (耗時 {time.time() - start_time:.1f} 秒)")
                        if request_id in self.active_requests:
                            self.active_requests[request_id]['state'] = state
                        return True
                    elif state == PMRequestState.FAILED:
                        error_info = self.get_request_info(request_id)
                        last_error = f"PM Request {request_id} 執行失敗: {error_info}"
                        self.logger.warning(f"{last_error} (嘗試 {attempt + 1}/{max_retries})")
                        if request_id in self.active_requests:
                            self.active_requests[request_id]['state'] = state
                        break
                    elif state in [PMRequestState.CANCELLED, PMRequestState.CANCELLING]:
                        last_error = f"PM Request {request_id} 已被取消 (狀態: {state})"
                        self.logger.warning(f"{last_error} (嘗試 {attempt + 1}/{max_retries})")
                        break

                    # 如果狀態長時間未變化，可能有問題
                    if time.time() - state_change_time > timeout / 2:
                        self.logger.warning(f"PM Request {request_id} 狀態 {state} 超過 {timeout/2} 秒未變化")

                    time.sleep(check_interval)

                # 如果到這裡，表示執行超時
                if state not in [PMRequestState.FAILED, PMRequestState.CANCELLED, PMRequestState.CANCELLING]:
                    last_error = f"PM Request {request_id} 執行超時 (最終狀態: {state})"
                    self.logger.warning(f"{last_error} (嘗試 {attempt + 1}/{max_retries})")

            except Exception as e:
                last_error = f"執行 PM Request 時發生異常: {e}"
                self.logger.warning(f"{last_error} (嘗試 {attempt + 1}/{max_retries})", exc_info=True)

        # 所有重試都失敗
        self.logger.error(f"PM Request {request_id} 執行失敗，已重試 {max_retries} 次。最後錯誤: {last_error}")
        if request_id in self.active_requests:
            self.active_requests[request_id]['state'] = PMRequestState.FAILED
            self.active_requests[request_id]['last_error'] = last_error

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

    def _get_pmp_results(self, request_id: int, max_rows: int = 1000) -> List[Dict]:
        """取得 PMP 結果"""
        results = []
        total_processed = 0
        try:
            # 使用較小的批次大小避免一次取得過多資料
            batch_size = min(25, max_rows // 10) if max_rows > 250 else 25

            # 遍歷 PMP 表格
            for (errorIndication, errorStatus, errorIndex, varBinds) in bulkCmd(
                self.snmp_engine,
                self.community,
                self.target,
                self.context,
                0, batch_size,  # 動態調整批次大小
                ObjectType(ObjectIdentity(self.OID_PM_RESULT_PMP_TABLE)),
                lexicographicMode=False,
                maxRows=max_rows
            ):
                if errorIndication or errorStatus:
                    if errorIndication:
                        self.logger.warning(f"PMP 查詢中斷: {errorIndication}")
                    if errorStatus:
                        self.logger.warning(f"PMP 查詢錯誤: {errorStatus}")
                    break

                batch_count = 0
                for varBind in varBinds:
                    oid = str(varBind[0])
                    value = varBind[1]
                    total_processed += 1
                    batch_count += 1

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

                            # 使用欄位常數來解析和儲存數值
                            if field_id == self.PMP_FIELD_NE_ID:
                                pmp_record['ne_id'] = str(value)
                            elif field_id == self.PMP_FIELD_PORT_ID:
                                pmp_record['port_id'] = str(value)
                            elif field_id == self.PMP_FIELD_TP_ID_HIGH:
                                pmp_record['tp_id_high'] = str(value)
                            elif field_id == self.PMP_FIELD_TP_ID_LOW:
                                pmp_record['tp_id_low'] = str(value)
                            elif field_id == self.PMP_FIELD_NE_NAME:
                                pmp_record['ne_name'] = str(value)
                            elif field_id == self.PMP_FIELD_OBJ_LOCATION:
                                pmp_record['obj_location'] = str(value)
                            elif field_id == self.PMP_FIELD_PMP_NAME:
                                pmp_record['pmp_name'] = str(value)
                            elif field_id == self.PMP_FIELD_LOCATION:
                                pmp_record['location'] = str(value)
                            elif field_id == self.PMP_FIELD_DIRECTION:
                                pmp_record['direction'] = str(value)
                            elif field_id == self.PMP_FIELD_RETRIEVAL_TIME:
                                pmp_record['retrieval_time'] = str(value)
                            elif field_id == self.PMP_FIELD_PERIOD_END_TIME:
                                pmp_record['period_end_time'] = str(value)
                            elif field_id == self.PMP_FIELD_MONITORED_TIME:
                                pmp_record['monitored_time'] = str(value)
                            elif field_id == self.PMP_FIELD_NUM_VALUES:
                                pmp_record['num_values'] = str(value)
                            elif field_id == self.PMP_FIELD_RELATED_PATHS:
                                pmp_record['related_paths'] = str(value)
                            elif field_id == self.PMP_FIELD_RELATED_SERVICES:
                                pmp_record['related_services'] = str(value)
                            elif field_id == self.PMP_FIELD_RELATED_SUBSCRIBERS:
                                pmp_record['related_subscribers'] = str(value)
                            elif field_id == self.PMP_FIELD_NATIVE_LOCATION:
                                pmp_record['native_location'] = str(value)
                            elif field_id == self.PMP_FIELD_MODULE_ID:
                                pmp_record['module_id'] = str(value)
                            elif field_id == self.PMP_FIELD_EQUIP_HOLDER_ID:
                                pmp_record['equip_holder_id'] = str(value)
                            else:
                                # 保留原始欄位以供除錯
                                pmp_record[f"field_{field_id}"] = value

                # 記錄處理進度
                if total_processed > 0 and total_processed % 500 == 0:
                    self.logger.debug(f"已處理 {total_processed} 筆 PMP 記錄，目前找到 {len(results)} 個 PMP")

                # 檢查是否達到記憶體限制
                if len(results) > max_rows:
                    self.logger.warning(f"PMP 結果數量達到限制 ({max_rows})，停止查詢")
                    break

        except Exception as e:
            self.logger.error(f"取得 PMP 結果時發生錯誤: {e}")

        self.logger.debug(f"PMP 查詢完成: 處理 {total_processed} 筆記錄，找到 {len(results)} 個 PMP")
        return results

    def _get_value_results(self, request_id: int, max_rows: int = 5000) -> List[Dict]:
        """取得數值結果"""
        results = []
        total_processed = 0
        try:
            # 使用較小的批次大小避免一次取得過多資料
            batch_size = min(25, max_rows // 20) if max_rows > 500 else 25

            # 遍歷數值表格
            for (errorIndication, errorStatus, errorIndex, varBinds) in bulkCmd(
                self.snmp_engine,
                self.community,
                self.target,
                self.context,
                0, batch_size,
                ObjectType(ObjectIdentity(self.OID_PM_RESULT_VALUE_TABLE)),
                lexicographicMode=False,
                maxRows=max_rows
            ):
                if errorIndication or errorStatus:
                    if errorIndication:
                        self.logger.warning(f"Value 查詢中斷: {errorIndication}")
                    if errorStatus:
                        self.logger.warning(f"Value 查詢錯誤: {errorStatus}")
                    break

                batch_count = 0
                for varBind in varBinds:
                    oid = str(varBind[0])
                    value = varBind[1]
                    total_processed += 1
                    batch_count += 1

                    parts = oid.replace(f"{self.OID_PM_RESULT_VALUE_TABLE}.", "").split(".")
                    if len(parts) >= 4:
                        field_id = parts[0]
                        req_id = int(parts[1])
                        pmp_number = int(parts[2])
                        value_number = int(parts[3])

                        if req_id == request_id:
                            # 查找是否已有相同的記錄
                            existing_record = None
                            for record in results:
                                if (record['pmp_number'] == pmp_number and
                                    record['value_number'] == value_number):
                                    existing_record = record
                                    break

                            if existing_record is None:
                                value_record = {
                                    'request_id': req_id,
                                    'pmp_number': pmp_number,
                                    'value_number': value_number
                                }
                                results.append(value_record)
                            else:
                                value_record = existing_record

                            # 使用欄位常數來解析和儲存數值
                            if field_id == self.VALUE_FIELD_PARAM_NAME:
                                value_record['param_name'] = str(value)
                            elif field_id == self.VALUE_FIELD_PARAM_VALUE:
                                value_record['param_value'] = str(value)
                            elif field_id == self.VALUE_FIELD_UNIT:
                                value_record['unit'] = str(value)
                            elif field_id == self.VALUE_FIELD_STATUS:
                                value_record['status'] = str(value)
                            else:
                                # 保留原始欄位以供除錯
                                value_record[f"field_{field_id}"] = value

                # 記錄處理進度
                if total_processed > 0 and total_processed % 1000 == 0:
                    self.logger.debug(f"已處理 {total_processed} 筆 Value 記錄，目前找到 {len(results)} 個值")

                # 檢查是否達到記憶體限制
                if len(results) > max_rows:
                    self.logger.warning(f"Value 結果數量達到限制 ({max_rows})，停止查詢")
                    break

        except Exception as e:
            self.logger.error(f"取得數值結果時發生錯誤: {e}")

        self.logger.debug(f"Value 查詢完成: 處理 {total_processed} 筆記錄，找到 {len(results)} 個值")
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

    def cleanup_old_requests(self, max_age: int = 3600, max_failed_age: int = 1800) -> Dict[str, int]:
        """清理舊的 PM Requests"""
        current_time = time.time()
        to_delete = []
        cleanup_stats = {
            'old_requests': 0,
            'failed_requests': 0,
            'total_cleaned': 0,
            'cleanup_errors': 0
        }

        # 檢查需要清理的 requests
        for request_id, info in self.active_requests.items():
            age = current_time - info.get('created_time', current_time)
            state = info.get('state', PMRequestState.CREATED)

            # 清理條件：
            # 1. 正常完成但超過 max_age 的
            # 2. 失敗狀態且超過 max_failed_age 的
            # 3. 處於異常狀態很久的
            should_cleanup = False

            if state == PMRequestState.FINISHED and age > max_age:
                should_cleanup = True
                cleanup_stats['old_requests'] += 1
            elif state in [PMRequestState.FAILED, PMRequestState.CANCELLED] and age > max_failed_age:
                should_cleanup = True
                cleanup_stats['failed_requests'] += 1
            elif state in [PMRequestState.PENDING, PMRequestState.STARTED] and age > max_age * 2:
                # 處於執行狀態過久的，可能是異常狀況
                should_cleanup = True
                cleanup_stats['old_requests'] += 1
                self.logger.warning(f"清理長時間處於 {state} 狀態的 Request {request_id}")

            if should_cleanup:
                to_delete.append(request_id)

        # 執行清理
        for request_id in to_delete:
            try:
                if self.delete_pm_request(request_id):
                    cleanup_stats['total_cleaned'] += 1
                else:
                    cleanup_stats['cleanup_errors'] += 1
            except Exception as e:
                self.logger.error(f"清理 PM Request {request_id} 時發生錯誤: {e}")
                cleanup_stats['cleanup_errors'] += 1

        # 記錄清理結果
        if cleanup_stats['total_cleaned'] > 0:
            self.logger.info(f"PM Request 清理完成: "
                           f"成功清理 {cleanup_stats['total_cleaned']} 個 "
                           f"(舊的: {cleanup_stats['old_requests']}, "
                           f"失敗的: {cleanup_stats['failed_requests']}, "
                           f"錯誤: {cleanup_stats['cleanup_errors']})")

        return cleanup_stats