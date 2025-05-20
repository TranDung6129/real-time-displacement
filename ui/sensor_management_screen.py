# ui/sensor_management_screen.py
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton
from PyQt6.QtCore import pyqtSignal

class SensorManagementScreenWidget(QWidget):
    connect_requested = pyqtSignal(str, int, bool) # port, baudrate, use_mock
    disconnect_requested = pyqtSignal()
    # mock_data_requested = pyqtSignal() # Gộp vào connect_requested

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        control_layout = QHBoxLayout()
        self.port_label = QLabel("Cổng Serial:")
        self.port_input = QLineEdit("/dev/ttyUSB0") # Hoặc "COM3" cho Windows
        self.baud_label = QLabel("Baudrate:")
        self.baud_input = QLineEdit("115200")
        self.connect_button = QPushButton("Kết nối Cảm biến")
        self.mock_button = QPushButton("Dữ liệu Giả lập")

        control_layout.addWidget(self.port_label)
        control_layout.addWidget(self.port_input)
        control_layout.addWidget(self.baud_label)
        control_layout.addWidget(self.baud_input)
        control_layout.addWidget(self.connect_button)
        control_layout.addWidget(self.mock_button)
        layout.addLayout(control_layout)

        self.status_label = QLabel("Trạng thái: Chưa kết nối")
        layout.addWidget(self.status_label)
        layout.addStretch(1) # Đẩy các control lên trên

        self.connect_button.clicked.connect(self.on_connect_button_clicked)
        self.mock_button.clicked.connect(self.on_mock_button_clicked)

        self.is_collecting = False

    def on_connect_button_clicked(self):
        if not self.is_collecting:
            port = self.port_input.text()
            try:
                baudrate = int(self.baud_input.text())
                self.connect_requested.emit(port, baudrate, False) # False for not using mock
            except ValueError:
                self.update_status("Lỗi: Baudrate phải là số.", False)
        else:
            self.disconnect_requested.emit()

    def on_mock_button_clicked(self):
        if not self.is_collecting:
            self.connect_requested.emit("", 0, True) # True for using mock
        else:
            # Có thể hiển thị thông báo nếu đang kết nối thật
            self.update_status("Đang kết nối, ngắt trước khi dùng mock.", False)

    def update_status(self, message, is_connected, is_collecting_now=None):
        self.status_label.setText(f"Trạng thái: {message}")
        self.status_label.setStyleSheet("color: green;" if is_connected else "color: red;")
        if is_collecting_now is not None:
            self.is_collecting = is_collecting_now
            if self.is_collecting:
                self.connect_button.setText("Ngắt kết nối")
                self.mock_button.setEnabled(False)
                self.port_input.setEnabled(False)
                self.baud_input.setEnabled(False)
            else:
                self.connect_button.setText("Kết nối Cảm biến")
                self.mock_button.setEnabled(True)
                self.port_input.setEnabled(True)
                self.baud_input.setEnabled(True) 