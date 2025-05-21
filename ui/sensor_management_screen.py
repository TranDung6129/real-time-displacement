# ui/sensor_management_screen.py
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                           QFrame, QPushButton, QTableWidget, QTableWidgetItem,
                           QComboBox, QLineEdit, QFormLayout, QMessageBox,
                           QGroupBox, QDialog, QDialogButtonBox, QHeaderView,
                           QSpacerItem, QSizePolicy, QGridLayout, QTextEdit,
                           QMenu, QSplitter)
from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal, QSize
from PyQt6.QtGui import QIcon, QAction

import logging
import psutil
import json
import uuid
import pyqtgraph as pg
import serial.tools.list_ports

logger = logging.getLogger(__name__)

# --- Dialog Chi tiết Cảm biến (SensorDetailDialog) ---
class SensorDetailDialog(QDialog):
    def __init__(self, sensor_info, sensor_data_raw, parent=None):
        super().__init__(parent)
        sensor_name = sensor_info.get('config', {}).get('name', sensor_info.get('id', 'N/A'))
        self.setWindowTitle(f"Chi tiết Cảm biến: {sensor_name}")
        self.setMinimumSize(550, 450)

        layout = QVBoxLayout(self)

        form_layout = QFormLayout()
        form_layout.addRow("ID Cảm biến:", QLabel(str(sensor_info.get('id', 'N/A'))))
        form_layout.addRow("Tên Cảm biến:", QLabel(str(sensor_name)))
        form_layout.addRow("Loại Cảm biến:", QLabel(str(sensor_info.get('type', 'N/A'))))
        form_layout.addRow("Trạng thái:", QLabel("Đã kết nối" if sensor_info.get('connected') else "Chưa kết nối"))
        
        config = sensor_info.get('config', {})
        form_layout.addRow("Giao thức:", QLabel(str(config.get('protocol', 'N/A'))))
        form_layout.addRow("Cổng/Địa chỉ:", QLabel(str(config.get('port_address', 'N/A'))))
        
        for key, value in config.items():
            if key not in ['protocol', 'port_address', 'name']:
                 form_layout.addRow(f"Cấu hình ({key}):", QLabel(str(value)))
        layout.addLayout(form_layout)

        data_group = QGroupBox("Dữ liệu Raw Gần nhất")
        data_layout = QVBoxLayout(data_group)
        self.raw_data_display = QTextEdit()
        self.raw_data_display.setReadOnly(True)
        self.raw_data_display.setFontFamily("Courier New")
        
        if sensor_data_raw:
            try:
                pretty_json = json.dumps(sensor_data_raw, indent=4, ensure_ascii=False)
                self.raw_data_display.setText(pretty_json)
            except TypeError:
                self.raw_data_display.setText(str(sensor_data_raw))
        else:
            self.raw_data_display.setText("Không có dữ liệu gần nhất hoặc cảm biến chưa kết nối.")
            
        data_layout.addWidget(self.raw_data_display)
        layout.addWidget(data_group)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)

