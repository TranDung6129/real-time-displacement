# updated_device_model.py
import serial
import time
import numpy as np
from typing import List, Dict, Any, Optional, Union
import logging

# Thiết lập logging
logger = logging.getLogger(__name__)

class DeviceModel:
    """Lớp lưu trữ dữ liệu của thiết bị"""
    def __init__(self):
        self.data = {}
        self.serialPort = None

    def setDeviceData(self, key: str, value: Any) -> None:
        """Lưu giá trị dữ liệu với khóa xác định"""
        self.data[key] = value

    def getDeviceData(self, key: str) -> Any:
        """Lấy giá trị dữ liệu từ khóa xác định"""
        return self.data.get(key)

class WitDataProcessor:
    """Lớp xử lý dữ liệu thô từ cảm biến WITMOTION"""
    def __init__(self):
        self.device = DeviceModel()
        self.temp_bytes = []
        self.PACK_SIZE = 11
        self.accRange = 16.0
        self.gyroRange = 2000.0
        self.angleRange = 180.0
        
        # Trạng thái kết nối
        self.is_connected = False
        self.connection_error = None

    def process_byte(self, byte_val: int) -> None:
        """
        Xử lý byte dữ liệu từ cảm biến.
        
        Args:
            byte_val: Giá trị byte cần xử lý
        """
        self.temp_bytes.append(byte_val)
        
        # Kiểm tra byte đầu tiên - phải là 0x55
        if self.temp_bytes[0] != 0x55:
            del self.temp_bytes[0]
            return
            
        # Kiểm tra byte thứ hai - phải nằm trong khoảng 0x50-0x5A
        if len(self.temp_bytes) > 1:
            if not (0x50 <= self.temp_bytes[1] <= 0x5A):
                del self.temp_bytes[0]
                return
                
        # Xử lý khi đủ một gói dữ liệu
        if len(self.temp_bytes) == self.PACK_SIZE:
            # Kiểm tra checksum
            check_sum = sum(self.temp_bytes[:-1]) & 0xFF
            if check_sum == self.temp_bytes[-1]:
                # Xử lý theo loại gói
                packet_type = self.temp_bytes[1]
                if packet_type == 0x51:
                    self._decode_acceleration(self.temp_bytes)
                elif packet_type == 0x52:
                    self._decode_gyro(self.temp_bytes)
                elif packet_type == 0x53:
                    self._decode_angle(self.temp_bytes)
            else:
                logger.warning(f"Checksum error: expected {check_sum}, got {self.temp_bytes[-1]}")
                
            # Xóa buffer để chuẩn bị cho gói tiếp theo
            self.temp_bytes = []

    def _decode_data(self, data: List[int], data_type: str) -> None:
        """
        Giải mã dữ liệu cảm biến theo loại.
        
        Args:
            data: Mảng bytes dữ liệu
            data_type: Loại dữ liệu ("acc", "gyro", "angle")
        """
        # Lấy phạm vi dữ liệu tương ứng
        data_range = {
            "acc": self.accRange,
            "gyro": self.gyroRange,
            "angle": self.angleRange
        }.get(data_type)
        
        if not data_range:
            logger.error(f"Không hỗ trợ loại dữ liệu: {data_type}")
            return
            
        # Giải mã giá trị cho 3 trục
        values = []
        for i in range(3):
            idx = i * 2
            val = (data[idx + 3] << 8 | data[idx + 2]) / 32768.0 * data_range
            if val >= data_range:
                val -= 2 * data_range
            values.append(round(val, 4))
                      
        # Lưu giá trị vào device model
        prefixes = {"acc": "acc", "gyro": "gyro", "angle": "angle"}
        prefix = prefixes[data_type]
        
        self.device.setDeviceData(f"{prefix}X", values[0])
        self.device.setDeviceData(f"{prefix}Y", values[1])
        self.device.setDeviceData(f"{prefix}Z", values[2])
        
        # Ghi log level debug
        logger.debug(f"{data_type.upper()}: X={values[0]}, Y={values[1]}, Z={values[2]}")

    def _decode_acceleration(self, data: List[int]) -> None:
        """
        Giải mã dữ liệu gia tốc.
        
        Args:
            data: Mảng bytes dữ liệu
        """
        self._decode_data(data, "acc")

    def _decode_gyro(self, data: List[int]) -> None:
        """
        Giải mã dữ liệu gyro.
        
        Args:
            data: Mảng bytes dữ liệu
        """
        self._decode_data(data, "gyro")

    def _decode_angle(self, data: List[int]) -> None:
        """
        Giải mã dữ liệu góc.
        
        Args:
            data: Mảng bytes dữ liệu
        """
        self._decode_data(data, "angle") 
        
    def read_from_serial(self, port: str, baudrate: int = 115200) -> None:
        """
        Đọc dữ liệu từ cổng serial.
        
        Args:
            port: Cổng serial (ví dụ: COM3, /dev/ttyUSB0)
            baudrate: Tốc độ baud (mặc định: 115200)
        """
        try:
            # Mở kết nối serial
            self.device.serialPort = serial.Serial(port, baudrate, timeout=1)
            logger.info(f"Kết nối thành công đến {port} với baudrate {baudrate}")
            print(f"Connected to {port} at baudrate {baudrate}")
            
            # Đặt trạng thái kết nối
            self.is_connected = True
            self.connection_error = None
            
            # Cấu hình tốc độ đọc dữ liệu
            self.configure_data_rate(b'\x0B')  # 200 Hz
            
            # Vòng lặp đọc dữ liệu liên tục
            while True:
                if self.device.serialPort.in_waiting > 0:
                    data = self.device.serialPort.read(self.device.serialPort.in_waiting)
                    for byte in data:
                        self.process_byte(byte)
                time.sleep(0.01)  # 100 Hz
                
        except serial.SerialException as e:
            # Ghi log lỗi kết nối
            error_msg = f"Lỗi kết nối serial: {e}"
            logger.error(error_msg)
            print(f"Serial error: {e}")
            
            # Cập nhật trạng thái
            self.is_connected = False
            self.connection_error = str(e)
            
        except Exception as e:
            # Ghi log lỗi khác
            error_msg = f"Lỗi không xác định: {e}"
            logger.error(error_msg)
            print(f"Unknown error: {e}")
            
            # Cập nhật trạng thái
            self.is_connected = False
            self.connection_error = str(e)
            
        finally:
            # Đóng cổng serial nếu đang mở
            if self.device.serialPort and self.device.serialPort.is_open:
                self.device.serialPort.close()
                logger.info("Đã đóng kết nối serial")
                
            # Cập nhật trạng thái kết nối
            self.is_connected = False

    def configure_data_rate(self, data_rate: bytes) -> bool:
        """
        Cấu hình tốc độ đọc dữ liệu cho cảm biến.
        
        Args:
            data_rate: Mã byte tốc độ dữ liệu
            
        Returns:
            bool: True nếu thành công, False nếu thất bại
        """
        if not (self.device.serialPort and self.device.serialPort.is_open):
            logger.error("Không thể cấu hình: cổng serial chưa được mở")
            return False
            
        try:
            # Tạo lệnh cấu hình
            command = b'\xFF\xAA\x03' + data_rate
            # Thêm checksum
            checksum = sum(command) & 0xFF
            command += bytes([checksum])
            
            # Gửi lệnh
            self.device.serialPort.write(command)
            
            # Log tốc độ đã cấu hình
            rate_map = {
                b'\x00': 0.1, b'\x01': 1, b'\x02': 5, b'\x05': 10,
                b'\x0A': 20, b'\x14': 50, b'\x19': 100, b'\x0B': 200
            }
            rate_value = rate_map.get(data_rate, "unknown")
            logger.info(f"Đã cấu hình tốc độ dữ liệu: {rate_value} Hz")
            print(f"Data rate set to {rate_value} Hz")
            
            # Chờ một chút để cảm biến xử lý lệnh
            time.sleep(0.1)
            return True
            
        except Exception as e:
            logger.error(f"Lỗi khi cấu hình tốc độ dữ liệu: {e}")
            return False

