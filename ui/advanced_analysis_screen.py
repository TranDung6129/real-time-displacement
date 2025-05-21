# ui/advanced_analysis_screen.py
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
                             QPushButton, QComboBox, QListWidget, QTableWidget,
                             QAbstractItemView, QSplitter, QDoubleSpinBox, QSpinBox,
                             QTabWidget, QSpacerItem, QSizePolicy, QHeaderView,
                             QDialog, QTreeWidget, QTreeWidgetItem, QDialogButtonBox, QTableWidgetItem,
                             QMessageBox)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
import pyqtgraph as pg
import numpy as np

# Giả sử bạn đã tạo các module phân tích
from analysis.statistical_tools import (calculate_descriptive_stats,
                                        calculate_correlation_matrix,
                                        calculate_histogram)
from analysis.spectral_tools import calculate_fft
from analysis.anomaly_detection_tools import (
    detect_outliers_zscore,
    detect_anomalies_moving_average,
    detect_sudden_changes
)
# from analysis.anomaly_detection_tools import ... (sẽ thêm sau)


class SelectFieldsDialog(QDialog):
    """Dialog cho phép người dùng chọn các trường dữ liệu để phân tích."""
    # Signal: fields_selected(list_of_selected_field_keys)
    fields_selected_signal = pyqtSignal(list)

    def __init__(self, data_processor, previously_selected_keys=None, parent=None):
        super().__init__(parent)
        self.data_processor = data_processor
        self.previously_selected_keys = previously_selected_keys if previously_selected_keys else []
        self.setWindowTitle("Chọn Trường Dữ liệu Phân tích")
        self.setMinimumSize(400, 500)

        layout = QVBoxLayout(self)
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabel("Các trường dữ liệu có sẵn")
        self.populate_tree()
        layout.addWidget(self.tree_widget)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept_selection)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def populate_tree(self):
        self.tree_widget.clear()
        
        # Lấy dữ liệu từ DataProcessor
        plot_data = self.data_processor.get_plot_data()
        if not plot_data:
            return

        # Tạo node cho dữ liệu gia tốc
        acc_node = QTreeWidgetItem(self.tree_widget, ["Gia tốc"])
        for axis in ['x', 'y', 'z']:
            if f'acc_{axis}' in plot_data['acc_data']:
                item = QTreeWidgetItem(acc_node, [f"Acc{axis.upper()}"])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if f"Acc{axis.upper()}" in self.previously_selected_keys else Qt.CheckState.Unchecked)

        # Tạo node cho dữ liệu vận tốc
        vel_node = QTreeWidgetItem(self.tree_widget, ["Vận tốc"])
        for axis in ['x', 'y', 'z']:
            if f'vel_{axis}' in plot_data['vel_data']:
                item = QTreeWidgetItem(vel_node, [f"Vel{axis.upper()}"])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if f"Vel{axis.upper()}" in self.previously_selected_keys else Qt.CheckState.Unchecked)

        # Tạo node cho dữ liệu chuyển vị
        disp_node = QTreeWidgetItem(self.tree_widget, ["Chuyển vị"])
        for axis in ['x', 'y', 'z']:
            if f'disp_{axis}' in plot_data['disp_data']:
                item = QTreeWidgetItem(disp_node, [f"Disp{axis.upper()}"])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if f"Disp{axis.upper()}" in self.previously_selected_keys else Qt.CheckState.Unchecked)

        # Tạo node cho dữ liệu gia tốc thô (FFT)
        raw_acc_node = QTreeWidgetItem(self.tree_widget, ["Gia tốc thô (FFT)"])
        raw_acc_fields = {
            'acc_x_raw_for_fft': 'RawAccX_for_fft',
            'acc_y_raw_for_fft': 'RawAccY_for_fft',
            'acc_z_raw_for_fft': 'RawAccZ_for_fft'
        }
        for attr, field_name in raw_acc_fields.items():
            if hasattr(self.data_processor, attr) and getattr(self.data_processor, attr).size > 0:
                item = QTreeWidgetItem(raw_acc_node, [field_name])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if field_name in self.previously_selected_keys else Qt.CheckState.Unchecked)

        # Mở rộng tất cả các node
        for i in range(self.tree_widget.topLevelItemCount()):
            self.tree_widget.topLevelItem(i).setExpanded(True)

    def accept_selection(self):
        selected_keys = []
        root = self.tree_widget.invisibleRootItem()
        sensor_count = root.childCount()
        for i in range(sensor_count):
            sensor_node = root.child(i) # Ví dụ: "Cảm biến Hiện tại"
            # sensor_id = sensor_node.text(0) # Sẽ dùng khi có nhiều cảm biến
            field_count = sensor_node.childCount()
            for j in range(field_count):
                field_item = sensor_node.child(j)
                if field_item.checkState(0) == Qt.CheckState.Checked:
                    selected_keys.append(field_item.text(0)) # Key của trường dữ liệu
        
        self.fields_selected_signal.emit(selected_keys)
        self.accept()


