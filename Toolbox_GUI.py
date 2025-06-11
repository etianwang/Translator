import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel,
    QVBoxLayout, QGraphicsBlurEffect, QSpacerItem, QSizePolicy
)
from PyQt5.QtGui import (
    QPixmap, QPainter, QPainterPath, QRegion, QColor, QFont, QFontDatabase, QIcon
)
from PyQt5.QtCore import Qt, QRectF, QPoint
import subprocess
from PDF_translator.PDF_translator_fn import run_pdf_gui
from CAD_translator.CAD_translator_fn import run_cad_gui
from PPT_translator.PPT_translator_fn import run_ppt_gui

def resource_path(relative_path):
    """兼容 PyInstaller 的资源路径"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

class ToolboxWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("✨ 翻译工具箱")
        self.setFixedSize(600, 600)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowIcon(QIcon(resource_path("assets/icon.ico")))
        self.drag_position = None  # 拖动支持

        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.setup_blurred_background()
        self.set_mask_round_corners(20)
        self.load_custom_font()
        self.setup_ui()
        self.add_close_button()

    def setup_blurred_background(self):
        bg_path = resource_path("assets/bg.png")
        original = QPixmap(bg_path).scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)

        # 创建一张透明层 pixmap
        transparent_pixmap = QPixmap(original.size())
        transparent_pixmap.fill(Qt.transparent)

        # 绘制原图并加透明度
        painter = QPainter(transparent_pixmap)
        painter.setOpacity(0.9)  # 👈 设置透明度（0 = 全透明，1 = 不透明）
        painter.drawPixmap(0, 0, original)
        painter.end()

        self.bg_label = QLabel(self)
        self.bg_label.setPixmap(transparent_pixmap)
        self.bg_label.setGeometry(0, 0, self.width(), self.height())

        # 模糊
        blur = QGraphicsBlurEffect()
        blur.setBlurRadius(5)
        self.bg_label.setGraphicsEffect(blur)
        self.bg_label.lower()

    def set_mask_round_corners(self, radius=20):
        path = QPainterPath()
        rect = QRectF(0, 0, self.width(), self.height())
        path.addRoundedRect(rect, radius, radius)
        region = QRegion(path.toFillPolygon().toPolygon())
        self.setMask(region)

    def load_custom_font(self):
        font_path = resource_path("assets/站酷文艺体.ttf")
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id == -1:
            print("❌ 字体加载失败，使用默认字体")
            self.setFont(QFont("微软雅黑", 16))
        else:
            family = QFontDatabase.applicationFontFamilies(font_id)
            if family:
                self.setFont(QFont(family[0], 16))
                print("✅ 加载字体成功：", family[0])
            else:
                self.setFont(QFont("微软雅黑", 16))

    def setup_ui(self):
        from PyQt5.QtWidgets import QFrame, QHBoxLayout

        # 主容器布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(10)

        # ===== 上方内容区 =====
        content_layout = QVBoxLayout()
        content_layout.setAlignment(Qt.AlignTop)

        label = QLabel("请选择要启动的工具：")
        label.setStyleSheet("color: white;")
        label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(label)

        content_layout.addSpacerItem(QSpacerItem(20, 30, QSizePolicy.Minimum, QSizePolicy.Fixed))

        button_style = """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.15);
                color: white;
                border: 2px solid white;
                border-radius: 12px;
                padding: 12px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.3);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.1);
            }
        """

        self.cad_button = QPushButton("🧱 CAD 翻译器")
        self.cad_button.setStyleSheet(button_style)
        self.cad_button.clicked.connect(run_cad_gui)
        content_layout.addWidget(self.cad_button)

        content_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Fixed))

        self.pdf_button = QPushButton("📄 PDF 翻译器")
        self.pdf_button.setStyleSheet(button_style)
        self.pdf_button.clicked.connect(run_pdf_gui)
        content_layout.addWidget(self.pdf_button)

        content_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Fixed))

        self.ppt_button = QPushButton("📊 PPT 翻译器")
        self.ppt_button.setStyleSheet(button_style)
        self.ppt_button.clicked.connect(run_ppt_gui)
        content_layout.addWidget(self.ppt_button)

        # 中间提示
        bottom_label = QLabel("🛠 Excel翻译工具开发中...")
        bottom_label.setStyleSheet("color: white; font-size: 30px;")
        bottom_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(bottom_label)

        # 将上方内容布局加到主布局
        main_layout.addLayout(content_layout)
        main_layout.addStretch()  # 撑开，让 footer 紧贴底部

        # ===== 下方 Footer 区 =====
        footer_container = QWidget()
        footer_container.setFixedHeight(50)  # 👈 固定 footer 区高度

        footer_layout = QVBoxLayout(footer_container)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(4)

        # 横线
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Plain)
        separator.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.3);
                max-height: 1px;
                min-height: 1px;
                border: none;
            }
        """)
        footer_layout.addWidget(separator)

        # Footer 文本
        footer_label = QLabel("© 2025 Honsen Etienne | 翻译工具箱 v1.0 | Powered by PyQt5")
        footer_label.setStyleSheet("color: rgba(255, 255, 255, 0.5); font-size: 20px;")
        footer_label.setAlignment(Qt.AlignCenter)
        footer_layout.addWidget(footer_label)

        # 加入主布局底部
        main_layout.addWidget(footer_container)

    def add_close_button(self):
        self.close_button = QPushButton("✕", self)
        self.close_button.setGeometry(self.width() - 35, 10, 25, 25)
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.2);
                color: white;
                border: 1px solid white;
                border-radius: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(255, 0, 0, 0.6);
            }
        """)
        self.close_button.clicked.connect(self.close)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_position:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def run_cad_translator(self):
        script_path = os.path.join(self.base_dir, "CAD_translator", "CAD_translator", "main.py")
        subprocess.Popen([sys.executable, script_path])

    def run_pdf_translator(self):
        script_path = os.path.join(self.base_dir, "PDF_translator", "main.py")
        subprocess.Popen([sys.executable, script_path])

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 加载字体
    font_path = resource_path("assets/站酷文艺体.ttf")
    font_id = QFontDatabase.addApplicationFont(font_path)
    if font_id != -1:
        family = QFontDatabase.applicationFontFamilies(font_id)[0]
        font = QFont(family, 18)  # 👈 设置字号为 18，默认是 11-12
    else:
        font = QFont("微软雅黑", 18)

    app.setFont(font)  # 👈 设置为全局应用字体
    window = ToolboxWindow()
    window.show()
    sys.exit(app.exec_())