class MockDataProcessor:
    """
    Bộ xử lý dữ liệu giả lập để phát triển và kiểm thử khi không có cảm biến thực.
    """
    def __init__(self):
        self.device = DeviceModel()
        self.time = 0
        self.update_interval = 0.01  # 100Hz
        
        # Tần số các thành phần mô phỏng
        self.freqs = {
            'acc': {'X': 2.0, 'Y': 3.0, 'Z': 5.0},
            'gyro': {'X': 1.0, 'Y': 1.5, 'Z': 0.7},
            'angle': {'X': 0.5, 'Y': 0.3, 'Z': 0.2}
        }
        
        # Biên độ các thành phần
        self.amplitudes = {
            'acc': {'X': 1.0, 'Y': 0.8, 'Z': 1.2},
            'gyro': {'X': 20.0, 'Y': 15.0, 'Z': 10.0},
            'angle': {'X': 5.0, 'Y': 10.0, 'Z': 15.0}
        }
        
        # Nhiễu
        self.noise_level = 0.05
        
        # Trạng thái kết nối
        self.is_connected = True
        self.connection_error = None
        
        logger.info("Khởi tạo bộ xử lý dữ liệu giả lập")
    
    def generate_data(self):
        """Tạo dữ liệu mô phỏng với sóng sin và nhiễu"""
        for sensor_type in ['acc', 'gyro', 'angle']:
            for axis in ['X', 'Y', 'Z']:
                # Tính thành phần hình sin
                freq = self.freqs[sensor_type][axis]
                amp = self.amplitudes[sensor_type][axis]
                value = amp * np.sin(2 * np.pi * freq * self.time)
                
                # Thêm nhiễu ngẫu nhiên
                noise = self.noise_level * amp * (np.random.random() - 0.5)
                value += noise
                
                # Lưu giá trị
                key = f"{sensor_type}{axis}"
                self.device.setDeviceData(key, value)
        
        # Tăng thời gian
        self.time += self.update_interval
    
    def read_from_serial(self, port: str, baudrate: int = 115200) -> None:
        """
        Giả lập đọc từ serial bằng cách tạo dữ liệu định kỳ.
        
        Args:
            port: Cổng serial (không sử dụng)
            baudrate: Tốc độ baud (không sử dụng)
        """
        try:
            logger.info(f"Sử dụng dữ liệu giả lập (bỏ qua port {port} và baudrate {baudrate})")
            print(f"Using mock data (ignoring port {port} and baudrate {baudrate})")
            
            # Giả lập kết nối
            self.is_connected = True
            self.connection_error = None
            
            # Tạo dữ liệu liên tục
            while True:
                self.generate_data()
                time.sleep(self.update_interval)
                
        except KeyboardInterrupt:
            logger.info("Dừng tạo dữ liệu giả lập")
            print("Mock data generation stopped")
            
        except Exception as e:
            logger.error(f"Lỗi khi tạo dữ liệu giả lập: {e}")
            print(f"Error: {e}")
            
            # Cập nhật trạng thái
            self.is_connected = False
            self.connection_error = str(e)
        
        finally:
            # Cập nhật trạng thái kết nối
            self.is_connected = False
    
    def configure_data_rate(self, data_rate: bytes) -> bool:
        """
        Giả lập cấu hình tốc độ đọc dữ liệu.
        
        Args:
            data_rate: Mã byte tốc độ dữ liệu (không sử dụng)
            
        Returns:
            bool: Luôn trả về True
        """
        # Ánh xạ giá trị data_rate sang tốc độ Hz
        rate_map = {
            b'\x00': 0.1, b'\x01': 1, b'\x02': 5, b'\x05': 10,
            b'\x0A': 20, b'\x14': 50, b'\x19': 100
        }
        
        # Cập nhật update_interval nếu tốc độ hợp lệ
        if data_rate in rate_map:
            rate_hz = rate_map[data_rate]
            self.update_interval = 1.0 / rate_hz
            logger.info(f"Đã cấu hình bộ giả lập với tốc độ: {rate_hz} Hz")
            
        return True