class AnalysisWorker(QThread):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, analysis_type, data_dict, params=None):
        super().__init__()
        self.analysis_type = analysis_type
        self.data_dict = data_dict
        self.params = params or {}

    def run(self):
        try:
            if self.analysis_type == "descriptive_stats":
                result = calculate_descriptive_stats(self.data_dict)
            elif self.analysis_type == "correlation":
                result = calculate_correlation_matrix(self.data_dict)
            elif self.analysis_type == "histogram":
                result = calculate_histogram(
                    self.data_dict['data'],
                    num_bins=self.params.get('num_bins', 50)
                )
            elif self.analysis_type == "fft":
                result = calculate_fft(
                    self.data_dict['data'],
                    dt=self.params.get('dt', 0.005),
                    n_fft_points=self.params.get('n_fft_points', 512),
                    window_type=self.params.get('window_type', 'Hann')
                )
            elif self.analysis_type == "anomaly":
                method = self.params.get('method', 'Z-score')
                if method == "Z-score":
                    result = detect_outliers_zscore(
                        self.data_dict['data'],
                        threshold=self.params.get('threshold', 3.0)
                    )
                elif method == "Moving Average":
                    result = detect_anomalies_moving_average(
                        self.data_dict['data'],
                        window_size=self.params.get('window_size', 20),
                        threshold=self.params.get('threshold', 2.0)
                    )
                elif method == "Sudden Changes":
                    result = detect_sudden_changes(
                        self.data_dict['data'],
                        threshold=self.params.get('threshold', 2.0)
                    )
                else:
                    raise ValueError(f"Phương pháp không hợp lệ: {method}")
            else:
                raise ValueError(f"Loại phân tích không hợp lệ: {self.analysis_type}")

            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


TAB_ANALYSIS_TYPE_MAP = {
    "Thống kê Mô tả": "descriptive_stats",
    "Phân tích Tương quan": "correlation",
    "Phân tích Phân phối": "histogram",
    "FFT Chi tiết": "fft",
    "Phân tích Bất thường": "anomaly"
}

