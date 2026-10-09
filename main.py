import sys
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QRectF, QSize, Qt, QStandardPaths, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QFont, QImage, QPainter, QPen, QPixmap, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from flower_library import LibraryWorker


class CropPreview(QWidget):
    selection_changed = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(480, 260)
        self.setMouseTracking(True)
        self.image = QPixmap()
        self.image_size = (0, 0)
        self.anchor = None
        self.selection = None
        self.target = QRectF()

    def set_image(self, data, width, height):
        self.image = QPixmap.fromImage(QImage.fromData(data))
        self.image_size = (width, height)
        self.anchor = None
        self.selection = None
        self.update()

    def clear_selection(self):
        self.selection = None
        self.update()
        self.selection_changed.emit()

    def normalized_selection(self):
        if not self.selection or not self.target.width() or not self.target.height():
            return None
        box = QRectF(self.selection).normalized().intersected(self.target)
        if box.width() < 4 or box.height() < 4:
            return None
        return (
            (box.left() - self.target.left()) / self.target.width(),
            (box.top() - self.target.top()) / self.target.height(),
            box.width() / self.target.width(),
            box.height() / self.target.height(),
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f5f6f8"))
        if self.image.isNull():
            painter.setPen(QColor("#727987"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "选择查询图片，可直接使用局部截图，也可在图上框选")
            return
        scaled = self.image.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.target = QRectF((self.width() - scaled.width()) / 2, (self.height() - scaled.height()) / 2, scaled.width(), scaled.height())
        painter.drawPixmap(self.target.topLeft(), scaled)
        if self.selection:
            painter.setPen(QPen(QColor("#e97445"), 2, Qt.PenStyle.DashLine))
            painter.drawRect(self.selection.normalized())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.target.contains(event.position()):
            self.anchor = event.position().toPoint()
            self.selection = QRect(self.anchor, self.anchor)

    def mouseMoveEvent(self, event):
        if self.anchor is not None:
            self.selection = QRect(self.anchor, event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        if self.anchor is not None:
            self.selection = QRect(self.anchor, event.position().toPoint()).normalized()
            self.anchor = None
            self.update()
            self.selection_changed.emit()


class Signals(QObject):
    initialize = Signal()
    add_root = Signal(str)
    rescan = Signal()
    preview = Signal(str)
    search = Signal(str, object)
    convert = Signal(str, str)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("花型搜图")
        self.resize(1120, 760)
        data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        data_dir.mkdir(parents=True, exist_ok=True)

        self.thread = QThread(self)
        self.worker = LibraryWorker(data_dir)
        self.worker.moveToThread(self.thread)
        self.signals = Signals()
        self.signals.initialize.connect(self.worker.initialize)
        self.signals.add_root.connect(self.worker.add_root)
        self.signals.rescan.connect(self.worker.rescan)
        self.signals.preview.connect(self.worker.load_preview)
        self.signals.search.connect(self.worker.search)
        self.signals.convert.connect(self.worker.convert)
        self.worker.status.connect(self.set_status)
        self.worker.progress.connect(self.set_progress)
        self.worker.roots_changed.connect(self.show_roots)
        self.worker.preview_ready.connect(self.set_preview)
        self.worker.results.connect(self.show_results)
        self.worker.failed.connect(self.show_error)

        tabs = QTabWidget()
        tabs.addTab(self._search_page(), "以图搜图")
        tabs.addTab(self._library_page(), "图库管理")
        tabs.addTab(self._convert_page(), "TIFF 转 JPG")
        self.setCentralWidget(tabs)

        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(12, 4, 12, 8)
        self.status_label = QLabel("正在启动本地图库…")
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(230)
        self.progress_bar.setRange(0, 1)
        footer_layout.addWidget(self.status_label, 1)
        footer_layout.addWidget(self.progress_bar)
        self.statusBar().addPermanentWidget(footer, 1)

        self.thread.start()
        self.signals.initialize.emit()

    def _search_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.query_path = QLineEdit()
        self.query_path.setPlaceholderText("选择整图或局部截图")
        choose = QPushButton("选择图片")
        choose.clicked.connect(self.choose_query)
        self.search_button = QPushButton("开始搜索")
        self.search_button.clicked.connect(self.start_search)
        row.addWidget(self.query_path, 1)
        row.addWidget(choose)
        row.addWidget(self.search_button)
        layout.addLayout(row)

        self.preview = CropPreview()
        layout.addWidget(self.preview, 1)
        tools = QHBoxLayout()
        hint = QLabel("拖动鼠标可框选局部；不框选时搜索整张图片。")
        clear = QPushButton("清除框选")
        clear.clicked.connect(self.preview.clear_selection)
        tools.addWidget(hint, 1)
        tools.addWidget(clear)
        layout.addLayout(tools)

        self.results_list = QListWidget()
        self.results_list.setIconSize(QSize(120, 80))
        self.results_list.itemDoubleClicked.connect(self.open_result)
        layout.addWidget(self.results_list, 1)
        return page

    def _library_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        add = QPushButton("添加图库目录")
        add.clicked.connect(self.add_root)
        scan = QPushButton("更新图库索引")
        scan.clicked.connect(self.signals.rescan.emit)
        row.addWidget(add)
        row.addWidget(scan)
        row.addStretch(1)
        layout.addLayout(row)
        self.roots_list = QListWidget()
        layout.addWidget(self.roots_list)
        return page

    def _convert_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.source_dir = QLineEdit()
        self.output_dir = QLineEdit()
        source_button = QPushButton("选择…")
        output_button = QPushButton("选择…")
        source_row = QWidget()
        source_layout = QHBoxLayout(source_row)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.addWidget(self.source_dir)
        source_layout.addWidget(source_button)
        output_row = QWidget()
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(self.output_dir)
        output_layout.addWidget(output_button)
        source_button.clicked.connect(lambda: self.select_directory(self.source_dir))
        output_button.clicked.connect(lambda: self.select_directory(self.output_dir))
        form.addRow("TIFF 来源目录", source_row)
        form.addRow("JPG 输出目录", output_row)
        layout.addLayout(form)
        layout.addWidget(QLabel("默认最长边 4,096 像素、质量 90；输出到独立目录，已有文件不会覆盖。"))
        convert = QPushButton("批量转换")
        convert.clicked.connect(self.start_conversion)
        layout.addWidget(convert)
        layout.addStretch(1)
        return page

    def choose_query(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择查询图片", "", "图片 (*.tif *.tiff *.jpg *.jpeg *.png)")
        if path:
            self.query_path.setText(path)
            self.signals.preview.emit(path)

    def add_root(self):
        path = QFileDialog.getExistingDirectory(self, "选择花型图库目录")
        if path:
            self.signals.add_root.emit(path)

    def select_directory(self, field):
        path = QFileDialog.getExistingDirectory(self, "选择目录")
        if path:
            field.setText(path)

    def start_search(self):
        path = self.query_path.text().strip()
        if not path or not Path(path).is_file():
            QMessageBox.information(self, "需要查询图片", "请选择一张查询图片。")
            return
        self.results_list.clear()
        self.search_button.setEnabled(False)
        self.signals.search.emit(path, self.preview.normalized_selection())

    def start_conversion(self):
        source, output = self.source_dir.text().strip(), self.output_dir.text().strip()
        if not Path(source).is_dir() or not output:
            QMessageBox.information(self, "需要选择目录", "请分别选择 TIFF 来源目录和 JPG 输出目录。")
            return
        self.signals.convert.emit(source, output)

    @Slot(str, int, int)
    def set_preview(self, path, width, height):
        self.preview.set_image(Path(path).read_bytes(), width, height)

    @Slot(list)
    def show_results(self, matches):
        self.search_button.setEnabled(True)
        self.results_list.clear()
        for inliers, votes, path, thumbnail in matches:
            item = QListWidgetItem(QIcon(thumbnail), f"{Path(path).name}  ·  局部匹配 {inliers} 点\n{path}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.results_list.addItem(item)
        if not matches:
            self.set_status("没有找到可靠匹配；可以尝试框选更大、纹理更清晰的区域")
        else:
            self.set_status(f"找到 {len(matches)} 个候选，双击可打开原文件")

    @Slot(list)
    def show_roots(self, roots):
        self.roots_list.clear()
        self.roots_list.addItems(roots)

    def open_result(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @Slot(str)
    def set_status(self, message):
        self.status_label.setText(message)

    @Slot(int, int)
    def set_progress(self, current, total):
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(current)

    @Slot(str)
    def show_error(self, message):
        self.search_button.setEnabled(True)
        self.set_status(f"操作失败：{message}")

    def closeEvent(self, event):
        self.thread.requestInterruption()
        self.thread.quit()
        self.thread.wait()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("FlowerSearch")
    app.setOrganizationName("FlowerSearch")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
