import logging
from PyQt6.QtCore import QTimer
import numpy as np # Import numpy

logger = logging.getLogger(__name__)

class PlotManager:
    def __init__(self, display_screen, data_processor):
        self.display_screen = display_screen
        self.data_processor = data_processor # DataProcessor đã được cập nhật
        self.plot_update_timer = QTimer()
        self.plot_update_timer.timeout.connect(self.update_plots)
        self.is_collecting_data = False
        self.current_sensor_id_plotting = None # Sensor ID đang được vẽ
        self._target_plot_rate_hz = 10 # Mặc định 10Hz

    def set_plot_rate(self, rate_hz):
        if rate_hz and rate_hz > 0:
            self._target_plot_rate_hz = rate_hz
            logger.info(f"Target plot rate set to {rate_hz} Hz.")
            if self.is_collecting_data: # Nếu đang vẽ thì cập nhật interval ngay
                 interval_ms = int(1000 / self._target_plot_rate_hz)
                 self.plot_update_timer.setInterval(interval_ms)
                 logger.info(f"Plot interval updated to {interval_ms} ms for sensor {self.current_sensor_id_plotting}")


    def start_plotting(self, rate_hz, sensor_id):
        if not sensor_id:
            logger.warning("Cannot start plotting without a sensor_id.")
            return
            
        self.current_sensor_id_plotting = sensor_id
        self._target_plot_rate_hz = rate_hz if rate_hz and rate_hz > 0 else self._target_plot_rate_hz

        if self._target_plot_rate_hz > 0:
            interval_ms = int(1000 / self._target_plot_rate_hz)
            self.plot_update_timer.setInterval(interval_ms)
            
            if not self.plot_update_timer.isActive():
                self.is_collecting_data = True # Đặt cờ trước khi start timer
                self.plot_update_timer.start()
                logger.info(f"Plotting started for sensor {self.current_sensor_id_plotting} at {self._target_plot_rate_hz} Hz (interval {interval_ms} ms)")
            else: # Timer đang chạy, có thể chỉ thay đổi sensor_id hoặc rate
                 logger.info(f"Plotting already active, now for sensor {self.current_sensor_id_plotting} at {self._target_plot_rate_hz} Hz (interval {interval_ms} ms)")
                 self.is_collecting_data = True # Đảm bảo cờ đúng
        else:
            logger.warning(f"Invalid plot rate: {self._target_plot_rate_hz}. Plotting not started for {self.current_sensor_id_plotting}.")


    def stop_plotting(self):
        if self.plot_update_timer.isActive():
            self.plot_update_timer.stop()
        self.is_collecting_data = False
        # Không reset current_sensor_id_plotting ở đây, MainWindow sẽ quản lý
        logger.info(f"Plotting stopped for sensor {self.current_sensor_id_plotting}.")

    def update_plots(self):
        if not self.is_collecting_data or not self.current_sensor_id_plotting:
            return

        # Lấy dữ liệu cho sensor_id cụ thể từ DataProcessor
        plot_data = self.data_processor.get_plot_data_for_sensor(self.current_sensor_id_plotting)
        
        if not plot_data or not plot_data['time_data'].size:
            # logger.debug(f"No data or empty time_data for sensor {self.current_sensor_id_plotting}")
            return

        self.display_screen.update_plots(
            time_data=plot_data['time_data'],
            acc_data=plot_data['acc_data'],
            vel_data=plot_data['vel_data'],
            disp_data=plot_data['disp_data'],
            fft_data=plot_data['fft_data'],
            dominant_freqs=plot_data['dominant_freqs']
        )

    def reset_plots(self):
        # Reset dữ liệu trong DataProcessor cho sensor hiện tại nếu có
        if self.current_sensor_id_plotting:
             self.data_processor.reset_sensor_data(self.current_sensor_id_plotting)
        
        # Reset các đường cong trên DisplayScreen
        # DisplayScreenWidget.reset_plots() đã làm việc này khá tốt
        self.display_screen.reset_plots()
        logger.info(f"Plots reset, current plotting sensor: {self.current_sensor_id_plotting}") 