class AdvancedAnalysisScreenWidget(QWidget):
    def __init__(self, data_processor, parent=None):
        super().__init__(parent)
        self.data_processor = data_processor
        self.current_data_snapshot = None
        self.selected_analysis_fields = []
        self.analysis_worker = None
        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout(self) # QHBoxLayout cho splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Panel điều khiển bên trái ---
        left_panel_widget = QWidget()
        left_panel_layout = QVBoxLayout(left_panel_widget)
        left_panel_layout.setContentsMargins(5,5,5,5) # Thu nhỏ margins

        # 1. Nút chọn trường dữ liệu
        self.select_fields_button = QPushButton("Thêm/Sửa Trường Phân tích")
        self.select_fields_button.clicked.connect(self.open_select_fields_dialog)
        left_panel_layout.addWidget(self.select_fields_button)

        # 2. Danh sách các trường đã chọn để phân tích
        left_panel_layout.addWidget(QLabel("Các trường được chọn:"))
        self.selected_fields_list_widget = QListWidget()
        self.selected_fields_list_widget.setFixedHeight(150) # Giới hạn chiều cao
        left_panel_layout.addWidget(self.selected_fields_list_widget)

        # 3. Tùy chọn số điểm dữ liệu
        data_points_layout = QHBoxLayout()
        data_points_layout.addWidget(QLabel("Số điểm phân tích:"))
        self.num_data_points_spinbox = QSpinBox()
        self.num_data_points_spinbox.setMinimum(100) # Ví dụ
        self.num_data_points_spinbox.setMaximum(2000) # Giới hạn bằng max_points của DataProcessor
        self.num_data_points_spinbox.setValue(1000) # Giá trị mặc định
        data_points_layout.addWidget(self.num_data_points_spinbox)
        left_panel_layout.addLayout(data_points_layout)
        
        # 4. Nút tải dữ liệu
        self.load_data_button = QPushButton("Tải và Phân tích Dữ liệu")
        self.load_data_button.clicked.connect(self.load_and_analyze_data)
        left_panel_layout.addWidget(self.load_data_button)

        left_panel_layout.addStretch(1) # Đẩy các control lên trên
        left_panel_widget.setLayout(left_panel_layout)

        # --- Khu vực hiển thị kết quả phân tích bên phải (sử dụng QTabWidget) ---
        right_panel_widget = QWidget()
        right_panel_layout = QVBoxLayout(right_panel_widget)
        self.analysis_tabs = QTabWidget()

        # Tab 1: Thống kê Mô tả
        self.stats_tab = QWidget()
        self.stats_layout = QVBoxLayout(self.stats_tab)
        self.stats_table = QTableWidget()
        self.stats_layout.addWidget(self.stats_table)
        self.analysis_tabs.addTab(self.stats_tab, "Thống kê Mô tả")

        # Tab 2: Phân tích Tương quan
        self.correlation_tab = QWidget()
        self.correlation_layout = QVBoxLayout(self.correlation_tab)
        self.correlation_label = QLabel("Chọn ít nhất 2 trường để xem xét tương quan.")
        self.correlation_plot_widget = pg.ImageView()
        self.correlation_table = QTableWidget()
        self.correlation_layout.addWidget(self.correlation_label)
        self.correlation_layout.addWidget(self.correlation_plot_widget)
        self.correlation_layout.addWidget(QLabel("Ma trận tương quan:"))
        self.correlation_layout.addWidget(self.correlation_table)
        self.analysis_tabs.addTab(self.correlation_tab, "Phân tích Tương quan")

        # Tab 3: Phân tích Phân phối
        self.distribution_tab = QWidget()
        self.distribution_layout = QVBoxLayout(self.distribution_tab)
        self.dist_field_selector_combo = QComboBox()
        self.dist_plot_widget = pg.PlotWidget()
        self.dist_plot_widget.showGrid(x=True, y=True)
        self.distribution_layout.addWidget(QLabel("Chọn trường dữ liệu để xem phân phối:"))
        self.distribution_layout.addWidget(self.dist_field_selector_combo)
        self.distribution_layout.addWidget(self.dist_plot_widget)
        self.analysis_tabs.addTab(self.distribution_tab, "Phân tích Phân phối")

        # Tab 4: Phân tích FFT Chi tiết
        self.fft_detail_tab = QWidget()
        self.fft_detail_layout = QVBoxLayout(self.fft_detail_tab)
        self.fft_field_selector_combo = QComboBox()
        self.fft_plot_widget = pg.PlotWidget(title="Phân tích FFT Chi tiết")
        self.fft_plot_widget.setLabel('left', 'Amplitude')
        self.fft_plot_widget.setLabel('bottom', 'Frequency (Hz)')
        self.fft_plot_widget.showGrid(x=True, y=True)
        self.fft_detail_layout.addWidget(QLabel("Chọn trường dữ liệu (Gia tốc thô) để phân tích FFT:"))
        self.fft_detail_layout.addWidget(self.fft_field_selector_combo)
        self.fft_detail_layout.addWidget(self.fft_plot_widget)
        self.analysis_tabs.addTab(self.fft_detail_tab, "FFT Chi tiết")
        
        # Tab 5: Phân tích Bất thường (MỚI)
        self.anomaly_tab = QWidget()
        self.anomaly_layout = QVBoxLayout(self.anomaly_tab)
        # ... UI cho anomaly detection sẽ thêm ở đây ...
        self.anomaly_field_selector_combo = QComboBox()
        self.anomaly_method_combo = QComboBox()
        self.anomaly_method_combo.addItems(["Ngưỡng Cố định", "Z-score", "IQR"])
        self.anomaly_param1_input = QDoubleSpinBox() # Ví dụ: Ngưỡng, Z-score multiplier
        self.anomaly_param2_input = QDoubleSpinBox() # Ví dụ: Ngưỡng trên (nếu cần)
        self.anomaly_plot_widget = pg.PlotWidget(title="Phân tích Bất thường")
        self.anomaly_results_table = QTableWidget() # Hiển thị danh sách điểm bất thường

        self.anomaly_layout.addWidget(QLabel("Chọn trường dữ liệu:"))
        self.anomaly_layout.addWidget(self.anomaly_field_selector_combo)
        self.anomaly_layout.addWidget(QLabel("Phương pháp phát hiện:"))
        self.anomaly_layout.addWidget(self.anomaly_method_combo)
        # Thêm label và input cho các tham số tùy theo phương pháp
        self.anomaly_layout.addWidget(self.anomaly_param1_input)
        self.anomaly_layout.addWidget(self.anomaly_param2_input) # Có thể ẩn/hiện tùy phương pháp
        self.anomaly_layout.addWidget(self.anomaly_plot_widget)
        self.anomaly_layout.addWidget(QLabel("Danh sách điểm bất thường:"))
        self.anomaly_layout.addWidget(self.anomaly_results_table)
        self.analysis_tabs.addTab(self.anomaly_tab, "Phân tích Bất thường")


        self.analysis_tabs.currentChanged.connect(self.on_tab_changed)
        right_panel_layout.addWidget(self.analysis_tabs)
        right_panel_widget.setLayout(right_panel_layout)

        splitter.addWidget(left_panel_widget)
        splitter.addWidget(right_panel_widget)
        splitter.setStretchFactor(0, 1) # Panel trái nhỏ hơn
        splitter.setStretchFactor(1, 3) # Panel phải lớn hơn

        main_layout.addWidget(splitter)
        self.setLayout(main_layout)

    def open_select_fields_dialog(self):
        dialog = SelectFieldsDialog(self.data_processor, self.selected_analysis_fields, self)
        dialog.fields_selected_signal.connect(self.update_selected_analysis_fields)
        dialog.exec()

    def update_selected_analysis_fields(self, selected_keys):
        self.selected_analysis_fields = selected_keys
        self.selected_fields_list_widget.clear()
        self.selected_fields_list_widget.addItems(self.selected_analysis_fields)
        
        # Cập nhật lại các combobox chọn trường trong các tab phân tích
        self.dist_field_selector_combo.clear()
        self.fft_field_selector_combo.clear() # Sẽ chỉ thêm RawAcc
        self.anomaly_field_selector_combo.clear()

        if self.selected_analysis_fields:
            self.dist_field_selector_combo.addItems(self.selected_analysis_fields)
            self.anomaly_field_selector_combo.addItems(self.selected_analysis_fields)
            
            fft_candidates = [f for f in self.selected_analysis_fields if "RawAcc" in f]
            if not fft_candidates: # Nếu không có RawAcc nào được chọn, thêm mặc định nếu có trong snapshot
                if self.current_data_snapshot:
                     fft_candidates = [k for k in self.current_data_snapshot.keys() if "RawAcc" in k]
            self.fft_field_selector_combo.addItems(fft_candidates)


    def load_and_analyze_data(self):
        raw_data_from_dp = self.data_processor.get_plot_data()
        if not raw_data_from_dp or not raw_data_from_dp['time_data'].size:
            self.current_data_snapshot = None
            QMessageBox.warning(self, "Cảnh báo", "Không có dữ liệu từ DataProcessor.")
            self.clear_all_analysis_outputs()
            return

        num_points_to_use = self.num_data_points_spinbox.value()
        self.current_data_snapshot = {}
        
        time_data_full = raw_data_from_dp['time_data']
        actual_num_points = min(num_points_to_use, len(time_data_full))
        if actual_num_points == 0:
            self.current_data_snapshot = None
            QMessageBox.warning(self, "Cảnh báo", "Không có điểm dữ liệu nào sau khi cắt.")
            self.clear_all_analysis_outputs()
            return

        self.current_data_snapshot['time'] = np.copy(time_data_full[-actual_num_points:])

        # Các trường dữ liệu chính
        for dtype_key, data_map in {'acc': raw_data_from_dp['acc_data'],
                                   'vel': raw_data_from_dp['vel_data'],
                                   'disp': raw_data_from_dp['disp_data']}.items():
            for axis_key, axis_data_full in data_map.items():
                field_name = f"{dtype_key.capitalize()}{axis_key.upper()}"
                if len(axis_data_full) >= actual_num_points:
                    self.current_data_snapshot[field_name] = np.copy(axis_data_full[-actual_num_points:])
                elif len(axis_data_full) > 0 : # Nếu có ít hơn số điểm yêu cầu nhưng vẫn có dữ liệu
                    self.current_data_snapshot[field_name] = np.copy(axis_data_full)
                else:
                    self.current_data_snapshot[field_name] = np.array([])


        # Dữ liệu gia tốc thô cho FFT (lấy toàn bộ buffer có sẵn từ DP, rồi cắt sau nếu cần trong hàm FFT)
        # Hoặc cắt luôn tại đây theo actual_num_points nếu logic FFT dùng số điểm đó
        raw_acc_keys_map = {
            'RawAccX_for_fft': self.data_processor.acc_x_raw_for_fft, #
            'RawAccY_for_fft': self.data_processor.acc_y_raw_for_fft, #
            'RawAccZ_for_fft': self.data_processor.acc_z_raw_for_fft  #
        }
        for key, raw_data_full in raw_acc_keys_map.items():
            if len(raw_data_full) >= actual_num_points:
                 self.current_data_snapshot[key] = np.copy(raw_data_full[-actual_num_points:])
            elif len(raw_data_full) > 0:
                 self.current_data_snapshot[key] = np.copy(raw_data_full)
            else:
                 self.current_data_snapshot[key] = np.array([])

        print(f"Đã tải {actual_num_points} điểm dữ liệu để phân tích.")
        
        # Cập nhật các combobox chọn trường nếu danh sách selected_analysis_fields rỗng
        if not self.selected_analysis_fields:
            all_available_snapshot_keys = [k for k in self.current_data_snapshot.keys() if k != 'time']
            self.update_selected_analysis_fields(all_available_snapshot_keys) # Chọn tất cả mặc định nếu chưa chọn gì
        else:
            # Gọi lại để cập nhật combobox nếu selected_analysis_fields đã có từ trước
             self.update_selected_analysis_fields(self.selected_analysis_fields)


        self.on_tab_changed(self.analysis_tabs.currentIndex())

    def clear_all_analysis_outputs(self):
        """Xóa tất cả các kết quả phân tích trên các tab."""
        self.stats_table.setRowCount(0)
        self.stats_table.setColumnCount(0)
        self.correlation_plot_widget.clear()
        self.correlation_table.setRowCount(0)
        self.correlation_table.setColumnCount(0)
        if hasattr(self.dist_plot_widget, 'clear'): self.dist_plot_widget.clear() # PlotWidget
        if hasattr(self.fft_plot_widget, 'clear'): self.fft_plot_widget.clear()
        if hasattr(self.anomaly_plot_widget, 'clear'): self.anomaly_plot_widget.clear()
        self.anomaly_results_table.setRowCount(0)
        self.anomaly_results_table.setColumnCount(0)


    def get_selected_data_from_snapshot(self):
        """Lấy dữ liệu từ snapshot dựa trên self.selected_analysis_fields, đảm bảo tất cả các trường có cùng độ dài nhỏ nhất."""
        if self.current_data_snapshot is None or not self.selected_analysis_fields:
            return None, None

        # Tìm min_len của tất cả các trường được chọn (kể cả time)
        lengths = [self.current_data_snapshot.get('time', np.array([])).size]
        for field_key in self.selected_analysis_fields:
            if field_key in self.current_data_snapshot:
                lengths.append(self.current_data_snapshot[field_key].size)
        min_len = min(lengths) if lengths else 0

        data_to_analyze = {}
        for field_key in self.selected_analysis_fields:
            if field_key in self.current_data_snapshot and self.current_data_snapshot[field_key].size >= min_len and min_len > 0:
                data_to_analyze[field_key] = self.current_data_snapshot[field_key][:min_len]

        if not data_to_analyze:
            return None, None

        time_vector = self.current_data_snapshot['time'][:min_len] if 'time' in self.current_data_snapshot else np.array([])
        return time_vector, data_to_analyze
        

    def on_tab_changed(self, index):
        if self.current_data_snapshot is None:
            QMessageBox.information(self, "Thông báo", "Vui lòng nhấn 'Tải và Phân tích Dữ liệu' trước.")
            self.clear_all_analysis_outputs()
            return

        time_vector, data_for_current_tab = self.get_selected_data_from_snapshot()

        if data_for_current_tab is None or (time_vector is not None and time_vector.size == 0):
            QMessageBox.warning(self, "Cảnh báo", "Không có dữ liệu hợp lệ được chọn hoặc tải để phân tích.")
            self.clear_all_analysis_outputs()
            return

        active_tab_title = self.analysis_tabs.tabText(index)
        analysis_type = TAB_ANALYSIS_TYPE_MAP.get(active_tab_title)
        if not analysis_type:
            QMessageBox.critical(self, "Lỗi", f"Không xác định được loại phân tích cho tab: {active_tab_title}")
            return

        # Tạo worker mới cho phân tích
        if self.analysis_worker and self.analysis_worker.isRunning():
            self.analysis_worker.terminate()
            self.analysis_worker.wait()

        # Chuẩn bị tham số cho worker
        params = {}
        if analysis_type == "fft":
            selected_field = self.fft_field_selector_combo.currentText()
            if selected_field and selected_field in self.current_data_snapshot:
                params = {
                    'dt': self.data_processor.dt_sensor_for_fft_analysis if hasattr(self.data_processor, 'dt_sensor_for_fft_analysis') else 0.005,
                    'n_fft_points': self.data_processor.N_FFT_POINTS,
                    'window_type': 'Hann'
                }
                data_for_current_tab = {'data': self.current_data_snapshot[selected_field]}
        elif analysis_type == "anomaly":
            selected_field = self.anomaly_field_selector_combo.currentText()
            if selected_field and selected_field in self.current_data_snapshot:
                data_for_current_tab = {'data': self.current_data_snapshot[selected_field]}
        elif analysis_type == "histogram":
            selected_field = self.dist_field_selector_combo.currentText()
            if selected_field and selected_field in self.current_data_snapshot:
                data_for_current_tab = {'data': self.current_data_snapshot[selected_field]}

        self.analysis_worker = AnalysisWorker(analysis_type, data_for_current_tab, params)
        self.analysis_worker.finished.connect(lambda result: self.handle_analysis_result(active_tab_title, result))
        self.analysis_worker.error.connect(lambda msg: QMessageBox.critical(self, "Lỗi", f"Lỗi phân tích: {msg}"))
        self.analysis_worker.start()

    def handle_analysis_result(self, analysis_type, result):
        if analysis_type == "Thống kê Mô tả":
            self.display_descriptive_stats(result)
        elif analysis_type == "Phân tích Tương quan":
            corr_matrix, field_names = result
            self.display_correlation_analysis(corr_matrix, field_names)
        elif analysis_type == "Phân tích Phân phối":
            hist_data, bin_edges = result
            selected_field = self.dist_field_selector_combo.currentText()
            self.display_distribution_analysis(hist_data, bin_edges, selected_field)
        elif analysis_type == "FFT Chi tiết":
            fft_freq, fft_amp = result
            selected_field = self.fft_field_selector_combo.currentText()
            self.display_detailed_fft(fft_freq, fft_amp, selected_field)
        elif analysis_type == "Phân tích Bất thường":
            anomaly_indices, anomaly_values = result
            selected_field = self.anomaly_field_selector_combo.currentText()
            self.display_anomaly_results(anomaly_indices, anomaly_values, selected_field)

    def display_anomaly_results(self, anomaly_indices, anomaly_values, field_name):
        # Vẽ đường dữ liệu gốc
        time_vector = self.current_data_snapshot['time']
        selected_field = self.anomaly_field_selector_combo.currentText()
        data_array = self.current_data_snapshot[selected_field] if selected_field in self.current_data_snapshot else None

        self.anomaly_plot_widget.clear()
        if data_array is not None:
            self.anomaly_plot_widget.plot(time_vector, data_array, pen='b', name='Dữ liệu gốc')

        # Vẽ các điểm bất thường
        if len(anomaly_indices) > 0:
            self.anomaly_plot_widget.plot(
                time_vector[anomaly_indices],
                anomaly_values,
                pen=None,
                symbol='o',
                symbolBrush='r',
                name='Bất thường'
            )

            self.anomaly_results_table.setRowCount(len(anomaly_indices))
            self.anomaly_results_table.setColumnCount(3)
            self.anomaly_results_table.setHorizontalHeaderLabels(["Thời gian", "Giá trị", "Chỉ số"])

            for i, idx in enumerate(anomaly_indices):
                self.anomaly_results_table.setItem(i, 0, QTableWidgetItem(f"{self.current_data_snapshot['time'][idx]:.3f}"))
                self.anomaly_results_table.setItem(i, 1, QTableWidgetItem(f"{anomaly_values[i]:.4f}"))
                self.anomaly_results_table.setItem(i, 2, QTableWidgetItem(str(idx)))

            self.anomaly_results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            QMessageBox.information(self, "Thông báo", f"Đã phát hiện {len(anomaly_indices)} điểm bất thường.")
        else:
            QMessageBox.information(self, "Thông báo", "Không phát hiện điểm bất thường nào.")

        # Thêm legend nếu chưa có
        if not hasattr(self.anomaly_plot_widget, '_legend') or self.anomaly_plot_widget._legend is None:
            self.anomaly_plot_widget.addLegend()

    # --- Các hàm hiển thị (Display functions) ---
    def display_descriptive_stats(self, stats_result_list):
        if not stats_result_list:
            self.stats_table.setRowCount(0)
            return

        metrics = [row['Metric'] for row in stats_result_list]
        field_names = [k for k in stats_result_list[0].keys() if k != 'Metric']

        self.stats_table.setRowCount(len(metrics))
        self.stats_table.setColumnCount(len(field_names))
        self.stats_table.setVerticalHeaderLabels(metrics)
        self.stats_table.setHorizontalHeaderLabels(field_names)

        for r_idx, row in enumerate(stats_result_list):
            for c_idx, field_name in enumerate(field_names):
                value = row.get(field_name, "N/A")
                item_text = f"{value:.4f}" if isinstance(value, (float, np.float64)) else str(value)
                self.stats_table.setItem(r_idx, c_idx, QTableWidgetItem(item_text))
        self.stats_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)


    def display_correlation_analysis(self, corr_matrix, field_names):
        if corr_matrix is None or not field_names:
            self.correlation_plot_widget.clear()
            self.correlation_table.setRowCount(0)
            self.correlation_table.setColumnCount(0)
            return
        
        self.correlation_plot_widget.setImage(corr_matrix.T, autoLevels=True)
        # Cần cải thiện việc đặt ticks cho heatmap (hiện ImageView không hỗ trợ trực tiếp tốt)
        # Có thể xem xét dùng pg.ImageItem trong một pg.PlotItem nếu cần ticks.

        self.correlation_table.setRowCount(len(field_names))
        self.correlation_table.setColumnCount(len(field_names))
        self.correlation_table.setHorizontalHeaderLabels(field_names)
        self.correlation_table.setVerticalHeaderLabels(field_names)

        for i in range(len(field_names)):
            for j in range(len(field_names)):
                self.correlation_table.setItem(i, j, QTableWidgetItem(f"{corr_matrix[i, j]:.4f}"))
        self.correlation_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    def display_distribution_analysis(self, hist_data, bin_edges, field_name):
        if hist_data is None or bin_edges is None:
            self.dist_plot_widget.clear()
            return
        
        bar_graph = pg.BarGraphItem(x=bin_edges[:-1], height=hist_data, width=(bin_edges[1]-bin_edges[0])*0.9, brush='b')
        self.dist_plot_widget.clear()
        self.dist_plot_widget.addItem(bar_graph)
        self.dist_plot_widget.setTitle(f"Phân phối của {field_name}")

    def display_detailed_fft(self, fft_freq, fft_amp, field_name):
        if fft_freq is None or fft_amp is None:
            self.fft_plot_widget.clear()
            return
        
            self.fft_plot_widget.clear()
        self.fft_plot_widget.plot(fft_freq, fft_amp, pen='r')
        self.fft_plot_widget.setTitle(f"FFT của {field_name}")