import time
import serial
import logging
from PyQt6.QtCore import QObject, pyqtSignal
from sensor.device_model import WitDataProcessor, MockDataProcessor

logger = logging.getLogger(__name__)

class SensorWorker(QObject):
    newData = pyqtSignal(dict)
    connectionStatus = pyqtSignal(bool, str)
    stopped = pyqtSignal()

    def __init__(self, port, baudrate, use_mock_data=False):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.use_mock_data = use_mock_data
        self._running = True
        self.sensor_processor = None

    def run(self):
        logger.info(f"SensorWorker bắt đầu chạy với mock_data={self.use_mock_data}")
        if self.use_mock_data:
            self.sensor_processor = MockDataProcessor()
            self.sensor_processor.is_connected = True
            self.sensor_processor.connection_error = None
            self.connectionStatus.emit(True, "Sử dụng dữ liệu giả lập")
        else:
            self.sensor_processor = WitDataProcessor()
            try:
                self.sensor_processor.device.serialPort = serial.Serial(self.port, self.baudrate, timeout=0.1)
                logger.info(f"Kết nối thành công đến {self.port} với baudrate {self.baudrate}")
                self.sensor_processor.is_connected = True
                self.sensor_processor.connection_error = None
                if not self.sensor_processor.configure_data_rate(b'\x0B'):
                    logger.warning("Không thể cấu hình data rate cho cảm biến.")
                self.connectionStatus.emit(True, f"Đã kết nối {self.port}")

            except serial.SerialException as e:
                error_msg = f"Lỗi kết nối serial: {e}"
                logger.error(error_msg)
                self.sensor_processor.is_connected = False
                self.sensor_processor.connection_error = str(e)
                self.connectionStatus.emit(False, error_msg)
                self.stop()
                return
            except Exception as e:
                error_msg = f"Lỗi không xác định khi khởi tạo SensorWorker: {e}"
                logger.error(error_msg, exc_info=True)
                self.sensor_processor.is_connected = False
                self.sensor_processor.connection_error = str(e)
                self.connectionStatus.emit(False, error_msg)
                self.stop()
                return

        expected_dt = self.sensor_processor.update_interval if self.use_mock_data else 0.005
        last_time_reading = time.perf_counter()

        while self._running:
            if self.use_mock_data:
                self.sensor_processor.generate_data()
                current_data = self.sensor_processor.device.data.copy()
                if current_data:
                    self.newData.emit(current_data)
                time.sleep(self.sensor_processor.update_interval)
            else:
                if self.sensor_processor.device.serialPort and self.sensor_processor.device.serialPort.is_open:
                    try:
                        if self.sensor_processor.device.serialPort.in_waiting > 0:
                            data_bytes = self.sensor_processor.device.serialPort.read(
                                self.sensor_processor.device.serialPort.in_waiting)
                            for byte_val in data_bytes:
                                self.sensor_processor.process_byte(byte_val)

                            current_data = self.sensor_processor.device.data.copy()
                            if "accX" in current_data:
                                if not hasattr(self.sensor_processor, '_last_emit_data') or \
                                   self.sensor_processor._last_emit_data != current_data:
                                    self.newData.emit(current_data)
                                    self.sensor_processor._last_emit_data = current_data.copy()

                        processing_time = time.perf_counter() - last_time_reading
                        sleep_time = expected_dt - processing_time
                        if sleep_time > 0:
                            time.sleep(sleep_time)
                        last_time_reading = time.perf_counter()

                    except serial.SerialException as e:
                        logger.error(f"Lỗi serial trong vòng lặp: {e}")
                        self.connectionStatus.emit(False, f"Lỗi serial: {e}")
                        self.stop()
                        break
                    except Exception as e:
                        logger.error(f"Lỗi không xác định trong vòng lặp SensorWorker: {e}", exc_info=True)
                else:
                    if self._running:
                        self.connectionStatus.emit(False, "Mất kết nối serial hoặc cổng không mở.")
                    self.stop()
                    break

            if not self._running:
                break

        if not self.use_mock_data and self.sensor_processor and \
           self.sensor_processor.device.serialPort and self.sensor_processor.device.serialPort.is_open:
            self.sensor_processor.device.serialPort.close()
            logger.info("Đã đóng cổng serial trong SensorWorker.")

        self.stopped.emit()
        logger.info("SensorWorker đã dừng.")

    def stop(self):
        self._running = False
        logger.info("Yêu cầu dừng SensorWorker.") 