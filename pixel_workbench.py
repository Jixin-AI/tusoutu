from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QProgressBar, QSpinBox, QSplitter,
    QTableWidget, QTreeWidget, QVBoxLayout, QWidget,
)


class PixelBookshop(QWidget):
    action = Signal(str)
    mode_changed = Signal(str)

    PALETTE = {
        "sky": "#f8dfcb", "wall": "#456848", "wall2": "#354f3c",
        "wood": "#a85a3e", "wood2": "#704538", "cream": "#ffedcf",
        "paper": "#f2cd91", "red": "#c95143", "green": "#819463",
        "dark": "#49382e", "glass": "#b7d5c9", "blue": "#6f8990",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "idle"
        self.frame = 0
        self.cat_x = 0.5
        self.hover = ""
        self.hotspots = {}
        self.setMinimumSize(760, 520)
        self.setMouseTracking(True)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(180)

    def set_mode(self, mode: str):
        self.mode = mode
        self.mode_changed.emit(mode)
        self.update()

    def _tick(self):
        self.frame = (self.frame + 1) % 8
        if self.mode == "search":
            self.cat_x += 0.035
            if self.cat_x > 0.78:
                self.cat_x = 0.39
        elif self.mode == "convert":
            self.cat_x += 0.025
            if self.cat_x > 0.68:
                self.cat_x = 0.39
        else:
            self.cat_x = 0.5
        self.update()

    def _rect(self, x, y, width, height):
        return QRect(round(x*self.width()), round(y*self.height()), round(width*self.width()), round(height*self.height()))

    def _block(self, p, x, y, width, height, color):
        p.fillRect(self._rect(x, y, width, height), QColor(color))

    def _label(self, p, rect, text, size, color, bold=False):
        p.setPen(QColor(color))
        font = QFont("Microsoft YaHei UI", size)
        if not font.exactMatch():
            font = QFont("SimHei", size)
        font.setBold(bold)
        p.setFont(font)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.fillRect(self.rect(), QColor(self.PALETTE["sky"]))
        u = max(2, min(self.width()/120, self.height()/82))
        def b(x,y,w,h,c): p.fillRect(QRect(round(x*u),round(y*u),round(w*u),round(h*u)),QColor(c))
        # Isometric kiosk silhouette and green back wall.
        b(9,13,104,57,self.PALETTE["wall2"]); b(11,11,102,57,self.PALETTE["wall"])
        b(12,12,100,3,self.PALETTE["green"]); b(10,66,106,4,self.PALETTE["wood2"])
        # Pixel shelves and colorful book spines.
        for sy in (24,39,54):
            b(16,sy,62,2,self.PALETTE["wood2"]); b(16,sy-1,62,1,self.PALETTE["paper"])
        books=[("#c95143",4),("#e1b66f",5),("#6f8990",4),("#bd7765",6),("#d6c49c",4),("#718456",5)]
        for row,sy in enumerate((17,26,32,41,47,56)):
            x=18
            while x < 75:
                c,h=books[(x+row*3)%len(books)]
                b(x,sy,3,h,c); b(x,sy,1,1,self.PALETTE["cream"]); x+=5
        # framed print and bunting.
        b(84,18,19,25,self.PALETTE["wood2"]); b(86,20,15,21,self.PALETTE["paper"])
        b(88,22,11,15,self.PALETTE["blue"]); b(90,29,7,2,self.PALETTE["cream"])
        for x in (82,92,102):
            b(x,47,1,5,self.PALETTE["paper"]); b(x-1,51,3,3,self.PALETTE["cream"])
        # newsstand sign.
        b(77,29,39,11,self.PALETTE["wood2"]); b(78,30,37,8,self.PALETTE["red"])
        self._label(p,self._rect(.65,.35,.32,.085),"花 型 书 报 亭",max(10,round(u*2.4)),self.PALETTE["cream"],True)
        # floor tiles.
        b(5,69,110,3,self.PALETTE["green"])
        for x in range(7,116,10):
            b(x,72,9,6,self.PALETTE["paper"] if x%3 else self.PALETTE["red"])
            b(x,72,9,1,self.PALETTE["wood2"]); b(x,77,9,1,self.PALETTE["wood2"])
        # mail post.
        b(9,45,10,25,self.PALETTE["red"]); b(8,43,12,3,self.PALETTE["wood2"])
        b(7,41,14,4,self.PALETTE["red"]); b(8,48,12,2,"#dc7560"); b(10,52,8,2,self.PALETTE["wood2"])
        b(10,58,8,2,self.PALETTE["wood2"])
        # counter and front display rack.
        b(37,61,47,3,self.PALETTE["wood2"]); b(39,64,42,8,self.PALETTE["red"])
        b(40,63,40,2,self.PALETTE["paper"]); b(42,65,35,1,"#e88768")
        b(40,72,40,1,self.PALETTE["wood2"])
        b(86,56,25,2,self.PALETTE["wood2"]); b(88,58,22,2,self.PALETTE["paper"])
        for i in range(3):
            x=89+i*7
            b(x,53-i%2,4,4,["#8c9d70","#9b786b","#718995"][i]); b(x+1,54-i%2,1,2,self.PALETTE["cream"])
        # query-photo stand at counter.
        b(43,55,27,2,self.PALETTE["wood2"]); b(45,52,23,3,self.PALETTE["glass"])
        b(47,53,7,1,self.PALETTE["cream"]); b(57,53,8,1,self.PALETTE["blue"])
        # pixel cat: idle snooze, search rummage, conversion stack books.
        cx=round(self.cat_x*120); bob=(self.frame//2)%2
        cat_scale=max(1,round(u/2))
        p.save()
        p.translate(round(cx*u), round(58*u))
        p.scale(cat_scale,cat_scale)
        p.translate(-cx,-58)
        b(cx-5,60,13,6,"#9b6d4d"); b(cx-3,58-bob,11,8,self.PALETTE["cream"])
        b(cx-3,56-bob,3,3,self.PALETTE["dark"]); b(cx+5,56-bob,3,3,self.PALETTE["dark"])
        b(cx-2,57-bob,2,2,"#bd8870"); b(cx+6,57-bob,2,2,"#bd8870")
        b(cx,61-bob,1,1,self.PALETTE["dark"]); b(cx+4,61-bob,1,1,self.PALETTE["dark"])
        b(cx+2,63-bob,2,1,self.PALETTE["red"])
        if self.mode == "idle":
            b(cx+8,52-bob,2,1,self.PALETTE["dark"]); b(cx+11,50-bob,2,1,self.PALETTE["dark"])
            self._label(p,self._rect(.39,.49,.12,.04),"z  z  z",max(9,round(u*2.2)),self.PALETTE["dark"])
        elif self.mode == "search":
            b(cx+10,62,4,1,self.PALETTE["paper"]); b(cx+13,61,1,2,self.PALETTE["paper"])
            if self.frame%2: b(cx+18,58,4,3,self.PALETTE["red"])
            self._label(p,self._rect(.47,.48,.22,.04),"翻！翻！找花型…",max(8,round(u*1.8)),self.PALETTE["dark"])
        else:
            b(cx+11,59-(self.frame%2),4,2,self.PALETTE["red"]); b(cx+12,59-(self.frame%2),1,2,self.PALETTE["paper"])
            b(cx+17,60,4,2,self.PALETTE["green"]); b(cx+18,60,1,2,self.PALETTE["cream"])
            self._label(p,self._rect(.47,.48,.22,.04),"正在把花型上架…",max(8,round(u*1.8)),self.PALETTE["dark"])
        p.restore()
        # Clickable arcade-style signboards across the front.
        self.hotspots={
            "search":self._rect(.04,.82,.28,.13),
            "library":self._rect(.36,.82,.28,.13),
            "convert":self._rect(.68,.82,.28,.13),
        }
        cards=[("search","① 图搜图","上传客户花型"),("library","② 花型目录","选择整库 / 子文件夹"),("convert","③ JPG 上架","转换与自动监测")]
        for key,title,sub in cards:
            r=self.hotspots[key]
            p.fillRect(r,QColor("#fff0d5" if key != self.hover else "#f9dda5"))
            p.setPen(QPen(QColor(self.PALETTE["wood2"]),max(2,round(u*.55))))
            p.drawRect(r.adjusted(1,1,-2,-2))
            self._label(p,QRect(r.left(),r.top()+3,r.width(),round(r.height()*.45)),title,max(9,round(u*1.55)),self.PALETTE["dark"],True)
            self._label(p,QRect(r.left()+3,r.top()+round(r.height()*.48),r.width()-6,round(r.height()*.38)),sub,max(7,round(u*1.05)),self.PALETTE["wood2"])
        p.end()

    def mouseMoveEvent(self,event):
        self.hover=next((key for key,r in self.hotspots.items() if r.contains(event.position().toPoint())),"")
        self.setCursor(Qt.CursorShape.PointingHandCursor if self.hover else Qt.CursorShape.ArrowCursor)
        self.update()

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            for key,r in self.hotspots.items():
                if r.contains(event.position().toPoint()):
                    self.action.emit(key); return


class PixelWorkbench:
    def __init__(self, window, results_view_type):
        self.w=window
        self.results_view_type=results_view_type

    def build(self):
        from PySide6.QtWidgets import QStackedWidget
        w=self.w
        self.root=QStackedWidget()
        self.scene=PixelBookshop()
        self.scene.action.connect(self._open_feature)
        self.scene.mode_changed.connect(lambda mode:w.mascot_label.setText({"idle":"小猫在书架旁打盹","search":"小猫正在翻箱倒柜找花型","convert":"小猫正在忙碌上架花型"}.get(mode,"小猫在工作")))
        self._build_search_page()
        self._build_convert_page()
        self.root.addWidget(self.scene)
        self.root.addWidget(self.search_page)
        self.root.addWidget(self.convert_page)
        w.mascot=self.scene
        w.mascot_label=QLabel("小猫在书架旁打盹")
        w.tabs=self.root
        return self.root

    def _back_button(self):
        button=QPushButton("← 回到书报亭")
        button.clicked.connect(lambda:self.root.setCurrentWidget(self.scene))
        return button

    def _page(self,title,subtitle):
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(20,16,20,16)
        top=QHBoxLayout(); titles=QVBoxLayout(); heading=QLabel(title); heading.setObjectName("brand")
        hint=QLabel(subtitle); hint.setObjectName("eyebrow"); titles.addWidget(heading); titles.addWidget(hint)
        top.addLayout(titles); top.addStretch(1); top.addWidget(self._back_button()); layout.addLayout(top)
        return page,layout

    def _build_search_page(self):
        w=self.w
        page,layout=self._page("图搜图 · 找花型","把客户照片或局部花型交给小猫，去书架里找相似款")
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
        buttons.addSpacing(12); buttons.addWidget(QLabel("相似度")); w.threshold=QSpinBox(); w.threshold.setRange(1,100); w.threshold.setValue(20)
        buttons.addWidget(w.threshold); buttons.addWidget(QLabel("%")); buttons.addStretch(1)
        w.search_button=QPushButton("小猫，开始找花型"); w.search_button.clicked.connect(w.start_search); buttons.addWidget(w.search_button)
        query_layout.addLayout(buttons); layout.addWidget(query_box)
        split=QSplitter(Qt.Orientation.Horizontal)
        scope_box=QGroupBox("搜索范围：整本花型库或指定子文件夹")
        scope_layout=QVBoxLayout(scope_box); w.scope_tree=QTreeWidget(); w.scope_tree.setHeaderHidden(True); scope_layout.addWidget(w.scope_tree)
        split.addWidget(scope_box)
        results_box=QGroupBox("找到的花型")
        results_layout=QVBoxLayout(results_box); w.search_status=QLabel("选好图片和目录，小猫就去书架上找。"); w.search_status.setWordWrap(True)
        results_layout.addWidget(w.search_status); w.results_view=self.results_view_type(); w.results_view.setMinimumHeight(210)
        w.results_view.open_requested.connect(w._open_path); results_layout.addWidget(w.results_view,1)
        split.addWidget(results_box); split.setStretchFactor(0,1); split.setStretchFactor(1,4); layout.addWidget(split,1)
        self.search_page=page

    def _build_convert_page(self):
        w=self.w
        page,layout=self._page("花型库 · JPG 上架","选择原花型库和 JPG 书架，支持手动扫描与定时监测")
        folders=QGroupBox("书报亭的两个仓库")
        form=QFormLayout(folders)
        for title,attribute,button_text,callback in (("原花型库","source_edit","选择花型库",w.choose_source),("JPG 书架","output_edit","选择 JPG 库",w.choose_output)):
            row=QHBoxLayout(); edit=QLineEdit(); edit.setReadOnly(True); setattr(w,attribute,edit)
            button=QPushButton(button_text); button.clicked.connect(callback); row.addWidget(edit,1); row.addWidget(button); form.addRow(title,row)
        layout.addWidget(folders)
        actions=QGroupBox("整理并上架")
        action_layout=QVBoxLayout(actions); controls=QHBoxLayout(); w.scan_button=QPushButton("立即扫描并转换"); w.scan_button.clicked.connect(w.start_scan)
        w.monitor_button=QPushButton("开始自动监测"); w.monitor_button.clicked.connect(w.toggle_monitor)
        controls.addWidget(w.scan_button); controls.addWidget(w.monitor_button); controls.addSpacing(12); controls.addWidget(QLabel("监测间隔"))
        w.interval_value=QSpinBox(); w.interval_value.setRange(1,168); w.interval_value.setValue(1)
        w.interval_unit=QComboBox(); w.interval_unit.addItem("小时","hours"); w.interval_unit.addItem("天","days")
        w.interval_value.valueChanged.connect(w._update_interval_limit); w.interval_unit.currentIndexChanged.connect(w._update_interval_limit)
        controls.addWidget(w.interval_value); controls.addWidget(w.interval_unit); controls.addStretch(1); action_layout.addLayout(controls)
        w.progress=QProgressBar(); w.progress.setRange(0,1); w.progress.setValue(0); action_layout.addWidget(w.progress)
        w.conversion_table=QTableWidget(0,4); w.conversion_table.setHorizontalHeaderLabels(["花型文件","状态","耗时","说明"])
        w.conversion_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        w.conversion_table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeMode.Stretch)
        w.conversion_table.setColumnWidth(1,105); w.conversion_table.setColumnWidth(2,100); action_layout.addWidget(w.conversion_table,1)
        layout.addWidget(actions,1); self.convert_page=page

    def _open_feature(self,key):
        if key=="search": self.root.setCurrentWidget(self.search_page)
        elif key=="convert": self.root.setCurrentWidget(self.convert_page)
        else:
            self.root.setCurrentWidget(self.search_page)
            if self.w.scope_tree.topLevelItemCount(): self.w.scope_tree.setCurrentItem(self.w.scope_tree.topLevelItem(0))
