from __future__ import annotations

import sys
import time
import math
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRectF, QSize, QSettings, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QImage, QImageReader, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from library import format_elapsed, scan_and_convert, search_images
from pixel_workbench import PixelWorkbench


WORKBENCH_STYLE = """
QMainWindow, QWidget { color: #3d352c; font-family: 'Microsoft YaHei UI'; font-size: 10pt; background: #f2e5d1; }
QLabel { background: transparent; color: #5a4a3b; }
QLabel#brand { color: #42362b; font-size: 20pt; font-weight: 700; }
QLabel#eyebrow { color: #7b5c43; font-size: 9pt; }
QLabel#statusBadge { color: #385b3f; background: #d8e3c6; border: 2px solid #526b48; padding: 6px 12px; }
QGroupBox { background: #fff8ec; border: 2px solid #574638; margin-top: 12px; padding: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #684a34; font-weight: 700; background: #f2e5d1; }
QLineEdit, QSpinBox, QComboBox { color: #3d352c; background: #fffdf6; border: 2px solid #92745a; padding: 6px 8px; selection-background-color: #c85a43; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border: 2px solid #526b48; }
QPushButton { color: #3d352c; background: #e8c997; border: 2px solid #574638; padding: 7px 12px; font-weight: 600; }
QPushButton:hover { background: #f2dcae; }
QPushButton:pressed { background: #d5a86b; }
QPushButton:disabled { color: #9b9084; background: #e6dfd3; border-color: #b4a796; }
QTreeWidget, QTableWidget { color: #3d352c; background: #fffdf6; alternate-background-color: #f5ebdc; border: 2px solid #92745a; gridline-color: #d7c5ac; selection-background-color: #d9e1c7; selection-color: #273d2c; outline: 0; }
QHeaderView::section { color: #493a2e; background: #e8d7bc; border: none; border-bottom: 2px solid #92745a; padding: 7px 8px; font-weight: 700; }
QProgressBar { color: #3d352c; background: #fffdf6; border: 2px solid #574638; min-height: 14px; max-height: 14px; text-align: center; }
QProgressBar::chunk { background: #718b59; }
QScrollBar:vertical { background: #e6d8c3; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: #ad8b64; min-height: 28px; }
QScrollBar:horizontal { background: #e6d8c3; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: #ad8b64; min-width: 28px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QMenu { color: #3d352c; background: #fff8ec; border: 2px solid #574638; }
QMenu::item:selected { background: #d9e1c7; }
QToolTip { color: #3d352c; background: #fff8ec; border: 1px solid #92745a; padding: 5px; }
QStatusBar { color: #6f5d49; background: #eadbc4; border-top: 2px solid #92745a; }
QTabWidget::pane { border: 2px solid #574638; background: #f8efdf; }
QTabBar::tab { color: #493a2e; background: #e5d2b4; border: 2px solid #574638; padding: 9px 18px; margin-right: 4px; }
QTabBar::tab:selected { color: #fff8ec; background: #58734d; }
"""


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


