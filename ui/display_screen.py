# ui/display_screen.py
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGridLayout
import pyqtgraph as pg
import numpy as np

class DisplayScreenWidget(QWidget):
    MAX_DATA_POINTS = 1000 # Giữ lại để giới hạn số điểm vẽ

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        # Label hiển thị tần số đặc trưng
        self.dominant_freq_label = QLabel("Tần số đặc trưng X: -- Hz, Y: -- Hz, Z: -- Hz")
        main_layout.addWidget(self.dominant_freq_label)

        plot_grid_layout = QGridLayout()
        self.plot_widget_main = pg.GraphicsLayoutWidget()
        self.plot_widget_fft = pg.GraphicsLayoutWidget()

        plot_grid_layout.addWidget(self.plot_widget_main, 0, 0)
        plot_grid_layout.addWidget(self.plot_widget_fft, 0, 1)
        main_layout.addLayout(plot_grid_layout)

        # Plots chính
        self.plot_acc = self.plot_widget_main.addPlot(row=0, col=0, title="Gia tốc (m/s^2)")
        self.plot_vel = self.plot_widget_main.addPlot(row=1, col=0, title="Vận tốc (m/s)")
        self.plot_disp = self.plot_widget_main.addPlot(row=2, col=0, title="Li độ (m)")

        # Plots FFT
        self.plot_fft_x = self.plot_widget_fft.addPlot(row=0, col=0, title="FFT Gia tốc X")
        self.plot_fft_y = self.plot_widget_fft.addPlot(row=1, col=0, title="FFT Gia tốc Y")
        self.plot_fft_z = self.plot_widget_fft.addPlot(row=2, col=0, title="FFT Gia tốc Z")

        for plot_item_pg in [self.plot_acc, self.plot_vel, self.plot_disp,
                               self.plot_fft_x, self.plot_fft_y, self.plot_fft_z]:
            plot_item_pg.showGrid(x=True, y=True)
            if plot_item_pg not in [self.plot_fft_x, self.plot_fft_y, self.plot_fft_z]:
                plot_item_pg.addLegend()
            plot_item_pg.setDownsampling(auto=True, mode='peak', ds=5) # Bật downsampling

        # Curves cho plots chính
        self.curves_acc = {
            'x': self.plot_acc.plot(pen='r', name='AccX'),
            'y': self.plot_acc.plot(pen='g', name='AccY'),
            'z': self.plot_acc.plot(pen='b', name='AccZ')
        }
        self.curves_vel = {
            'x': self.plot_vel.plot(pen='r', name='VelX'),
            'y': self.plot_vel.plot(pen='g', name='VelY'),
            'z': self.plot_vel.plot(pen='b', name='VelZ')
        }
        self.curves_disp = {
            'x': self.plot_disp.plot(pen='r', name='DispX'),
            'y': self.plot_disp.plot(pen='g', name='DispY'),
            'z': self.plot_disp.plot(pen='b', name='DispZ')
        }

        # Curves cho FFT
        self.curve_fft_x = self.plot_fft_x.plot(pen='r')
        self.curve_fft_y = self.plot_fft_y.plot(pen='g')
        self.curve_fft_z = self.plot_fft_z.plot(pen='b')

    def update_plots(self, time_data, acc_data, vel_data, disp_data, fft_data, dominant_freqs):
        min_main_len = min(
            len(time_data),
            len(acc_data.get('x', [])), len(acc_data.get('y', [])), len(acc_data.get('z', [])),
            len(vel_data.get('x', [])), len(vel_data.get('y', [])), len(vel_data.get('z', [])),
            len(disp_data.get('x', [])), len(disp_data.get('y', [])), len(disp_data.get('z', []))
        )

        if min_main_len == 0:
            return

        n_points_main = min(min_main_len, self.MAX_DATA_POINTS)
        plot_time_main = time_data[-n_points_main:]

        if len(plot_time_main) > 0:
            self.curves_acc['x'].setData(plot_time_main, acc_data['x'][-n_points_main:])
            self.curves_acc['y'].setData(plot_time_main, acc_data['y'][-n_points_main:])
            self.curves_acc['z'].setData(plot_time_main, acc_data['z'][-n_points_main:])

            self.curves_vel['x'].setData(plot_time_main, vel_data['x'][-n_points_main:])
            self.curves_vel['y'].setData(plot_time_main, vel_data['y'][-n_points_main:])
            self.curves_vel['z'].setData(plot_time_main, vel_data['z'][-n_points_main:])

            self.curves_disp['x'].setData(plot_time_main, disp_data['x'][-n_points_main:])
            self.curves_disp['y'].setData(plot_time_main, disp_data['y'][-n_points_main:])
            self.curves_disp['z'].setData(plot_time_main, disp_data['z'][-n_points_main:])

        # Update FFT plots
        if fft_data['x_freq'] is not None and fft_data['x_amp'] is not None:
            self.curve_fft_x.setData(fft_data['x_freq'], fft_data['x_amp'])
        else:
            self.curve_fft_x.clear()

        if fft_data['y_freq'] is not None and fft_data['y_amp'] is not None:
            self.curve_fft_y.setData(fft_data['y_freq'], fft_data['y_amp'])
        else:
            self.curve_fft_y.clear()

        if fft_data['z_freq'] is not None and fft_data['z_amp'] is not None:
            self.curve_fft_z.setData(fft_data['z_freq'], fft_data['z_amp'])
        else:
            self.curve_fft_z.clear()

        self.update_dominant_freq_label(dominant_freqs)

    def update_dominant_freq_label(self, dominant_freqs):
        fx = dominant_freqs.get('x', 0)
        fy = dominant_freqs.get('y', 0)
        fz = dominant_freqs.get('z', 0)
        self.dominant_freq_label.setText(f"Tần số X: {fx:.2f} Hz, Y: {fy:.2f} Hz, Z: {fz:.2f} Hz")

    def reset_plots(self):
        empty_arr = np.array([])
        for axis in ['x', 'y', 'z']:
            self.curves_acc[axis].setData(empty_arr, empty_arr)
            self.curves_vel[axis].setData(empty_arr, empty_arr)
            self.curves_disp[axis].setData(empty_arr, empty_arr)
        self.curve_fft_x.clear()
        self.curve_fft_y.clear()
        self.curve_fft_z.clear()
        self.update_dominant_freq_label({'x': 0, 'y': 0, 'z': 0}) 