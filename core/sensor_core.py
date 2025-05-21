# core/sensor_core.py
import logging
import time
import serial # Cần import pyserial
from PyQt6.QtCore import QObject, pyqtSignal, QThread, QTimer
# Import WitDataProcessor và MockDataProcessor từ project của bạn
from sensor.device_model import WitDataProcessor, MockDataProcessor # Đường dẫn này có thể cần điều chỉnh

logger = logging.getLogger(__name__)

class SensorInstance(QObject):
    """
    Đại diện cho một cảm biến cụ thể, quản lý kết nối và luồng dữ liệu của nó.
    """
    # Thêm sensor_id vào các signal để SensorManager có thể phân biệt
    newData = pyqtSignal(str, dict) # sensor_id, data_dict
    connectionStatus = pyqtSignal(str, bool, str) # sensor_id, connected, message
    stopped = pyqtSignal(str) # sensor_id

    def __init__(self, sensor_id, config, parent=None):
        super().__init__(parent)
        self.sensor_id = sensor_id
        self.config = config # name, type, protocol, port, baudrate, address, etc.
        self._is_connected = False
        self._running = False
        self.thread = None
        self.worker = None # Sẽ là một worker tương tự SensorWorker hiện tại
        self.last_data = {}

    def get_sensor_info(self):
        return {
            'id': self.sensor_id,
            'config': self.config,
            'connected': self._is_connected,
            'type': self.config.get('type', 'N/A')
        }

    @property
    def connected(self):
        return self._is_connected

    def connect_sensor(self):
        if self._running:
            logger.warning(f"Sensor {self.sensor_id} is already running or trying to connect.")
            return

        logger.info(f"Attempting to connect sensor {self.sensor_id} with config: {self.config}")
        self._running = True
        
        # Tạo worker dựa trên protocol và type
        # Đây là phần tương tự như SensorWorker hiện tại của bạn
        # nhưng được khởi tạo với cấu hình của instance này
        protocol = self.config.get("protocol")
        sensor_type = self.config.get("type") # ví dụ: "wit_motion_imu", "mock_sensor"

        # Sử dụng cấu trúc tương tự SensorWorker hiện tại
        # Chuyển port, baudrate, use_mock_data từ self.config
        _port = self.config.get('port', '') # Giả sử key 'port' cho UART
        _baudrate = self.config.get('baudrate', 115200)
        _use_mock = (protocol == "Mock")
        
        # TODO: Mở rộng để hỗ trợ các giao thức khác như TCP/IP, UDP từ config
        # if protocol == "TCP/IP":
        #    host, port_num = self.config.get('address', (None, None))
        #    self.worker = TCPSensorWorker(self.sensor_id, host, port_num, ...)
        # else: # Mặc định UART / Mock
        
        # Tạo worker mới (tương tự SensorWorker của bạn)
        # Bạn cần một lớp worker chung hoặc các lớp worker riêng cho từng loại giao thức
        # Dưới đây là ví dụ đơn giản hóa, bạn cần điều chỉnh cho phù hợp
        self.worker = GenericSensorWorker(self.sensor_id, self.config)
        self.thread = QThread()
        self.worker.moveToThread(self.thread)

        self.worker.newData.connect(self._on_worker_new_data)
        self.worker.connectionStatus.connect(self._on_worker_connection_status)
        self.worker.stopped.connect(self._on_worker_stopped)

        self.thread.started.connect(self.worker.run)
        self.thread.finished.connect(self.thread.deleteLater) # Dọn dẹp thread
        self.worker.finished_signal.connect(self.thread.quit) # Worker nên có tín hiệu này

        logger.info(f"Starting thread for sensor {self.sensor_id}...")
        self.thread.start()

    def _on_worker_new_data(self, data_dict): # Worker sẽ không gửi sensor_id nữa
        self.last_data = data_dict
        self.newData.emit(self.sensor_id, data_dict)


    def _on_worker_connection_status(self, connected_status, message_text): # Worker sẽ không gửi sensor_id
        self._is_connected = connected_status
        # Nếu kết nối thất bại ngay từ đầu, worker có thể tự dừng
        if not self._is_connected and not self.worker._running_flag_from_manager: # Giả sử worker có cờ này
             self._running = False # Đặt lại cờ của SensorInstance
        self.connectionStatus.emit(self.sensor_id, self._is_connected, message_text)


    def _on_worker_stopped(self): # Worker sẽ không gửi sensor_id
        logger.info(f"Worker for sensor {self.sensor_id} has stopped.")
        self._is_connected = False # Đảm bảo trạng thái là ngắt kết nối
        self._running = False # Đặt lại cờ của SensorInstance

        if self.thread and self.thread.isRunning():
            self.thread.quit()
            if not self.thread.wait(1000): # Chờ thread dừng
                logger.warning(f"Thread for {self.sensor_id} did not quit gracefully, terminating.")
                self.thread.terminate()
                self.thread.wait() # Chờ sau khi terminate

        self.worker = None # Giải phóng worker
        self.thread = None # Giải phóng thread
        self.stopped.emit(self.sensor_id) # Thông báo rằng instance này đã dừng hẳn


    def disconnect_sensor(self):
        logger.info(f"Requesting to disconnect sensor {self.sensor_id}")
        if self.worker and self._running:
            self.worker.stop() # Yêu cầu worker dừng
        else:
            # Nếu không có worker hoặc không đang chạy, coi như đã dừng
            self._running = False
            self._is_connected = False
            self.stopped.emit(self.sensor_id)


    def cleanup(self): # Được gọi bởi SensorManager trước khi xóa instance
        self.disconnect_sensor()
        # Đảm bảo các signal được ngắt kết nối nếu cần, mặc dù QObject tự làm điều này khi delete