class SearchResultsView(QGraphicsView):
    open_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.graphics_scene = QGraphicsScene(self)
        self.setScene(self.graphics_scene)
        self.setBackgroundBrush(QColor("#f8efdf"))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMinimumHeight(260)
        self.flow_paths = []
        self.flow_phase = 0.0
        self.flow_timer = QTimer(self)
        self.flow_timer.timeout.connect(self._advance_flow)
        self.flow_timer.start(160)
        self._show_empty("上传或粘贴图片后开始搜索")

    def _advance_flow(self):
        if self.flow_paths:
            self.flow_phase = (self.flow_phase + 0.012) % 1
            self.viewport().update()

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        for index, path in enumerate(self.flow_paths[:36]):
            point = path.pointAtPercent((self.flow_phase + index * 0.071) % 1)
            size = 5 if index % 2 else 7
            painter.fillRect(round(point.x()), round(point.y()), size, size, QColor("#c85a43"))
        painter.restore()

    def _show_empty(self, message: str):
        self.graphics_scene.clear()
        self.flow_paths.clear()
        text = self.graphics_scene.addText(message)
        text.setDefaultTextColor(QColor("#745d45"))
        text.setPos(32, 32)
        self.graphics_scene.setSceneRect(0, 0, 720, 120)

    def _node(self, x: float, center_y: float, width: float, height: float, label: str, root=False):
        node = QGraphicsRectItem(x, center_y - height / 2, width, height)
        node.setBrush(QBrush(QColor("#d9e3c5") if root else QColor("#fff8ec")))
        node.setPen(QPen(QColor("#526b48") if root else QColor("#92745a"), 2))
        self.graphics_scene.addItem(node)
        text = QGraphicsTextItem()
        text.setPlainText(label)
        text.setFont(QFont("Microsoft YaHei UI", 10))
        text.setDefaultTextColor(QColor("#493a2e"))
        text.setTextWidth(width - 24)
        text.setPos(x + 12, center_y - text.boundingRect().height() / 2)
        self.graphics_scene.addItem(text)
        return node

    def set_results(self, results: list[dict], root_label: str, scope: str = ""):
        if not results:
            self._show_empty("没有找到匹配图案")
            return

        self.graphics_scene.clear()
        self.flow_paths.clear()
        ordered = sorted(results, key=lambda item: item["score"], reverse=True)
        folders: dict[str, dict] = {}
        paths: list[list[str]] = []
        for index, result in enumerate(ordered):
            relative = result.get("relative_path", "").replace("\\", "/").strip("/")
            normalized_scope = scope.replace("\\", "/").strip("/")
            if normalized_scope and (relative == normalized_scope or relative.startswith(normalized_scope + "/")):
                relative = relative[len(normalized_scope):].strip("/")
            parts = [part for part in relative.split("/") if part and part != "."][:-1]
            paths.append(parts)
            prefix = []
            for part in parts:
                prefix.append(part)
                key = "/".join(prefix)
                folders.setdefault(key, {"name": part, "depth": len(prefix), "rows": []})["rows"].append(index)

        row_gap = 116
        top = 60
        file_x = 300 + max((len(parts) for parts in paths), default=0) * 190
        image_x = file_x + 380
        result_centers = [top + index * row_gap for index in range(len(ordered))]
        folder_positions = {
            key: (260 + (node["depth"] - 1) * 190, sum(result_centers[i] for i in node["rows"]) / len(node["rows"]))
            for key, node in folders.items()
        }
        root_y = sum(result_centers) / len(result_centers)
        edges = QPen(QColor("#92745a"), 2, Qt.PenStyle.DashLine)
        for key, (x, y) in folder_positions.items():
            parent = key.rpartition("/")[0]
            parent_x, parent_y = folder_positions[parent] if parent else (38, root_y)
            parent_width = 150 if parent else 190
            path = QPainterPath()
            path.moveTo(parent_x + parent_width, parent_y)
            mid_x = (parent_x + parent_width + x) / 2
            path.cubicTo(mid_x, parent_y, mid_x, y, x, y)
            self.graphics_scene.addPath(path, edges)
            self.flow_paths.append(path)

        for index, (result, parts, y) in enumerate(zip(ordered, paths, result_centers)):
            parent = "/".join(parts)
            if parent:
                parent_x, parent_y = folder_positions[parent]
                start_x = parent_x + 150
            else:
                parent_x, parent_y, start_x = 38, root_y, 228
            path = QPainterPath()
            path.moveTo(start_x, parent_y)
            mid_x = (start_x + file_x) / 2
            path.cubicTo(mid_x, parent_y, mid_x, y, file_x, y)
            self.graphics_scene.addPath(path, edges)
            self.flow_paths.append(path)

            path = QPainterPath()
            path.moveTo(file_x + 330, y)
            mid_x = (file_x + 330 + image_x) / 2
            path.cubicTo(mid_x, y, mid_x, y, image_x, y)
            self.graphics_scene.addPath(path, edges)
            self.flow_paths.append(path)

        self._node(38, root_y, 220, 64, "总路径\n" + root_label, root=True)
        for key, node_data in folders.items():
            x, y = folder_positions[key]
            self._node(x, y, 150, 42, "▰  " + node_data["name"])

        file_width, file_height = 330, 64
        for result, y in zip(ordered, result_centers):
            file_node = self._node(file_x, y, file_width, file_height, "文件路径\n" + result["source_path"])
            file_node.setData(0, result["source_path"])

        card_width, card_height = 270, 96
        for result, y in zip(ordered, result_centers):
            card = QGraphicsRectItem(image_x, y - card_height / 2, card_width, card_height)
            card.setBrush(QBrush(QColor("#fff8ec")))
            card.setPen(QPen(QColor("#92745a"), 2))
            card.setData(0, result["source_path"])
            self.graphics_scene.addItem(card)
            reader = QImageReader(result.get("output_path", ""))
            reader.setScaledSize(QSize(76, 76))
            image = reader.read()
            if not image.isNull():
                preview = self.graphics_scene.addPixmap(QPixmap.fromImage(image))
                preview.setPos(image_x + 10, y - 38)
                preview.setData(0, result["source_path"])
            name = QGraphicsTextItem()
            name.setPlainText("结果图\n" + Path(result["source_path"]).name)
            name.setFont(QFont("Microsoft YaHei UI", 9))
            name.setDefaultTextColor(QColor("#493a2e"))
            name.setPos(image_x + 96, y - 34)
            name.setData(0, result["source_path"])
            self.graphics_scene.addItem(name)
            detail = QGraphicsTextItem()
            detail.setPlainText(f"相似度 {result['score']}%  ·  页码 {result['page'] or '—'}")
            detail.setFont(QFont("Microsoft YaHei UI", 9))
            detail.setDefaultTextColor(QColor("#58734d"))
            detail.setPos(image_x + 96, y + 24)
            detail.setData(0, result["source_path"])
            self.graphics_scene.addItem(detail)

        max_x = image_x + card_width + 48
        max_y = top + len(ordered) * row_gap + 32
        self.graphics_scene.setSceneRect(0, 0, max_x, max_y)
        self._node(38, root_y, 220, 64, "总路径\n" + root_label, root=True)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        while item and item.data(0) is None:
            item = item.parentItem()
        if item and item.data(0):
            self.open_requested.emit(item.data(0))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("花型书报亭")
        self.resize(1440, 920)
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
        if self.source_root and not self._source_is_dir():
            self.source_root = self.output_root = None
            self.settings.remove("source_root")
            self.settings.remove("output_root")
        self._refresh_paths()
        if self.source_root:
            self._populate_scope()

    def _build_ui(self):
        self.pixel_workbench = PixelWorkbench(self, SearchResultsView)
        self.setCentralWidget(self.pixel_workbench.build())
        self.statusBar().showMessage("就绪 · 书架已准备好")

    def _set_cat_mode(self, mode: str, message: str):
        if hasattr(self, "mascot"):
            self.mascot.set_mode(mode)
            self.mascot_label.setText(message)

    def _refresh_paths(self):
        self.source_edit.setText(str(self.source_root) if self.source_root else "")
        self.output_edit.setText(str(self.output_root) if self.output_root else "")

    def _source_is_dir(self):
        try:
            return bool(self.source_root and self.source_root.is_dir())
        except OSError:
            return False

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
        if not self._source_is_dir():
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
        if not self._source_is_dir() or not self.output_root:
            QMessageBox.information(self, "提示", "请先选择花型库和 JPG 库文件夹。")
            return
        db_path = self._database_path()
        self.conversion_table.setRowCount(0)
        self._set_cat_mode("convert", "小猫正在整理花型书籍")
        self.search_status.setText("正在扫描花型库并更新 JPG 库…")
        self._start_task(
            lambda report: scan_and_convert(self.source_root, self.output_root, db_path, report),
            self._scan_finished,
        )

    def _scan_finished(self, summary: dict):
        self._set_cat_mode("idle", "小猫整理完啦，继续打盹")
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
            if not self._source_is_dir() or not self.output_root:
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
        self.results_view.set_results([], "搜索结果")
        self._set_cat_mode("search", "小猫正在翻找花型")
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
        selected = self.scope_tree.currentItem()
        scope = selected.data(0, Qt.ItemDataRole.UserRole) if selected else ""
        root_label = Path(scope).name if scope else (self.source_root.name if self.source_root else "搜索结果")
        self.results_view.set_results(results, root_label, scope or "")
        self._set_cat_mode("idle", "小猫找到啦，回书架休息")
        elapsed = format_elapsed(time.monotonic() - self.search_started)
        self.search_status.setText(f"搜索完成，耗时 {elapsed}，找到 {len(results)} 个结果。")
        self.statusBar().showMessage(f"搜图耗时 {elapsed}")

    def _update_search_clock(self):
        self.search_status.setText(f"正在搜索，已耗时 {format_elapsed(time.monotonic() - self.search_started)}")

    def _on_failure(self, message: str):
        self._set_cat_mode("idle", "小猫在书架旁打盹")
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

    def _open_path(self, path: str):
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(WORKBENCH_STYLE)
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())
