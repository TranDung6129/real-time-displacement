import logging
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QTabWidget
from PyQt6.QtCore import QThread

from workers.sensor_worker import SensorWorker
from core.data_processor import DataProcessor
from core.plot_manager import PlotManager
from algorithm.kinematic_processor import KinematicProcessor
from ui.display_screen import DisplayScreenWidget
from ui.sensor_management_screen import SensorManagementScreenWidget
from ui.settings_screen import SettingsScreenWidget
from ui.advanced_analysis_screen import AdvancedAnalysisScreenWidget

logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ứng dụng Theo dõi Cảm biến Đa Tab")
        self.setGeometry(100, 100, 1600, 900)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        # Initialize data processing components first
        self.data_processor = DataProcessor()

        # Initialize UI components
        self.tabs = QTabWidget()
        self.display_screen = DisplayScreenWidget()
        self.sensor_screen = SensorManagementScreenWidget()
        self.settings_screen = SettingsScreenWidget()
        self.advanced_analysis_screen = AdvancedAnalysisScreenWidget(self.data_processor)

        # Initialize plot manager after display_screen is created
        self.plot_manager = PlotManager(self.display_screen, self.data_processor)

        self.tabs.addTab(self.display_screen, "Hiển thị Đồ thị")
        self.tabs.addTab(self.sensor_screen, "Quản lý Cảm biến")
        self.tabs.addTab(self.settings_screen, "Thiết lập")
        self.tabs.addTab(self.advanced_analysis_screen, "Phân tích Chuyên sâu")

        self.layout.addWidget(self.tabs)

        # Initialize connection management variables
        self.sensor_thread = None
        self.sensor_worker = None
        self.integrators = None
        self.dt_sensor_current = 0.005
        self.sample_frame_size_integrator = 20

        # Connect signals
        self.sensor_screen.connect_requested.connect(self.handle_connect_request)
        self.sensor_screen.disconnect_requested.connect(self.stop_sensor_data)
        self.settings_screen.display_rate_changed.connect(self.plot_manager.start_plotting)

        # Initialize display rate
        self.plot_manager.start_plotting(self.settings_screen.get_current_display_rate())

    def initialize_integrators(self, dt_sensor):
        self.dt_sensor_current = dt_sensor
        calc_multiplier_val = 50
        q_filter = 0.9875
        self.sample_frame_size_integrator = 20

        self.integrators = {
            'x': KinematicProcessor(
                dt=dt_sensor,
                sample_frame_size=self.sample_frame_size_integrator,
                calc_frame_multiplier=calc_multiplier_val,
                rls_filter_q_vel=q_filter,
                rls_filter_q_disp=q_filter
            ),
            'y': KinematicProcessor(
                dt=dt_sensor,
                sample_frame_size=self.sample_frame_size_integrator,
                calc_frame_multiplier=calc_multiplier_val,
                rls_filter_q_vel=q_filter,
                rls_filter_q_disp=q_filter
            ),
            'z': KinematicProcessor(
                dt=dt_sensor,
                sample_frame_size=self.sample_frame_size_integrator,
                calc_frame_multiplier=calc_multiplier_val,
                rls_filter_q_vel=q_filter,
                rls_filter_q_disp=q_filter
            )
        }
        logger.info(f"Đã khởi tạo các bộ tích hợp với dt={dt_sensor}")

    def handle_connect_request(self, port, baudrate, use_mock_data):
        if self.plot_manager.is_collecting_data:
            logger.warning("Đang thu thập dữ liệu, không thể bắt đầu kết nối mới.")
            self.sensor_screen.update_status("Đang thu thập, ngắt trước khi kết nối lại.", True, self.plot_manager.is_collecting_data)
            return

        dt_sensor_val = 0.1 if use_mock_data else 0.005  # 0.1s for mock, 0.005s for real sensor
        self.initialize_integrators(dt_sensor_val)

        self.sensor_worker = SensorWorker(port, baudrate, use_mock_data)
        self.sensor_thread = QThread()
        self.sensor_worker.moveToThread(self.sensor_thread)

        self.sensor_worker.newData.connect(self.process_incoming_data)
        self.sensor_worker.connectionStatus.connect(self.handle_connection_status)
        self.sensor_worker.stopped.connect(self.on_worker_stopped)

        self.sensor_thread.started.connect(self.sensor_worker.run)
        self.sensor_thread.start()

    def stop_sensor_data(self):
        if self.sensor_worker:
            self.sensor_worker.stop()

    def on_worker_stopped(self):
        logger.info("Worker đã thực sự dừng trong MainWindow.")
        if self.sensor_thread and self.sensor_thread.isRunning():
            self.sensor_thread.quit()
            if not self.sensor_thread.wait(3000):
                logger.warning("Thread không dừng kịp, sẽ terminate.")
                self.sensor_thread.terminate()
                self.sensor_thread.wait()

        self.plot_manager.stop_plotting()
        self.sensor_screen.update_status("Đã ngắt kết nối.", False, self.plot_manager.is_collecting_data)

        self.sensor_thread = None
        self.sensor_worker = None

    def handle_connection_status(self, connected, message):
        self.sensor_screen.update_status(message, connected, connected if connected else False)
        if connected:
            self.plot_manager.is_collecting_data = True
            self.plot_manager.reset_plots()
            self.plot_manager.start_plotting(self.settings_screen.get_current_display_rate())
            logger.info("Timer vẽ đồ thị đã bắt đầu.")
        else:
            if self.plot_manager.is_collecting_data:
                self.plot_manager.is_collecting_data = False
                self.plot_manager.stop_plotting()
                logger.info("Timer vẽ đồ thị đã dừng do mất kết nối.")

    def process_incoming_data(self, sensor_data_dict):
        if not self.plot_manager.is_collecting_data or not self.integrators:
            return

        self.data_processor.process_sensor_data(
            sensor_data_dict,
            self.integrators,
            self.dt_sensor_current,
            self.sample_frame_size_integrator
        )
        self.data_processor.calculate_fft(self.dt_sensor_current)

    def closeEvent(self, event):
        logger.info("Đóng ứng dụng.")
        self.stop_sensor_data()
        if self.sensor_thread and self.sensor_thread.isRunning():
            logger.info("Đang chờ SensorWorker dừng...")
            if not self.sensor_thread.wait(3000):
                logger.warning("SensorWorker không dừng kịp khi đóng ứng dụng.")
        super().closeEvent(event) 