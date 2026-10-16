#!/usr/bin/env python3
import html
import json
import hashlib
import os
import re
import subprocess
import sys
import signal
import urllib.parse
from pathlib import Path

from PyQt6.QtCore import QItemSelectionModel, QMimeData, QSize, QSettings, QTimer, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QDrag, QIcon, QKeySequence, QShortcut
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QFrame, QHBoxLayout, QInputDialog, QKeySequenceEdit, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import database
from capture import clean_selection
from text_format import sentence_start
from paths import APP_ID, APP_ROOT, ASSET_DIR, DATA_DIR
from hotkeys import Hotkeys, valid_keys

ROOT = APP_ROOT
PROVIDERS = {
    "merriam": "Merriam-Webster",
    "collins": "Collins",
    "oxford": "Oxford Learner's",
}

POS_LABELS = {
    "n": "名词 · noun", "v": "动词 · verb", "vt": "及物动词 · transitive verb",
    "vi": "不及物动词 · intransitive verb", "adj": "形容词 · adjective",
    "adv": "副词 · adverb", "participle": "分词形式", "plural": "复数形式",
    "imperative": "祈使式", "prep": "介词 · preposition", "conj": "连词 · conjunction",
    "pron": "代词 · pronoun", "interj": "感叹词 · interjection", "other": "其他",
}


