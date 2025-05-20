# Real-time Displacement Monitoring System

Hệ thống theo dõi chuyển vị thời gian thực sử dụng cảm biến gia tốc WITMOTION.

## Tính năng

- Hiển thị đồ thị gia tốc, vận tốc và chuyển vị theo thời gian thực
- Phân tích FFT để xác định tần số đặc trưng
- Hỗ trợ kết nối cảm biến thật và dữ liệu giả lập
- Giao diện đa tab dễ sử dụng
- Điều chỉnh tốc độ hiển thị

## Cài đặt

1. Clone repository:
```bash
git clone https://github.com/your-username/real-time-displacement.git
cd real-time-displacement
```

2. Tạo môi trường ảo và cài đặt các thư viện:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# hoặc
venv\Scripts\activate  # Windows

pip install -r requirements.txt
```

## Sử dụng

1. Kết nối cảm biến WITMOTION qua cổng USB
2. Chạy ứng dụng:
```bash
python main.py
```

3. Trong tab "Quản lý Cảm biến":
   - Nhập cổng serial (ví dụ: /dev/ttyUSB0 cho Linux, COM3 cho Windows)
   - Nhập baudrate (mặc định: 115200)
   - Nhấn "Kết nối Cảm biến" hoặc "Dữ liệu Giả lập"

4. Trong tab "Thiết lập":
   - Điều chỉnh tốc độ hiển thị (10-200 Hz)

## Cấu trúc dự án

```
real-time-displacement/
├── algorithm/          # Các thuật toán xử lý tín hiệu
├── sensor/            # Xử lý dữ liệu cảm biến
├── ui/                # Giao diện người dùng
├── workers/           # Xử lý đa luồng
├── core/              # Xử lý dữ liệu và đồ thị
└── main.py           # Điểm khởi đầu ứng dụng
```

## Yêu cầu hệ thống

- Python 3.8+
- PyQt6
- pyqtgraph
- numpy
- scipy
- pyserial

## Giấy phép

MIT License 