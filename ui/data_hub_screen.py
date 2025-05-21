# ui/data_hub_screen.py
import logging
import json
import csv
import time
import numpy as np
import paho.mqtt.client as mqtt
from collections import deque
import serial.tools.list_ports

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QTableView, QLineEdit,
    QFormLayout, QComboBox, QCheckBox, QMessageBox, QFileDialog,
    QHeaderView, QSplitter, QTextEdit, QSpinBox
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QObject, QThread, QTimer, QDateTime,
    QAbstractTableModel, QModelIndex, QVariant
)
from PyQt6.QtGui import QIcon, QColor

logger = logging.getLogger(__name__)

# Constants
DEFAULT_MAX_TABLE_ROWS = 200  # Adjusted default for potentially faster rendering
DEFAULT_UPDATE_INTERVAL_MS = 1000
DEFAULT_MAX_BUFFER_SIZE = 500 # Max items per sensor in _data_buffer_deque

# Default data keys for different sensor types
DEFAULT_SENSOR_DATA_KEYS = {
    'wit_motion_imu': {
        'raw': ['AccX', 'AccY', 'AccZ', 'GyroX', 'GyroY', 'GyroZ', 'MagX', 'MagY', 'MagZ'],
        'processed': ['AccX', 'AccY', 'AccZ', 'VelX', 'VelY', 'VelZ', 'DispX', 'DispY', 'DispZ']
    },
    'wit_motion_acc': {
        'raw': ['AccX', 'AccY', 'AccZ'],
        'processed': ['AccX', 'AccY', 'AccZ', 'VelX', 'VelY', 'VelZ', 'DispX', 'DispY', 'DispZ']
    },
    'wit_motion_gyro': {
        'raw': ['GyroX', 'GyroY', 'GyroZ'],
        'processed': ['VelX', 'VelY', 'VelZ', 'DispX', 'DispY', 'DispZ']
    },
    'wit_motion_mag': {
        'raw': ['MagX', 'MagY', 'MagZ'],
        'processed': []
    }
}