class WordTree(QTreeWidget):
    words_dropped = pyqtSignal(list, int)
    MIME = "application/x-glyph-word-ids"

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setExpandsOnDoubleClick(False)
        self.setIndentation(16)
        self.setToolTip("Ctrl 多选，Shift 连选；拖到合集标题可批量加入")

    def selected_word_ids(self):
        return sorted({data["id"] for item in self.selectedItems()
                       if (data := item.data(0, Qt.ItemDataRole.UserRole)) and "id" in data})

    def startDrag(self, supported_actions):
        ids = self.selected_word_ids()
        if not ids:
            return
        mime = QMimeData(); mime.setData(self.MIME, json.dumps(ids).encode())
        drag = QDrag(self); drag.setMimeData(mime); drag.exec(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event):
        if event.source() is self and event.mimeData().hasFormat(self.MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item and item.parent(): item = item.parent()
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if event.source() is self and event.mimeData().hasFormat(self.MIME) and data and "group_id" in data:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item and item.parent(): item = item.parent()
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if event.source() is not self or not event.mimeData().hasFormat(self.MIME) or not data or "group_id" not in data:
            event.ignore(); return
        ids = json.loads(bytes(event.mimeData().data(self.MIME)))
        event.acceptProposedAction()
        # Refresh only after Qt has finished the drag/drop event.
        QTimer.singleShot(0, lambda: self.words_dropped.emit(ids, data["group_id"]))


class GlyphWindow(QMainWindow):
    @staticmethod
    def icon_button(text, tip, size=34):
        button = QToolButton()
        button.setObjectName("iconAction")
        button.setText(text)
        button.setFixedSize(size, size)
        button.setToolTip(tip)
        button.setToolTipDuration(6000)
        button.setAccessibleName(tip)
        return button

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Glyph")
        self.setWindowIcon(QIcon(str(ASSET_DIR / "glyph.png")))
        self.setMinimumSize(430, 430)
        self.resize(720, 780)
        self.current_word = None
        self.view_mode = "all"
        self.collection_id = None
        self.web = None
        self.hotkeys = Hotkeys()
        self.workers = []
        self.web_profile = QWebEngineProfile("Glyph", self)
        web_data = DATA_DIR / "web-profile"
        self.web_profile.setPersistentStoragePath(str(web_data))
        self.web_profile.setCachePath(str(web_data / "cache"))
        self.web_profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self.last_db_state = (0, 0)
        self.settings = QSettings("Glyph", "Glyph")
        self.build_ui()
        geometry = self.settings.value("geometry")
        if geometry: self.restoreGeometry(geometry)
        self.load_words()
        self.watch_timer = QTimer(self)
        self.watch_timer.timeout.connect(self.watch_database)
        self.watch_timer.start(1000)

    def build_ui(self):
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        nav = QFrame(); nav.setObjectName("nav")
        nav_layout = QVBoxLayout(nav); nav_layout.setContentsMargins(6, 10, 6, 10)
        self.nav_buttons = {}
        for symbol, tip, mode in (("A", "全部词汇", "all"), ("▣", "合集", "collections"), ("↻", "复习", "review")):
            button = self.icon_button(symbol, tip, 38); button.setCheckable(True)
            if mode == "all":
                button.setText("")
                button.setIcon(QIcon(str(ASSET_DIR / "glyph.png")))
                button.setIconSize(QSize(20, 20))
            button.clicked.connect(lambda _checked=False, value=mode: self.set_view(value))
            nav_layout.addWidget(button); self.nav_buttons[mode] = button
        nav_layout.addStretch(1); self.nav_buttons["all"].setChecked(True)
        root_layout.addWidget(nav)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        sidebar = QWidget(); side = QVBoxLayout(sidebar); side.setContentsMargins(8, 8, 8, 8)
        self.mode_label = QLabel("全部词汇"); self.mode_label.setObjectName("muted")
        self.collection_filter = QComboBox(); self.collection_filter.currentIndexChanged.connect(self.collection_changed)
        self.collection_filter.setToolTip("全部合集：显示可折叠分组；也可只查看一个合集")
        self.collection_filter.hide()
        self.search = QLineEdit(); self.search.setPlaceholderText("Search words…"); self.search.textChanged.connect(self.load_words)
        self.search.setFixedHeight(34)
        search_row = QWidget(); search_layout = QHBoxLayout(search_row); search_layout.setContentsMargins(0, 0, 0, 0); search_layout.setSpacing(6)
        self.multi_select_button = QPushButton("多选"); self.multi_select_button.setCheckable(True)
        self.multi_select_button.setFixedSize(52, 34)
        self.multi_select_button.setToolTip("开启后直接点击可选中多个词，再点一次恢复普通选择")
        self.multi_select_button.toggled.connect(self.set_multi_select)
        search_layout.addWidget(self.search, 1); search_layout.addWidget(self.multi_select_button)
        self.word_list = WordTree(); self.word_list.currentItemChanged.connect(self.on_word_selected)
        self.multi_select_shortcut = QShortcut(QKeySequence(database.get_setting("multi_select_shortcut", "Ctrl+Shift+M")), self)
        self.multi_select_shortcut.activated.connect(self.multi_select_button.toggle)
        self.word_list.itemClicked.connect(self.on_tree_clicked)
        self.word_list.itemExpanded.connect(self.update_group_heading)
        self.word_list.itemCollapsed.connect(self.update_group_heading)
        self.word_list.itemSelectionChanged.connect(self.update_batch_actions)
        self.word_list.words_dropped.connect(self.assign_selected_words)
        self.batch_bar = QWidget(); batch_layout = QHBoxLayout(self.batch_bar); batch_layout.setContentsMargins(0, 0, 0, 0)
        self.selection_label = QLabel(); self.selection_label.setObjectName("muted")
        batch_group = QPushButton("加入合集"); batch_group.setToolTip("将所有选中的词批量加入一个合集")
        self.batch_group_button = batch_group
        batch_group.clicked.connect(self.choose_batch_collection)
        batch_layout.addWidget(self.selection_label, 1); batch_layout.addWidget(batch_group)
        self.batch_bar.hide()
        side.addWidget(self.mode_label); side.addWidget(self.collection_filter); side.addWidget(search_row); side.addWidget(self.word_list, 1)
        side.addWidget(self.batch_bar)
        self.populate_collections()

        right = QWidget(); right_layout = QVBoxLayout(right); right_layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QFrame(); toolbar.setObjectName("toolbar")
        tools = QHBoxLayout(toolbar); tools.setContentsMargins(8, 6, 8, 6)
        sidebar_button = self.icon_button("☰", "显示或收起左侧词汇列表"); sidebar_button.setCheckable(True); sidebar_button.setChecked(True)
        sidebar_button.clicked.connect(sidebar.setVisible)
        add = self.icon_button("＋", "手动添加单词或短语"); add.clicked.connect(self.manual_add)
        self.local_button = QPushButton("Local"); self.local_button.setCheckable(True)
        self.web_button = QPushButton("Web"); self.web_button.setCheckable(True)
        for button, tip in ((self.local_button, "查看本地英文释义和中文参考"), (self.web_button, "在应用内打开在线词典")):
            button.setFixedSize(64, 34); button.setToolTip(tip); button.setAccessibleName(tip)
        self.local_button.clicked.connect(lambda: self.set_dictionary_mode("local"))
        self.web_button.clicked.connect(lambda: self.set_dictionary_mode("web"))
        self.provider = QComboBox()
        self.provider.setFixedHeight(34)
        self.provider.setToolTip("选择在线词典，点击名称可切换")
        for key, name in PROVIDERS.items(): self.provider.addItem(name, key)
        saved_provider = database.get_setting("web_provider", "merriam")
        self.provider.setCurrentIndex(max(0, self.provider.findData(saved_provider)))
        self.provider.currentIndexChanged.connect(self.provider_changed)
        menu_button = self.icon_button("⋮", "更多操作、设置和彻底退出"); menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu_button.setMenu(self.make_menu())
        tools.addWidget(sidebar_button); tools.addWidget(add); tools.addStretch(1)
        tools.addWidget(self.local_button); tools.addWidget(self.web_button); tools.addWidget(self.provider); tools.addStretch(1); tools.addWidget(menu_button)
        right_layout.addWidget(toolbar)

        self.pages = QStackedWidget()
        self.local_scroll = QScrollArea(); self.local_scroll.setWidgetResizable(True)
        self.local_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.local_widget = QWidget(); self.local_layout = QVBoxLayout(self.local_widget)
        self.local_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.local_layout.setContentsMargins(30, 22, 30, 26); self.local_layout.setSpacing(8)
        self.local_scroll.setWidget(self.local_widget)
        self.web_container = QWidget(); self.web_layout = QVBoxLayout(self.web_container); self.web_layout.setContentsMargins(0, 0, 0, 0)
        self.pages.addWidget(self.local_scroll); self.pages.addWidget(self.web_container)
        right_layout.addWidget(self.pages, 1)
        self.splitter.addWidget(sidebar); self.splitter.addWidget(right)
        width = int(database.get_setting("list_width", "220")); self.splitter.setSizes([width, 720 - width])
        self.splitter.splitterMoved.connect(lambda pos, _index: database.set_setting("list_width", pos))
        root_layout.addWidget(self.splitter, 1)
        self.setCentralWidget(root)
        mode = database.get_setting("default_dictionary_mode", database.get_setting("dictionary_mode", "local"))
        self.set_dictionary_mode("web" if mode in ("web", "merriam", "collins", "oxford") else "local")

    def make_menu(self):
        menu = QMenu(self)
        menu.addAction("框选 OCR 收录", self.start_ocr)
        menu.addAction("新建合集", self.new_collection)
        menu.addSeparator()
        menu.addAction("设置", self.edit_settings)
        if os.environ.get("APPIMAGE"):
            menu.addAction("安装启动入口 / 快捷键…", self.integrate_appimage)
        menu.addAction("彻底退出 Glyph", QApplication.instance().quit)
        return menu

    def start_ocr(self):
        self.hide()
        self.freeze_web(True)
        self.launch_worker("ocr_capture.py")

    def launch_worker(self, script):
        self.workers = [worker for worker in self.workers if worker.poll() is None]
        self.workers.append(subprocess.Popen([sys.executable, str(ROOT / "app" / script)], start_new_session=True))

    def dispatch(self, action):
        if action == "capture": self.launch_worker("capture.py")
        elif action == "ocr": self.start_ocr()
        elif action == "quit": QApplication.instance().quit()
        elif action == "toggle": self.toggle()

    def shutdown(self):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.sync()
        self.watch_timer.stop()
        self.hotkeys.close()
        for worker in self.workers:
            if worker.poll() is None:
                try: os.killpg(worker.pid, signal.SIGTERM)
                except ProcessLookupError: pass
        self.destroy_web()
        # Flush the disk-backed profile while QApplication is still alive.
        # Keeping it until interpreter teardown can race Cookie/cache writes.
        if self.web_profile is not None:
            from PyQt6 import sip
            sip.delete(self.web_profile)
            self.web_profile = None

    def set_dictionary_mode(self, mode):
        is_web = mode == "web"
        self.pages.setCurrentIndex(1 if is_web else 0)
        self.local_button.setChecked(not is_web); self.web_button.setChecked(is_web)
        self.provider.setVisible(is_web)
        database.set_setting("dictionary_mode", mode)
        if is_web:
            self.load_web()
            self.freeze_web(False)
        else:
            self.freeze_web(True)

    def provider_changed(self, *_args):
        database.set_setting("web_provider", self.provider.currentData())
        if self.pages.currentIndex() == 1: self.load_web(force=True)

    def dictionary_url(self):
        word = self.current_word["normalized"] if self.current_word else ""
        encoded = urllib.parse.quote(word, safe="")
        slug = urllib.parse.quote(word.replace(" ", "-"), safe="-")
        provider = self.provider.currentData()
        if provider == "merriam": return f"https://www.merriam-webster.com/dictionary/{encoded}" if word else "https://www.merriam-webster.com/"
        if provider == "collins": return f"https://www.collinsdictionary.com/dictionary/english/{slug}" if word else "https://www.collinsdictionary.com/"
        return f"https://www.oxfordlearnersdictionaries.com/definition/english/{slug}" if word else "https://www.oxfordlearnersdictionaries.com/"

    def create_web(self):
        if self.web: return
        self.web = QWebEngineView()
        self.web.setPage(QWebEnginePage(self.web_profile, self.web))
        self.web.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        self.web.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, False)
        self.web.page().setBackgroundColor(Qt.GlobalColor.white)
        self.web_layout.addWidget(self.web)

    def load_web(self, force=False):
        self.create_web(); url = QUrl(self.dictionary_url())
        if force or self.web.url() != url: self.web.setUrl(url)

    def destroy_web(self):
        if not self.web: return
        from PyQt6 import sip
        self.web.stop(); self.web_layout.removeWidget(self.web)
        sip.delete(self.web); self.web = None

    def freeze_web(self, frozen):
        if not self.web:
            return
        state = QWebEnginePage.LifecycleState.Frozen if frozen else QWebEnginePage.LifecycleState.Active
        self.web.page().setLifecycleState(state)

    def set_view(self, mode):
        self.view_mode = mode
        for name, button in self.nav_buttons.items(): button.setChecked(name == mode)
        self.collection_filter.setVisible(mode == "collections")
        self.load_words()

    def set_multi_select(self, enabled):
        mode = QAbstractItemView.SelectionMode.MultiSelection if enabled else QAbstractItemView.SelectionMode.ExtendedSelection
        self.word_list.setSelectionMode(mode)
        self.multi_select_button.setText("完成" if enabled else "多选")
        self.multi_select_button.setAccessibleName("结束多选" if enabled else "开启多选")
        if not enabled:
            selected = self.word_list.selectedItems()
            current = self.word_list.currentItem()
            keep = current if current in selected else (selected[0] if selected else None)
            self.word_list.clearSelection()
            if keep is not None: keep.setSelected(True)
        self.update_batch_actions()

    def populate_collections(self, reload=True):
        current = self.collection_filter.currentData() if self.collection_filter.count() else None
        self.collection_filter.blockSignals(True); self.collection_filter.clear()
        self.collection_filter.addItem("全部合集", None)
        self.collection_filter.addItem("默认（未分组）", 0)
        for collection in database.list_collections():
            self.collection_filter.addItem(f"{collection['name']}  ·  {collection['total']}", collection["id"])
        index = self.collection_filter.findData(current)
        if index >= 0: self.collection_filter.setCurrentIndex(index)
        self.collection_filter.blockSignals(False)
        self.collection_id = self.collection_filter.currentData()
        if reload: self.collection_changed()

    def collection_changed(self, *_args):
        self.collection_id = self.collection_filter.currentData()
        if self.collection_id == 0:
            database.set_setting("current_collection", "")
        elif self.collection_id is not None:
            database.set_setting("current_collection", self.collection_filter.currentText().split("  ·  ", 1)[0])
        if self.view_mode == "collections" and hasattr(self, "word_list"): self.load_words()

    def load_words(self, *_args):
        selected_id = self.current_word["id"] if self.current_word else None
        selected_ids = set(self.word_list.selected_word_ids())
        if not selected_ids and selected_id: selected_ids.add(selected_id)
        expanded = {}
        for index in range(self.word_list.topLevelItemCount()):
            item = self.word_list.topLevelItem(index); data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and "group_id" in data: expanded[data["group_id"]] = item.isExpanded()
        expanded = {**getattr(self, "group_expansion", {}), **expanded}
        self.group_expansion = expanded
        self.populate_collections(reload=False)
        rows = [dict(row) for row in database.list_words(
            self.search.text().strip(),
            collection_id=self.collection_id if self.view_mode == "collections" and self.collection_id else None,
            due_only=self.view_mode == "review",
        )]
        memberships = {}
        for word_id, collection_id in database.collection_memberships():
            memberships.setdefault(word_id, set()).add(collection_id)
        if self.view_mode == "collections" and self.collection_id == 0:
            rows = [row for row in rows if not memberships.get(row["id"])]
        titles = {"all": "全部词汇", "collections": "合集词汇", "review": "今日待复习"}
        self.mode_label.setText(f"{titles[self.view_mode]}  ·  {len(rows)}")
        self.word_list.blockSignals(True); self.word_list.clear(); target = None; first = None
        grouped = self.view_mode == "collections"
        self.word_list.setRootIsDecorated(False)
        groups = {}
        if grouped:
            descriptors = [(collection["id"], collection["name"]) for collection in database.list_collections()]
            descriptors.append((0, "默认"))
            for group_id, name in descriptors:
                if self.collection_id is not None and group_id != self.collection_id: continue
                group = QTreeWidgetItem([name]); group.setData(0, Qt.ItemDataRole.UserRole, {"group_id": group_id, "name": name})
                group.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDropEnabled)
                group.setToolTip(0, "点击展开或收起；拖动所选词到这里加入")
                self.word_list.addTopLevelItem(group); group.setExpanded(expanded.get(group_id, True))
                groups[group_id] = group
        for data in rows:
            count = f"  ·  {data['encounter_count']}" if data["encounter_count"] > 1 else ""
            destinations = [groups[key] for key in (memberships.get(data["id"]) or {0}) if key in groups] if grouped else [None]
            for parent in destinations:
                item = QTreeWidgetItem([f"{data['display']}{count}"])
                item.setData(0, Qt.ItemDataRole.UserRole, data)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
                if parent: parent.addChild(item)
                else: self.word_list.addTopLevelItem(item)
                if first is None: first = item
                if data["id"] == selected_id and target is None: target = item
                if data["id"] in selected_ids: item.setSelected(True)
        for group in groups.values():
            data = group.data(0, Qt.ItemDataRole.UserRole)
            self.update_group_heading(group)
        target = target if target is not None else first
        if target is not None:
            self.word_list.setCurrentItem(target, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
            if not self.word_list.selected_word_ids(): target.setSelected(True)
        self.word_list.blockSignals(False)
        if target is not None: self.on_word_selected(target)
        else: self.current_word = None; self.render_empty()
        self.update_batch_actions()
        self.last_db_state = self.database_state()

    def on_word_selected(self, current, _previous=None):
        if not current: return
        data = current.data(0, Qt.ItemDataRole.UserRole)
        if not data or "id" not in data: return
        self.current_word = data
        self.render_local()
        if self.pages.currentIndex() == 1: self.load_web(force=True)

    def on_tree_clicked(self, item, _column):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and "group_id" in data:
            item.setExpanded(not item.isExpanded())
            database.set_setting("current_collection", data["name"] if data["group_id"] else "")

    def update_group_heading(self, item):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and "group_id" in data:
            arrow = "▾" if item.isExpanded() else "▸"
            item.setText(0, f"{arrow} {data['name']}  ·  {item.childCount()}")
            font = item.font(0); font.setBold(True); item.setFont(0, font)

    def update_batch_actions(self):
        if not hasattr(self, "batch_bar"): return
        count = len(self.word_list.selected_word_ids())
        self.batch_bar.setVisible(self.multi_select_button.isChecked() or count > 1)
        self.batch_group_button.setEnabled(count > 0)
        self.selection_label.setText(f"已选 {count} 个词")

    def choose_batch_collection(self):
        ids = self.word_list.selected_word_ids()
        if not ids: return
        groups = database.list_collections()
        if not groups: self.new_collection(); groups = database.list_collections()
        if not groups: return
        labels = [row["name"] for row in groups]
        value, ok = QInputDialog.getItem(self, "批量加入合集", f"将 {len(ids)} 个词加入：", labels, editable=False)
        if ok:
            self.assign_selected_words(ids, groups[labels.index(value)]["id"])

    def assign_selected_words(self, ids, group_id):
        if group_id == 0:
            answer = QMessageBox.question(self, "移回默认", f"将 {len(ids)} 个词移回默认？这些词会退出原有合集，词条和复习记录保留。")
            if answer != QMessageBox.StandardButton.Yes: return
        database.assign_words_to_collection(ids, group_id)
        expansion = getattr(self, "group_expansion", {})
        expansion[group_id] = True; self.group_expansion = expansion
        # Keep the destination visible when adding from a filtered collection.
        self.collection_filter.blockSignals(True); self.collection_filter.setCurrentIndex(0); self.collection_filter.blockSignals(False)
        self.collection_id = None
        self.load_words()
        for index in range(self.word_list.topLevelItemCount()):
            item = self.word_list.topLevelItem(index)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("group_id") == group_id: item.setExpanded(True)

    def clear_local(self):
        while self.local_layout.count():
            item = self.local_layout.takeAt(0)
            if item.widget():
                item.widget().hide(); item.widget().deleteLater()

    def render_empty(self):
        self.clear_local(); label = QLabel("这里暂时没有词汇"); label.setObjectName("muted")
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter); self.local_layout.addWidget(label); self.local_layout.addStretch(1)

    @staticmethod
    def canonical_pos(value):
        value = (value or "").lower().strip(". ")
        if value in ("a", "s", "adj"): return "adj"
        if value == "r": return "adv"
        if value in ("p", "p pr"): return "participle"
        if value == "pl": return "plural"
        if value == "imp": return "imperative"
        return value or "other"

    @staticmethod
    def readable_definition(value):
        value = re.sub(r"\s+", " ", value).strip()
        numbered = re.match(r"^(\d+\.\s+)(.*)$", value)
        prefix = numbered.group(1) if numbered else ""
        value = numbered.group(2) if numbered else value
        value = re.sub(
            r"^p\.?\s*pr\.?\s*&\s*vb\.?\s*n\.?\s+of\s+",
            "present participle and gerund of ", value, flags=re.I,
        )
        value = re.sub(r"^p\.?\s*pr\.?\s+of\s+", "present participle of ", value, flags=re.I)
        value = re.sub(r"^pa\.?\s*p\.?\s+of\s+", "past participle of ", value, flags=re.I)
        value = re.sub(r"^pl\.?\s+of\s+", "plural of ", value, flags=re.I)
        return prefix + sentence_start(value)

    @staticmethod
    def split_definitions(text, fallback):
        groups = {}; order = []; current = fallback
        pattern = re.compile(r"^(n|v|vt|vi|a|adj|adv|prep|conj|pron|num|art|aux|s)(?:\.\s*|\s+)", re.I)
        for raw in (text or "").splitlines():
            value = raw.strip()
            if not value: continue
            match = pattern.match(value)
            if match: current = GlyphWindow.canonical_pos(match.group(1)); value = value[match.end():]
            if current not in groups: groups[current] = []; order.append(current)
            if value not in groups[current]: groups[current].append(value)
        return [(key, groups[key]) for key in order]

    def add_section(self, title, source, groups):
        heading = QLabel(f"<b>{html.escape(title)}</b>  <span style='color:#8f96a3;font-size:11px'>{html.escape(source)}</span>")
        heading.setContentsMargins(0, 10, 0, 0); self.local_layout.addWidget(heading)
        for pos, values in groups:
            pos_label = POS_LABELS.get(pos, pos)
            pos_heading = QLabel(f"<span style='color:#9a8cff;font-weight:700'>{html.escape(pos_label)}</span>")
            self.local_layout.addWidget(pos_heading)
            seen = set()
            for value in values:
                readable = self.readable_definition(value)
                key = readable.casefold()
                if not readable or key in seen:
                    continue
                seen.add(key)
                line = QWidget(); row = QHBoxLayout(line); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(7)
                bullet = QLabel("•"); bullet.setAlignment(Qt.AlignmentFlag.AlignTop); row.addWidget(bullet)
                label = QLabel(html.escape(readable)); label.setWordWrap(True); label.setMinimumWidth(0)
                label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                row.addWidget(label, 1); self.local_layout.addWidget(line)

    def add_translation_note(self):
        if database.get_setting("show_translation_note", "1") != "1":
            return
        note = QWidget(); row = QHBoxLayout(note); row.setContentsMargins(0, 2, 0, 0)
        text = QLabel("中文释义是独立参考，不与上方英文义项逐条对应")
        text.setObjectName("muted"); text.setWordWrap(True); row.addWidget(text, 1)
        close = self.icon_button("×", "关闭这条提示，以后不再显示", 26)
        close.clicked.connect(self.dismiss_translation_note); row.addWidget(close)
        self.local_layout.addWidget(note)

    def dismiss_translation_note(self):
        database.set_setting("show_translation_note", "0")
        self.render_local()

    def render_local(self):
        if not self.current_word: return
        self.clear_local(); word = self.current_word["normalized"]
        header = QWidget(); row = QHBoxLayout(header); row.setContentsMargins(0, 0, 0, 0)
        count = self.current_word["encounter_count"]
        count_text = f" <span style='color:#7f8590;font-size:12px'>· {count}</span>" if count > 1 else ""
        title = QLabel(f"<span style='font-size:28px;font-weight:700'>{html.escape(self.current_word['display'])}</span>{count_text}")
        row.addWidget(title, 1)
        row.setSpacing(4)
        for text, tip, handler in (("×", "删除这个词及其复习记录（点击后确认）", self.remove_current), ("−", "收录次数减 1（最少保留 1 次）", lambda: self.adjust_current(-1)), ("+", "收录次数加 1", lambda: self.adjust_current(1)), ("✎", "修改单词拼写或显示的大小写", self.edit_current), ("▣", "管理所属合集；多选时可批量加入合集", self.group_current_selection)):
            button = self.icon_button(text, tip); button.clicked.connect(handler); row.addWidget(button)
        self.local_layout.addWidget(header)

        review = QWidget(); reviews = QHBoxLayout(review); reviews.setContentsMargins(0, 6, 0, 4)
        reviews.addWidget(QLabel("复习")); reviews.addStretch(1)
        for label, rating, tip in (
            ("生疏", 1, "想不起含义，或理解有明显错误；安排较早复习"),
            ("不稳", 2, "大致知道含义，但还需要提示或犹豫较久"),
            ("熟练", 3, "不用提示就能想起并理解含义；逐步延长复习间隔"),
        ):
            button = QPushButton(label); button.setFixedSize(64, 32)
            button.setToolTip(tip); button.setAccessibleDescription(tip)
            button.clicked.connect(lambda _checked=False, value=rating: self.rate_current(value)); reviews.addWidget(button)
        self.local_layout.addWidget(review)
        state = database.review_state(self.current_word["id"])
        if state:
            due = QLabel(f"下次复习：{state['due_at'][:10]}"); due.setObjectName("muted"); self.local_layout.addWidget(due)

        entries = database.lookup_dictionary(word); wordnet = database.lookup_wordnet(word); source = "WordNet 2025"
        if not wordnet:
            for prefix in ("un", "re", "dis", "mis", "non", "over", "under"):
                candidate = word[len(prefix):] if word.startswith(prefix) else ""
                found = database.lookup_wordnet(candidate) if len(candidate) > 2 else []
                if found: wordnet = found; source = f"WordNet 2025 · 构词参考：{candidate}"; break
        en_groups = {}; en_order = []
        for entry in wordnet:
            pos = self.canonical_pos(entry["pos"]); value = re.sub(r"\s+", " ", entry["definition"]).strip()
            if pos not in en_groups: en_groups[pos] = []; en_order.append(pos)
            if value not in en_groups[pos]: en_groups[pos].append(value)
        if not en_groups:
            for entry in entries:
                for pos, values in self.split_definitions(entry["definition_en"], self.canonical_pos(entry["pos"])):
                    if pos not in en_groups: en_groups[pos] = []; en_order.append(pos)
                    en_groups[pos].extend(value for value in values if value not in en_groups[pos])
            source = "ECDICT"
        if en_groups: self.add_section("English definitions", source, [(p, en_groups[p]) for p in en_order])
        zh_groups = {}; zh_order = []
        for entry in entries:
            for pos, values in self.split_definitions(entry["definition_zh"], self.canonical_pos(entry["pos"])):
                if pos not in zh_groups: zh_groups[pos] = []; zh_order.append(pos)
                zh_groups[pos].extend(v for v in values if v not in zh_groups[pos])
        if zh_groups:
            self.add_section("中文参考", "ECDICT", [(p, zh_groups[p]) for p in zh_order])
            self.add_translation_note()
        if not en_groups and not zh_groups: self.local_layout.addWidget(QLabel("暂无可靠本地释义，可切换到 Web。"))

        relations = database.related_words(word)
        for kind, title_text in (("synonym", "Synonyms"), ("antonym", "Antonyms"), ("family", "Word family")):
            values = relations[kind]
            if not values: continue
            self.local_layout.addWidget(QLabel(f"<b>{title_text}</b>"))
            line = QWidget(); flow = QHBoxLayout(line); flow.setContentsMargins(0, 0, 0, 0)
            for value in values[:6]:
                button = QPushButton(f"+ {value}"); button.clicked.connect(lambda _checked=False, picked=value: self.add_related(picked)); flow.addWidget(button)
            flow.addStretch(1); self.local_layout.addWidget(line)
        self.local_layout.addStretch(1)

    def manual_add(self):
        value, ok = QInputDialog.getText(self, "手动添加", "英文单词或短语：")
        word = clean_selection(value) if ok else ""
        if word: database.capture(word, word.casefold(), "manual"); self.current_word = None; self.load_words()

    def new_collection(self):
        value, ok = QInputDialog.getText(self, "新建合集", "合集名称：")
        if ok and value.strip():
            name = " ".join(value.split())
            database.add_collection(name); database.set_setting("current_collection", name)
            self.populate_collections(reload=False)
            self.collection_filter.setCurrentIndex(0)
            self.set_view("collections")

    def group_current_selection(self):
        if len(self.word_list.selected_word_ids()) > 1: self.choose_batch_collection()
        else: self.manage_collections()

    def manage_collections(self):
        if not self.current_word: return
        collections = database.list_collections()
        if not collections: self.new_collection(); return
        current = database.word_collection_ids(self.current_word["id"])
        dialog = QDialog(self); dialog.setWindowTitle("所属合集"); layout = QVBoxLayout(dialog); checks = []
        for collection in collections:
            check = QCheckBox(collection["name"]); check.setChecked(collection["id"] in current); layout.addWidget(check); checks.append((collection["id"], check))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            database.set_word_collections(self.current_word["id"], [cid for cid, check in checks if check.isChecked()]); self.populate_collections(); self.load_words()

    def edit_current(self):
        if not self.current_word: return
        value, ok = QInputDialog.getText(self, "修正词汇", "词汇：", text=self.current_word["display"])
        word = clean_selection(value) if ok else ""
        if word: database.rename_word(self.current_word["id"], word, word.casefold()); self.current_word = None; self.load_words()

    def remove_current(self):
        if not self.current_word: return
        if QMessageBox.question(self, "删除词条", f"删除 {self.current_word['display']}？") == QMessageBox.StandardButton.Yes:
            database.delete_word(self.current_word["id"]); self.current_word = None; self.load_words()

    def adjust_current(self, delta):
        if self.current_word: database.adjust_count(self.current_word["id"], delta); self.load_words()

    def rate_current(self, rating):
        if self.current_word:
            database.review_word(self.current_word["id"], rating)
            self.render_local()

    def add_related(self, word):
        database.capture(word, word.casefold(), "relation"); self.current_word = None; self.load_words()

    @staticmethod
    def shortcut_text(editor):
        value = editor.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        return value.replace("Meta+", "Mod+")

    @staticmethod
    def valid_shortcut(value):
        return bool(re.fullmatch(r"[A-Za-z0-9_-]+(?:\+[A-Za-z0-9_-]+)*", value))

    def write_shortcuts(self, capture_key, ocr_key, toggle_key):
        return self.hotkeys.configure(capture_key, ocr_key, toggle_key)

    def integrate_appimage(self):
        import shutil
        from appimage_integration import install
        use_niri = bool(shutil.which("niri") and (Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "niri/config.kdl").is_file())
        description = "安装应用启动入口，并启用 niri 全局快捷键集成？" if use_niri else "安装 Glyph 应用启动入口？当前桌面暂不支持全局快捷键集成。"
        description += "\n\n不会开机自启，也不复制 AppImage。请将它保存在固定位置。\n已有旧版手动快捷键时，请先移除旧绑定，避免冲突。"
        if QMessageBox.question(self, "安装 Glyph", description) != QMessageBox.StandardButton.Yes: return
        try:
            message = install(niri=use_niri)
            if use_niri:
                keys = [database.get_setting(key, default) for key, default in (("capture_shortcut", "Alt+E"), ("ocr_shortcut", "Alt+Shift+E"), ("toggle_shortcut", "Alt+R"))]
                self.hotkeys.configure(*keys)
            QMessageBox.information(self, "Glyph", message)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            QMessageBox.warning(self, "安装失败", str(error))

    def edit_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Glyph 设置")
        dialog.setWindowIcon(QIcon())
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        capture_edit = QKeySequenceEdit(QKeySequence(database.get_setting("capture_shortcut", "Alt+E")))
        ocr_edit = QKeySequenceEdit(QKeySequence(database.get_setting("ocr_shortcut", "Alt+Shift+E")))
        toggle_edit = QKeySequenceEdit(QKeySequence(database.get_setting("toggle_shortcut", "Alt+R")))
        global_before = [self.shortcut_text(editor) for editor in (capture_edit, ocr_edit, toggle_edit)]
        multi_edit = QKeySequenceEdit(self.multi_select_shortcut.key())
        multi_edit.setMaximumSequenceLength(1)
        mode = QComboBox(); mode.addItem("Local 本地释义", "local"); mode.addItem("Web 在线词典", "web")
        mode.setCurrentIndex(max(0, mode.findData(database.get_setting("default_dictionary_mode", "local"))))
        provider = QComboBox()
        for key, name in PROVIDERS.items(): provider.addItem(name, key)
        provider.setCurrentIndex(max(0, provider.findData(database.get_setting("web_provider", "merriam"))))
        form.addRow("复制收录", capture_edit); form.addRow("框选 OCR", ocr_edit); form.addRow("呼出 / 隐藏", toggle_edit)
        form.addRow("切换多选（仅软件内）", multi_edit)
        form.addRow("默认打开", mode); form.addRow("默认网页词典", provider)
        layout.addLayout(form)
        hotkey_status = QLabel(self.hotkeys.error or "全局快捷键需启用 niri 集成；软件内多选快捷键不受影响。")
        hotkey_status.setWordWrap(True); hotkey_status.setObjectName("muted"); layout.addWidget(hotkey_status)
        hint = QLabel("点击快捷键框后直接按组合键；Backspace 可清空。")
        hint.setObjectName("muted"); layout.addWidget(hint)
        usage = QLabel("多选与分组\n点击搜索框旁的“多选”，即可逐个点击选词，无需按住键盘。\n普通选择模式：Ctrl + 点击增减选择；Shift + 点击选择连续范围。\n选中多个词后，点“加入合集”；在合集页也可拖到合集标题。\n切换多选的快捷键仅在 Glyph 窗口内有效，可在上方修改或清空。")
        usage.setWordWrap(True); usage.setObjectName("muted"); layout.addWidget(usage)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        keys = [self.shortcut_text(editor) for editor in (capture_edit, ocr_edit, toggle_edit)]
        if not valid_keys(keys):
            QMessageBox.warning(self, "无法保存", "三个快捷键必须不同，并包含 Ctrl、Alt 或 Super。")
            return
        local_key = multi_edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        if local_key and self.shortcut_text(multi_edit) in keys:
            QMessageBox.warning(self, "无法保存", "多选快捷键不能与上方三个全局快捷键重复。")
            return
        if keys != global_before and not self.write_shortcuts(*keys):
            QMessageBox.warning(self, "无法保存", self.hotkeys.error)
            return
        for setting, value in zip(("capture_shortcut", "ocr_shortcut", "toggle_shortcut"), keys):
            database.set_setting(setting, value)
        database.set_setting("multi_select_shortcut", local_key)
        self.multi_select_shortcut.setKey(QKeySequence(local_key))
        database.set_setting("default_dictionary_mode", mode.currentData())
        database.set_setting("web_provider", provider.currentData())
        self.provider.setCurrentIndex(self.provider.findData(provider.currentData()))

    def database_state(self):
        wal = database.DB_PATH.with_name(database.DB_PATH.name + "-wal")
        return tuple(path.stat().st_mtime_ns if path.exists() else 0 for path in (database.DB_PATH, wal))

    def watch_database(self):
        if self.database_state() != self.last_db_state: self.load_words()

    def toggle(self):
        if self.isVisible():
            self.hide(); self.freeze_web(True)
        else:
            self.show(); self.freeze_web(self.pages.currentIndex() != 1); self.raise_(); self.activateWindow()

    def hideEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry()); super().hideEvent(event)

    def closeEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry()); self.hide(); self.freeze_web(True); event.ignore()


