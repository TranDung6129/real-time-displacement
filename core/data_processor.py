import numpy as np
from scipy.fft import rfft, rfftfreq
from scipy.signal import windows
import logging

logger = logging.getLogger(__name__)

class DataProcessor:
    def __init__(self, n_fft_points=512):
        self.N_FFT_POINTS = n_fft_points
        self.reset_data_arrays()

    def reset_data_arrays(self):
        self.time_data = np.array([])
        self.acc_x_raw_for_fft = np.array([])
        self.acc_y_raw_for_fft = np.array([])
        self.acc_z_raw_for_fft = np.array([])

        self.processed_acc_data = {'x': np.array([]), 'y': np.array([]), 'z': np.array([])}
        self.processed_vel_data = {'x': np.array([]), 'y': np.array([]), 'z': np.array([])}
        self.processed_disp_data = {'x': np.array([]), 'y': np.array([]), 'z': np.array([])}
        self.current_time_for_plot = 0.0

        self.acc_buffer_x = []
        self.acc_buffer_y = []
        self.acc_buffer_z = []

        self.dominant_freqs = {'x': 0, 'y': 0, 'z': 0}
        self.fft_plot_data = {
            'x_freq': None, 'x_amp': None,
            'y_freq': None, 'y_amp': None,
            'z_freq': None, 'z_amp': None
        }

    def process_sensor_data(self, sensor_data_dict, integrators, dt_sensor, sample_frame_size):
        if not sensor_data_dict:
            return

        try:
            accX = sensor_data_dict.get("accX")
            accY = sensor_data_dict.get("accY")
            accZ = sensor_data_dict.get("accZ")

            if accX is None or accY is None or accZ is None:
                return

            g_conversion = 9.80665
            accX_ms2 = accX * g_conversion
            accY_ms2 = accY * g_conversion
            accZ_ms2 = (accZ - 1.0) * g_conversion

            fft_buffer_size = self.N_FFT_POINTS * 2
            self.acc_x_raw_for_fft = np.append(self.acc_x_raw_for_fft, accX_ms2)[-fft_buffer_size:]
            self.acc_y_raw_for_fft = np.append(self.acc_y_raw_for_fft, accY_ms2)[-fft_buffer_size:]
            self.acc_z_raw_for_fft = np.append(self.acc_z_raw_for_fft, accZ_ms2)[-fft_buffer_size:]

            self.acc_buffer_x.append(accX_ms2)
            self.acc_buffer_y.append(accY_ms2)
            self.acc_buffer_z.append(accZ_ms2)

            if len(self.acc_buffer_x) >= sample_frame_size:
                frame_x = np.array(self.acc_buffer_x[:sample_frame_size])
                frame_y = np.array(self.acc_buffer_y[:sample_frame_size])
                frame_z = np.array(self.acc_buffer_z[:sample_frame_size])

                self.acc_buffer_x = self.acc_buffer_x[sample_frame_size:]
                self.acc_buffer_y = self.acc_buffer_y[sample_frame_size:]
                self.acc_buffer_z = self.acc_buffer_z[sample_frame_size:]

                disp_fx, vel_fx, acc_fx_filtered = integrators['x'].process_frame(frame_x)
                disp_fy, vel_fy, acc_fy_filtered = integrators['y'].process_frame(frame_y)
                disp_fz, vel_fz, acc_fz_filtered = integrators['z'].process_frame(frame_z)

                num_samples_in_frame = len(acc_fx_filtered)
                new_times_segment = np.arange(
                    self.current_time_for_plot,
                    self.current_time_for_plot + num_samples_in_frame * dt_sensor,
                    dt_sensor
                )[:num_samples_in_frame]

                if not new_times_segment.size:
                    return

                self.current_time_for_plot += num_samples_in_frame * dt_sensor

                self.time_data = np.append(self.time_data, new_times_segment)
                self.processed_acc_data['x'] = np.append(self.processed_acc_data['x'], acc_fx_filtered)
                self.processed_acc_data['y'] = np.append(self.processed_acc_data['y'], acc_fy_filtered)
                self.processed_acc_data['z'] = np.append(self.processed_acc_data['z'], acc_fz_filtered)
                self.processed_vel_data['x'] = np.append(self.processed_vel_data['x'], vel_fx)
                self.processed_vel_data['y'] = np.append(self.processed_vel_data['y'], vel_fy)
                self.processed_vel_data['z'] = np.append(self.processed_vel_data['z'], vel_fz)
                self.processed_disp_data['x'] = np.append(self.processed_disp_data['x'], disp_fx)
                self.processed_disp_data['y'] = np.append(self.processed_disp_data['y'], disp_fy)
                self.processed_disp_data['z'] = np.append(self.processed_disp_data['z'], disp_fz)

                self._trim_data_arrays()

        except Exception as e:
            logger.error(f"Lỗi khi xử lý dữ liệu cảm biến: {e}", exc_info=True)

    def _trim_data_arrays(self, max_points=2000):
        data_arrays_to_trim = [
            self.time_data,
            self.processed_acc_data['x'], self.processed_acc_data['y'], self.processed_acc_data['z'],
            self.processed_vel_data['x'], self.processed_vel_data['y'], self.processed_vel_data['z'],
            self.processed_disp_data['x'], self.processed_disp_data['y'], self.processed_disp_data['z']
        ]

        current_min_len = min(len(arr) for arr in data_arrays_to_trim if hasattr(arr, '__len__'))

        if current_min_len > max_points:
            slice_start = -max_points
            self.time_data = self.time_data[slice_start:]
            for axis in ['x', 'y', 'z']:
                self.processed_acc_data[axis] = self.processed_acc_data[axis][slice_start:]
                self.processed_vel_data[axis] = self.processed_vel_data[axis][slice_start:]
                self.processed_disp_data[axis] = self.processed_disp_data[axis][slice_start:]

    def calculate_fft(self, dt_sensor):
        if dt_sensor <= 0:
            return

        data_segments_fft = {
            'x': self.acc_x_raw_for_fft,
            'y': self.acc_y_raw_for_fft,
            'z': self.acc_z_raw_for_fft
        }
        new_dominant_freqs = {}

        for axis, acc_data_axis in data_segments_fft.items():
            if len(acc_data_axis) >= self.N_FFT_POINTS:
                segment_for_fft = acc_data_axis[-self.N_FFT_POINTS:]
                hanning_window = windows.hann(self.N_FFT_POINTS)
                segment_windowed = segment_for_fft * hanning_window

                yf = rfft(segment_windowed)
                xf = rfftfreq(self.N_FFT_POINTS, dt_sensor)

                if len(xf) > 1 and len(yf) > 1:
                    amplitude_spectrum = np.abs(yf[1:])
                    freq_axis_fft = xf[1:]

                    if amplitude_spectrum.size > 0:
                        self.fft_plot_data[f'{axis}_freq'] = freq_axis_fft
                        self.fft_plot_data[f'{axis}_amp'] = amplitude_spectrum

                        min_freq_idx = np.where(freq_axis_fft >= 0.1)[0]
                        if min_freq_idx.size > 0:
                            start_idx = min_freq_idx[0]
                            if start_idx < len(amplitude_spectrum):
                                peak_idx = np.argmax(amplitude_spectrum[start_idx:]) + start_idx
                                dominant_freq = freq_axis_fft[peak_idx]
                                new_dominant_freqs[axis] = dominant_freq
                            else:
                                new_dominant_freqs[axis] = 0
                                self.fft_plot_data[f'{axis}_freq'] = None
                                self.fft_plot_data[f'{axis}_amp'] = None
                        else:
                            new_dominant_freqs[axis] = 0
                            self.fft_plot_data[f'{axis}_freq'] = None
                            self.fft_plot_data[f'{axis}_amp'] = None
                    else:
                        new_dominant_freqs[axis] = 0
                        self.fft_plot_data[f'{axis}_freq'] = None
                        self.fft_plot_data[f'{axis}_amp'] = None
                else:
                    new_dominant_freqs[axis] = 0
                    self.fft_plot_data[f'{axis}_freq'] = None
                    self.fft_plot_data[f'{axis}_amp'] = None
            else:
                new_dominant_freqs[axis] = self.dominant_freqs.get(axis, 0)

        if new_dominant_freqs:
            self.dominant_freqs.update(new_dominant_freqs)

    def get_plot_data(self):
        return {
            'time_data': self.time_data,
            'acc_data': self.processed_acc_data,
            'vel_data': self.processed_vel_data,
            'disp_data': self.processed_disp_data,
            'fft_data': self.fft_plot_data,
            'dominant_freqs': self.dominant_freqs
        } 