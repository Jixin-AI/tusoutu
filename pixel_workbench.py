from __future__ import annotations

import math
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QProgressBar, QSpinBox, QSplitter,
    QTableWidget, QTreeWidget, QVBoxLayout, QWidget,
)

PIXEL_LETTERS = {
    "A": ("01110", "10001", "10001", "11111", "10001"),
    "D": ("11110", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "11110", "10000", "11111"),
    "N": ("10001", "11001", "10101", "10011", "10001"),
    "S": ("01111", "10000", "01110", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100"),
    "W": ("10001", "10001", "10101", "10101", "01010"),
}


class SceneDimmer(QWidget):
    def paintEvent(self, event):
        QPainter(self).fillRect(self.rect(), QColor(24, 22, 20, 150))

    def mousePressEvent(self, event):
        event.accept()


class ScenePanel(QDialog):
    def __init__(self, scene, title, size):
        super().__init__(scene, Qt.WindowType.Widget)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.scene = scene
        self.base_size = size
        self.setObjectName("workbenchPopup")
        self.setWindowTitle(title)
        self.setModal(False)
        self.finished.connect(scene.dimmer.hide)

    def open(self):
        self.place()
        self.scene.dimmer.setGeometry(self.scene.rect())
        self.scene.dimmer.show()
        self.scene.dimmer.raise_()
        self.show()
        self.raise_()

    def place(self):
        width = min(self.base_size[0], max(1, self.scene.width() - 64))
        height = min(self.base_size[1], max(1, self.scene.height() - 64))
        self.resize(width, height)
        self.move((self.scene.width() - width) // 2, (self.scene.height() - height) // 2)


class PixelBookshop(QWidget):
    """Reference-led pixel library scene with task-driven foreground cat."""
    action = Signal(str)
    mode_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        assets = Path(__file__).resolve().parent / "assets"
        font_path=Path("C:/Windows/Fonts/msyh.ttc")
        if font_path.exists(): QFontDatabase.addApplicationFont(str(font_path))
        self.background = QPixmap(str(assets / "bookshop-urban.png"))
        self.tree_canopies = (
            (QPixmap(str(assets / "tree-canopy-left.png")), QRectF(0, 0, 590, 420), 0.2),
            (QPixmap(str(assets / "tree-canopy-middle.png")), QRectF(520, 165, 780, 90), 2.1),
            (QPixmap(str(assets / "tree-canopy-right.png")), QRectF(1260, 125, 250, 330), 4.0),
        )
        self.objects = {
            "settings": QPixmap(str(assets / "postbox-interactive.png")),
            "search": QPixmap(str(assets / "counter-books-interactive.png")),
            "convert": QPixmap(str(assets / "pattern-rack-interactive.png")),
        }
        self.object_images = {key: sprite.toImage() for key, sprite in self.objects.items()}
        self.hover_outlines = {}
        sheet = QPixmap(str(assets / "girl-reading-sheet.png"))
        frames = [sheet.copy((index % 4) * 320, (index // 4) * 320, 320, 320) for index in range(16)] if not sheet.isNull() else []
        self.animations = {mode: frames for mode in ("idle", "search", "convert")}
        self.mode = "idle"
        self.mode_started = time.monotonic()
        self.activity = "小女孩在柜台看书"
        self.frame = 0
        self.cat_x = .525
        self.hover = ""
        self.hotspots = {}
        self.panels = []
        self.dimmer = SceneDimmer(self)
        self.dimmer.hide()
        self.setMinimumSize(760, 520)
        self.setMouseTracking(True)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(125)

    def set_mode(self, mode):
        self.mode = mode
        self.mode_started = time.monotonic()
        self.mode_changed.emit(mode)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for panel in self.panels:
            if panel.isVisible():
                panel.place()
        if self.dimmer.isVisible():
            self.dimmer.setGeometry(self.rect())
            self.dimmer.raise_()
            for panel in self.panels:
                if panel.isVisible():
                    panel.raise_()

    def _tick(self):
        self.frame = (self.frame + 1) % 48
        self.cat_x = .525
        self.update()

    def _label(self,p,rect,text,size,color,bold=False):
        p.setPen(QColor(color)); font=QFont("Microsoft YaHei UI",size); font.setBold(bold); p.setFont(font)
        p.drawText(rect,Qt.AlignmentFlag.AlignCenter,text)

    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing,False)
        p.fillRect(self.rect(),QColor("#171b18"))
        if self.background.isNull():
            self._label(p,self.rect(),"找不到 assets/bookshop-urban.png",16,"#fff0d2",True); return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,True)
        w,h=self.width(),self.height(); iw,ih=self.background.width(),self.background.height()
        dw,dh=w,h; ox=oy=0
        p.fillRect(self.rect(),QColor("#607f54"))
        if oy:
            p.fillRect(QRectF(0,0,w,oy),QColor("#b7a8a0"))
            p.fillRect(QRectF(0,oy+dh,w,h-oy-dh),QColor("#77895d"))
        p.drawPixmap(QRectF(ox,oy,dw,dh),self.background,QRectF(self.background.rect()))
        phase=self.frame*math.tau/48
        for canopy,source_rect,offset in self.tree_canopies:
            if canopy.isNull(): continue
            width,height=source_rect.width()*dw/iw,source_rect.height()*dh/ih
            x,y=ox+source_rect.x()*dw/iw,oy+source_rect.y()*dh/ih
            sway=math.sin(phase+offset)
            p.save(); p.translate(x+width/2+sway*5,y+height/2); p.rotate(sway*.55)
            p.drawPixmap(QRectF(-width/2,-height/2,width,height),canopy,QRectF(canopy.rect())); p.restore()
        leaves=((.14,.18,"#d8b94f"),(.25,.25,"#c9a63b"),(.42,.29,"#dfc85c"),(.54,.24,"#c9ae49"),(.69,.27,"#d9bd4a"),(.79,.23,"#d5b74d"),(.91,.32,"#c99b35"),(.34,.16,"#d7c15a"),(.61,.18,"#d1b64c"),(.86,.19,"#ddb846"))
        for i,(sx,sy,color) in enumerate(leaves):
            progress=((self.frame+i*7)%48)/48
            x=ox+(sx+math.sin(phase*1.15+i*1.7)*.018+progress*.045)*dw
            y=oy+(sy+progress*.55)*dh
            scale=max(4,dh*(.014+(i%3)*.002))
            p.save(); p.translate(x,y); p.rotate(math.sin(phase*1.5+i)*42); p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(color))
            leaf=QPolygonF([QPointF(0,-scale*.58),QPointF(scale*.25,-scale*.28),QPointF(scale*.58,-scale*.38),QPointF(scale*.46,-scale*.08),QPointF(scale*.68,scale*.12),QPointF(scale*.30,scale*.22),QPointF(scale*.20,scale*.58),QPointF(0,scale*.31),QPointF(-scale*.20,scale*.58),QPointF(-scale*.26,scale*.23),QPointF(-scale*.62,scale*.12),QPointF(-scale*.40,-scale*.12),QPointF(-scale*.48,-scale*.40),QPointF(-scale*.16,-scale*.28)])
            p.drawPolygon(leaf); p.setPen(QPen(QColor("#8f7133"),max(1,scale*.09))); p.drawLine(QPointF(0,scale*.06),QPointF(0,scale*.74)); p.restore()
        sign="NEWSSTAND"; sign_width=dw*.31; cell=min(sign_width/(len(sign)*6-1),dh*.043/5)
        left=ox+dw*.55-(len(sign)*6*cell-cell)/2; top=oy+.337*dh
        for letter_index,letter in enumerate(sign):
            for row,bits in enumerate(PIXEL_LETTERS[letter]):
                for column,bit in enumerate(bits):
                    if bit=="1":
                        rect=QRectF(left+(letter_index*6+column)*cell,top+row*cell,cell-1,cell-1)
                        p.fillRect(rect.translated(2,2),QColor("#973d32"))
                        p.fillRect(rect,QColor("#fff5dc"))
        object_layout={"settings":(.327,.82,.19),"search":(.525,.82,.145),"convert":(.77,.82,.23)}
        placements={}
        self.hotspots={}
        for key,(cx,bottom,height) in object_layout.items():
            sprite=self.objects[key]
            sprite_height=dh*height; sprite_width=sprite_height*sprite.width()/sprite.height()
            rect=QRectF(ox+cx*dw-sprite_width/2,oy+bottom*dh-sprite_height,sprite_width,sprite_height)
            placements[key]=rect
            self.hotspots[key]=rect.toRect()
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(28,32,25,115))
            p.drawEllipse(QRectF(rect.center().x()-rect.width()*.38,oy+bottom*dh-4,rect.width()*.76,8))
        p.drawPixmap(placements["settings"],self.objects["settings"],QRectF(self.objects["settings"].rect()))
        p.drawPixmap(placements["convert"],self.objects["convert"],QRectF(self.objects["convert"].rect()))
        plaque=QRectF(placements["settings"].left()+placements["settings"].width()*.35,placements["settings"].top()+placements["settings"].height()*.35,placements["settings"].width()*.30,placements["settings"].height()*.09)
        p.fillRect(plaque,QColor("#fff0cc")); p.setPen(QPen(QColor("#6f1f1d"),1)); p.drawRect(plaque.adjusted(0,0,-1,-1))
        font=QFont("Microsoft YaHei UI"); font.setBold(True); font.setStretch(80)
        for size in range(max(5,round(plaque.height())),3,-1):
            font.setPixelSize(size)
            if QFontMetrics(font).horizontalAdvance("中国邮政")<=plaque.width()-2: break
        p.setPen(QColor("#6f1f1d")); p.setFont(font); p.drawText(plaque.adjusted(1,0,-1,0),Qt.AlignmentFlag.AlignCenter,"中国邮政")
        counter=placements["search"]
        counter_surface=counter.top()+counter.height()*.10
        if self.mode=="idle": p.drawPixmap(counter,self.objects["search"],QRectF(self.objects["search"].rect()))
        animation = self.animations.get(self.mode, [])
        if animation:
            girl = animation[int((time.monotonic() - self.mode_started) * 1000 / 190) % len(animation)]
        else:
            girl = QPixmap()
        if not girl.isNull():
            girl_height = round(dh * ({"idle":.10,"search":.13,"convert":.12}[self.mode]))
            girl_width = round(girl.width() * girl_height / girl.height())
            girl_bottom=counter_surface+girl_height*.028
            target = QRectF(ox+self.cat_x*dw-girl_width/2, girl_bottom-girl_height, girl_width, girl_height)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawPixmap(target, girl, QRectF(girl.rect()))
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        if self.mode!="idle":
            p.drawPixmap(counter,self.objects["search"],QRectF(self.objects["search"].rect()))
        activity_rect=QRectF(dw*.40,dh*.022,dw*.20,dh*.043)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(23,45,41,220)); p.drawRoundedRect(activity_rect,5,5)
        self._label(p,activity_rect,self.activity,max(9,round(dh*.015)),"#fff1d0",True)
        if self.hover in self.hotspots:
            r=self.hotspots[self.hover]
            outline=self._hover_outline(self.hover,r.size())
            p.drawPixmap(r.left()-2,r.top()-2,outline)
            text={"settings":"设置 · 点击打开书店设置","search":"图搜图 · 点击上传花型素材","convert":"点击开始转换花型库"}[self.hover]
            bubble=QRect(r.center().x()-132,r.top()-36,264,30)
            p.fillRect(bubble,QColor(37,30,25,225)); self._label(p,bubble,text,12,"#fff0d2",True)

    def _hover_outline(self,key,size):
        cache_key=(key,size.width(),size.height())
        if cache_key not in self.hover_outlines:
            sprite=self.objects[key].scaled(size,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
            silhouette=QImage(sprite.size(),QImage.Format.Format_ARGB32_Premultiplied); silhouette.fill(Qt.GlobalColor.transparent)
            painter=QPainter(silhouette); painter.drawPixmap(0,0,sprite); painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn); painter.fillRect(silhouette.rect(),QColor("#ffe3a0")); painter.end()
            outline=QImage(sprite.width()+4,sprite.height()+4,QImage.Format.Format_ARGB32_Premultiplied); outline.fill(Qt.GlobalColor.transparent)
            painter=QPainter(outline)
            for dx,dy in ((-2,0),(2,0),(0,-2),(0,2),(-1,-1),(1,-1),(-1,1),(1,1)):
                painter.drawImage(2+dx,2+dy,silhouette)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut); painter.drawImage(2,2,silhouette); painter.end()
            self.hover_outlines[cache_key]=QPixmap.fromImage(outline)
        return self.hover_outlines[cache_key]

    def _item_at(self,point):
        for key,rect in self.hotspots.items():
            if rect.contains(point):
                image=self.object_images[key]
                x=min(image.width()-1,int((point.x()-rect.x())*image.width()/rect.width()))
                y=min(image.height()-1,int((point.y()-rect.y())*image.height()/rect.height()))
                if image.pixelColor(x,y).alpha()>16: return key
        return ""

    def mouseMoveEvent(self,event):
        self.hover=self._item_at(event.position().toPoint())
        self.setCursor(Qt.CursorShape.PointingHandCursor if self.hover else Qt.CursorShape.ArrowCursor)
        self.update()

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            key=self._item_at(event.position().toPoint())
            if key: self.action.emit(key)