# --- Dialog Thêm Cảm biến (AddSensorDialog) ---
class AddSensorDialog(QDialog):
    def __init__(self, sensor_manager, parent=None):
        super().__init__(parent)
        self.sensor_manager = sensor_manager
        self.setWindowTitle("Thêm Cảm biến Mới")
        self.setMinimumWidth(450)

        self.layout = QVBoxLayout(self)
        self.form_layout = QFormLayout()

        self.sensor_name_input = QLineEdit()
        self.sensor_name_input.setPlaceholderText("Ví dụ: Cảm biến nhiệt phòng lab")
        self.form_layout.addRow("Tên Cảm biến (*):", self.sensor_name_input)

        self.sensor_id_input = QLineEdit()
        self.sensor_id_input.setPlaceholderText("Để trống để tự tạo ID duy nhất")
        self.form_layout.addRow("ID Cảm biến:", self.sensor_id_input)

        self.sensor_type_combo = QComboBox()
        if self.sensor_manager:
            self.sensor_type_combo.addItems(self.sensor_manager.get_available_sensor_types())
        else:
            self.sensor_type_combo.addItems(["wit_motion_imu", "mock_sensor", "accelerometer", "temperature"])
        self.sensor_type_combo.currentTextChanged.connect(self._update_specific_config_fields)
        self.form_layout.addRow("Loại Cảm biến (*):", self.sensor_type_combo)

        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems(["UART", "TCP/IP", "UDP", "Bluetooth", "Mock"])
        self.protocol_combo.currentTextChanged.connect(self._update_connection_fields)
        self.form_layout.addRow("Giao thức Kết nối (*):", self.protocol_combo)
        
        self.connection_details_group = QGroupBox("Chi tiết Kết nối Giao thức")
        self.connection_details_layout = QFormLayout()
        self.connection_details_group.setLayout(self.connection_details_layout)
        self.form_layout.addRow(self.connection_details_group)

        self.specific_config_group = QGroupBox("Cấu hình Đặc thù Loại Cảm biến")
        self.specific_config_layout = QFormLayout()
        self.specific_config_group.setLayout(self.specific_config_layout)
        self.form_layout.addRow(self.specific_config_group)
        
        self.sampling_rate_input = QLineEdit()
        self.sampling_rate_input.setPlaceholderText("Ví dụ: 100 (Hz), nếu cảm biến hỗ trợ")
        self.form_layout.addRow("Tốc độ lấy mẫu (Hz):", self.sampling_rate_input)

        self.layout.addLayout(self.form_layout)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept_and_validate)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)

        self.current_connection_widgets = {}
        self.current_specific_config_widgets = {}

        self._update_connection_fields()
        self._update_specific_config_fields()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            sub_layout = item.layout()
            if sub_layout:
                while sub_layout.count():
                    child_item = sub_layout.takeAt(0)
                    child_widget = child_item.widget()
                    if child_widget:
                        child_widget.deleteLater()
                    child_layout = child_item.layout()
                    if child_layout:
                        self._clear_layout(child_layout)

    def _update_connection_fields(self):
        self._clear_layout(self.connection_details_layout)
        self.current_connection_widgets.clear()
        protocol = self.protocol_combo.currentText()

        if protocol == "UART":
            # Tạo QHBoxLayout để chứa ComboBox và Button
            port_entry_layout = QHBoxLayout()
            
            self.port_combo = QComboBox()
            self.port_combo.setMinimumWidth(200)
            self.refresh_ports_button = QPushButton("Làm mới")
            self.refresh_ports_button.clicked.connect(self.refresh_com_ports)

            port_entry_layout.addWidget(self.port_combo)
            port_entry_layout.addWidget(self.refresh_ports_button)
            port_entry_layout.addStretch(1)

            self.connection_details_layout.addRow("Cổng COM (*):", port_entry_layout)
            
            self.current_connection_widgets['port_address'] = self.port_combo
            
            self.baudrate_input = QComboBox()
            self.baudrate_input.addItems(["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"])
            self.baudrate_input.setCurrentText("115200")
            self.connection_details_layout.addRow("Tốc độ Baud (*):", self.baudrate_input)
            self.current_connection_widgets['baudrate'] = self.baudrate_input

        elif protocol in ["TCP/IP", "UDP"]:
            self.ip_address_input = QLineEdit()
            self.ip_address_input.setPlaceholderText("Ví dụ: 192.168.1.100")
            self.connection_details_layout.addRow("Địa chỉ IP (*):", self.ip_address_input)
            self.current_connection_widgets['ip_address'] = self.ip_address_input
            
            self.port_number_input = QLineEdit()
            self.port_number_input.setPlaceholderText("Ví dụ: 8080")
            self.connection_details_layout.addRow("Cổng (*):", self.port_number_input)
            self.current_connection_widgets['port_number'] = self.port_number_input
        elif protocol == "Bluetooth":
            self.mac_address_input = QLineEdit()
            self.mac_address_input.setPlaceholderText("Ví dụ: 00:1A:2B:3C:4D:5E")
            self.connection_details_layout.addRow("Địa chỉ MAC (*):", self.mac_address_input)
            self.current_connection_widgets['mac_address'] = self.mac_address_input
        elif protocol == "Mock":
             self.connection_details_layout.addRow(QLabel("Cảm biến Mock không yêu cầu chi tiết kết nối."))
        self.connection_details_group.setVisible(self.connection_details_layout.rowCount() > 0)

    def refresh_com_ports(self):
        """Refresh the list of available COM ports"""
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        found = False
        if ports:
            for port in ports:
                # Bỏ qua các cổng có mô tả chứa 'n/a' (không phân biệt hoa thường)
                if port.device.startswith(('COM', '/dev/tty')) and 'n/a' not in port.description.lower():
                    self.port_combo.addItem(f"{port.device} - {port.description}", port.device)
                    found = True
        if not found:
            self.port_combo.addItem("Không tìm thấy cổng COM khả dụng", "")

    def _update_specific_config_fields(self):
        self._clear_layout(self.specific_config_layout)
        self.current_specific_config_widgets.clear()
        sensor_type = self.sensor_type_combo.currentText()

        if sensor_type == "accelerometer" or sensor_type == "wit_motion_imu":
            self.accel_range_input = QComboBox()
            self.accel_range_input.addItems(["±2g", "±4g", "±8g", "±16g"])
            self.specific_config_layout.addRow("Dải đo Gia tốc:", self.accel_range_input)
            self.current_specific_config_widgets['accel_range'] = self.accel_range_input
            
            if sensor_type == "wit_motion_imu":
                self.wit_data_rate_combo = QComboBox()
                self.wit_data_rate_combo.addItem("0.1 Hz (Chậm)", "0x00")
                self.wit_data_rate_combo.addItem("1 Hz", "0x01")
                self.wit_data_rate_combo.addItem("5 Hz", "0x02")
                self.wit_data_rate_combo.addItem("10 Hz (Mặc định)", "0x05")
                self.wit_data_rate_combo.addItem("20 Hz", "0x0A")
                self.wit_data_rate_combo.addItem("50 Hz", "0x14")
                self.wit_data_rate_combo.addItem("100 Hz", "0x19")
                self.wit_data_rate_combo.addItem("200 Hz (Nhanh)", "0x0B")
                self.wit_data_rate_combo.setCurrentIndex(7)
                self.specific_config_layout.addRow("WIT Data Rate:", self.wit_data_rate_combo)
                self.current_specific_config_widgets['wit_data_rate_hex'] = self.wit_data_rate_combo

        elif sensor_type == "temperature":
            self.temp_unit_input = QComboBox()
            self.temp_unit_input.addItems(["Celsius", "Fahrenheit", "Kelvin"])
            self.specific_config_layout.addRow("Đơn vị (Unit):", self.temp_unit_input)
            self.current_specific_config_widgets['unit'] = self.temp_unit_input
        self.specific_config_group.setVisible(self.specific_config_layout.rowCount() > 0)

    def accept_and_validate(self):
        if not self.sensor_name_input.text().strip():
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập Tên Cảm biến.")
            return

        protocol = self.protocol_combo.currentText()
        if protocol == "UART":
            if not self.current_connection_widgets['port_address'].currentData():
                QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng chọn Cổng COM cho UART.")
                return
        elif protocol in ["TCP/IP", "UDP"]:
            if not self.current_connection_widgets['ip_address'].text().strip() or \
               not self.current_connection_widgets['port_number'].text().strip():
                QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập đầy đủ IP và Cổng.")
                return
        elif protocol == "Bluetooth":
            if not self.current_connection_widgets['mac_address'].text().strip():
                 QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập địa chỉ MAC cho Bluetooth.")
                 return
        self.accept()

    def get_sensor_config(self):
        sensor_name = self.sensor_name_input.text().strip()
        sensor_id_text = self.sensor_id_input.text().strip()
        sensor_type = self.sensor_type_combo.currentText()

        if not sensor_id_text:
            sensor_id = f"{sensor_type.replace(' ', '_').upper()}_{uuid.uuid4().hex[:6].upper()}"
        else:
            sensor_id = sensor_id_text

        config = {
            "id": sensor_id,
            "name": sensor_name,
            "type": sensor_type,
            "protocol": self.protocol_combo.currentText()
        }

        protocol = config["protocol"]
        if protocol == "UART":
            config['port'] = self.current_connection_widgets['port_address'].currentData()
            config['baudrate'] = int(self.current_connection_widgets['baudrate'].currentText())
        elif protocol in ["TCP/IP", "UDP"]:
            ip = self.current_connection_widgets['ip_address'].text().strip()
            port_num_str = self.current_connection_widgets['port_number'].text().strip()
            try:
                port_num = int(port_num_str)
                config['address'] = (ip, port_num)
            except ValueError:
                logger.error(f"Số cổng không hợp lệ: {port_num_str}")
                return None, None, None

        elif protocol == "Bluetooth":
            config['mac_address'] = self.current_connection_widgets['mac_address'].text().strip()
        
        if sensor_type == "accelerometer" or sensor_type == "wit_motion_imu":
            if 'accel_range' in self.current_specific_config_widgets:
                config["accel_range"] = self.current_specific_config_widgets['accel_range'].currentText()
            if sensor_type == "wit_motion_imu" and 'wit_data_rate_hex' in self.current_specific_config_widgets:
                config["wit_data_rate_byte_hex"] = self.current_specific_config_widgets['wit_data_rate_hex'].currentData(Qt.ItemDataRole.UserRole)

        elif sensor_type == "temperature":
            if 'unit' in self.current_specific_config_widgets:
                config["unit"] = self.current_specific_config_widgets['unit'].currentText()

        sr_text = self.sampling_rate_input.text().strip()
        if sr_text:
            try:
                config["sampling_rate_hz"] = float(sr_text)
            except ValueError:
                logger.warning(f"Giá trị tốc độ lấy mẫu không hợp lệ: {sr_text}")
        
        return sensor_id, sensor_type, config

