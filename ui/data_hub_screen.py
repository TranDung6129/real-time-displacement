# ui/data_hub_screen.py
import logging
import json
import csv
import time
import numpy as np
import paho.mqtt.client as mqtt

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QLineEdit,
    QFormLayout, QComboBox, QCheckBox, QMessageBox, QFileDialog,
    QHeaderView, QSplitter, QTextEdit, QSpinBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QThread, QTimer, QDateTime
from PyQt6.QtGui import QIcon

logger = logging.getLogger(__name__)

# Constants
MAX_TABLE_ROWS = 500  # Maximum number of rows to display in table
DEFAULT_UPDATE_INTERVAL_MS = 1000  # Default update interval in milliseconds
MAX_BUFFER_SIZE = 1000  # Maximum buffer size per sensor

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
        self.client.on_publish = self._on_publish # Optional: for logging successful publishes

        self._is_connected = False
        self._stop_requested = False
        self.publish_queue = [] # (topic, payload, qos, retain)

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
            self._stop_requested = True # Dừng worker nếu không kết nối được

    def _on_disconnect(self, client, userdata, reason_code, properties):
        self._is_connected = False
        # reason_code = 0 thường là do người dùng chủ động ngắt kết nối
        msg = f"Đã ngắt kết nối MQTT Broker (RC: {reason_code})" if reason_code == 0 else f"Mất kết nối MQTT Broker (RC: {reason_code})"
        self.connection_status_changed.emit(False, msg)
        logger.info(f"MQTT: Disconnected (RC: {reason_code})")
        # Không tự động dừng worker ở đây, có thể thử kết nối lại hoặc chờ lệnh dừng

    def _on_publish(self, client, userdata, mid, reason_code, properties):
        # logger.debug(f"MQTT: Data published with MID {mid}, RC {reason_code}")
        pass


    def connect_to_broker(self):
        if self._is_connected:
            logger.info("MQTT: Already connected.")
            return
        self._stop_requested = False # Reset cờ dừng
        try:
            logger.info(f"MQTT: Attempting to connect to {self.broker_address}:{self.port}")
            self.client.connect(self.broker_address, self.port, keepalive=60)
            self.client.loop_start() # Bắt đầu vòng lặp mạng trong luồng riêng
        except Exception as e:
            self._is_connected = False
            error_msg = f"Lỗi khởi tạo kết nối MQTT: {e}"
            self.connection_status_changed.emit(False, error_msg)
            logger.error(error_msg, exc_info=True)
            self._stop_requested = True

    def publish_message(self, topic, payload_dict, qos=0, retain=False):
        if not self._is_connected:
            # self.error_occurred.emit("MQTT chưa kết nối. Không thể gửi tin nhắn.")
            # logger.warning("MQTT not connected. Cannot publish.")
            # Có thể đưa vào hàng đợi nếu muốn
            return False
        try:
            payload_str = json.dumps(payload_dict)
            msg_info = self.client.publish(topic, payload_str, qos=qos, retain=retain)
            if msg_info.is_published(): # Kiểm tra ngay nếu có thể (cho QoS 0)
                 # logger.debug(f"MQTT: Queued publish to {topic}: {payload_str[:50]}...")
                 self.message_published.emit(topic, payload_str[:80] + "..." if len(payload_str) > 80 else payload_str)
            else: # Chờ callback on_publish cho QoS > 0
                pass
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
            self.client.loop_stop() # Dừng vòng lặp mạng
            self.client.disconnect()
            logger.info("MQTT: Disconnected by stop request.")
        else:
            # Nếu không kết nối, vẫn đảm bảo loop_stop được gọi nếu nó đã start
            self.client.loop_stop(force=True)
            logger.info("MQTT: Loop stopped (was not connected).")


