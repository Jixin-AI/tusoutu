from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRectF, QSize, QSettings, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QImageReader, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from library import format_elapsed, scan_and_convert, search_images


class TaskThread(QThread):
    progress = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, task):
        super().__init__()
        self.task = task

    def run(self):
        try:
            self.succeeded.emit(self.task(self.progress.emit))
        except Exception as exc:
            self.failed.emit(str(exc))


class CropView(QGraphicsView):
    def __init__(self, image: QImage):
        super().__init__()
        self.image = image
        self.graphics_scene = QGraphicsScene(self)
        self.graphics_scene.addPixmap(QPixmap.fromImage(image))
        self.setScene(self.graphics_scene)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setBackgroundBrush(Qt.GlobalColor.darkGray)
        self.start = QPointF()
        self.selection: QGraphicsRectItem | None = None
        self.crop_rect = QRectF()
        self.drawing = False
        self.fitInView(self.graphics_scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.graphics_scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _image_point(self, point: QPointF) -> QPointF:
        bounds = self.graphics_scene.sceneRect()
        return QPointF(
            min(max(point.x(), bounds.left()), bounds.right()),
            min(max(point.y(), bounds.top()), bounds.bottom()),
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start = self._image_point(self.mapToScene(event.position().toPoint()))
            self.drawing = True
            if self.selection:
                self.graphics_scene.removeItem(self.selection)
            self.selection = self.graphics_scene.addRect(QRectF(self.start, self.start), QPen(Qt.GlobalColor.red, 2))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.selection and self.drawing:
            end = self._image_point(self.mapToScene(event.position().toPoint()))
            self.crop_rect = QRectF(self.start, end).normalized()
            self.selection.setRect(self.crop_rect)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.selection and event.button() == Qt.MouseButton.LeftButton:
            end = self._image_point(self.mapToScene(event.position().toPoint()))
            self.crop_rect = QRectF(self.start, end).normalized()
            self.selection.setRect(self.crop_rect)
            self.drawing = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def cropped_image(self) -> QImage:
        if self.crop_rect.width() < 2 or self.crop_rect.height() < 2:
            return QImage()
        return self.image.copy(self.crop_rect.toAlignedRect())


class CropDialog(QDialog):
    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.setWindowTitle("裁剪查询图片")
        self.resize(900, 650)
        self.view = CropView(image)
        self.crop = QImage()
        hint = QLabel("在图片上拖动鼠标选择要搜索的区域")
        buttons = QHBoxLayout()
        cancel = QPushButton("取消")
        apply = QPushButton("使用裁剪区域")
        cancel.clicked.connect(self.reject)
        apply.clicked.connect(self._accept_crop)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(apply)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.view, 1)
        layout.addLayout(buttons)

    def _accept_crop(self):
        self.crop = self.view.cropped_image()
        if self.crop.isNull():
            QMessageBox.information(self, "提示", "请先拖动选择裁剪区域。")
            return
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("花型图搜图")
        self.resize(1180, 800)
        self.settings = QSettings("JixinAI", "FlowerSearch")
        self.source_root = Path(self.settings.value("source_root", "")) if self.settings.value("source_root", "") else None
        self.output_root = Path(self.settings.value("output_root", "")) if self.settings.value("output_root", "") else None
        self.query_image = QImage()
        self.worker: TaskThread | None = None
        self.busy = False
        self.monitor = QTimer(self)
        self.monitor.timeout.connect(self.start_scan)
        self.search_clock = QTimer(self)
        self.search_clock.timeout.connect(self._update_search_clock)
        self.search_started = 0.0
        self._build_ui()
        self._refresh_paths()
        if self.source_root and self.source_root.is_dir():
            self._populate_scope()

    def _build_ui(self):
        central = QWidget()
        root_layout = QVBoxLayout(central)

        folders = QGroupBox("花型库与 JPG 库")
        folder_form = QFormLayout(folders)
        source_row = QHBoxLayout()
        self.source_edit = QLineEdit()
        self.source_edit.setReadOnly(True)
        source_button = QPushButton("选择花型库")
        source_button.clicked.connect(self.choose_source)
        source_row.addWidget(self.source_edit, 1)
        source_row.addWidget(source_button)
        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setReadOnly(True)
        output_button = QPushButton("选择 JPG 库")
        output_button.clicked.connect(self.choose_output)
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(output_button)
        folder_form.addRow("源文件夹", source_row)
        folder_form.addRow("转换文件夹", output_row)

        controls = QHBoxLayout()
        self.scan_button = QPushButton("立即扫描并转换")
        self.scan_button.clicked.connect(self.start_scan)
        self.monitor_button = QPushButton("开始自动监测")
        self.monitor_button.clicked.connect(self.toggle_monitor)
        self.interval_value = QSpinBox()
        self.interval_value.setRange(1, 168)
        self.interval_value.setValue(1)
        self.interval_unit = QComboBox()
        self.interval_unit.addItem("小时", "hours")
        self.interval_unit.addItem("天", "days")
        self.interval_value.valueChanged.connect(self._update_interval_limit)
        self.interval_unit.currentIndexChanged.connect(self._update_interval_limit)
        controls.addWidget(self.scan_button)
        controls.addWidget(self.monitor_button)
        controls.addSpacing(12)
        controls.addWidget(QLabel("监测间隔"))
        controls.addWidget(self.interval_value)
        controls.addWidget(self.interval_unit)
        controls.addStretch(1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        controls.addWidget(self.progress, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("搜索范围（选择整个图库或子文件夹）"))
        self.scope_tree = QTreeWidget()
        self.scope_tree.setHeaderHidden(True)
        left_layout.addWidget(self.scope_tree, 2)
        left_layout.addWidget(QLabel("转换记录（每个文件显示耗时）"))
        self.conversion_table = QTableWidget(0, 4)
        self.conversion_table.setHorizontalHeaderLabels(["文件", "状态", "耗时", "说明"])
        self.conversion_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.conversion_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.conversion_table.setColumnWidth(1, 75)
        self.conversion_table.setColumnWidth(2, 100)
        left_layout.addWidget(self.conversion_table, 3)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        search_box = QGroupBox("以图搜图")
        search_layout = QVBoxLayout(search_box)
        self.query_preview = QLabel("选择或粘贴一张查询图片")
        self.query_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.query_preview.setMinimumHeight(190)
        self.query_preview.setStyleSheet("QLabel { background: #f2f4f7; border: 1px dashed #aeb6c2; color: #667085; }")
        query_buttons = QHBoxLayout()
        choose_query = QPushButton("上传图片")
        choose_query.clicked.connect(self.choose_query)
        paste_query = QPushButton("粘贴图片")
        paste_query.clicked.connect(self.paste_query)
        self.crop_button = QPushButton("裁剪")
        self.crop_button.clicked.connect(self.crop_query)
        query_buttons.addWidget(choose_query)
        query_buttons.addWidget(paste_query)
        query_buttons.addWidget(self.crop_button)
        query_buttons.addStretch(1)
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 100)
        self.threshold.setValue(20)
        query_buttons.addWidget(QLabel("相似度门槛"))
        query_buttons.addWidget(self.threshold)
        query_buttons.addWidget(QLabel("%"))
        self.search_button = QPushButton("开始搜索")
        self.search_button.clicked.connect(self.start_search)
        query_buttons.addWidget(self.search_button)
        search_layout.addWidget(self.query_preview)
        search_layout.addLayout(query_buttons)
        right_layout.addWidget(search_box)

        self.search_status = QLabel("选择花型库后，先扫描并转换，再开始搜索。")
        right_layout.addWidget(self.search_status)
        self.results_table = QTableWidget(0, 4)
        self.results_table.setHorizontalHeaderLabels(["相似度", "文件名", "页码", "源文件路径"])
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.results_table.setColumnWidth(0, 85)
        self.results_table.setColumnWidth(2, 65)
        self.results_table.cellDoubleClicked.connect(self.open_result)
        right_layout.addWidget(self.results_table, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)

        root_layout.addWidget(folders)
        root_layout.addLayout(controls)
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("就绪")

    def _refresh_paths(self):
        self.source_edit.setText(str(self.source_root) if self.source_root else "")
        self.output_edit.setText(str(self.output_root) if self.output_root else "")

    def choose_source(self):
        folder = QFileDialog.getExistingDirectory(self, "选择花型库文件夹")
        if not folder:
            return
        self.source_root = Path(folder)
        self.settings.setValue("source_root", folder)
        self.output_root = self.source_root.parent / f"{self.source_root.name}_JPG"
        self.settings.setValue("output_root", str(self.output_root))
        self._refresh_paths()
        self._populate_scope()

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "选择 JPG 库文件夹")
        if not folder:
            return
        self.output_root = Path(folder)
        self.settings.setValue("output_root", folder)
        self._refresh_paths()

    def _populate_scope(self):
        self.scope_tree.clear()
        if not self.source_root or not self.source_root.is_dir():
            return
        root_item = QTreeWidgetItem([self.source_root.name or str(self.source_root)])
        root_item.setData(0, Qt.ItemDataRole.UserRole, "")
        self.scope_tree.addTopLevelItem(root_item)
        try:
            output = self.output_root.resolve() if self.output_root else None
            directories = sorted(
                (p for p in self.source_root.rglob("*")
                 if p.is_dir() and (not output or not self._path_is_inside(p.resolve(), output))),
                key=lambda p: (len(p.parts), p.as_posix().casefold()),
            )
            items = {"": root_item}
            for directory in directories:
                relative = directory.relative_to(self.source_root).as_posix()
                parent_rel = Path(relative).parent.as_posix()
                parent_item = items.get("" if parent_rel == "." else parent_rel, root_item)
                item = QTreeWidgetItem([directory.name])
                item.setData(0, Qt.ItemDataRole.UserRole, relative)
                parent_item.addChild(item)
                items[relative] = item
            root_item.setExpanded(True)
            self.scope_tree.setCurrentItem(root_item)
        except OSError as exc:
            self.statusBar().showMessage(f"无法读取子文件夹：{exc}")

    @staticmethod
    def _path_is_inside(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    def _database_path(self) -> Path:
        if not self.output_root:
            raise ValueError("请先选择 JPG 库文件夹")
        return self.output_root / ".flower_search.sqlite3"

    def _start_task(self, task, on_success):
        if self.busy:
            return
        self.busy = True
        self.progress.setRange(0, 0)
        worker = TaskThread(task)
        self.worker = worker
        worker.progress.connect(self._on_progress)
        worker.succeeded.connect(on_success)
        worker.failed.connect(self._on_failure)
        worker.finished.connect(self._task_finished)
        worker.start()

    def start_scan(self):
        if self.busy:
            return
        if not self.source_root or not self.source_root.is_dir() or not self.output_root:
            QMessageBox.information(self, "提示", "请先选择花型库和 JPG 库文件夹。")
            return
        db_path = self._database_path()
        self.conversion_table.setRowCount(0)
        self.search_status.setText("正在扫描花型库并更新 JPG 库…")
        self._start_task(
            lambda report: scan_and_convert(self.source_root, self.output_root, db_path, report),
            self._scan_finished,
        )

    def _scan_finished(self, summary: dict):
        self._populate_scope()
        self.search_status.setText(
            f"扫描完成：发现 {summary['found']} 个文件，新增或转换 {summary['converted']} 个，"
            f"索引更新 {summary.get('reindexed', 0)} 个，"
            f"失败 {summary['failed']} 个，未变化 {summary['skipped']} 个。"
        )
        self.statusBar().showMessage("JPG 库已同步")

    def _update_interval_limit(self, *_):
        if self.interval_unit.currentData() == "days":
            self.interval_value.setRange(1, 7)
            self.interval_value.setSuffix(" 天")
        else:
            self.interval_value.setRange(1, 168)
            self.interval_value.setSuffix(" 小时")
        if self.monitor.isActive():
            self.monitor.start(self._interval_ms())

    def _interval_ms(self) -> int:
        multiplier = 24 if self.interval_unit.currentData() == "days" else 1
        return self.interval_value.value() * multiplier * 60 * 60 * 1000

    def toggle_monitor(self):
        if self.monitor.isActive():
            self.monitor.stop()
            self.monitor_button.setText("开始自动监测")
            self.statusBar().showMessage("自动监测已停止")
        else:
            if not self.source_root or not self.source_root.is_dir() or not self.output_root:
                QMessageBox.information(self, "提示", "请先选择花型库和 JPG 库文件夹。")
                return
            self.monitor.start(self._interval_ms())
            self.monitor_button.setText("停止自动监测")
            self.statusBar().showMessage("自动监测已启动（软件运行期间）")
            self.start_scan()

    def choose_query(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "选择查询图片", "", "图片文件 (*.jpg *.jpeg *.png *.bmp *.tif *.tiff)"
        )
        if filename:
            reader = QImageReader(filename)
            size = reader.size()
            if size.isValid() and max(size.width(), size.height()) > 2000:
                scale = 2000 / max(size.width(), size.height())
                reader.setScaledSize(QSize(round(size.width() * scale), round(size.height() * scale)))
            self._set_query(reader.read())

    def paste_query(self):
        image = QApplication.clipboard().image()
        if image.isNull():
            QMessageBox.information(self, "提示", "剪贴板里没有图片。")
            return
        self._set_query(image)

    def _set_query(self, image: QImage):
        if image.isNull():
            QMessageBox.warning(self, "无法读取图片", "请选择常见图片格式的文件。")
            return
        if max(image.width(), image.height()) > 2000:
            scale = 2000 / max(image.width(), image.height())
            image = image.scaled(
                round(image.width() * scale), round(image.height() * scale),
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
            )
        self.query_image = image
        pixmap = QPixmap.fromImage(image).scaled(
            self.query_preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.query_preview.setPixmap(pixmap)
        self.crop_button.setEnabled(True)

    def crop_query(self):
        if self.query_image.isNull():
            QMessageBox.information(self, "提示", "请先上传或粘贴查询图片。")
            return
        dialog = CropDialog(self.query_image, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set_query(dialog.crop)

    def _query_bytes(self) -> bytes:
        array = QByteArray()
        buffer = QBuffer(array)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self.query_image.save(buffer, "PNG")
        buffer.close()
        return bytes(array)

    def start_search(self):
        if self.busy:
            return
        if self.query_image.isNull():
            QMessageBox.information(self, "提示", "请先上传或粘贴查询图片。")
            return
        if not self.output_root or not self._database_path().is_file():
            QMessageBox.information(self, "提示", "请先扫描并转换花型库。")
            return
        selected = self.scope_tree.currentItem()
        scope = selected.data(0, Qt.ItemDataRole.UserRole) if selected else ""
        query = self._query_bytes()
        db_path = self._database_path()
        threshold = self.threshold.value()
        self.results_table.setRowCount(0)
        self.search_started = time.monotonic()
        self.search_status.setText("正在搜索…")
        self.search_clock.start(1000)
        self._start_task(
            lambda report: search_images(
                db_path,
                query,
                scope or "",
                threshold,
                lambda current, total: report((current, total)),
            ),
            self._search_finished,
        )

    def _on_progress(self, value):
        if isinstance(value, dict):
            row = self.conversion_table.rowCount()
            self.conversion_table.insertRow(row)
            self.conversion_table.setItem(row, 0, QTableWidgetItem(value["name"]))
            self.conversion_table.setItem(row, 1, QTableWidgetItem(value["status"]))
            self.conversion_table.setItem(row, 2, QTableWidgetItem(value["elapsed"]))
            self.conversion_table.setItem(row, 3, QTableWidgetItem(value["message"]))
            self.conversion_table.scrollToBottom()
        elif isinstance(value, tuple):
            current, total = value
            self.search_status.setText(f"正在搜索局部特征：{current}/{total}，已耗时 {format_elapsed(time.monotonic() - self.search_started)}")

    def _search_finished(self, results: list[dict]):
        self.search_clock.stop()
        for result in results:
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            source = result["source_path"]
            name = Path(source).name
            self.results_table.setItem(row, 0, QTableWidgetItem(f"{result['score']}%"))
            self.results_table.setItem(row, 1, QTableWidgetItem(name))
            self.results_table.setItem(row, 2, QTableWidgetItem(str(result["page"]) if result["page"] else "—"))
            path_item = QTableWidgetItem(source)
            path_item.setData(Qt.ItemDataRole.UserRole, source)
            self.results_table.setItem(row, 3, path_item)
        elapsed = format_elapsed(time.monotonic() - self.search_started)
        self.search_status.setText(f"搜索完成，耗时 {elapsed}，找到 {len(results)} 个结果。")
        self.statusBar().showMessage(f"搜图耗时 {elapsed}")

    def _update_search_clock(self):
        self.search_status.setText(f"正在搜索，已耗时 {format_elapsed(time.monotonic() - self.search_started)}")

    def _on_failure(self, message: str):
        self.search_clock.stop()
        self.search_status.setText("任务失败")
        QMessageBox.warning(self, "任务失败", message)

    def _task_finished(self):
        self.busy = False
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        if self.worker:
            self.worker.deleteLater()
        self.worker = None

    def open_result(self, row: int, column: int):
        item = self.results_table.item(row, 3)
        if item:
            QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.ItemDataRole.UserRole)))


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