class MQTTPublisherWorker(QObject):
    connection_status_changed = pyqtSignal(bool, str) # connected, message
    message_published = pyqtSignal(str, str) # topic, payload
    error_occurred = pyqtSignal(str)

    def __init__(self, broker_address, port, client_id="", username=None, password=None, parent=None):
        super().__init__(parent)
        self.broker_address = broker_address
        self.port = port
        self.client_id = client_id if client_id else f"qt-publisher-{mqtt.base62(mqtt.uuid.uuid4().int, padding=22)}"
        self.username = username
        self.password = password

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id)
        if self.username:
            self.client.username_pw_set(self.username, self.password)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_publish = self._on_publish

        self._is_connected = False
        self._stop_requested = False

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            self._is_connected = True
            self.connection_status_changed.emit(True, f"Đã kết nối tới MQTT Broker: {self.broker_address}")
            logger.info(f"MQTT: Connected to {self.broker_address} with client ID {self.client_id}")
        else:
            self._is_connected = False
            error_msg = f"Lỗi kết nối MQTT Broker: {mqtt.connack_string(reason_code)}"
            self.connection_status_changed.emit(False, error_msg)
            logger.error(error_msg)
            self._stop_requested = True

    def _on_disconnect(self, client, userdata, reason_code, properties):
        self._is_connected = False
        msg = f"Đã ngắt kết nối MQTT Broker (RC: {reason_code})" if reason_code == 0 else f"Mất kết nối MQTT Broker (RC: {reason_code})"
        self.connection_status_changed.emit(False, msg)
        logger.info(f"MQTT: Disconnected (RC: {reason_code})")

    def _on_publish(self, client, userdata, mid, reason_code, properties):
        pass

    def connect_to_broker(self):
        if self._is_connected:
            logger.info("MQTT: Already connected.")
            return
        self._stop_requested = False
        try:
            logger.info(f"MQTT: Attempting to connect to {self.broker_address}:{self.port}")
            self.client.connect(self.broker_address, self.port, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            self._is_connected = False
            error_msg = f"Lỗi khởi tạo kết nối MQTT: {e}"
            self.connection_status_changed.emit(False, error_msg)
            logger.error(error_msg, exc_info=True)
            self._stop_requested = True

    def publish_message(self, topic, payload_dict, qos=0, retain=False):
        if not self._is_connected:
            return False
        try:
            payload_str = json.dumps(payload_dict)
            msg_info = self.client.publish(topic, payload_str, qos=qos, retain=retain)
            if msg_info.is_published():
                 self.message_published.emit(topic, payload_str[:80] + "..." if len(payload_str) > 80 else payload_str)
            return True
        except Exception as e:
            error_msg = f"Lỗi khi gửi tin nhắn MQTT tới topic {topic}: {e}"
            self.error_occurred.emit(error_msg)
            logger.error(error_msg, exc_info=True)
            return False

    def stop(self):
        logger.info("MQTT: Stop requested.")
        self._stop_requested = True
        if self._is_connected:
            self.client.loop_stop()
            self.client.disconnect()
            logger.info("MQTT: Disconnected by stop request.")
        else:
            self.client.loop_stop(force=True)
            logger.info("MQTT: Loop stopped (was not connected).")


class SensorDataTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []  # List of dictionaries (each dict is a row)
        self._headers = ["Timestamp"]
        self._column_map = {} # 'SensorID_DataKey' -> conceptual column index beyond timestamp
        self._display_column_names = ["Timestamp"] # Actual headers for display

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self._display_column_names)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return QVariant()

        row = index.row()
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            try:
                point_data = self._data[row]
                # First column is always timestamp
                if col == 0:
                    return f"{point_data.get('timestamp', 0.0):.3f}"

                # Map displayed column back to internal 'SensorID_DataKey'
                # This requires knowing which conceptual column this display column maps to.
                # This part is tricky and depends on how _display_column_names is structured
                # based on _column_map during `set_table_structure`.

                # Simplified: Assume _display_column_names[col] holds a key that can be used
                # to fetch data if the data structure in _data[row] is flat.
                # For complex multi-sensor views, this logic needs careful design.
                # The current _data structure is a flat list of recent global points,
                # so we need to find the data based on the header.
                
                header_key = self._display_column_names[col] # e.g. "SensorA_AccX"

                # The value for a specific sensor_datakey might not exist in every row
                # if rows are individual sensor readings.
                # If `self._data` stores combined rows, this is different.
                # The original `_data_buffer` was per sensor, then aggregated.
                # Let's assume `self._data` contains aggregated, most recent points.

                # Search for the value corresponding to the header key.
                # The header_key is in the format "SensorShortName_DataKey"
                # The point_data has "sensor_id" and then data keys directly.
                
                # We need to parse sensor_id and data_key from header_key if it's structured.
                # For now, let's assume point_data contains the value if the column applies.
                
                # This part needs the full `_column_map` and sensor ID from `point_data`
                # to correctly look up values.
                
                # A direct lookup if point_data was structured like {'Timestamp': ..., 'SensorA_AccX': ...}
                # return str(point_data.get(header_key, ""))

                # Based on original structure:
                # point_data = {'timestamp': ..., 'sensor_id': 'ActualSensorID', 'AccX': ..., 'AccY':...}
                # header_key = "SensorShortName_DataKey"
                
                parts = header_key.split('_', 1)
                if len(parts) == 2:
                    # We need to check if point_data['sensor_id'] matches the sensor part of header_key
                    # This is complex because the table shows data from *multiple* sensors.
                    # The easiest way is if the _column_map from DataHubScreenWidget is available here
                    # or if the data is pre-flattened.

                    # Let's simplify for now: if the key exists in point_data, show it.
                    # This won't work perfectly for a multi-sensor merged table without more context.
                    if header_key in point_data: # If data was pre-flattened with combined keys
                        value = point_data[header_key]
                        return f"{value:.4f}" if isinstance(value, float) else str(value)
                    
                    # If point_data has sensor_id and the data_key directly:
                    # E.g. header "SensorABC_AccX" and point_data['sensor_id'] starts with "SensorABC"
                    # and point_data has "AccX". This is still not robust.

                    # The most straightforward way for QAbstractTableModel is for `_data`
                    # to be a list of lists/tuples, where each inner list/tuple directly
                    # corresponds to a row's column values in order.
                    # The `refresh_data_display` in DataHubScreenWidget would need to prepare
                    # `_data` in this [ [r1c1, r1c2,...], [r2c1, r2c2,...] ] format.
                    
                    # Given the current _update_table_efficiently, it seems _data
                    # is a list of dicts, and column mapping is done there.
                    # We'll replicate a simplified version of that for now.

                    # This part is highly dependent on how `set_table_structure` and `_get_latest_data_points`
                    # prepare the data and headers. The original `_column_map` in `DataHubScreenWidget`
                    # was `SensorID_DataKey` -> column_index.
                    # We'll assume `self._data[row]` has keys like `ActualSensorID_DataKey`.
                    # This means `_get_latest_data_points` must structure its output accordingly.

                    # The original _update_table_efficiently used _column_map to find the column.
                    # Here, we are *given* the column, and need the data.
                    # This implies the _data items should have keys that are directly the column headers (display names)
                    # or a mapping is needed.

                    # For now, returning empty if not timestamp as the exact mapping is complex here.
                    # This should be filled by `_get_latest_data_points` creating flat dicts.
                    data_value = point_data.get(self._display_column_names[col])
                    if data_value is not None:
                        return f"{data_value:.4f}" if isinstance(data_value, float) else str(data_value)
                    return ""

            except IndexError:
                return QVariant()
            except KeyError: # If a specific data key is not in this point_data
                return "" # Return empty string for missing data in that row for that column
        return QVariant()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                try:
                    return self._display_column_names[section]
                except IndexError:
                    return QVariant()
        return QVariant()

    def set_table_structure(self, display_column_names, internal_column_map):
        self.beginResetModel()
        self._display_column_names = display_column_names
        self._column_map = internal_column_map # Store this if needed for mapping back, though not used directly in data() yet
        self._data = []
        self.endResetModel()

    def update_data(self, new_data_list_of_dicts):
        """ new_data_list_of_dicts should be a list of dicts,
            where each dict has keys corresponding to _display_column_names.
        """
        self.beginResetModel() # Signals that the entire model is changing
        self._data = new_data_list_of_dicts
        self.endResetModel()


class DataHubScreenWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sensor_manager = None
        self.data_processor = None

        self._data_buffer_deque = {}  # sensor_id -> deque([(timestamp, data_point_dict), ...], maxlen=DEFAULT_MAX_BUFFER_SIZE)
        self._selected_sensors_for_table = []
        
        # _column_map: Maps 'InternalSensorID_DataKey' to a conceptual full column key.
        # This is used to create the _display_column_names for the model.
        self._internal_column_map_keys = [] # List of 'InternalSensorID_DataKey'

        self._last_update_time = {}
        self._update_interval_ms = DEFAULT_UPDATE_INTERVAL_MS
        self._max_table_rows = DEFAULT_MAX_TABLE_ROWS # Max rows the model will hold and display
        self._is_updating_model = False

        self.mqtt_worker = None
        self.mqtt_thread = None

        self.init_ui()
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.refresh_data_display)
        # Timer will be started after managers are set and table structure is defined.
    
    def set_managers(self, sensor_manager, data_processor):
        try:
            self.sensor_manager = sensor_manager
            self.data_processor = data_processor
            self.update_sensor_selection_combo()

            if self.sensor_manager:
                self.sensor_manager.sensorDataReceived.connect(self.handle_raw_sensor_data)
                self.sensor_manager.sensorListChanged.connect(self.update_sensor_selection_combo)
            
            # Initial table setup after managers are set
            self._update_table_structure_and_model_data()
            if not self.update_timer.isActive():
                 self.update_timer.start(self._update_interval_ms)

        except Exception as e:
            logger.error(f"Error setting managers: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to initialize managers: {str(e)}")

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Vertical)

        table_group = QGroupBox("Hiển thị Dữ liệu Cảm biến Dạng Bảng")
        table_layout = QVBoxLayout(table_group)

        selection_layout = QHBoxLayout()
        selection_layout.addWidget(QLabel("Chọn cảm biến hiển thị:"))
        self.sensor_selection_combo = QComboBox()
        self.sensor_selection_combo.setToolTip("Chọn các cảm biến để hiển thị trong bảng bên dưới.")
        self.update_table_button = QPushButton("Cập nhật Bảng")
        # Update button now calls the structure update method
        self.update_table_button.clicked.connect(self._update_table_structure_and_model_data)
        selection_layout.addWidget(self.sensor_selection_combo, 1)
        selection_layout.addWidget(self.update_table_button)
        table_layout.addLayout(selection_layout)

        self.data_table_view = QTableView() # Changed from QTableWidget
        self.data_table_model = SensorDataTableModel(self)
        self.data_table_view.setModel(self.data_table_model)
        
        self.data_table_view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.data_table_view.setAlternatingRowColors(True)
        self.data_table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.data_table_view.setSortingEnabled(True) # Allow model sorting if implemented
        table_layout.addWidget(self.data_table_view)

        export_button = QPushButton(QIcon.fromTheme("document-save"), "Xuất ra CSV")
        export_button.clicked.connect(self.export_table_to_csv)
        table_layout.addWidget(export_button, 0, Qt.AlignmentFlag.AlignRight)
        splitter.addWidget(table_group)

        mqtt_group = QGroupBox("Truyền Dữ liệu qua MQTT (Publisher)")
        mqtt_layout_main = QVBoxLayout(mqtt_group)
        mqtt_config_layout = QFormLayout()
        self.mqtt_broker_input = QLineEdit("mqtt.eclipseprojects.io")
        self.mqtt_port_input = QLineEdit("1883")
        self.mqtt_client_id_input = QLineEdit()
        self.mqtt_client_id_input.setPlaceholderText("Để trống để tự tạo")
        self.mqtt_username_input = QLineEdit()
        self.mqtt_password_input = QLineEdit()
        self.mqtt_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.mqtt_topic_prefix_input = QLineEdit("sensor/data/")
        self.mqtt_topic_prefix_input.setPlaceholderText("Ví dụ: myhome/floor1/sensor/")
        mqtt_config_layout.addRow("MQTT Broker:", self.mqtt_broker_input)
        mqtt_config_layout.addRow("Cổng:", self.mqtt_port_input)
        mqtt_config_layout.addRow("Client ID:", self.mqtt_client_id_input)
        mqtt_config_layout.addRow("Username:", self.mqtt_username_input)
        mqtt_config_layout.addRow("Password:", self.mqtt_password_input)
        mqtt_config_layout.addRow("Tiền tố Topic:", self.mqtt_topic_prefix_input)
        mqtt_layout_main.addLayout(mqtt_config_layout)
        publish_options_layout = QHBoxLayout()
        self.publish_raw_checkbox = QCheckBox("Gửi Dữ liệu Thô")
        self.publish_processed_checkbox = QCheckBox("Gửi Dữ liệu Đã Xử lý")
        self.publish_processed_checkbox.setChecked(True)
        publish_options_layout.addWidget(self.publish_raw_checkbox)
        publish_options_layout.addWidget(self.publish_processed_checkbox)
        mqtt_layout_main.addLayout(publish_options_layout)
        mqtt_control_layout = QHBoxLayout()
        self.mqtt_connect_button = QPushButton("Kết nối MQTT")
        self.mqtt_connect_button.clicked.connect(self.toggle_mqtt_connection)
        self.mqtt_status_label = QLabel("Trạng thái MQTT: Chưa kết nối")
        self.mqtt_status_label.setStyleSheet("color: red;")
        mqtt_control_layout.addWidget(self.mqtt_connect_button)
        mqtt_control_layout.addWidget(self.mqtt_status_label, 1)
        mqtt_layout_main.addLayout(mqtt_control_layout)
        self.mqtt_log_display = QTextEdit()
        self.mqtt_log_display.setReadOnly(True)
        self.mqtt_log_display.setMaximumHeight(100)
        mqtt_layout_main.addWidget(QLabel("Log MQTT:"))
        mqtt_layout_main.addWidget(self.mqtt_log_display)
        splitter.addWidget(mqtt_group)
        
        main_layout.addWidget(splitter)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        performance_group = QGroupBox("Cài đặt Hiệu suất")
        performance_layout = QFormLayout(performance_group)
        self.update_interval_spinbox = QSpinBox()
        self.update_interval_spinbox.setRange(200, 5000) # Min interval 200ms
        self.update_interval_spinbox.setValue(self._update_interval_ms)
        self.update_interval_spinbox.setSuffix(" ms")
        self.update_interval_spinbox.valueChanged.connect(self.update_refresh_interval)
        self.max_rows_spinbox = QSpinBox()
        self.max_rows_spinbox.setRange(50, 2000) # Max rows for display
        self.max_rows_spinbox.setValue(self._max_table_rows)
        self.max_rows_spinbox.valueChanged.connect(self.update_max_display_rows)
        performance_layout.addRow("Tần suất cập nhật:", self.update_interval_spinbox)
        performance_layout.addRow("Số dòng hiển thị tối đa:", self.max_rows_spinbox)
        main_layout.addWidget(performance_group)

    def update_refresh_interval(self, interval_ms):
        try:
            self._update_interval_ms = interval_ms
            self.update_timer.setInterval(interval_ms)
            logger.info(f"Data table refresh interval updated to {interval_ms}ms")
        except Exception as e:
            logger.error(f"Error updating refresh interval: {str(e)}", exc_info=True)

    def update_max_display_rows(self, max_rows):
        try:
            self._max_table_rows = max_rows
            # No need to trim deques here as they have their own maxlen.
            # This _max_table_rows will be used when preparing data for the model.
            logger.info(f"Maximum display table rows updated to {max_rows}")
            self.refresh_data_display() # Refresh to apply new row limit
        except Exception as e:
            logger.error(f"Error updating max display rows: {str(e)}", exc_info=True)


    def handle_raw_sensor_data(self, sensor_id, data_dict):
        try:
            if not self._selected_sensors_for_table or sensor_id not in self._selected_sensors_for_table:
                # If "All sensors" is not selected or this specific sensor is not part of the selection
                is_all_selected = self.sensor_selection_combo.currentData() is None
                if not is_all_selected and sensor_id not in self._selected_sensors_for_table:
                    return

            current_timestamp = time.time()
            if not isinstance(data_dict, dict):
                logger.warning(f"Invalid data format from sensor {sensor_id}")
                return

            if sensor_id not in self._data_buffer_deque:
                self._data_buffer_deque[sensor_id] = deque(maxlen=DEFAULT_MAX_BUFFER_SIZE)
            
            entry = {'timestamp': current_timestamp, 'sensor_id': sensor_id}
            for key, value in data_dict.items():
                entry[key] = float(value) if isinstance(value, (int, float)) else str(value)
            
            self._data_buffer_deque[sensor_id].append(entry)
            self._handle_mqtt_publishing(sensor_id, current_timestamp, data_dict)

        except Exception as e:
            logger.error(f"Error handling sensor data: {str(e)}", exc_info=True)

    def _handle_mqtt_publishing(self, sensor_id, timestamp, raw_data):
        if not (self.mqtt_worker and self.mqtt_worker._is_connected):
            return
        try:
            data_to_publish = {}
            if self.publish_raw_checkbox.isChecked():
                data_to_publish['raw'] = raw_data
            if self.publish_processed_checkbox.isChecked() and self.data_processor:
                processed_data = self._get_latest_processed_data(sensor_id)
                if processed_data:
                    data_to_publish['processed'] = processed_data
            
            if data_to_publish:
                data_to_publish['timestamp_ms'] = int(timestamp * 1000)
                topic = f"{self.mqtt_topic_prefix_input.text().strip()}{sensor_id}"
                self.mqtt_worker.publish_message(topic, data_to_publish)
        except Exception as e:
            logger.error(f"Error publishing MQTT data: {str(e)}", exc_info=True)
            self.handle_mqtt_error(f"Error publishing data: {str(e)}")

    def _get_latest_processed_data(self, sensor_id):
        try:
            proc_data = self.data_processor.get_plot_data_for_sensor(sensor_id) #
            if not proc_data: return None
            latest_processed = {}
            for cat_key, cat_data in proc_data.items():
                if isinstance(cat_data, dict):
                    if cat_key in ['acc_data', 'vel_data', 'disp_data']:
                        for axis, arr in cat_data.items():
                            if isinstance(arr, np.ndarray) and arr.size > 0:
                                latest_processed[f"{cat_key.replace('_data','')}_{axis}"] = float(arr[-1])
            return latest_processed
        except Exception as e:
            logger.error(f"Error getting processed data: {str(e)}", exc_info=True)
            return None

    def refresh_data_display(self):
        if self._is_updating_model or not self._selected_sensors_for_table:
            return
        try:
            self._is_updating_model = True
            
            # Collect all points from selected sensors
            all_points_aggregated = []
            for sensor_id in self._selected_sensors_for_table:
                if sensor_id in self._data_buffer_deque:
                    all_points_aggregated.extend(list(self._data_buffer_deque[sensor_id]))
            
            if not all_points_aggregated:
                self.data_table_model.update_data([])
                return

            # Sort by timestamp descending to get the latest
            all_points_aggregated.sort(key=lambda x: x['timestamp'], reverse=True)
            
            # Take top N rows for display model
            display_points_for_model = all_points_aggregated[:self._max_table_rows]

            # Prepare data for the model
            model_ready_data = []
            for point in display_points_for_model:
                row_values = {'Timestamp': point['timestamp']}
                current_point_sensor_id = point['sensor_id']
                
                # Get sensor info for short name comparison
                s_info = self.sensor_manager.get_sensor_info(current_point_sensor_id)
                current_point_sensor_short_name = s_info.get('config', {}).get('name', current_point_sensor_id).split('_')[0] if s_info else current_point_sensor_id.split('_')[0]

                # Process each display column (skip Timestamp)
                for col_idx in range(1, len(self.data_table_model._display_column_names)):
                    display_header = self.data_table_model._display_column_names[col_idx]
                    
                    try:
                        # Split display header into sensor name and data key
                        sensor_short_name_header, data_key_header = display_header.rsplit('_', 1)
                        
                        # Check if this point's sensor matches the column's sensor
                        if current_point_sensor_short_name == sensor_short_name_header:
                            # Try to get value from point data
                            if data_key_header in point:
                                value = point[data_key_header]
                                row_values[display_header] = f"{value:.4f}" if isinstance(value, float) else str(value)
                            else:
                                row_values[display_header] = ""
                        else:
                            row_values[display_header] = ""
                            
                    except ValueError:
                        # If header can't be split, it's not a sensor data column
                        row_values[display_header] = ""
                        continue

                model_ready_data.append(row_values)

            self.data_table_model.update_data(model_ready_data)

        except Exception as e:
            logger.error(f"Error refreshing data display: {str(e)}", exc_info=True)
        finally:
            self._is_updating_model = False

    def export_table_to_csv(self):
        if self.data_table_model.rowCount() == 0:
            QMessageBox.information(self, "Information", "No data to export.")
            return
        try:
            path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "", "CSV Files (*.csv);;All Files (*.*)")
            if not path: return
            if not path.lower().endswith('.csv'): path += '.csv'

            with open(path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                headers = [self.data_table_model.headerData(i, Qt.Orientation.Horizontal) 
                           for i in range(self.data_table_model.columnCount())]
                writer.writerow(headers)
                for row in range(self.data_table_model.rowCount()):
                    row_data = [self.data_table_model.data(self.data_table_model.index(row, col), Qt.ItemDataRole.DisplayRole)
                                for col in range(self.data_table_model.columnCount())]
                    writer.writerow(row_data)
            QMessageBox.information(self, "Success", f"Successfully exported to: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export CSV: {str(e)}")
            logger.error(f"Error exporting CSV: {str(e)}", exc_info=True)

    def closeEvent(self, event):
        try:
            if self.mqtt_worker: self.mqtt_worker.stop()
            if self.mqtt_thread and self.mqtt_thread.isRunning():
                self.mqtt_thread.quit()
                self.mqtt_thread.wait(500)
            self.update_timer.stop()
            self._data_buffer_deque.clear()
            super().closeEvent(event)
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}", exc_info=True)
            super().closeEvent(event)

    def toggle_mqtt_connection(self):
        try:
            if self.mqtt_worker and self.mqtt_worker._is_connected:
                self._disconnect_mqtt()
            else:
                self._connect_mqtt()
        except Exception as e:
            logger.error(f"Error toggling MQTT connection: {str(e)}", exc_info=True)

    def _disconnect_mqtt(self):
        try:
            if self.mqtt_worker: self.mqtt_worker.stop()
            if self.mqtt_thread and self.mqtt_thread.isRunning():
                self.mqtt_thread.quit()
                if not self.mqtt_thread.wait(1000): self.mqtt_thread.terminate()
            self.mqtt_thread = None; self.mqtt_worker = None
            self.mqtt_connect_button.setText("Connect MQTT")
            self.set_mqtt_status(False, "Manually disconnected.")
        except Exception as e: logger.error(f"Error disconnecting MQTT: {str(e)}", exc_info=True); raise

    def _connect_mqtt(self):
        try:
            broker = self.mqtt_broker_input.text().strip()
            if not broker: raise ValueError("MQTT Broker address cannot be empty")
            try:
                port = int(self.mqtt_port_input.text().strip())
                if not (0 < port < 65536): raise ValueError("Port must be between 1 and 65535")
            except ValueError as e: raise ValueError(f"Invalid MQTT port: {str(e)}")
            
            client_id = self.mqtt_client_id_input.text().strip()
            username = self.mqtt_username_input.text().strip()
            password = self.mqtt_password_input.text()

            self.mqtt_worker = MQTTPublisherWorker(broker, port, client_id, username or None, password or None)
            self.mqtt_thread = QThread(self)
            self.mqtt_worker.moveToThread(self.mqtt_thread)
            self.mqtt_worker.connection_status_changed.connect(self.handle_mqtt_connection_status)
            self.mqtt_worker.message_published.connect(self.handle_mqtt_message_published)
            self.mqtt_worker.error_occurred.connect(self.handle_mqtt_error)
            self.mqtt_thread.started.connect(self.mqtt_worker.connect_to_broker)
            self.mqtt_thread.start()
            self.mqtt_connect_button.setText("Connecting...")
            self.mqtt_connect_button.setEnabled(False)
        except Exception as e:
            logger.error(f"Error connecting to MQTT: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "MQTT Error", f"Failed to connect to MQTT: {str(e)}")
            self.mqtt_connect_button.setEnabled(True)
            self.mqtt_connect_button.setText("Connect MQTT")

    def handle_mqtt_connection_status(self, connected, message):
        try:
            self.set_mqtt_status(connected, message)
            self.mqtt_connect_button.setEnabled(True)
            self.mqtt_connect_button.setText("Disconnect MQTT" if connected else "Connect MQTT")
            if not connected and self.mqtt_worker and not self.mqtt_worker._stop_requested:
                self._cleanup_mqtt_resources()
        except Exception as e: logger.error(f"Error handling MQTT connection status: {str(e)}", exc_info=True)

    def _cleanup_mqtt_resources(self):
        try:
            if self.mqtt_thread and self.mqtt_thread.isRunning():
                self.mqtt_thread.quit()
                self.mqtt_thread.wait(500)
            self.mqtt_worker = None; self.mqtt_thread = None
        except Exception as e: logger.error(f"Error cleaning up MQTT resources: {str(e)}", exc_info=True)

    def handle_mqtt_message_published(self, topic, payload_preview):
        try:
            log_msg = f"[{QDateTime.currentDateTime().toString('HH:mm:ss')}] Published to {topic}: {payload_preview}\n"
            self.mqtt_log_display.insertPlainText(log_msg)
            self.mqtt_log_display.ensureCursorVisible()
        except Exception as e: logger.error(f"Error handling MQTT message published: {str(e)}", exc_info=True)

    def handle_mqtt_error(self, error_message):
        try:
            log_msg = f"[{QDateTime.currentDateTime().toString('HH:mm:ss')}] MQTT Error: {error_message}\n"
            self.mqtt_log_display.insertPlainText(log_msg)
            self.mqtt_log_display.ensureCursorVisible()
        except Exception as e: logger.error(f"Error handling MQTT error: {str(e)}", exc_info=True)

    def set_mqtt_status(self, connected, message):
        try:
            self.mqtt_status_label.setText(f"MQTT Status: {message}")
            self.mqtt_status_label.setStyleSheet("color: green;" if connected else "color: red;")
            log_msg = f"[{QDateTime.currentDateTime().toString('HH:mm:ss')}] Status: {message}\n"
            self.mqtt_log_display.insertPlainText(log_msg)
            self.mqtt_log_display.ensureCursorVisible()
        except Exception as e: logger.error(f"Error setting MQTT status: {str(e)}", exc_info=True)

    def _update_table_structure_and_model_data(self):
        try:
            self._internal_column_map_keys = [] # Reset internal keys
            self._data_buffer_deque.clear() # Clear data when structure changes

            selected_sensor_id_user_data = self.sensor_selection_combo.currentData()
            sensors_to_display_ids = []
            if selected_sensor_id_user_data is None:
                if self.sensor_manager:
                    sensors_to_display_ids = self.sensor_manager.get_all_sensor_ids()
            elif selected_sensor_id_user_data:
                sensors_to_display_ids = [selected_sensor_id_user_data]

            self._selected_sensors_for_table = sensors_to_display_ids
            
            display_headers = ["Timestamp"]
            if not sensors_to_display_ids or not self.data_processor:
                self.data_table_model.set_table_structure(["Message"], {})
                self.data_table_model.update_data([{"Message": "No sensors selected or DataProcessor not ready."}])
                return

            for sensor_id in self._selected_sensors_for_table:
                sensor_instance = self.sensor_manager.get_sensor_instance(sensor_id)
                s_info = self.sensor_manager.get_sensor_info(sensor_id)
                sensor_type = s_info.get('type', '') if s_info else ''
                sensor_short_name = s_info.get('config', {}).get('name', sensor_id).split('_')[0] if s_info else sensor_id.split('_')[0]
                
                # Get sample data
                sample_raw_data = sensor_instance.last_data if sensor_instance and sensor_instance.last_data else {}
                
                # Initialize data keys list
                data_keys_for_sensor = []
                
                # Try to get data keys from actual data first (RAW)
                if self.publish_raw_checkbox.isChecked() and sample_raw_data:
                    data_keys_for_sensor.extend(sorted(sample_raw_data.keys()))
                
                # Try to get processed data keys (only Vel, Disp, FFT)
                if self.publish_processed_checkbox.isChecked() or \
                   (not self.publish_raw_checkbox.isChecked() and not data_keys_for_sensor):
                    processed_keys_set = set()
                    plot_data = self.data_processor.get_plot_data_for_sensor(sensor_id)
                    if plot_data:
                        # Only Vel, Disp
                        for main_key in ['vel_data', 'disp_data']:
                            if main_key in plot_data and isinstance(plot_data[main_key], dict):
                                for axis_key in plot_data[main_key]:
                                    processed_keys_set.add(
                                        f"{main_key.replace('_data','').capitalize()}{axis_key.upper()}")
                        # FFT
                        if 'fft_data' in plot_data and isinstance(plot_data['fft_data'], dict):
                            for axis_key in plot_data['fft_data']:
                                processed_keys_set.add(f"FFT{axis_key.upper()}")
                    # Add processed keys, ensuring no duplicates
                    for pk in sorted(list(processed_keys_set)):
                        if pk not in data_keys_for_sensor:
                            data_keys_for_sensor.append(pk)

                # If still no data keys found, use default keys based on sensor type
                if not data_keys_for_sensor and sensor_type in DEFAULT_SENSOR_DATA_KEYS:
                    default_keys = []
                    if self.publish_raw_checkbox.isChecked():
                        default_keys.extend(DEFAULT_SENSOR_DATA_KEYS[sensor_type]['raw'])
                    if self.publish_processed_checkbox.isChecked():
                        # Only Vel, Disp, FFT for processed
                        default_keys.extend([f"VelX", f"VelY", f"VelZ", f"DispX", f"DispY", f"DispZ", "FFTX", "FFTY", "FFTZ"])
                    # Remove duplicates while preserving order
                    data_keys_for_sensor = list(dict.fromkeys(default_keys))

                # If still no data keys, fallback to raw data if available
                if not data_keys_for_sensor and sample_raw_data:
                    data_keys_for_sensor.extend(sorted(sample_raw_data.keys()))

                # Add columns for this sensor
                for data_key in data_keys_for_sensor:
                    internal_full_key = f"{sensor_id}_{data_key}"
                    self._internal_column_map_keys.append(internal_full_key)
                    display_headers.append(f"{sensor_short_name}_{data_key}")
            
            self.data_table_model.set_table_structure(display_headers, self._internal_column_map_keys)
            self.data_table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            if len(display_headers) > 1:
                self.data_table_view.horizontalHeader().setStretchLastSection(False)
                self.data_table_view.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive) # Timestamp
            
            self.refresh_data_display()

        except Exception as e:
            logger.error(f"Error updating table structure: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to update table structure: {str(e)}")

    def update_sensor_selection_combo(self):
        current_selection_data = self.sensor_selection_combo.currentData()
        self.sensor_selection_combo.clear()
        if self.sensor_manager:
            all_sensor_ids = self.sensor_manager.get_all_sensor_ids() #
            if all_sensor_ids:
                self.sensor_selection_combo.addItem("Tất cả cảm biến", userData=None)
                for sensor_id in all_sensor_ids:
                    s_info = self.sensor_manager.get_sensor_info(sensor_id) #
                    name = s_info.get('config', {}).get('name', sensor_id) if s_info else sensor_id
                    self.sensor_selection_combo.addItem(f"{name} ({sensor_id})", userData=sensor_id)
                
                # Try to restore previous selection
                index_to_restore = self.sensor_selection_combo.findData(current_selection_data)
                if index_to_restore != -1:
                    self.sensor_selection_combo.setCurrentIndex(index_to_restore)
                elif all_sensor_ids: # Default to "All sensors" if previous selection not found
                    self.sensor_selection_combo.setCurrentIndex(0)

            else:
                self.sensor_selection_combo.addItem("Không có cảm biến nào", userData=None)
        else:
            self.sensor_selection_combo.addItem("SensorManager chưa sẵn sàng", userData=None)
        
        # Automatically update table structure when combo changes
        self._update_table_structure_and_model_data()