# --- Màn hình Quản lý Cảm biến Chính (SensorManagementScreen) ---
class SensorManagementScreen(QWidget):
    sensor_selected = pyqtSignal(str)
    connect_sensor_requested = pyqtSignal(str)
    disconnect_sensor_requested = pyqtSignal(str)
    add_sensor_requested = pyqtSignal(str, str, dict)
    remove_sensor_requested = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sensor_manager = None
        self.sensor_processor = None
        
        self.cpu_data = []
        self.mem_data = []
        self.time_data = []
        self.max_data_points_resource_plot = 120

        self.setup_ui()

        self.resource_update_timer = QTimer(self)
        self.resource_update_timer.timeout.connect(self.update_resource_graphs_and_stats)
        self.resource_update_timer.start(1000)

        self.table_update_timer = QTimer(self)
        self.table_update_timer.timeout.connect(self.update_sensors_table_if_needed)
        self.table_update_timer.start(1500)

    def set_managers(self, sensor_manager, sensor_processor):
        self.sensor_manager = sensor_manager
        self.sensor_processor = sensor_processor
        self.update_sensors_table()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        add_sensor_button = QPushButton(QIcon.fromTheme("list-add", QIcon("path/to/fallback/add_icon.png")), "Thêm Cảm biến Mới")
        add_sensor_button.setIconSize(QSize(16,16))
        add_sensor_button.setStyleSheet("padding: 8px 15px; font-size: 14px; background-color: #27ae60; color: white; border-radius: 3px;")
        add_sensor_button.clicked.connect(self.open_add_sensor_dialog)
        
        top_bar_layout = QHBoxLayout()
        top_bar_layout.addWidget(add_sensor_button)
        top_bar_layout.addStretch()
        main_layout.addLayout(top_bar_layout)

        splitter = QSplitter(Qt.Orientation.Vertical)

        sensors_list_group = QGroupBox("Danh sách Cảm biến")
        sensors_list_layout = QVBoxLayout(sensors_list_group)
        self.sensors_table = QTableWidget()
        self.sensors_table.setColumnCount(6)
        self.sensors_table.setHorizontalHeaderLabels(["Tên Cảm biến", "ID", "Loại", "Giao thức", "Trạng thái", "Kết nối/Ngắt"])
        self.sensors_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sensors_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.sensors_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.sensors_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sensors_table.customContextMenuRequested.connect(self.show_table_context_menu)
        sensors_list_layout.addWidget(self.sensors_table)
        splitter.addWidget(sensors_list_group)

        resources_stats_group = QGroupBox("Tài nguyên Hệ thống và Thống kê Cảm biến")
        resources_stats_layout = QGridLayout(resources_stats_group)

        self.cpu_plot_widget = pg.PlotWidget(title="CPU Usage (%)")
        self.cpu_plot_widget.setLabel('left', '% CPU')
        self.cpu_plot_widget.setLabel('bottom', 'Thời gian (s)')
        self.cpu_plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.cpu_curve = self.cpu_plot_widget.plot(pen='r')
        resources_stats_layout.addWidget(self.cpu_plot_widget, 0, 0)

        self.mem_plot_widget = pg.PlotWidget(title="Memory Usage (%)")
        self.mem_plot_widget.setLabel('left', '% RAM')
        self.mem_plot_widget.setLabel('bottom', 'Thời gian (s)')
        self.mem_plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.mem_curve = self.mem_plot_widget.plot(pen='b')
        resources_stats_layout.addWidget(self.mem_plot_widget, 0, 1)

        stats_frame = QFrame()
        stats_layout = QFormLayout(stats_frame)
        self.connected_sensors_label = QLabel("0")
        self.data_rate_label = QLabel("0 FPS")
        stats_layout.addRow("Số cảm biến đã kết nối:", self.connected_sensors_label)
        stats_layout.addRow("Tốc độ dữ liệu tổng hợp:", self.data_rate_label)
        resources_stats_layout.addWidget(stats_frame, 1, 0, 1, 2)

        splitter.addWidget(resources_stats_group)
        
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        main_layout.addWidget(splitter)

    def open_add_sensor_dialog(self):
        dialog = AddSensorDialog(self.sensor_manager, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            sensor_id, sensor_type, config = dialog.get_sensor_config()
            if sensor_id is None:
                QMessageBox.critical(self, "Lỗi Cấu hình", "Cấu hình cảm biến không hợp lệ. Vui lòng kiểm tra lại.")
                return

            logger.debug(f"Dialog accepted. Requesting to add sensor ID: {sensor_id}, Type: {sensor_type}, Config: {config}")
            
            if self.sensor_manager and sensor_id in self.sensor_manager.get_all_sensor_ids():
                 QMessageBox.warning(self, "Lỗi", f"ID Cảm biến '{sensor_id}' đã tồn tại. Vui lòng chọn ID khác.")
                 return

            self.add_sensor_requested.emit(sensor_id, sensor_type, config)
        else:
            logger.debug("AddSensorDialog cancelled by user.")

    def show_table_context_menu(self, position: QPoint):
        selected_items = self.sensors_table.selectedItems()
        if not selected_items:
            return

        row = selected_items[0].row()
        sensor_id_item = self.sensors_table.item(row, 1)
        if not sensor_id_item:
            return
        
        sensor_id = sensor_id_item.text()

        menu = QMenu(self)
        
        detail_action = QAction("Xem Chi tiết", self)
        detail_action.triggered.connect(lambda: self.show_sensor_detail_for_id(sensor_id))
        menu.addAction(detail_action)
        
        delete_action = QAction("Xóa Cảm biến", self)
        delete_action.triggered.connect(lambda: self.request_remove_sensor(sensor_id))
        menu.addAction(delete_action)

        menu.exec(self.sensors_table.viewport().mapToGlobal(position))

    def show_sensor_detail_for_id(self, sensor_id: str):
        if self.sensor_manager:
            sensor_info = self.sensor_manager.get_sensor_info(sensor_id)
            if sensor_info:
                sensor_instance = self.sensor_manager.get_sensor_instance(sensor_id)
                sensor_data_raw = sensor_instance.last_data if sensor_instance else None
                                        
                dialog = SensorDetailDialog(sensor_info, sensor_data_raw, self)
                dialog.exec()
            else:
                QMessageBox.warning(self, "Lỗi", f"Không tìm thấy thông tin cho cảm biến ID: {sensor_id}")
        else:
            QMessageBox.critical(self, "Lỗi nghiêm trọng", "SensorManager chưa được khởi tạo.")

    def request_remove_sensor(self, sensor_id: str):
        if not self.sensor_manager:
            QMessageBox.critical(self, "Lỗi nghiêm trọng", "SensorManager chưa được khởi tạo.")
            return

        sensor_info = self.sensor_manager.get_sensor_info(sensor_id)
        sensor_name = sensor_info.get('config', {}).get('name', sensor_id) if sensor_info else sensor_id
        
        reply = QMessageBox.question(self, 'Xác nhận Xóa', 
                                     f"Bạn có chắc chắn muốn xóa cảm biến '{sensor_name}' (ID: {sensor_id}) không?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No:
            return

        self.remove_sensor_requested.emit(sensor_id)

    def update_sensors_table_if_needed(self):
        if not self.sensor_manager: return
        
        current_row_count = self.sensors_table.rowCount()
        manager_sensor_count = len(self.sensor_manager.get_all_sensor_ids())

        if current_row_count != manager_sensor_count:
            self.update_sensors_table()
            return

        for row in range(current_row_count):
            try:
                sensor_id = self.sensors_table.item(row, 1).text()
                sensor_info = self.sensor_manager.get_sensor_info(sensor_id)
                if sensor_info:
                    current_status_in_table = self.sensors_table.item(row, 4).text()
                    actual_status = "Đã kết nối" if sensor_info.get('connected') else "Chưa kết nối"
                    if current_status_in_table != actual_status:
                        self.update_sensors_table()
                        return
            except AttributeError:
                self.update_sensors_table()
                return

    def update_sensors_table(self):
        if not self.sensor_manager:
            self.sensors_table.setRowCount(0)
            return
            
        self.sensors_table.setRowCount(0) 
        all_sensor_ids = self.sensor_manager.get_all_sensor_ids()
        
        for sensor_id in all_sensor_ids:
            sensor_info = self.sensor_manager.get_sensor_info(sensor_id)
            if not sensor_info: continue

            config = sensor_info.get('config', {})
            row = self.sensors_table.rowCount()
            self.sensors_table.insertRow(row)
            
            self.sensors_table.setItem(row, 0, QTableWidgetItem(str(config.get('name', sensor_id))))
            self.sensors_table.setItem(row, 1, QTableWidgetItem(str(sensor_id)))
            self.sensors_table.setItem(row, 2, QTableWidgetItem(str(sensor_info.get('type', 'N/A'))))
            self.sensors_table.setItem(row, 3, QTableWidgetItem(str(config.get('protocol', 'N/A'))))
            
            is_connected = sensor_info.get('connected', False)
            status_text = "Đã kết nối" if is_connected else "Chưa kết nối"
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(Qt.GlobalColor.darkGreen if is_connected else Qt.GlobalColor.red)
            self.sensors_table.setItem(row, 4, status_item)
            
            connect_button = QPushButton()
            connect_button.setIconSize(QSize(16,16))
            if is_connected:
                connect_button.setText("Ngắt")
                connect_button.setIcon(QIcon.fromTheme("network-offline", QIcon("path/to/disconnect_icon.png")))
                connect_button.clicked.connect(lambda _, sid=sensor_id: self.disconnect_sensor_requested.emit(sid))
            else:
                connect_button.setText("Nối")
                connect_button.setIcon(QIcon.fromTheme("network-transmit-receive", QIcon("path/to/connect_icon.png")))
                connect_button.clicked.connect(lambda _, sid=sensor_id: self.connect_sensor_requested.emit(sid))
            self.sensors_table.setCellWidget(row, 5, connect_button)

        self.sensors_table.resizeColumnsToContents()
        self.sensors_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.sensors_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)

    def on_sensor_selection_changed(self):
        selected_items = self.sensors_table.selectedItems()
        if selected_items:
            row = selected_items[0].row()
            sensor_id_item = self.sensors_table.item(row, 1)
            if sensor_id_item:
                sensor_id = sensor_id_item.text()
                self.sensor_selected.emit(sensor_id)

    def update_resource_graphs_and_stats(self):
        current_time = len(self.time_data) 
        
        self.cpu_data.append(psutil.cpu_percent(interval=None))
        self.mem_data.append(psutil.virtual_memory().percent)
        self.time_data.append(current_time)

        if len(self.time_data) > self.max_data_points_resource_plot:
            self.time_data.pop(0)
            self.cpu_data.pop(0)
            self.mem_data.pop(0)
        
        self.cpu_plot_widget.setXRange(max(0, current_time - self.max_data_points_resource_plot), current_time)
        self.mem_plot_widget.setXRange(max(0, current_time - self.max_data_points_resource_plot), current_time)

        self.cpu_curve.setData(self.time_data, self.cpu_data)
        self.mem_curve.setData(self.time_data, self.mem_data)

        if self.sensor_manager:
            connected_count = self.sensor_manager.get_connected_sensors_count()
            self.connected_sensors_label.setText(str(connected_count))
        
        if self.sensor_processor:
            pass

    def closeEvent(self, event):
        self.resource_update_timer.stop()
        self.table_update_timer.stop()
        super().closeEvent(event) 