class PixelWorkbench:
    def __init__(self, window, results_view_type):
        self.w=window
        self.results_view_type=results_view_type

    def build(self):
        w=self.w
        self.scene=PixelBookshop()
        self.scene.action.connect(self._open_feature)
        self.scene.mode_changed.connect(lambda mode:self.set_activity({"idle":"小女孩在柜台看书","search":"小女孩正在翻找花型","convert":"小女孩正在整理、上架花型书籍"}.get(mode,"小女孩在工作")))
        self._build_settings_page()
        self._build_search_page()
        self._build_convert_page()
        w.mascot=self.scene
        w.mascot_label=QLabel("小女孩在柜台看书")
        return self.scene

    def set_activity(self,text):
        self.scene.activity=text
        self.w.mascot_label.setText(text)
        self.scene.update()

    def _dialog(self,title,size):
        dialog=ScenePanel(self.scene,title,size); dialog.resize(*size); dialog.hide()
        self.scene.panels.append(dialog)
        layout=QVBoxLayout(dialog); layout.setContentsMargins(14,12,14,12)
        return dialog,layout

    def _panel_header(self,dialog,layout,title,subtitle):
        row=QHBoxLayout(); stack=QVBoxLayout(); heading=QLabel(title); heading.setObjectName("brand")
        hint=QLabel(subtitle); hint.setObjectName("eyebrow"); stack.addWidget(heading); stack.addWidget(hint)
        mascot=QLabel(); mascot.setObjectName("mascotIcon"); mascot.setFixedSize(58,58)
        self._paint_mascot_icon(mascot,self.scene.mode)
        self.scene.mode_changed.connect(lambda mode, icon=mascot:self._paint_mascot_icon(icon,mode))
        row.addWidget(mascot); row.addLayout(stack); row.addStretch(1); close=QPushButton("返回书店"); close.clicked.connect(dialog.close); row.addWidget(close)
        layout.addLayout(row)

    def _paint_mascot_icon(self,label,mode):
        icon=self.scene.animations[mode][0]
        pixmap=icon.scaled(32,32,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(pixmap)

    def _build_search_page(self):
        w=self.w
        self.search_dialog,layout=self._dialog("图搜图 · 花型书店",(1050,760))
        self.active_dialog=self.search_dialog
        self._panel_header(self.search_dialog,layout,"图搜图 · 找花型","把客户照片或局部花型交给小女孩，去书架里找相似款")
        query_box=QGroupBox("客户提供的花型")
        query_layout=QVBoxLayout(query_box)
        w.query_preview=QLabel("上传或粘贴一张客户图片")
        w.query_preview.setAlignment(Qt.AlignmentFlag.AlignCenter); w.query_preview.setMinimumHeight(130)
        w.query_preview.setStyleSheet("QLabel { background:#f8efdf; border:2px dashed #92745a; color:#846e56; }")
        query_layout.addWidget(w.query_preview)
        buttons=QHBoxLayout()
        for title,callback in (("上传图片",w.choose_query),("粘贴图片",w.paste_query),("裁剪局部",w.crop_query)):
            button=QPushButton(title); button.clicked.connect(callback); buttons.addWidget(button)
            if title=="裁剪局部": w.crop_button=button
        buttons.addSpacing(12); buttons.addWidget(QLabel("相似度")); w.similarity_label=QLabel(); buttons.addWidget(w.similarity_label); buttons.addStretch(1)
        w.threshold.valueChanged.connect(lambda value:w.similarity_label.setText(f"{value}%"))
        w.similarity_label.setText(f"{w.threshold.value()}%")
        w.search_button=QPushButton("小姑娘，开始找花型"); w.search_button.clicked.connect(w.start_search); buttons.addWidget(w.search_button)
        query_layout.addLayout(buttons); layout.addWidget(query_box)
        split=QSplitter(Qt.Orientation.Horizontal)
        scope_box=QGroupBox("搜索范围：整本花型库或指定子文件夹")
        scope_layout=QVBoxLayout(scope_box); w.scope_tree=QTreeWidget(); w.scope_tree.setHeaderHidden(True); scope_layout.addWidget(w.scope_tree)
        split.addWidget(scope_box)
        results_box=QGroupBox("找到的花型")
        results_layout=QVBoxLayout(results_box); w.search_status=QLabel("选好图片和目录，小女孩就去书架上找。"); w.search_status.setWordWrap(True)
        results_layout.addWidget(w.search_status); w.results_view=self.results_view_type(); w.results_view.setMinimumHeight(210)
        w.results_view.open_requested.connect(w._open_path); results_layout.addWidget(w.results_view,1)
        split.addWidget(results_box); split.setStretchFactor(0,1); split.setStretchFactor(1,4); layout.addWidget(split,1)
        self.search_dialog.finished.connect(lambda *_:self._return_idle())

    def _build_convert_page(self):
        w=self.w
        self.convert_dialog,layout=self._dialog("花型库 · 整理上架",(900,650))
        self.active_dialog=self.convert_dialog
        self._panel_header(self.convert_dialog,layout,"花型库 · JPG 上架","小女孩会扫描花型库，将新花型整理成 JPG 放上书架")
        folders=QGroupBox("书报亭的两个仓库")
        form=QFormLayout(folders)
        for title,attribute in (("原花型库","source_edit"),("JPG 书架","output_edit")):
            row=QHBoxLayout(); summary=QLabel("尚未设置"); summary.setWordWrap(True); setattr(w,attribute+"_summary",summary)
            button=QPushButton("在设置中修改"); button.clicked.connect(self.open_settings); row.addWidget(summary,1); row.addWidget(button); form.addRow(title,row)
        layout.addWidget(folders)
        actions=QGroupBox("整理并上架")
        action_layout=QVBoxLayout(actions); controls=QHBoxLayout(); w.scan_button=QPushButton("立即扫描并转换"); w.scan_button.clicked.connect(w.start_scan)
        w.monitor_button=QPushButton("开始自动监测"); w.monitor_button.clicked.connect(w.toggle_monitor)
        controls.addWidget(w.scan_button); controls.addWidget(w.monitor_button); controls.addSpacing(12); controls.addWidget(QLabel("监测间隔请在设置中调整"))
        controls.addStretch(1); action_layout.addLayout(controls)
        w.progress=QProgressBar(); w.progress.setRange(0,1); w.progress.setValue(0); action_layout.addWidget(w.progress)
        w.conversion_table=QTableWidget(0,4); w.conversion_table.setHorizontalHeaderLabels(["花型文件","状态","耗时","说明"])
        w.conversion_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        w.conversion_table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeMode.Stretch)
        w.conversion_table.setColumnWidth(1,105); w.conversion_table.setColumnWidth(2,100); action_layout.addWidget(w.conversion_table,1)
        layout.addWidget(actions,1); self.convert_dialog.finished.connect(lambda *_:self._return_idle())

    def _build_settings_page(self):
        self.settings_dialog,layout=self._dialog("书店设置",(620,360))
        self.active_dialog=self.settings_dialog
        self._panel_header(self.settings_dialog,layout,"书店设置","配置书库位置与搜图默认参数")
        paths=QGroupBox("书库位置")
        form=QFormLayout(paths)
        for title,attribute,button_text,callback in (("原花型库","source_edit","选择花型库",self.w.choose_source),("JPG 书架","output_edit","选择 JPG 库",self.w.choose_output)):
            row=QHBoxLayout(); edit=QLineEdit(); edit.setReadOnly(True); setattr(self.w,attribute,edit)
            button=QPushButton(button_text); button.clicked.connect(callback); row.addWidget(edit,1); row.addWidget(button); form.addRow(title,row)
        layout.addWidget(paths)
        controls=QGroupBox("默认参数")
        row=QHBoxLayout(controls); row.addWidget(QLabel("默认相似度")); self.w.threshold=QSpinBox(); self.w.threshold.setRange(1,100); self.w.threshold.setValue(int(self.w.settings.value("similarity",20)))
        row.addWidget(self.w.threshold); row.addWidget(QLabel("%")); row.addSpacing(18); row.addWidget(QLabel("监测间隔"))
        self.w.interval_value=QSpinBox(); self.w.interval_value.setRange(1,168); self.w.interval_value.setValue(int(self.w.settings.value("monitor_interval",1)))
        self.w.interval_unit=QComboBox(); self.w.interval_unit.addItem("小时","hours"); self.w.interval_unit.addItem("天","days")
        self.w.interval_unit.setCurrentIndex(max(0,self.w.interval_unit.findData(self.w.settings.value("monitor_unit","hours"))))
        self.w.interval_value.valueChanged.connect(self.w._update_interval_limit); self.w.interval_unit.currentIndexChanged.connect(self.w._update_interval_limit)
        self.w.threshold.valueChanged.connect(lambda value:self.w.settings.setValue("similarity",value))
        self.w.interval_value.valueChanged.connect(lambda value:self.w.settings.setValue("monitor_interval",value))
        self.w.interval_unit.currentIndexChanged.connect(lambda _:self.w.settings.setValue("monitor_unit",self.w.interval_unit.currentData()))
        self.w._update_interval_limit()
        row.addWidget(self.w.interval_value); row.addWidget(self.w.interval_unit); row.addStretch(1); layout.addWidget(controls)
        self.settings_dialog.finished.connect(lambda *_:self._return_idle())

    def open_settings(self):
        self.active_dialog=self.settings_dialog
        self.settings_dialog.open()

    def _return_idle(self):
        if not self.w.busy:
            self.w._set_cat_mode("idle","小女孩在柜台看书")

    def _open_feature(self,key):
        for dialog in (self.search_dialog,self.convert_dialog,self.settings_dialog):
            if dialog.isVisible():
                dialog.close()
        if key=="search":
            self.active_dialog=self.search_dialog; self.search_dialog.open()
            if self.w.query_image.isNull():
                QTimer.singleShot(0,self.w.choose_query)
        elif key=="convert":
            self.w.start_scan()
        elif key=="library":
            self.active_dialog=self.search_dialog; self.search_dialog.open()
            if self.w.scope_tree.topLevelItemCount(): self.w.scope_tree.setCurrentItem(self.w.scope_tree.topLevelItem(0))
        elif key=="settings":
            self.open_settings()
