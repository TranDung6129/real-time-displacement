import logging
from PyQt6.QtCore import QTimer

logger = logging.getLogger(__name__)

class PlotManager:
    def __init__(self, display_screen, data_processor):
        self.display_screen = display_screen
        self.data_processor = data_processor
        self.plot_update_timer = QTimer()
        self.plot_update_timer.timeout.connect(self.update_plots)
        self.is_collecting_data = False

    def start_plotting(self, rate_hz):
        if rate_hz and rate_hz > 0:
            interval_ms = int(1000 / rate_hz)
            self.plot_update_timer.setInterval(interval_ms)
            logger.info(f"Đã thay đổi tốc độ hiển thị thành {rate_hz} Hz (interval {interval_ms} ms)")
            if self.is_collecting_data and not self.plot_update_timer.isActive():
                self.plot_update_timer.start()

    def stop_plotting(self):
        self.plot_update_timer.stop()
        self.is_collecting_data = False

    def update_plots(self):
        if not self.is_collecting_data:
            return

        plot_data = self.data_processor.get_plot_data()
        if not plot_data['time_data'].size:
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
        self.data_processor.reset_data_arrays()
        self.display_screen.reset_plots() 