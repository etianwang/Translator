import sys
import os
import time
import requests
from datetime import datetime
from PyQt5 import QtWidgets, QtGui, QtCore
from PyQt5.QtWidgets import QApplication
from ._api import DoclingoAPI  # 保持原有调用

opened_windows = {}

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

DEFAULT_API_KEY = "sk_eafed7bbe0b0ce580d3eca2705fa68ce"


class PPTTranslatorUI(QtWidgets.QWidget):
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._mouse_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == QtCore.Qt.MouseButton.LeftButton:
            self.move(event.globalPos() - self._mouse_pos)
            event.accept()

    def __init__(self):
        super().__init__()
        self.setFixedSize(800, 860)
        self.setWindowFlags(QtCore.Qt.WindowType.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Honsen PPT 翻译器")

        font_path = resource_path("PPT_translator/站酷文艺体.ttf")
        font_id = QtGui.QFontDatabase.addApplicationFont(font_path)
        font_family = QtGui.QFontDatabase.applicationFontFamilies(font_id)[0]
        self.setFont(QtGui.QFont(font_family, 16))

        background = QtWidgets.QLabel(self)
        pixmap = QtGui.QPixmap(resource_path("PPT_translator/background.jpg")).scaled(self.size(), QtCore.Qt.AspectRatioMode.IgnoreAspectRatio)
        if not pixmap.isNull():
            mask = QtGui.QBitmap(pixmap.size())
            mask.fill(QtCore.Qt.GlobalColor.color0)
            painter = QtGui.QPainter(mask)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            painter.setBrush(QtGui.QBrush(QtCore.Qt.GlobalColor.color1))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawRoundedRect(pixmap.rect(), 20, 20)
            painter.end()
            pixmap.setMask(mask)

            transparent_pixmap = QtGui.QPixmap(pixmap.size())
            transparent_pixmap.fill(QtCore.Qt.GlobalColor.transparent)
            painter = QtGui.QPainter(transparent_pixmap)
            painter.setOpacity(0.4)
            painter.drawPixmap(0, 0, pixmap)
            painter.end()
            background.setPixmap(transparent_pixmap)

        background.setGeometry(0, 0, 800, 860)
        background.setStyleSheet("border-radius: 20px;")
        background.lower()

        container = QtWidgets.QWidget(self)
        container.setObjectName("container")
        container.setGeometry(20, 20, 760, 820)
        container.setStyleSheet("""
            #container {
                background-color: rgba(255, 255, 255, 100);
                border-radius: 20px;
                padding: 20px;
            }
            QLineEdit, QComboBox, QTextEdit {
                padding: 6px;
                border: 1px solid #ccc;
                border-radius: 10px;
                background-color: rgba(255, 255, 255, 200);
            }
            QPushButton {
                background-color: rgba(243, 243, 243, 0.6);
                color: black;
                padding: 8px;
                border: none;
                border-radius: 10px;
            }
            QPushButton:hover {
                background-color: rgba(172, 172, 172, 0.6);
            }
            QCheckBox {
                padding: 4px;
            }
        """)

        layout = QtWidgets.QVBoxLayout(container)

        close_btn = QtWidgets.QPushButton("✕")
        close_btn.setFixedSize(32, 32)
        close_btn.setStyleSheet("background-color: transparent; color: #333; font-size: 18px;")
        close_btn.clicked.connect(self.close)
        close_layout = QtWidgets.QHBoxLayout()
        close_layout.addStretch()
        close_layout.addWidget(close_btn)
        layout.addLayout(close_layout)

        title_label = QtWidgets.QLabel("Honsen PPT 翻译器（联网版v.1）")
        title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("color: #222; font-size: 30px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title_label)

        file_layout = QtWidgets.QHBoxLayout()
        self.file_input = QtWidgets.QLineEdit()
        browse_btn = QtWidgets.QPushButton("浏览 PPTX")
        browse_btn.clicked.connect(self.select_file)
        file_layout.addWidget(self.file_input)
        file_layout.addWidget(browse_btn)

        lang_layout = QtWidgets.QHBoxLayout()
        lang_label = QtWidgets.QLabel("目标语言：")
        self.lang_combo = QtWidgets.QComboBox()
        self.lang_combo.addItems(["en", "zh-CN", "fr", "de", "es", "ja", "ko", "ru", "it", "pt"])
        self.lang_combo.setCurrentText("fr")
        lang_layout.addWidget(lang_label)
        lang_layout.addWidget(self.lang_combo)

        engine_layout = QtWidgets.QHBoxLayout()
        engine_label = QtWidgets.QLabel("翻译引擎：")
        self.engine_combo = QtWidgets.QComboBox()
        self.engine_combo.addItems(["chatgpt-4omini", "claude", "gemini"])
        engine_layout.addWidget(engine_label)
        engine_layout.addWidget(self.engine_combo)

        self.ocr_checkbox = QtWidgets.QCheckBox("启用 OCR 图像识别")
        self.translate_btn = QtWidgets.QPushButton("开始翻译")
        self.translate_btn.clicked.connect(self.translate_ppt)

        self.log_output = QtWidgets.QTextEdit()
        self.log_output.setMinimumHeight(200)
        self.log_output.setReadOnly(True)

        layout.addLayout(file_layout)
        layout.addLayout(lang_layout)
        layout.addLayout(engine_layout)
        layout.addWidget(self.ocr_checkbox)
        layout.addWidget(self.translate_btn)
        layout.addWidget(QtWidgets.QLabel("日志输出："))
        layout.addWidget(self.log_output)

    def select_file(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择 PPT 文件", "", "PPTX 文件 (*.pptx)")
        if file_path:
            self.file_input.setText(file_path)

    def log(self, text):
        self.log_output.append(text)
        QtWidgets.QApplication.processEvents()

    def translate_ppt(self):
        file_path = self.file_input.text().strip()
        target_lang = self.lang_combo.currentText()
        engine = self.engine_combo.currentText()
        use_ocr = self.ocr_checkbox.isChecked()

        if not file_path:
            self.log("❗ 请先选择 PPT 文件。")
            return

        self.translate_btn.setEnabled(False)
        self.translate_btn.setText("处理中...")

        self.thread = TranslateThread(file_path, target_lang, engine, use_ocr, DEFAULT_API_KEY)
        self.thread.log_signal.connect(self.log)
        self.thread.done_signal.connect(self.on_translation_done)
        self.thread.start()

    def on_translation_done(self, path):
        QtWidgets.QMessageBox.information(self, "翻译成功", f"文件已保存至：\n{path}")
        os.startfile(path)
        self.translate_btn.setEnabled(True)
        self.translate_btn.setText("开始翻译")


class TranslateThread(QtCore.QThread):
    log_signal = QtCore.pyqtSignal(str)
    done_signal = QtCore.pyqtSignal(str)

    def __init__(self, file_path, target_lang, engine, use_ocr, api_key):
        super().__init__()
        self.file_path = file_path
        self.target_lang = target_lang
        self.engine = engine
        self.use_ocr = use_ocr
        self.api_key = api_key

    def run(self):
        def log(msg):
            self.log_signal.emit(msg)

        try:
            api = DoclingoAPI(self.api_key)
            log("📤 正在上传并发起翻译...")
            query_key = api.submit_translation_new(
                file_path=self.file_path,
                target_lang=self.target_lang,
                model=self.engine,
                ocr_flag=1 if self.use_ocr else 0
            )

            log("⏳ 正在查询翻译进度...")
            for _ in range(60):
                status_info = api.check_translation_status(query_key)
                status = status_info.get("status")
                progress = status_info.get("translateRate", "-")
                if status == 1:
                    url = status_info.get("targetFileUrl")
                    if url:
                        now = datetime.now()
                        base_name = os.path.splitext(os.path.basename(self.file_path))[0]
                        ext = os.path.splitext(url)[-1] or ".pptx"
                        time_str = now.strftime("%Hh%M_%d%m%y")
                        out_name = f"{self.target_lang}_{base_name}_{time_str}{ext}"
                        out_path = os.path.join(os.path.dirname(self.file_path), out_name)
                        log("📥 正在下载译文文件...")
                        r = requests.get(url)
                        with open(out_path, "wb") as f:
                            f.write(r.content)
                        log(f"🎉 翻译完成，文件已保存至：{out_path}")
                        self.done_signal.emit(out_path)
                        return
                elif status == 2:
                    reason = status_info.get("failReason", "未知错误")
                    log(f"❌ 翻译失败：{reason}")
                    return
                else:
                    log(f"⌛ 翻译中（进度：{progress}），等待中...")
                time.sleep(5)

            log("❌ 翻译超时，任务未完成。")
        except Exception as e:
            log(f"❌ 出现异常：{str(e)}")


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    translator = PPTTranslatorUI()
    translator.show()
    sys.exit(app.exec())


def run_ppt_gui():
    try:
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        window = PPTTranslatorUI()
        window.show()
        opened_windows["ppt"] = window

    except Exception as e:
        import traceback
        with open("ppt_crash.log", "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
