# ui/settings_screen.py
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox
from PyQt6.QtCore import pyqtSignal

class SettingsScreenWidget(QWidget):
    display_rate_changed = pyqtSignal(int) # rate_hz

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Layout tốc độ hiển thị
        frame_rate_layout = QHBoxLayout()
        self.frame_rate_label = QLabel("Tốc độ hiển thị (Hz):")
        self.frame_rate_combo = QComboBox()
        frame_rates = [10, 20, 50, 100, 200] # Các tùy chọn tốc độ
        for rate in frame_rates:
            self.frame_rate_combo.addItem(f"{rate} Hz", rate)

        default_rate_index = 0 # Mặc định 10Hz
        if 10 in frame_rates: # Đảm bảo giá trị mặc định có trong danh sách
             default_rate_index = frame_rates.index(10)
        self.frame_rate_combo.setCurrentIndex(default_rate_index)

        self.frame_rate_combo.currentIndexChanged.connect(self.on_display_rate_changed)

        frame_rate_layout.addWidget(self.frame_rate_label)
        frame_rate_layout.addWidget(self.frame_rate_combo)
        frame_rate_layout.addStretch(1)

        layout.addLayout(frame_rate_layout)
        layout.addStretch(1) # Đẩy các control lên trên

    def on_display_rate_changed(self):
        rate_hz = self.frame_rate_combo.currentData()
        if rate_hz:
            self.display_rate_changed.emit(rate_hz)

    def get_current_display_rate(self):
        return self.frame_rate_combo.currentData() 