class DataHubScreenWidget(QWidget):
    """Widget for displaying and managing sensor data with MQTT publishing capabilities."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sensor_manager = None
        self.data_processor = None

        # Data management
        self._data_buffer = {}  # sensor_id -> [timestamp, data_point_dict]
        self._selected_sensors_for_table = []
        self._column_map = {}  # Map 'SensorID_DataKey' to column index
        self._last_update_time = {}  # Track last update time for each sensor
        self._update_interval_ms = DEFAULT_UPDATE_INTERVAL_MS
        self._max_buffer_size = MAX_BUFFER_SIZE
        self._is_updating_table = False  # Flag to prevent concurrent updates

        # MQTT management
        self.mqtt_worker = None
        self.mqtt_thread = None

        # Initialize UI and start update timer
        self.init_ui()
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.refresh_data_display)
        self.update_timer.start(self._update_interval_ms)

    def set_managers(self, sensor_manager, data_processor):
        """Set the sensor manager and data processor instances."""
        try:
            self.sensor_manager = sensor_manager
            self.data_processor = data_processor
            self.update_sensor_selection_combo()

            if self.sensor_manager:
                self.sensor_manager.sensorDataReceived.connect(self.handle_raw_sensor_data)
                self.sensor_manager.sensorListChanged.connect(self.update_sensor_selection_combo)
        except Exception as e:
            logger.error(f"Error setting managers: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to initialize managers: {str(e)}")

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # --- Phần hiển thị dữ liệu dạng bảng ---
        table_group = QGroupBox("Hiển thị Dữ liệu Cảm biến Dạng Bảng")
        table_layout = QVBoxLayout(table_group)

        # Chọn cảm biến và trường dữ liệu để hiển thị
        selection_layout = QHBoxLayout()
        selection_layout.addWidget(QLabel("Chọn cảm biến hiển thị:"))
        self.sensor_selection_combo = QComboBox()
        self.sensor_selection_combo.setToolTip("Chọn các cảm biến để hiển thị trong bảng bên dưới.")
        self.update_table_button = QPushButton("Cập nhật Bảng")
        self.update_table_button.clicked.connect(self._update_table_structure_and_data)
        selection_layout.addWidget(self.sensor_selection_combo, 1)
        selection_layout.addWidget(self.update_table_button)
        table_layout.addLayout(selection_layout)

        self.data_table = QTableWidget()
        self.data_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.data_table.setAlternatingRowColors(True)
        table_layout.addWidget(self.data_table)

        export_button = QPushButton(QIcon.fromTheme("document-save"), "Xuất ra CSV")
        export_button.clicked.connect(self.export_table_to_csv)
        table_layout.addWidget(export_button, 0, Qt.AlignmentFlag.AlignRight)
        splitter.addWidget(table_group)


        # --- Phần cấu hình và điều khiển MQTT Publisher ---
        mqtt_group = QGroupBox("Truyền Dữ liệu qua MQTT (Publisher)")
        mqtt_layout_main = QVBoxLayout(mqtt_group)

        mqtt_config_layout = QFormLayout()
        self.mqtt_broker_input = QLineEdit("mqtt.eclipseprojects.io") # Broker test công cộng
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
        splitter.setStretchFactor(0, 3) # Bảng chiếm nhiều hơn
        splitter.setStretchFactor(1, 2)

        # Add performance control widgets
        performance_group = QGroupBox("Cài đặt Hiệu suất")
        performance_layout = QFormLayout(performance_group)
        
        self.update_interval_spinbox = QSpinBox()
        self.update_interval_spinbox.setRange(100, 5000)
        self.update_interval_spinbox.setValue(self._update_interval_ms)
        self.update_interval_spinbox.setSuffix(" ms")
        self.update_interval_spinbox.valueChanged.connect(self.update_refresh_interval)
        
        self.max_rows_spinbox = QSpinBox()
        self.max_rows_spinbox.setRange(100, 10000)
        self.max_rows_spinbox.setValue(MAX_TABLE_ROWS)
        self.max_rows_spinbox.valueChanged.connect(self.update_max_rows)
        
        performance_layout.addRow("Tần suất cập nhật:", self.update_interval_spinbox)
        performance_layout.addRow("Số dòng tối đa:", self.max_rows_spinbox)
        
        # Add to main layout
        main_layout.addWidget(performance_group)

    def update_refresh_interval(self, interval_ms):
        """Update the refresh interval for the data table."""
        try:
            if not (100 <= interval_ms <= 5000):
                raise ValueError("Update interval must be between 100ms and 5000ms")
            
            self._update_interval_ms = interval_ms
            self.update_timer.setInterval(interval_ms)
            logger.info(f"Data table refresh interval updated to {interval_ms}ms")
        except Exception as e:
            logger.error(f"Error updating refresh interval: {str(e)}", exc_info=True)
            QMessageBox.warning(self, "Error", f"Failed to update refresh interval: {str(e)}")

    def update_max_rows(self, max_rows):
        """Update the maximum number of rows to display."""
        try:
            if not (100 <= max_rows <= 10000):
                raise ValueError("Maximum rows must be between 100 and 10000")
            
            global MAX_TABLE_ROWS
            MAX_TABLE_ROWS = max_rows
            self._trim_data_buffers()
            logger.info(f"Maximum table rows updated to {max_rows}")
        except Exception as e:
            logger.error(f"Error updating max rows: {str(e)}", exc_info=True)
            QMessageBox.warning(self, "Error", f"Failed to update maximum rows: {str(e)}")

    def _trim_data_buffers(self):
        """Trim data buffers to maintain maximum size."""
        try:
            for sensor_id in self._data_buffer:
                if len(self._data_buffer[sensor_id]) > MAX_TABLE_ROWS:
                    self._data_buffer[sensor_id] = self._data_buffer[sensor_id][-MAX_TABLE_ROWS:]
        except Exception as e:
            logger.error(f"Error trimming data buffers: {str(e)}", exc_info=True)

    def handle_raw_sensor_data(self, sensor_id, data_dict):
        """Handle incoming sensor data with improved error handling and data validation."""
        try:
            if sensor_id not in self._selected_sensors_for_table:
                return

            current_timestamp = time.time()
            
            # Validate data
            if not isinstance(data_dict, dict):
                logger.warning(f"Invalid data format from sensor {sensor_id}")
                return

            # Initialize buffer if needed
            if sensor_id not in self._data_buffer:
                self._data_buffer[sensor_id] = []
            
            # Create data entry with validation
            entry = {
                'timestamp': current_timestamp,
                'sensor_id': sensor_id
            }
            
            # Add validated data fields
            for key, value in data_dict.items():
                if isinstance(value, (int, float)):
                    entry[key] = float(value)
                else:
                    entry[key] = str(value)

            # Add to buffer with size limit
            self._data_buffer[sensor_id].append(entry)
            if len(self._data_buffer[sensor_id]) > self._max_buffer_size:
                self._data_buffer[sensor_id].pop(0)

            # Update MQTT if connected
            self._handle_mqtt_publishing(sensor_id, current_timestamp, data_dict)

        except Exception as e:
            logger.error(f"Error handling sensor data: {str(e)}", exc_info=True)
            QMessageBox.warning(self, "Data Processing Error", 
                              f"Error processing data from sensor {sensor_id}: {str(e)}")

    def _handle_mqtt_publishing(self, sensor_id, timestamp, raw_data):
        """Handle MQTT publishing with improved error handling."""
        if not (self.mqtt_worker and self.mqtt_worker._is_connected):
            return

        try:
            data_to_publish = {}
            
            # Add raw data if selected
            if self.publish_raw_checkbox.isChecked():
                data_to_publish['raw'] = raw_data
            
            # Add processed data if selected and available
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
        """Get latest processed data with error handling."""
        try:
            proc_data = self.data_processor.get_plot_data_for_sensor(sensor_id)
            if not proc_data:
                return None

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
        """Update the data table with improved performance and error handling."""
        if self._is_updating_table or not self._selected_sensors_for_table or not self._column_map:
            return

        try:
            self._is_updating_table = True
            self.data_table.setSortingEnabled(False)

            # Get latest data points
            display_points = self._get_latest_data_points()
            
            # Update table efficiently
            self._update_table_efficiently(display_points)

        except Exception as e:
            logger.error(f"Error refreshing data display: {str(e)}", exc_info=True)
            QMessageBox.warning(self, "Display Error", 
                              f"Error updating data table: {str(e)}")
        finally:
            self._is_updating_table = False
            self.data_table.setSortingEnabled(True)

    def _get_latest_data_points(self):
        """Get latest data points from all selected sensors."""
        all_points = []
        for sensor_id in self._selected_sensors_for_table:
            if sensor_id in self._data_buffer:
                all_points.extend(self._data_buffer[sensor_id])
        
        # Sort by timestamp and get latest points
        all_points.sort(key=lambda x: x['timestamp'], reverse=True)
        return all_points[:MAX_TABLE_ROWS]

    def _update_table_efficiently(self, display_points):
        """Update table efficiently with minimal UI updates."""
        current_rows = self.data_table.rowCount()
        new_rows = len(display_points)
        
        # Adjust row count if needed
        if current_rows != new_rows:
            self.data_table.setRowCount(new_rows)
        
        # Update cells efficiently
        for row_idx, point_data in enumerate(display_points):
            # Update timestamp
            ts_item = QTableWidgetItem(f"{point_data['timestamp']:.3f}")
            self.data_table.setItem(row_idx, 0, ts_item)
            
            # Update data columns
            sensor_id = point_data['sensor_id']
            for data_key, value in point_data.items():
                if data_key in ['timestamp', 'sensor_id']:
                    continue
                
                column_map_key = f"{sensor_id}_{data_key}"
                if column_map_key in self._column_map:
                    col_idx = self._column_map[column_map_key]
                    val_str = f"{value:.4f}" if isinstance(value, float) else str(value)
                    self.data_table.setItem(row_idx, col_idx, QTableWidgetItem(val_str))

    def export_table_to_csv(self):
        """Export table data to CSV with improved error handling and performance."""
        if self.data_table.rowCount() == 0:
            QMessageBox.information(self, "Information", "No data to export.")
            return

        try:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save CSV", "", "CSV Files (*.csv);;All Files (*.*)")
            if not path:
                return

            # Ensure .csv extension
            if not path.lower().endswith('.csv'):
                path += '.csv'

            # Prepare data for export
            headers = [self.data_table.horizontalHeaderItem(i).text() 
                      for i in range(self.data_table.columnCount())]
            
            # Use a list comprehension for better performance
            data = [
                [self.data_table.item(row, col).text() if self.data_table.item(row, col) else ""
                 for col in range(self.data_table.columnCount())]
                for row in range(self.data_table.rowCount())
            ]

            # Write to CSV
            with open(path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(headers)
                writer.writerows(data)

            QMessageBox.information(self, "Success", 
                                  f"Successfully exported {self.data_table.rowCount()} rows to: {path}")

        except PermissionError:
            QMessageBox.critical(self, "Error", 
                               "Cannot write to file. It may be open in another program.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export CSV: {str(e)}")
            logger.error(f"Error exporting CSV: {str(e)}", exc_info=True)

    def closeEvent(self, event):
        """Handle cleanup when widget is closed"""
        try:
            if self.mqtt_worker:
                self.mqtt_worker.stop()
            if self.mqtt_thread and self.mqtt_thread.isRunning():
                self.mqtt_thread.quit()
                self.mqtt_thread.wait(500)
            self.update_timer.stop()
            self._data_buffer.clear()
            super().closeEvent(event)
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}", exc_info=True)
            super().closeEvent(event)

    def toggle_mqtt_connection(self):
        """Toggle MQTT connection with improved error handling."""
        try:
            if self.mqtt_worker and self.mqtt_worker._is_connected:
                self._disconnect_mqtt()
            else:
                self._connect_mqtt()
        except Exception as e:
            logger.error(f"Error toggling MQTT connection: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "MQTT Error", f"Failed to toggle MQTT connection: {str(e)}")

    def _disconnect_mqtt(self):
        """Disconnect from MQTT broker safely."""
        try:
            self.mqtt_worker.stop()
            if self.mqtt_thread and self.mqtt_thread.isRunning():
                self.mqtt_thread.quit()
                if not self.mqtt_thread.wait(1000):
                    logger.warning("MQTT thread did not quit gracefully.")
                    self.mqtt_thread.terminate()
                self.mqtt_thread = None
            self.mqtt_worker = None
            self.mqtt_connect_button.setText("Connect MQTT")
            self.set_mqtt_status(False, "Manually disconnected.")
        except Exception as e:
            logger.error(f"Error disconnecting MQTT: {str(e)}", exc_info=True)
            raise

    def _connect_mqtt(self):
        """Connect to MQTT broker with validation."""
        try:
            broker = self.mqtt_broker_input.text().strip()
            if not broker:
                raise ValueError("MQTT Broker address cannot be empty")

            try:
                port = int(self.mqtt_port_input.text().strip())
                if not (0 < port < 65536):
                    raise ValueError("Port must be between 1 and 65535")
            except ValueError as e:
                raise ValueError(f"Invalid MQTT port: {str(e)}")

            client_id = self.mqtt_client_id_input.text().strip()
            username = self.mqtt_username_input.text().strip()
            password = self.mqtt_password_input.text()

            self.mqtt_worker = MQTTPublisherWorker(
                broker, port, client_id,
                username if username else None,
                password if password else None
            )
            self.mqtt_thread = QThread(self)
            self.mqtt_worker.moveToThread(self.mqtt_thread)

            # Connect signals
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
        """Handle MQTT connection status changes."""
        try:
            self.set_mqtt_status(connected, message)
            self.mqtt_connect_button.setEnabled(True)
            
            if connected:
                self.mqtt_connect_button.setText("Disconnect MQTT")
            else:
                self.mqtt_connect_button.setText("Connect MQTT")
                # Clean up if disconnected unexpectedly
                if self.mqtt_worker and not self.mqtt_worker._stop_requested:
                    self._cleanup_mqtt_resources()
        except Exception as e:
            logger.error(f"Error handling MQTT connection status: {str(e)}", exc_info=True)

    def _cleanup_mqtt_resources(self):
        """Clean up MQTT resources safely."""
        try:
            if self.mqtt_thread and self.mqtt_thread.isRunning():
                self.mqtt_thread.quit()
                self.mqtt_thread.wait(500)
            self.mqtt_worker = None
            self.mqtt_thread = None
        except Exception as e:
            logger.error(f"Error cleaning up MQTT resources: {str(e)}", exc_info=True)

    def handle_mqtt_message_published(self, topic, payload_preview):
        """Handle successful MQTT message publication."""
        try:
            timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
            log_msg = f"[{timestamp}] Published to {topic}: {payload_preview}\n"
            self.mqtt_log_display.insertPlainText(log_msg)
            self.mqtt_log_display.ensureCursorVisible()
        except Exception as e:
            logger.error(f"Error handling MQTT message published: {str(e)}", exc_info=True)

    def handle_mqtt_error(self, error_message):
        """Handle MQTT errors."""
        try:
            timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
            log_msg = f"[{timestamp}] MQTT Error: {error_message}\n"
            self.mqtt_log_display.insertPlainText(log_msg)
            self.mqtt_log_display.ensureCursorVisible()
        except Exception as e:
            logger.error(f"Error handling MQTT error: {str(e)}", exc_info=True)

    def set_mqtt_status(self, connected, message):
        """Set MQTT connection status with visual feedback."""
        try:
            self.mqtt_status_label.setText(f"MQTT Status: {message}")
            self.mqtt_status_label.setStyleSheet(
                "color: green;" if connected else "color: red;"
            )
            timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
            log_msg = f"[{timestamp}] Status: {message}\n"
            self.mqtt_log_display.insertPlainText(log_msg)
            self.mqtt_log_display.ensureCursorVisible()
        except Exception as e:
            logger.error(f"Error setting MQTT status: {str(e)}", exc_info=True)

    def _update_table_structure_and_data(self):
        """Update the table structure and data based on selected sensors."""
        try:
            self.data_table.setRowCount(0)  # Clear existing data
            self.data_table.setColumnCount(0)
            self._column_map.clear()
            self._data_buffer.clear()  # Clear data buffer when table structure changes

            selected_sensor_id_user_data = self.sensor_selection_combo.currentData()
            
            sensors_to_display_ids = []
            if selected_sensor_id_user_data is None:  # "All sensors" selected
                if self.sensor_manager:
                    sensors_to_display_ids = self.sensor_manager.get_all_sensor_ids()
            elif selected_sensor_id_user_data:  # Specific sensor selected
                sensors_to_display_ids = [selected_sensor_id_user_data]

            if not sensors_to_display_ids or not self.data_processor:
                self.data_table.setHorizontalHeaderLabels(["Message"])
                self.data_table.insertRow(0)
                self.data_table.setItem(0, 0, QTableWidgetItem(
                    "No sensors selected or DataProcessor not ready."))
                return

            self._selected_sensors_for_table = sensors_to_display_ids
            
            # Build table headers
            headers = ["Timestamp"]
            col_idx = 1
            for sensor_id in self._selected_sensors_for_table:
                # Get sample data keys from sensor instance
                sensor_instance = self.sensor_manager.get_sensor_instance(sensor_id)
                sample_raw_data = sensor_instance.last_data if sensor_instance and sensor_instance.last_data else {}
                
                # Get processed data keys
                data_keys_to_show = []
                if self.publish_raw_checkbox.isChecked() and sample_raw_data:
                    data_keys_to_show.extend(sorted(sample_raw_data.keys()))
                elif self.publish_processed_checkbox.isChecked():
                    processed_keys = []
                    plot_data = self.data_processor.get_plot_data_for_sensor(sensor_id)
                    for main_key in ['acc_data', 'vel_data', 'disp_data']:
                        if plot_data and main_key in plot_data:
                            for axis_key in plot_data[main_key]:
                                processed_keys.append(
                                    f"{main_key.replace('_data','').capitalize()}{axis_key.upper()}")
                    data_keys_to_show.extend(sorted(list(set(processed_keys))))

                if not data_keys_to_show and sample_raw_data:  # Fallback to raw if no processed data
                    data_keys_to_show.extend(sorted(sample_raw_data.keys()))

                for data_key in data_keys_to_show:
                    column_name = f"{sensor_id}_{data_key}"
                    headers.append(f"{sensor_id.split('_')[0]}_{data_key}")  # Shorter column name
                    self._column_map[column_name] = col_idx
                    col_idx += 1
            
            # Set up table structure
            self.data_table.setColumnCount(len(headers))
            self.data_table.setHorizontalHeaderLabels(headers)
            self.data_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            if len(headers) > 1:
                self.data_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

            # Refresh data display
            self.refresh_data_display()

        except Exception as e:
            logger.error(f"Error updating table structure: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to update table structure: {str(e)}")

    def update_sensor_selection_combo(self):
        self.sensor_selection_combo.clear()
        if self.sensor_manager:
            all_sensor_ids = self.sensor_manager.get_all_sensor_ids()
            if all_sensor_ids:
                self.sensor_selection_combo.addItem("Tất cả cảm biến", userData=None)
                for sensor_id in all_sensor_ids:
                    s_info = self.sensor_manager.get_sensor_info(sensor_id)
                    name = s_info.get('config', {}).get('name', sensor_id) if s_info else sensor_id
                    self.sensor_selection_combo.addItem(f"{name} ({sensor_id})", userData=sensor_id)
            else:
                self.sensor_selection_combo.addItem("Không có cảm biến nào", userData=None)
        else:
            self.sensor_selection_combo.addItem("SensorManager chưa sẵn sàng", userData=None)