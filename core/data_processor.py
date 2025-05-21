import numpy as np
from scipy.fft import rfft, rfftfreq
from scipy.signal import windows
import logging
from PyQt6.QtCore import QObject
# Import KinematicProcessor từ project của bạn
from algorithm.kinematic_processor import KinematicProcessor # Đường dẫn này có thể cần điều chỉnh

logger = logging.getLogger(__name__)

class DataProcessor(QObject): # Kế thừa QObject nếu cần signal/slot
    # Thêm signal nếu DataProcessor cần thông báo cho UI về dữ liệu đã xử lý mới
    # processedDataUpdated = pyqtSignal(str) # sensor_id
    # dominantFrequenciesUpdated = pyqtSignal(str, dict) # sensor_id, freqs

    def __init__(self, parent=None): # Thêm parent=None
        super().__init__(parent) # Gọi super constructor
        self.N_FFT_POINTS = 512
        
        # Các cấu trúc dữ liệu sẽ lưu trữ theo sensor_id
        self._sensor_data_store = {}
        # self.kinematic_processors = {} # sensor_id -> {'x': KinematicProcessor, ...}
        # self.dt_sensor_values = {} # sensor_id -> dt
        # self.sample_frame_sizes = {} # sensor_id -> sample_frame_size

        # Các thuộc tính cũ có thể không cần nữa hoặc cần refactor
        # self.time_data, self.acc_x_raw_for_fft, ...
        # self.processed_acc_data, ...
        # self.current_time_for_plot
        # self.acc_buffer_x, ...
        # self.dominant_freqs
        # self.fft_plot_data
        # self.dt_sensor_for_fft_analysis

        self.reset_all_data()


    def _ensure_sensor_id_structure(self, sensor_id, sensor_type="wit_motion_imu", dt=0.005, sample_frame_size=20):
        if sensor_id not in self._sensor_data_store:
            logger.info(f"DataProcessor: Initializing data structure for sensor_id: {sensor_id}")
            self._sensor_data_store[sensor_id] = {
                'config': {'type': sensor_type, 'dt': dt, 'sample_frame_size': sample_frame_size},
                'time_data': np.array([]),
                'raw_acc': {'x': np.array([]), 'y': np.array([]), 'z': np.array([])}, # Cho FFT
                'processed_acc': {'x': np.array([]), 'y': np.array([]), 'z': np.array([])},
                'processed_vel': {'x': np.array([]), 'y': np.array([]), 'z': np.array([])},
                'processed_disp': {'x': np.array([]), 'y': np.array([]), 'z': np.array([])},
                'current_time_plot': 0.0,
                'acc_input_buffers': {'x': [], 'y': [], 'z': []}, # Buffer nhỏ cho từng frame của KinematicProcessor
                'kinematic_processors': {
                    axis: KinematicProcessor(
                        dt=dt,
                        sample_frame_size=sample_frame_size,
                        # calc_frame_multiplier, rls_filter_q_vel, rls_filter_q_disp có thể lấy từ config chung
                        calc_frame_multiplier=50, # Ví dụ
                        rls_filter_q_vel=0.9875,  # Ví dụ
                        rls_filter_q_disp=0.9875  # Ví dụ
                    ) for axis in ['x', 'y', 'z']
                },
                'fft_plot_data': {ax: {'freq': None, 'amp': None} for ax in ['x', 'y', 'z']},
                'dominant_freqs': {'x': 0, 'y': 0, 'z': 0}
            }
        # Cập nhật dt nếu cần
        if self._sensor_data_store[sensor_id]['config']['dt'] != dt:
             self._sensor_data_store[sensor_id]['config']['dt'] = dt
             for kp in self._sensor_data_store[sensor_id]['kinematic_processors'].values():
                 kp.dt = dt # Giả sử KinematicProcessor cho phép cập nhật dt

    def reset_sensor_data(self, sensor_id):
        if sensor_id in self._sensor_data_store:
            dt = self._sensor_data_store[sensor_id]['config']['dt']
            sample_frame_size = self._sensor_data_store[sensor_id]['config']['sample_frame_size']
            sensor_type = self._sensor_data_store[sensor_id]['config']['type']
            self._ensure_sensor_id_structure(sensor_id, sensor_type, dt, sample_frame_size) # Effectively resets
            # Reset thêm các KinematicProcessor
            for kp_axis in self._sensor_data_store[sensor_id]['kinematic_processors'].values():
                kp_axis.reset()

            logger.info(f"Data for sensor {sensor_id} has been reset.")
            # self.processedDataUpdated.emit(sensor_id) # Thông báo cho UI biết để xóa đồ thị
        else:
            logger.warning(f"Cannot reset data for unknown sensor_id: {sensor_id}")

    def reset_all_data(self): # Đổi tên từ reset_data_arrays
        # self._sensor_data_store.clear() # Xóa tất cả
        # Hoặc reset từng sensor nếu muốn giữ lại cấu trúc
        for sensor_id in list(self._sensor_data_store.keys()):
            self.reset_sensor_data(sensor_id)
        logger.info("All sensor data structures have been reset in DataProcessor.")


    def remove_sensor_data(self, sensor_id):
        if sensor_id in self._sensor_data_store:
            del self._sensor_data_store[sensor_id]
            logger.info(f"Data structure for sensor {sensor_id} removed from DataProcessor.")
        else:
            logger.warning(f"Cannot remove data for unknown sensor_id: {sensor_id}")


    def handle_incoming_sensor_data(self, sensor_id, sensor_data_dict, sensor_config_from_manager=None):
        # sensor_config_from_manager là config đầy đủ từ SensorManager, chứa dt, sample_frame_size...
        # Cần lấy dt và sample_frame_size từ config này hoặc từ một nguồn khác
        # Ví dụ: giả sử dt và sample_frame_size được set khi sensor được thêm vào DataProcessor lần đầu
        
        # Ước lượng dt từ WIT data rate nếu là cảm biến WIT
        # Đây là phần quan trọng để KinematicProcessor hoạt động đúng
        _dt = 0.005 # Giá trị mặc định an toàn
        _sample_frame_size = 20 # Mặc định
        _sensor_type = "unknown"

        if sensor_config_from_manager:
            _sensor_type = sensor_config_from_manager.get('type', 'unknown')
            _sample_frame_size = sensor_config_from_manager.get('processing_sample_frame_size', 20) # Cần định nghĩa key này

            if _sensor_type == "wit_motion_imu":
                hex_val = sensor_config_from_manager.get('wit_data_rate_byte_hex', "0b").lower().replace("0x","")
                rate_map_to_dt = {"0b": 0.005, "19": 0.01, "14": 0.02, "0a": 0.05, "05": 0.1}
                _dt = rate_map_to_dt.get(hex_val, 0.01)
            elif _sensor_type == "mock_sensor":
                 _dt = sensor_config_from_manager.get('mock_update_interval', 0.1) # Giả sử mock có config này
            # Thêm các logic khác để xác định dt cho các loại sensor khác
            
        self._ensure_sensor_id_structure(sensor_id, _sensor_type, _dt, _sample_frame_size)
        sds = self._sensor_data_store[sensor_id] # Shortcut to sensor data store

        # Phần xử lý tương tự process_sensor_data cũ, nhưng dùng sds
        if not sensor_data_dict: return

        try:
            accX = sensor_data_dict.get("accX")
            accY = sensor_data_dict.get("accY")
            accZ = sensor_data_dict.get("accZ")

            if accX is None or accY is None or accZ is None: return

            g_conversion = 9.80665
            accX_ms2 = accX * g_conversion
            accY_ms2 = accY * g_conversion
            # Giả sử cảm biến WITMOTION, Z quy về 0 khi nằm yên
            # Nếu là cảm biến khác, có thể cần logic khác
            accZ_ms2 = (accZ - 1.0) * g_conversion if sds['config']['type'] == "wit_motion_imu" else accZ * g_conversion


            fft_buffer_size = self.N_FFT_POINTS * 2 # Giữ lại buffer lớn hơn một chút cho FFT
            sds['raw_acc']['x'] = np.append(sds['raw_acc']['x'], accX_ms2)[-fft_buffer_size:]
            sds['raw_acc']['y'] = np.append(sds['raw_acc']['y'], accY_ms2)[-fft_buffer_size:]
            sds['raw_acc']['z'] = np.append(sds['raw_acc']['z'], accZ_ms2)[-fft_buffer_size:]

            sds['acc_input_buffers']['x'].append(accX_ms2)
            sds['acc_input_buffers']['y'].append(accY_ms2)
            sds['acc_input_buffers']['z'].append(accZ_ms2)
            
            current_frame_size = sds['config']['sample_frame_size']

            if len(sds['acc_input_buffers']['x']) >= current_frame_size:
                frames = {}
                for axis in ['x', 'y', 'z']:
                    frames[axis] = np.array(sds['acc_input_buffers'][axis][:current_frame_size])
                    sds['acc_input_buffers'][axis] = sds['acc_input_buffers'][axis][current_frame_size:]

                disp_f, vel_f, acc_f_filtered = {}, {}, {}
                for axis in ['x', 'y', 'z']:
                    disp_f[axis], vel_f[axis], acc_f_filtered[axis] = \
                        sds['kinematic_processors'][axis].process_frame(frames[axis])

                num_samples_in_frame = len(acc_f_filtered['x']) # Giả sử các trục trả về cùng số mẫu
                
                # Phải dùng dt của sensor này
                dt_this_sensor = sds['config']['dt']
                new_times_segment = np.arange(
                    sds['current_time_plot'],
                    sds['current_time_plot'] + num_samples_in_frame * dt_this_sensor,
                    dt_this_sensor
                )[:num_samples_in_frame]

                if not new_times_segment.size: return

                sds['current_time_plot'] += num_samples_in_frame * dt_this_sensor
                sds['time_data'] = np.append(sds['time_data'], new_times_segment)

                for axis in ['x', 'y', 'z']:
                    sds['processed_acc'][axis] = np.append(sds['processed_acc'][axis], acc_f_filtered[axis])
                    sds['processed_vel'][axis] = np.append(sds['processed_vel'][axis], vel_f[axis])
                    sds['processed_disp'][axis] = np.append(sds['processed_disp'][axis], disp_f[axis])
                
                self._trim_data_arrays_for_sensor(sensor_id)
                # self.processedDataUpdated.emit(sensor_id) # Thông báo cho UI

        except Exception as e:
            logger.error(f"Error processing data for sensor {sensor_id}: {e}", exc_info=True)


    def _trim_data_arrays_for_sensor(self, sensor_id, max_points=2000):
        sds = self._sensor_data_store.get(sensor_id)
        if not sds: return

        data_arrays_to_trim_keys = [
            ('time_data', None),
            ('processed_acc', 'x'), ('processed_acc', 'y'), ('processed_acc', 'z'),
            ('processed_vel', 'x'), ('processed_vel', 'y'), ('processed_vel', 'z'),
            ('processed_disp', 'x'), ('processed_disp', 'y'), ('processed_disp', 'z'),
        ]
        
        current_min_len = -1

        for key1, key2 in data_arrays_to_trim_keys:
            arr = sds[key1] if key2 is None else sds[key1][key2]
            if hasattr(arr, '__len__'):
                if current_min_len == -1 or len(arr) < current_min_len:
                    current_min_len = len(arr)
        
        if current_min_len == -1: return # Không có mảng nào để trim

        if current_min_len > max_points:
            slice_start = current_min_len - max_points # Giữ lại max_points cuối cùng
            
            sds['time_data'] = sds['time_data'][slice_start:]
            for axis in ['x', 'y', 'z']:
                sds['processed_acc'][axis] = sds['processed_acc'][axis][slice_start:]
                sds['processed_vel'][axis] = sds['processed_vel'][axis][slice_start:]
                sds['processed_disp'][axis] = sds['processed_disp'][axis][slice_start:]


    def calculate_fft_for_sensor(self, sensor_id):
        sds = self._sensor_data_store.get(sensor_id)
        if not sds: return
        
        dt_sensor = sds['config']['dt']
        if dt_sensor <= 0: return

        new_dominant_freqs = {}
        for axis in ['x', 'y', 'z']:
            acc_data_axis = sds['raw_acc'][axis]
            if len(acc_data_axis) >= self.N_FFT_POINTS:
                segment_for_fft = acc_data_axis[-self.N_FFT_POINTS:]
                hanning_window = windows.hann(self.N_FFT_POINTS)
                segment_windowed = segment_for_fft * hanning_window

                yf = rfft(segment_windowed)
                xf = rfftfreq(self.N_FFT_POINTS, dt_sensor)
                
                if len(xf) > 1 and len(yf) > 1: # Bỏ qua thành phần DC
                    amplitude_spectrum = np.abs(yf[1:])
                    freq_axis_fft = xf[1:]

                    if amplitude_spectrum.size > 0:
                        sds['fft_plot_data'][axis]['freq'] = freq_axis_fft
                        sds['fft_plot_data'][axis]['amp'] = amplitude_spectrum

                        # Tìm tần số trội (bỏ qua các tần số quá thấp)
                        min_freq_idx = np.where(freq_axis_fft >= 0.1)[0] # Tần số từ 0.1 Hz trở lên
                        if min_freq_idx.size > 0:
                            start_idx = min_freq_idx[0]
                            if start_idx < len(amplitude_spectrum): # Đảm bảo start_idx hợp lệ
                                peak_idx = np.argmax(amplitude_spectrum[start_idx:]) + start_idx
                                dominant_freq = freq_axis_fft[peak_idx]
                                new_dominant_freqs[axis] = dominant_freq
                            else: # Không có peak hợp lệ
                                new_dominant_freqs[axis] = 0
                                sds['fft_plot_data'][axis]['freq'] = None
                                sds['fft_plot_data'][axis]['amp'] = None
                        else: # Không có tần số nào > 0.1 Hz
                            new_dominant_freqs[axis] = 0
                            sds['fft_plot_data'][axis]['freq'] = None
                            sds['fft_plot_data'][axis]['amp'] = None
                    else: # Spectrum rỗng
                        new_dominant_freqs[axis] = 0
                        sds['fft_plot_data'][axis]['freq'] = None
                        sds['fft_plot_data'][axis]['amp'] = None
                else: # Kết quả rfft không hợp lệ
                    new_dominant_freqs[axis] = 0
                    sds['fft_plot_data'][axis]['freq'] = None
                    sds['fft_plot_data'][axis]['amp'] = None
            else: # Không đủ dữ liệu
                new_dominant_freqs[axis] = sds['dominant_freqs'].get(axis, 0)
        
        if new_dominant_freqs:
            sds['dominant_freqs'].update(new_dominant_freqs)
            # self.dominantFrequenciesUpdated.emit(sensor_id, sds['dominant_freqs'])


    def get_plot_data_for_sensor(self, sensor_id):
        sds = self._sensor_data_store.get(sensor_id)
        if not sds:
            return { # Trả về cấu trúc rỗng để tránh lỗi
                'time_data': np.array([]),
                'acc_data': {'x': np.array([]), 'y': np.array([]), 'z': np.array([])},
                'vel_data': {'x': np.array([]), 'y': np.array([]), 'z': np.array([])},
                'disp_data': {'x': np.array([]), 'y': np.array([]), 'z': np.array([])},
                'fft_data': {'x': {'freq': None, 'amp': None}, 'y': {'freq': None, 'amp': None}, 'z': {'freq': None, 'amp': None}},
                'dominant_freqs': {'x': 0, 'y': 0, 'z': 0}
            }
        return {
            'time_data': sds['time_data'],
            'acc_data': sds['processed_acc'],
            'vel_data': sds['processed_vel'],
            'disp_data': sds['processed_disp'],
            'fft_data': sds['fft_plot_data'],
            'dominant_freqs': sds['dominant_freqs']
        } 