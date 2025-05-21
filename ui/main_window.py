import logging
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QTabWidget, QMessageBox
from PyQt6.QtCore import QThread, pyqtSignal

from core.data_processor import DataProcessor
from core.plot_manager import PlotManager
from ui.display_screen import DisplayScreenWidget
from ui.sensor_management_screen import SensorManagementScreen
from ui.settings_screen import SettingsScreenWidget
from ui.advanced_analysis_screen import AdvancedAnalysisScreenWidget
from ui.data_hub_screen import DataHubScreenWidget
from core.sensor_core import SensorManager

logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    # main_status_updated = pyqtSignal(str, str) # message, color

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ứng dụng Theo dõi Cảm biến Đa Tab - Multi Sensor")
        self.setGeometry(100, 100, 1700, 950) # Tăng kích thước một chút

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        # Khởi tạo các thành phần quản lý và xử lý dữ liệu
        self.sensor_manager = SensorManager(self) # Khởi tạo SensorManager
        self.data_processor = DataProcessor(self) # Khởi tạo DataProcessor

        # Khởi tạo UI components
        self.tabs = QTabWidget()
        self.display_screen = DisplayScreenWidget() # Vẫn giữ nguyên DisplayScreen ban đầu
        
        # Sử dụng SensorManagementScreen mới
        self.sensor_screen_new = SensorManagementScreen(self)
        self.sensor_screen_new.set_managers(self.sensor_manager, self.data_processor) # Truyền manager vào
        self.settings_screen = SettingsScreenWidget()
        # Truyền data_processor vào AdvancedAnalysisScreenWidget
        self.advanced_analysis_screen = AdvancedAnalysisScreenWidget(self.data_processor, self)
        self.data_hub_screen = DataHubScreenWidget(self)
        self.data_hub_screen.set_managers(self.sensor_manager, self.data_processor)
        # PlotManager cần biết về data_processor và display_screen
        # Hiện tại PlotManager chỉ vẽ cho một sensor, cần nâng cấp sau
        self.plot_manager = PlotManager(self.display_screen, self.data_processor)
        # TODO: PlotManager cần được cập nhật để có thể chọn sensor_id để vẽ

        self.tabs.addTab(self.display_screen, "Hiển thị Đồ thị (Sensor Mặc định)")
        self.tabs.addTab(self.sensor_screen_new, "Quản lý Cảm biến") # Tab mới
        self.tabs.addTab(self.settings_screen, "Thiết lập")
        self.tabs.addTab(self.advanced_analysis_screen, "Phân tích Chuyên sâu")
        self.tabs.addTab(self.data_hub_screen, "Data Hub")

        self.layout.addWidget(self.tabs)

        # Biến tạm để lưu sensor_id đang được hiển thị trên display_screen
        self.current_plotting_sensor_id = None 

        # Kết nối tín hiệu từ SensorManager và các màn hình
        self._connect_signals()

        # Khởi tạo tốc độ hiển thị ban đầu
        # self.plot_manager.start_plotting(self.settings_screen.get_current_display_rate())
        # Việc start_plotting sẽ phụ thuộc vào việc có sensor nào được chọn để vẽ không

    def _connect_signals(self):
        # Từ SensorManager -> DataProcessor và MainWindow/UI
        self.sensor_manager.sensorDataReceived.connect(self.handle_sensor_data_from_manager)
        self.sensor_manager.sensorConnectionStatusChanged.connect(self.handle_sensor_connection_status_from_manager)
        self.sensor_manager.sensorListChanged.connect(self.sensor_screen_new.update_sensors_table)
        self.sensor_manager.sensorListChanged.connect(self.data_hub_screen.update_sensor_selection_combo)

        # Từ SensorManagementScreen (UI) -> SensorManager (thông qua MainWindow)
        self.sensor_screen_new.add_sensor_requested.connect(self.handle_add_sensor_request)
        self.sensor_screen_new.remove_sensor_requested.connect(self.handle_remove_sensor_request)
        self.sensor_screen_new.connect_sensor_requested.connect(self.sensor_manager.connect_sensor_by_id)
        self.sensor_screen_new.disconnect_sensor_requested.connect(self.sensor_manager.disconnect_sensor_by_id)
        
        # Khi một sensor được chọn trong bảng của SensorManagementScreen
        self.sensor_screen_new.sensor_selected.connect(self.handle_sensor_selected_for_plotting)


        # Từ SettingsScreen -> PlotManager (hoặc thông qua MainWindow)
        self.settings_screen.display_rate_changed.connect(self.handle_display_rate_change)


    def handle_add_sensor_request(self, sensor_id, sensor_type, config):
        logger.info(f"MainWindow: Received request to add sensor: {sensor_id}, type: {sensor_type}")
        success = self.sensor_manager.add_sensor(sensor_id, sensor_type, config)
        if success:
            QMessageBox.information(self, "Thành công", f"Đã yêu cầu thêm cảm biến '{config.get('name', sensor_id)}'. Theo dõi trạng thái trong bảng.")
            # Nếu là sensor đầu tiên và chưa có sensor nào được vẽ, chọn nó để vẽ
            if self.current_plotting_sensor_id is None:
                 self.handle_sensor_selected_for_plotting(sensor_id)

            # DataProcessor cần biết về sensor mới này để chuẩn bị cấu trúc
            # (dt và sample_frame_size cần được truyền đúng)
            # Ví dụ lấy dt từ config nếu là WIT, hoặc mặc định
            dt_for_dp = 0.005
            sample_frame_for_dp = 20
            if sensor_type == "wit_motion_imu":
                hex_val = config.get('wit_data_rate_byte_hex', "0b").lower().replace("0x","")
                rate_map_to_dt = {"0b": 0.005, "19": 0.01, "14": 0.02, "0a": 0.05, "05": 0.1}
                dt_for_dp = rate_map_to_dt.get(hex_val, 0.01)
            
            self.data_processor._ensure_sensor_id_structure(sensor_id, sensor_type, dt_for_dp, sample_frame_for_dp)

        else:
            QMessageBox.warning(self, "Lỗi", f"Cảm biến ID '{sensor_id}' có thể đã tồn tại hoặc có lỗi khi thêm.")
        self.sensor_screen_new.update_sensors_table() # Cập nhật lại bảng


    def handle_remove_sensor_request(self, sensor_id):
        logger.info(f"MainWindow: Received request to remove sensor: {sensor_id}")
        if self.sensor_manager.remove_sensor(sensor_id):
            QMessageBox.information(self, "Thành công", f"Đã xóa cảm biến ID '{sensor_id}'.")
            self.data_processor.remove_sensor_data(sensor_id) # Xóa dữ liệu trong DataProcessor
            if self.current_plotting_sensor_id == sensor_id:
                self.current_plotting_sensor_id = None
                self.plot_manager.stop_plotting()
                self.plot_manager.reset_plots() # Xóa đồ thị cũ
                self.display_screen.dominant_freq_label.setText("Tần số đặc trưng X: -- Hz, Y: -- Hz, Z: -- Hz")

        else:
            QMessageBox.warning(self, "Lỗi", f"Không thể xóa cảm biến ID '{sensor_id}'.")
        # sensorListChanged từ SensorManager sẽ tự cập nhật bảng


    def handle_sensor_data_from_manager(self, sensor_id, data_dict):
        # Truyền config của sensor cho DataProcessor để nó biết dt, sample_frame_size
        sensor_info = self.sensor_manager.get_sensor_info(sensor_id)
        sensor_config = sensor_info.get('config') if sensor_info else {}

        self.data_processor.handle_incoming_sensor_data(sensor_id, data_dict, sensor_config)
        
        # Chỉ tính FFT và cập nhật plot nếu sensor này đang được hiển thị
        if sensor_id == self.current_plotting_sensor_id:
            self.data_processor.calculate_fft_for_sensor(sensor_id)
            # PlotManager sẽ tự lấy dữ liệu từ DataProcessor trong timer của nó


    def handle_sensor_connection_status_from_manager(self, sensor_id, connected, message):
        logger.info(f"MainWindow: Connection status for {sensor_id}: {connected}, Msg: {message}")
        self.sensor_screen_new.update_sensors_table() # Cập nhật trạng thái trong bảng
        
        if sensor_id == self.current_plotting_sensor_id:
            if connected:
                if not self.plot_manager.is_collecting_data: # Chỉ start nếu chưa chạy
                    self.plot_manager.reset_plots() # Reset đồ thị cho sensor mới
                    # Truyền sensor_id vào PlotManager để nó biết lấy dữ liệu của ai
                    self.plot_manager.start_plotting(self.settings_screen.get_current_display_rate(), sensor_id) 
                    logger.info(f"Plotting started for sensor {sensor_id}.")
            else: # Mất kết nối với sensor đang vẽ
                if self.plot_manager.is_collecting_data:
                    self.plot_manager.stop_plotting()
                    logger.info(f"Plotting stopped for sensor {sensor_id} due to disconnection.")
                    QMessageBox.warning(self, "Mất kết nối", f"Mất kết nối với cảm biến đang hiển thị: {sensor_id}. {message}")
        
        if not connected and "removed" not in message.lower(): # Không báo lỗi nếu là do người dùng xóa
             QMessageBox.warning(self, "Lỗi Kết nối Cảm biến", f"Sensor {sensor_id}: {message}")


    def handle_sensor_selected_for_plotting(self, sensor_id):
        logger.info(f"MainWindow: Sensor {sensor_id} selected for plotting.")
        if self.current_plotting_sensor_id == sensor_id:
            # Nếu đã chọn sensor này rồi thì không làm gì cả, trừ khi nó đang không vẽ
            sensor_info = self.sensor_manager.get_sensor_info(sensor_id)
            if sensor_info and sensor_info.get('connected') and not self.plot_manager.is_collecting_data:
                 logger.info(f"Re-starting plotting for already selected sensor {sensor_id}")
                 self.plot_manager.reset_plots()
                 self.plot_manager.start_plotting(self.settings_screen.get_current_display_rate(), sensor_id)
            return

        # Dừng plot sensor cũ nếu có
        if self.plot_manager.is_collecting_data:
            self.plot_manager.stop_plotting()

        self.current_plotting_sensor_id = sensor_id
        self.data_processor.reset_sensor_data(sensor_id) # Reset data cho sensor mới được chọn vẽ
        self.plot_manager.reset_plots() # Xóa đồ thị cũ

        # Cập nhật sensor ID cho màn hình phân tích
        if hasattr(self, 'advanced_analysis_screen'):
            self.advanced_analysis_screen.set_current_sensor(sensor_id)

        sensor_info = self.sensor_manager.get_sensor_info(sensor_id)
        if sensor_info and sensor_info.get('connected'):
            # Truyền sensor_id vào PlotManager
            self.plot_manager.start_plotting(self.settings_screen.get_current_display_rate(), sensor_id)
            self.tabs.setTabText(0, f"Hiển thị Đồ thị ({sensor_info.get('config',{}).get('name', sensor_id)})")
        else:
            self.tabs.setTabText(0, f"Hiển thị Đồ thị ({sensor_id} - Chưa kết nối)")
            logger.warning(f"Sensor {sensor_id} selected but not connected. Cannot start plotting.")
            QMessageBox.information(self, "Thông báo", f"Cảm biến '{sensor_id}' chưa được kết nối hoặc không có dữ liệu.")


    def handle_display_rate_change(self, rate_hz):
        logger.info(f"Display rate changed to {rate_hz} Hz")
        if self.current_plotting_sensor_id and self.plot_manager.is_collecting_data:
            self.plot_manager.start_plotting(rate_hz, self.current_plotting_sensor_id) # Restart với rate mới
        elif self.current_plotting_sensor_id: # Nếu có sensor được chọn nhưng chưa plot (ví dụ chưa connect)
            # Chỉ cần cập nhật rate, khi connect nó sẽ dùng rate này
            self.plot_manager.set_plot_rate(rate_hz) # PlotManager cần hàm này
        else: # Chưa có sensor nào được chọn
            self.plot_manager.set_plot_rate(rate_hz)


    def closeEvent(self, event):
        logger.info("Closing application...")
        if self.sensor_manager:
            self.sensor_manager.stop_all_sensors() # Yêu cầu tất cả các sensor dừng
        
        # Chờ các luồng dừng hẳn (có thể cần cơ chế wait phức tạp hơn)
        # QTimer.singleShot(1500, self.check_threads_and_close) # Ví dụ
        # event.ignore() # Ngăn cửa sổ đóng ngay, chờ check_threads_and_close
        
        # Hoặc đơn giản là chờ một chút
        # Cần đảm bảo các QThread được quit() và wait() đúng cách trong SensorInstance.cleanup()
        # mà SensorManager.stop_all_sensors() sẽ gọi
        # Cho phép đóng ngay, việc dọn dẹp thread nên nằm trong SensorInstance và SensorManager
        super().closeEvent(event) 