def install_style(app):
    app.setStyleSheet("""
        QWidget { background:#17191f; color:#e8eaf0; font-size:14px; }
        QFrame#nav { background:#191c22; border-right:1px solid #30343d; }
        QFrame#toolbar { background:#1d2027; border-bottom:1px solid #31353e; }
        QLineEdit, QComboBox, QListWidget, QTreeWidget { background:#20232a; border:1px solid #373c47; border-radius:8px; padding:6px; }
        QComboBox::drop-down { border:0; width:8px; }
        QComboBox::down-arrow { image:none; width:0; height:0; }
        QListWidget::item { padding:8px; border-left:3px solid transparent; }
        QListWidget::item:selected { background:#2c2943; color:#f4f2ff; border-left:3px solid #8376ee; }
        QTreeWidget::item { padding:7px 3px; border:0; }
        QTreeWidget { selection-background-color:#2c2943; selection-color:#f4f2ff; }
        QTreeWidget::item:selected { background:#2c2943; color:#f4f2ff; }
        QTreeWidget::branch { background:transparent; }
        QTreeWidget::branch:selected { background:#2c2943; }
        QPushButton, QToolButton { background:#262931; border:1px solid #353a45; border-radius:9px; padding:6px 10px; }
        QPushButton:hover, QToolButton:hover { background:#30343e; }
        QPushButton:checked, QToolButton:checked { background:#3a3450; color:#d3ccff; border-color:#8175e7; }
        QToolButton#iconAction { background:transparent; border:1px solid transparent; border-radius:7px; padding:0; }
        QToolButton#iconAction:hover { background:#292d37; border-color:#3a404c; }
        QToolButton#iconAction:pressed { background:#363143; }
        QToolButton#iconAction:checked { background:#302b40; color:#d3ccff; border-color:transparent; }
        QToolButton#iconAction:focus { border-color:#8175e7; }
        QToolTip { background:#282c35; color:#f0eef6; border:1px solid #454b59; padding:6px; }
        QLabel#muted { color:#969ca8; font-size:12px; }
        QSplitter::handle { background:#30343d; width:4px; }
        QScrollArea { border:0; }
    """)