class GenericSensorWorker(QObject): # Đây là phiên bản rút gọn của SensorWorker.py
    newData = pyqtSignal(dict)
    connectionStatus = pyqtSignal(bool, str)
    stopped = pyqtSignal()
    finished_signal = pyqtSignal() # Thêm tín hiệu này để báo cho thread biết khi nào nên quit

    def __init__(self, sensor_id, config):
        super().__init__()
        self.sensor_id = sensor_id
        self.config = config
        self._running_flag_from_manager = True # Ban đầu cho phép chạy
        self.sensor_processor_internal = None # WITDataProcessor hoặc MockDataProcessor
        self.serial_port_instance = None # Để lưu trữ instance của serial.Serial

    def run(self):
        logger.info(f"SensorWorker {self.sensor_id} starting with config: {self.config}")
        protocol = self.config.get("protocol")
        sensor_type = self.config.get("type")

        if protocol == "Mock":
            self.sensor_processor_internal = MockDataProcessor()
            # Giả lập kết nối thành công cho Mock
            time.sleep(0.1) # Giả lập độ trễ kết nối
            is_connected_mock = True # Hoặc có thể giả lập lỗi kết nối
            if is_connected_mock:
                self.connectionStatus.emit(True, f"Mock Sensor {self.sensor_id} Connected")
                logger.info(f"Mock sensor {self.sensor_id} connected.")
            else:
                self.connectionStatus.emit(False, f"Mock Sensor {self.sensor_id} Connection Failed")
                logger.error(f"Mock sensor {self.sensor_id} failed to connect.")
                self._running_flag_from_manager = False # Dừng nếu không kết nối được


        elif protocol == "UART" and sensor_type == "wit_motion_imu":
            self.sensor_processor_internal = WitDataProcessor()
            port_name = self.config.get('port')
            baud = self.config.get('baudrate')
            try:
                self.serial_port_instance = serial.Serial(port_name, baud, timeout=0.1)
                self.sensor_processor_internal.device.serialPort = self.serial_port_instance
                logger.info(f"Successfully connected to {port_name} for sensor {self.sensor_id}")
                self.sensor_processor_internal.is_connected = True
                
                # Cấu hình data rate cho WITMOTION nếu có
                data_rate_hex = self.config.get('wit_data_rate_byte_hex')
                if data_rate_hex:
                    data_rate_bytes = bytes.fromhex(data_rate_hex.replace("0x", ""))
                    if not self.sensor_processor_internal.configure_data_rate(data_rate_bytes):
                        logger.warning(f"Failed to configure data rate for {self.sensor_id}.")
                
                self.connectionStatus.emit(True, f"Connected to {port_name} ({self.sensor_id})")

            except serial.SerialException as e:
                error_msg = f"Serial connection error for {self.sensor_id} on {port_name}: {e}"
                logger.error(error_msg)
                self.sensor_processor_internal.is_connected = False
                self.connectionStatus.emit(False, error_msg)
                self._running_flag_from_manager = False # Dừng nếu không kết nối được
            except Exception as e:
                error_msg = f"Unknown error initializing {self.sensor_id}: {e}"
                logger.error(error_msg, exc_info=True)
                self.sensor_processor_internal.is_connected = False # Giả sử
                self.connectionStatus.emit(False, error_msg)
                self._running_flag_from_manager = False
        else:
            logger.error(f"Unsupported protocol '{protocol}' or sensor type '{sensor_type}' for {self.sensor_id}")
            self.connectionStatus.emit(False, f"Unsupported protocol/type for {self.sensor_id}")
            self._running_flag_from_manager = False


        # Vòng lặp đọc dữ liệu (tương tự SensorWorker cũ)
        expected_dt = 0.005 # Mặc định, cần điều chỉnh theo data rate của cảm biến
        if protocol == "Mock" and self.sensor_processor_internal:
            expected_dt = self.sensor_processor_internal.update_interval
        elif sensor_type == "wit_motion_imu" and self.config.get('wit_data_rate_byte_hex'):
            # Ước lượng dt từ data_rate_hex (cần logic mapping chính xác hơn)
            # Ví dụ 0x0B (200Hz) -> 0.005s; 0x19 (100Hz) -> 0.01s
            rate_map_to_dt = {
                "0b": 0.005, "19": 0.01, "14": 0.02, "0a": 0.05, "05": 0.1 # Hex strings
            }
            hex_val = self.config.get('wit_data_rate_byte_hex', "0b").lower().replace("0x","")
            expected_dt = rate_map_to_dt.get(hex_val, 0.01)


        last_time_reading = time.perf_counter()

        while self._running_flag_from_manager:
            if protocol == "Mock" and self.sensor_processor_internal:
                self.sensor_processor_internal.generate_data()
                current_data = self.sensor_processor_internal.device.data.copy()
                if current_data:
                    self.newData.emit(current_data)
                time.sleep(self.sensor_processor_internal.update_interval)

            elif protocol == "UART" and self.sensor_processor_internal and self.sensor_processor_internal.is_connected:
                if self.serial_port_instance and self.serial_port_instance.is_open:
                    try:
                        if self.serial_port_instance.in_waiting > 0:
                            data_bytes = self.serial_port_instance.read(self.serial_port_instance.in_waiting)
                            for byte_val in data_bytes:
                                self.sensor_processor_internal.process_byte(byte_val)
                            
                            current_data = self.sensor_processor_internal.device.data.copy()
                            if "accX" in current_data: # Hoặc một key bất kỳ để xác nhận có dữ liệu mới
                                # Tránh emit dữ liệu giống hệt nhau liên tục nếu cảm biến không thay đổi
                                if not hasattr(self, '_last_emitted_sensor_data') or \
                                   self._last_emitted_sensor_data != current_data:
                                    self.newData.emit(current_data)
                                    self._last_emitted_sensor_data = current_data.copy()
                        
                        processing_time = time.perf_counter() - last_time_reading
                        sleep_time = expected_dt - processing_time
                        if sleep_time > 0:
                            time.sleep(sleep_time)
                        last_time_reading = time.perf_counter()

                    except serial.SerialException as e:
                        logger.error(f"Serial error in loop for {self.sensor_id}: {e}")
                        self.connectionStatus.emit(False, f"Serial error ({self.sensor_id}): {e}")
                        self._running_flag_from_manager = False # Dừng worker
                        break 
                    except Exception as e:
                        logger.error(f"Unknown error in loop for {self.sensor_id}: {e}", exc_info=True)
                        # Có thể không dừng worker nếu lỗi không nghiêm trọng, tùy bạn quyết định
                else: # Cổng serial không mở hoặc không tồn tại
                    if self._running_flag_from_manager: # Chỉ emit nếu vẫn đang được yêu cầu chạy
                        self.connectionStatus.emit(False, f"Serial port not open for {self.sensor_id}.")
                    self._running_flag_from_manager = False # Dừng worker
                    break
            
            else: # Protocol không được hỗ trợ hoặc processor không tồn tại
                if not self.sensor_processor_internal or (hasattr(self.sensor_processor_internal, 'is_connected') and not self.sensor_processor_internal.is_connected):
                    # Nếu không có processor hoặc processor báo mất kết nối (trường hợp không phải serial exception)
                    if self._running_flag_from_manager:
                         self.connectionStatus.emit(False, f"Sensor {self.sensor_id} disconnected or processor error.")
                    self._running_flag_from_manager = False # Dừng worker
                    break
                time.sleep(0.1) # Ngủ nhẹ nếu không làm gì

            if not self._running_flag_from_manager: # Kiểm tra lại cờ sau mỗi vòng lặp
                break
        
        # Dọn dẹp khi worker dừng
        if protocol == "UART" and self.serial_port_instance and self.serial_port_instance.is_open:
            self.serial_port_instance.close()
            logger.info(f"Closed serial port for sensor {self.sensor_id}.")

        self.stopped.emit()
        self.finished_signal.emit() # Báo cho thread biết là đã xong
        logger.info(f"SensorWorker {self.sensor_id} has finished.")

    def stop(self):
        self._running_flag_from_manager = False
        logger.info(f"Stop requested for SensorWorker {self.sensor_id}")


