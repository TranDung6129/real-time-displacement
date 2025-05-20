# rls_flt_disp_revised.py
import numpy as np
import logging
# import matplotlib.pyplot as plt # Loại bỏ matplotlib
# from scipy.integrate import cumtrapz # cumtrapz không được sử dụng trong phiên bản trước

logger = logging.getLogger(__name__)

class RealTimeAccelerationIntegrator:
    """
    Tích hợp gia tốc thành vận tốc và vị trí trong thời gian thực
    sử dụng bộ lọc recursive least squares (RLS) để khử nhiễu và trôi dữ liệu
    """
    
    def __init__(self, sample_frame_size=20, calc_frame_multiplier=100, dt=0.005, filter_q=0.9825):
        """
        Khởi tạo bộ tích hợp gia tốc
        
        Tham số:
        * sample_frame_size: Số mẫu trong một frame xử lý
        * calc_frame_multiplier: Bội số frame tính toán so với sample_frame 
                               (sử dụng cho buffer nội bộ lớn hơn)
        * dt: khoảng thời gian giữa các mẫu gia tốc (giây)
        * filter_q: Hệ số quên (forgetting factor) cho bộ lọc RLS, giá trị gần 1 
                   sẽ giảm khả năng phản ứng nhưng tăng độ bền nhiễu
        """
        self.sample_frame_size = sample_frame_size
        self.calc_frame_multiplier = calc_frame_multiplier
        self.calc_frame_size = sample_frame_size * calc_frame_multiplier
        self.dt = dt
        self.filter_q = filter_q
        
        # Khởi tạo các buffer tính toán
        self.acc_buffer = np.zeros(self.calc_frame_size)
        self.vel_buffer = np.zeros(self.calc_frame_size)
        self.disp_buffer = np.zeros(self.calc_frame_size)
        
        # Các biến theo dõi trạng thái
        self.frame_count = 0
        self.is_initialized = False
        
        # Ma trận hiệp phương sai ban đầu cho RLS
        self.P = np.eye(2) * 1000
        # Bộ lọc ước lượng ban đầu (hệ số a và b trong mô hình v = a*t + b)
        self.theta = np.zeros(2)
        
        # Làm ấm bộ lọc
        self.warmup_frames = 5  # Giảm từ 10 xuống 5 frames để hiển thị kết quả nhanh hơn
        
        logger.info(f"Đã khởi tạo RLS Integrator: dt={dt}, frame_size={sample_frame_size}, "
                   f"calc_buffer={self.calc_frame_size}, q={filter_q}")
    
    def is_warmed_up(self):
        """Kiểm tra xem bộ lọc đã 'làm ấm' đủ chưa để cung cấp kết quả tin cậy"""
        return self.frame_count >= self.warmup_frames
    
    def reset(self):
        """Reset bộ tích hợp"""
        self.acc_buffer = np.zeros(self.calc_frame_size)
        self.vel_buffer = np.zeros(self.calc_frame_size)
        self.disp_buffer = np.zeros(self.calc_frame_size)
        self.frame_count = 0
        self.is_initialized = False
        self.P = np.eye(2) * 1000
        self.theta = np.zeros(2)
        
    def _remove_linear_trend(self, data, t):
        """
        Loại bỏ xu hướng tuyến tính từ mảng dữ liệu bằng RLS
        """
        n = len(data)
        for i in range(n):
            # Tạo vector đầu vào: [t, 1] - mô hình tuyến tính y = a*t + b
            phi = np.array([t[i], 1.0])
            
            # Dự đoán giá trị với các thông số hiện tại
            y_pred = np.dot(self.theta, phi)
            
            # Tính toán sai số dự đoán
            e = data[i] - y_pred
            
            # Cập nhật gain vector
            # Công thức: k = P*phi / (q + phi^T * P * phi)
            P_phi = np.dot(self.P, phi)
            denom = self.filter_q + np.dot(phi, P_phi)
            k = P_phi / denom
            
            # Cập nhật các tham số
            # theta = theta + k * e
            self.theta = self.theta + k * e
            
            # Cập nhật ma trận hiệp phương sai
            # P = (P - k*phi^T*P) / q
            self.P = (self.P - np.outer(k, np.dot(phi, self.P))) / self.filter_q
        
        # Trả về tín hiệu đã khử xu hướng
        trend = np.zeros_like(data)
        for i in range(n):
            trend[i] = np.dot(self.theta, [t[i], 1.0])
        
        return data - trend, trend
    
    def integrate_acceleration(self, acc_data):
        """
        Tích phân gia tốc thành vận tốc và vị trí
        kết hợp với bộ lọc khử xu hướng RLS
        """
        n = len(acc_data)
        
        # Tạo mảng thời gian
        t = np.arange(0, n*self.dt, self.dt)
        
        # Tích phân gia tốc thành vận tốc sử dụng phương pháp tích phân hình thang
        vel = np.zeros(n)
        for i in range(1, n):
            vel[i] = vel[i-1] + (acc_data[i-1] + acc_data[i]) * self.dt / 2
        
        # Loại bỏ xu hướng dài hạn khỏi vận tốc sử dụng bộ lọc RLS
        vel_detrended, vel_trend = self._remove_linear_trend(vel, t)
        
        # Tích phân vận tốc đã lọc thành vị trí
        disp = np.zeros(n)
        for i in range(1, n):
            disp[i] = disp[i-1] + (vel_detrended[i-1] + vel_detrended[i]) * self.dt / 2
        
        # Loại bỏ xu hướng dài hạn từ vị trí
        disp_detrended, disp_trend = self._remove_linear_trend(disp, t)
        
        return disp_detrended, vel_detrended, acc_data
    
    def process_frame(self, acc_frame):
        """
        Xử lý một frame gia tốc mới và trả về 
        vị trí, vận tốc và gia tốc đã lọc
        
        Dữ liệu trả về chỉ tương ứng với frame đầu vào
        """
        frame_len = len(acc_frame)
        if frame_len > self.sample_frame_size:
            logger.warning(f"Kích thước frame ({frame_len}) lớn hơn sample_frame_size ({self.sample_frame_size}). Sẽ cắt bớt.")
            acc_frame = acc_frame[:self.sample_frame_size]
            frame_len = self.sample_frame_size
            
        # Cập nhật frame thứ mấy để theo dõi warm-up
        self.frame_count += 1
            
        # Dịch buffer hiện tại để thêm dữ liệu mới
        self.acc_buffer = np.roll(self.acc_buffer, -frame_len)
        # Thêm dữ liệu mới vào cuối buffer
        self.acc_buffer[-frame_len:] = acc_frame
        
        # Chỉ xử lý khi có đủ dữ liệu
        if self.frame_count >= 1:
            # Tích hợp toàn bộ buffer
            disp_buffer, vel_buffer, acc_filtered = self.integrate_acceleration(self.acc_buffer)
            
            # Cập nhật các buffer
            self.vel_buffer = vel_buffer
            self.disp_buffer = disp_buffer
            
            # Trả về chỉ phần dữ liệu mới nhất tương ứng với frame đầu vào
            return disp_buffer[-frame_len:], vel_buffer[-frame_len:], acc_filtered[-frame_len:]
        else:
            # Nếu chưa có đủ dữ liệu, trả về mảng NaN
            return np.full(frame_len, np.nan), np.full(frame_len, np.nan), acc_frame

    # Các hàm get_results và plot_results có thể được loại bỏ nếu không dùng trong ứng dụng live
    # Hoặc giữ lại để debug nếu cần
    def get_cumulative_results(self): # Đổi tên để tránh nhầm lẫn
        # Phương thức này đã không còn phù hợp vì không có các thuộc tính cần thiết
        # Trả về các buffer hiện tại thay vì thuộc tính không tồn tại
        t = np.arange(0, len(self.acc_buffer) * self.dt, self.dt)
        return t, self.disp_buffer, self.vel_buffer, self.acc_buffer