def main():
    database.initialize()
    app = QApplication(sys.argv); app.setApplicationName("Glyph"); app.setDesktopFileName(APP_ID); app.setQuitOnLastWindowClosed(False)
    install_style(app)
    action = sys.argv[2] if len(sys.argv) == 3 and sys.argv[1] == "--action" else None
    if len(sys.argv) > 1 and action not in ("toggle", "capture", "ocr", "quit"):
        print("Usage: glyph [--action toggle|capture|ocr|quit]", file=sys.stderr)
        return 2
    digest = hashlib.sha256(str(DATA_DIR).encode()).hexdigest()[:12]
    server_name = f"glyph-{os.getuid()}-{digest}"
    probe = QLocalSocket(); probe.connectToServer(server_name)
    if probe.waitForConnected(150):
        probe.write((action or "toggle").encode()); probe.flush(); probe.waitForBytesWritten(150); return 0
    if action:
        return 0
    QLocalServer.removeServer(server_name)
    server = QLocalServer(app)
    if not server.listen(server_name):
        print(server.errorString(), file=sys.stderr); return 1
    window = GlyphWindow(); window.show()
    app.aboutToQuit.connect(window.shutdown)
    signal.signal(signal.SIGTERM, lambda *_args: app.quit())
    signal.signal(signal.SIGINT, lambda *_args: app.quit())
    keys = [database.get_setting(key, default) for key, default in (("capture_shortcut", "Alt+E"), ("ocr_shortcut", "Alt+Shift+E"), ("toggle_shortcut", "Alt+R"))]
    window.hotkeys.configure(*keys)
    def receive():
        socket = server.nextPendingConnection(); socket.waitForReadyRead(150)
        command = bytes(socket.readAll()).decode(errors="replace").strip()
        window.dispatch(command); socket.disconnectFromServer(); socket.deleteLater()
    server.newConnection.connect(receive)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