class SensorManager(QObject):
    """
    Quản lý nhiều SensorInstance.
    """
    # Tín hiệu báo cho UI biết về trạng thái của một sensor cụ thể
    sensorConnectionStatusChanged = pyqtSignal(str, bool, str) # sensor_id, connected, message
    sensorDataReceived = pyqtSignal(str, dict) # sensor_id, data_dict
    sensorListChanged = pyqtSignal() # Báo cho UI cập nhật bảng khi có sensor thêm/xóa

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sensors = {} # dict_of_sensor_id: SensorInstance

    def get_available_sensor_types(self):
        # Sau này có thể load từ plugin hoặc config file
        return ["wit_motion_imu", "mock_sensor", "accelerometer", "temperature"]

    def get_all_sensor_ids(self):
        return list(self._sensors.keys())

    def get_sensor_info(self, sensor_id):
        instance = self._sensors.get(sensor_id)
        return instance.get_sensor_info() if instance else None

    def get_sensor_instance(self, sensor_id): # Cần cho SensorDetailDialog
        return self._sensors.get(sensor_id)

    def get_connected_sensors_count(self):
        return sum(1 for s_id in self._sensors if self._sensors[s_id].connected)


    def add_sensor(self, sensor_id, sensor_type, config):
        if sensor_id in self._sensors:
            logger.warning(f"Sensor ID {sensor_id} already exists. Cannot add.")
            # Không emit connection status ở đây vì UI sẽ kiểm tra trước
            return False

        logger.info(f"SensorManager: Adding sensor {sensor_id} of type {sensor_type} with config: {config}")
        instance = SensorInstance(sensor_id, config)
        instance.newData.connect(self.sensorDataReceived) # Chuyển tiếp tín hiệu
        instance.connectionStatus.connect(self.sensorConnectionStatusChanged) # Chuyển tiếp
        instance.stopped.connect(lambda sid: self._handle_sensor_stopped(sid)) # Xử lý khi sensor dừng hẳn

        self._sensors[sensor_id] = instance
        instance.connect_sensor() # Yêu cầu instance tự kết nối
        
        self.sensorListChanged.emit() # Báo UI cập nhật
        # Trạng thái kết nối sẽ được cập nhật thông qua signal connectionStatus của instance
        return True


    def _handle_sensor_stopped(self, sensor_id):
        logger.info(f"SensorManager: Confirmed sensor {sensor_id} has stopped.")
        # Có thể cần cập nhật trạng thái một lần cuối nếu worker dừng mà không phải do disconnect_sensor
        instance = self._sensors.get(sensor_id)
        if instance and instance.connected: # Nếu nó vẫn báo connected thì cập nhật lại
            self.sensorConnectionStatusChanged.emit(sensor_id, False, "Worker stopped unexpectedly")
        # Không xóa instance ở đây, việc xóa sẽ do remove_sensor xử lý
        # Nếu instance tự dừng (ví dụ do lỗi), nó sẽ phát connectionStatus(False)


    def connect_sensor_by_id(self, sensor_id):
        instance = self._sensors.get(sensor_id)
        if instance:
            if not instance.connected and not instance._running: # Chỉ kết nối nếu chưa kết nối và chưa chạy
                logger.info(f"SensorManager: Requesting connect for sensor {sensor_id}")
                instance.connect_sensor()
            elif instance.connected:
                 logger.info(f"SensorManager: Sensor {sensor_id} is already connected.")
            elif instance._running:
                 logger.info(f"SensorManager: Sensor {sensor_id} is already in the process of connecting/running.")

        else:
            logger.warning(f"SensorManager: Cannot connect. Sensor ID {sensor_id} not found.")

    def disconnect_sensor_by_id(self, sensor_id):
        instance = self._sensors.get(sensor_id)
        if instance:
            logger.info(f"SensorManager: Requesting disconnect for sensor {sensor_id}")
            instance.disconnect_sensor()
            # Trạng thái sẽ được cập nhật qua signal connectionStatus khi worker thực sự dừng
        else:
            logger.warning(f"SensorManager: Cannot disconnect. Sensor ID {sensor_id} not found.")


    def remove_sensor(self, sensor_id):
        instance = self._sensors.pop(sensor_id, None)
        if instance:
            logger.info(f"SensorManager: Removing sensor {sensor_id}.")
            instance.cleanup() # Đảm bảo worker dừng và tài nguyên được giải phóng
            # Ngắt kết nối các signal của instance này để tránh lỗi sau khi nó bị xóa
            try:
                instance.newData.disconnect(self.sensorDataReceived)
                instance.connectionStatus.disconnect(self.sensorConnectionStatusChanged)
                instance.stopped.disconnect(self._handle_sensor_stopped)
            except TypeError: # Lỗi nếu signal chưa bao giờ được kết nối hoặc đã ngắt
                pass
            instance.deleteLater() # Hẹn xóa đối tượng QObject
            self.sensorListChanged.emit() # Báo UI cập nhật
            # Có thể emit một tín hiệu trạng thái đặc biệt "removed" nếu cần
            self.sensorConnectionStatusChanged.emit(sensor_id, False, "Sensor removed")
            return True
        logger.warning(f"SensorManager: Cannot remove. Sensor ID {sensor_id} not found.")
        return False

    def stop_all_sensors(self):
        logger.info("SensorManager: Stopping all sensors...")
        for sensor_id in list(self._sensors.keys()): # Dùng list key để tránh lỗi khi dict thay đổi
            self.disconnect_sensor_by_id(sensor_id)
        # Chờ các sensor dừng hẳn (có thể cần cơ chế phức tạp hơn nếu cần đồng bộ chặt chẽ)
        # time.sleep(1) # Chờ một chút cho các worker dừng