import sys
import logging
from PyQt6.QtWidgets import QApplication
import pyqtgraph as pg
from ui.main_window import MainWindow

# Cấu hình logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    app = QApplication(sys.argv)
    
    # Cấu hình pyqtgraph
    pg.setConfigOptions(antialias=True)
    pg.setConfigOption('background', 'w')
    pg.setConfigOption('foreground', 'k')

    # Khởi tạo và hiển thị cửa sổ chính
    main_win = MainWindow()
    main_win.show()

    # Chạy ứng dụng
    sys.exit(app.exec())

if __name__ == '__main__':
    main() 