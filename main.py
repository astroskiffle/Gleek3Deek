#!/usr/bin/env python3
"""
Gleek3Deek - ultra-light native 3D asset manager + viewer.

    pip install PySide6 vtk numpy
    # optional extras:
    pip install assimp-py      # in-process FBX / 3DS / LWO / DAE / etc. via Assimp
    pip install cadquery       # STEP/STP fallback if VTK has no OpenCASCADE module

    python main.py [optional_folder_or_file]
"""

from __future__ import annotations

import html
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from PySide6.QtCore import (
    QByteArray, QDir, QEasingCurve, QEvent, QFile, QMimeData, QObject, QSettings, QStandardPaths, Qt,
    QThreadPool, QTimer, QUrl, QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QShortcut
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QTextBrowser, QComboBox, QDialog, QFileDialog, QInputDialog, QLineEdit, QMenu, QMessageBox,
    QPushButton, QSizePolicy, QSlider, QTabWidget)
from PySide6.QtWidgets import QDockWidget, QScrollArea, QTabBar
from PySide6.QtWidgets import (
    QApplication, QFileSystemModel, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QSplitter, QStackedWidget, QToolButton, QTreeView, QVBoxLayout, QWidget,
    QAbstractItemView, QStyle, QStyledItemDelegate, QStyleOptionViewItem)
import vtkmodules.vtkRenderingOpenGL2  # noqa: F401  (registers GL backend)
import vtkmodules.vtkInteractionStyle  # noqa: F401  (registers styles)
import vtkmodules.vtkRenderingFreeType  # noqa: F401  (text for the axes gizmo)
from formats import ALL_EXTS, asset_ext
from panels import TagsDialog
from library import (
    COLORS, Library, parse_query, push_recent, query_is_empty, resolve_library_path, split_tags)
from gallery import Gallery, LoadTask, ORIENT, SORTS, ThumbnailManager, _setting_int, scan_assets

from viewer import ABOUT, APP_NAME, Viewer


# ---------------------------------------------------------------------------
# About dialog (all wording lives in the ABOUT dictionary at the top of viewer.py)
# ---------------------------------------------------------------------------
def about_html() -> str:
    a, esc = ABOUT, html.escape
    items = "".join(
        f"<li><b>{esc(n)}</b> &mdash; {esc(lic)}"
        + (f' <span style="color:#7c8794">({esc(url)})</span>' if url else "") + "</li>"
        for n, lic, url in a["third_party"])
    licence = esc(a["licence_text"].format(copyright=a["copyright"]))
    h = "color:#6aa8e8; margin:14px 0 4px 0;"
    return (f'<h4 style="{h}">{esc(a["legal_heading"])}</h4>'
            f'<p>{esc(a["copyright"])}</p><p>{esc(a["legal_notice"])}</p>'
            f'<h4 style="{h}">{esc(a["licence_heading"])}</h4>'
            f'<p>{esc(a["licence_intro"])}</p>'
            f'<pre style="white-space:pre-wrap; font-size:11px; color:#aeb8c4;">{licence}</pre>'
            f'<h4 style="{h}">{esc(a["third_party_heading"])}</h4>'
            f'<p>{esc(a["third_party_intro"])}</p><ul>{items}</ul>'
            f'<p style="color:#7c8794;">{esc(a["third_party_note"])}</p>')


class AboutDialog(QDialog):
    """Closes with the title-bar X, the ✕ button, the Close button, or Esc."""

    def __init__(self, parent=None):
        super().__init__(parent)
        a, esc = ABOUT, html.escape
        self.setWindowTitle(f"About {a['app_name']}")
        self.setModal(True)
        self.setMinimumSize(540, 580)
        root = QVBoxLayout(self)
        root.setSpacing(10)
        head = QHBoxLayout()
        title = QLabel(a["app_name"] + (f"  {a['version']}" if a.get("version") else ""))
        title.setObjectName("aboutTitle")
        head.addWidget(title, 1)
        x = QToolButton()
        x.setText("✕")
        x.setToolTip("Close (Esc)")
        x.setObjectName("aboutClose")
        x.clicked.connect(self.close)
        head.addWidget(x)
        root.addLayout(head)
        tag = QLabel(a["tagline"])
        tag.setObjectName("aboutTagline")
        tag.setWordWrap(True)
        root.addWidget(tag)

        heading = QLabel(a["author_heading"])
        heading.setObjectName("aboutHeading")
        root.addWidget(heading)
        who = QLabel(f"<span style='font-size:15px'><b>{esc(a['author_name'])}</b>"
                     f" &nbsp;/&nbsp; {esc(a['author_alias'])}</span>"
                     + (f"<br><span style='color:#8d99a8'>{esc(a['author_note'])}</span>"
                        if a.get("author_note") else ""))
        who.setTextFormat(Qt.RichText)
        who.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(who)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(about_html())
        root.addWidget(browser, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton(a["close_label"])
        close.setDefault(True)
        close.clicked.connect(self.close)
        row.addWidget(close)
        root.addLayout(row)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
DARK_QSS = """
* { font-family: 'Segoe UI', 'Inter', 'Ubuntu', sans-serif; }
QMainWindow, QWidget { background:#14181e; color:#d5dbe3; }
QTreeView, QListWidget { background:#14181e; border:none; outline:0; }
QTreeView::item { padding:3px 0; }
QTreeView::item:selected, QListWidget::item:selected { background:#27486b; color:#fff; border-radius:6px; }
QTreeView::item:hover, QListWidget::item:hover { background:#1f2630; border-radius:6px; }
QListWidget::item { color:#c3cad4; padding:4px; }
QSplitter::handle { background:#0e1116; width:2px; }
QScrollBar:vertical { background:#0b0e12; width:16px; margin:0; border-left:1px solid #1c232c; }
QScrollBar::handle:vertical { background:#6f86a3; border-radius:6px; margin:2px 3px; min-height:48px; }
QScrollBar::handle:vertical:hover { background:#8fa8c6; }
QScrollBar::handle:vertical:pressed { background:#6aa8e8; }
QScrollBar:horizontal { background:#0b0e12; height:16px; margin:0; border-top:1px solid #1c232c; }
QScrollBar::handle:horizontal { background:#6f86a3; border-radius:6px; margin:3px 2px; min-width:48px; }
QScrollBar::handle:horizontal:hover { background:#8fa8c6; }
QScrollBar::handle:horizontal:pressed { background:#6aa8e8; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; background:none; border:none; }
QScrollBar::add-page, QScrollBar::sub-page { background:none; }
QAbstractScrollArea::corner { background:#0b0e12; }
QToolTip { background:#1b2028; color:#e0e6ed; border:1px solid #3a4656; }
#hud { background:#1b2028; border:1px solid #2f3947; border-radius:10px; }
#hudTitle { color:#8d99a8; font-size:11px; padding:0 8px; background:transparent; }
#hud QToolButton { background:#252d38; border:none; border-radius:6px; padding:4px 9px; color:#d5dbe3; }
#hud QToolButton:hover { background:#34506f; }
#hud QToolButton:checked { background:#3d6fa5; color:#fff; }
#hud QToolButton::menu-indicator { image:none; }
#hudClose { color:#9aa5b2; } #hudClose:hover { background:#8e2a2a !important; color:#fff; }
QMenu { background:#1b2028; border:1px solid #2f3947; color:#d5dbe3; padding:4px; }
QMenu::item { padding:5px 24px 5px 12px; border-radius:4px; }
QMenu::item:selected { background:#34506f; }
QMenu::separator { height:1px; background:#2f3947; margin:4px 8px; }
#galleryBar { background:#10141a; border-bottom:1px solid #0b0e12; }
QLineEdit, QComboBox { background:#1b2028; border:1px solid #2f3947; border-radius:6px; padding:4px 8px; color:#d5dbe3; }
QLineEdit:focus, QComboBox:focus { border-color:#3d6fa5; }
QLineEdit#addressBar[bad="true"] { border-color:#c0504d; color:#f0b4b2; }
QToolButton#upBtn { background:#1b2028; border:1px solid #2f3947; border-radius:6px; padding:3px 6px; }
QToolButton#upBtn:hover { background:#252d38; }
QComboBox QAbstractItemView { background:#1b2028; selection-background-color:#34506f; border:1px solid #2f3947; }
QSlider::groove:horizontal { height:4px; background:#2c3542; border-radius:2px; }
QSlider::handle:horizontal { width:12px; margin:-5px 0; background:#6aa8e8; border-radius:6px; }
#barLabel { color:#7c8794; background:transparent; }
#drawerBtn { background:#10141a; border:none; border-left:1px solid #1c232c; color:#aeb8c4; }
#drawerBtn:hover { background:#27486b; }
QDockWidget { color:#d5dbe3; }
QDockWidget::title { background:#10141a; padding:6px 8px; border-bottom:1px solid #1c232c; }
QMainWindow::separator { background:#0e1116; width:4px; height:4px; }
QMainWindow::separator:hover { background:#34506f; }
QTabBar::tab { background:#1b2028; color:#aeb8c4; padding:6px 12px; border:1px solid #2f3947; border-bottom:none; border-top-left-radius:6px; border-top-right-radius:6px; margin-right:2px; }
QTabBar::tab:selected { background:#27486b; color:#ffffff; }
QTabBar::tab:hover:!selected { background:#252d38; }
QTabWidget::pane { border:1px solid #2f3947; border-radius:4px; top:-1px; }
QScrollArea { background:#14181e; border:none; }
QMenuBar { background:#10141a; color:#d5dbe3; }
QMenuBar::item { padding:4px 10px; background:transparent; }
QMenuBar::item:selected { background:#34506f; border-radius:4px; }
QTextBrowser { background:#10141a; border:1px solid #2f3947; border-radius:6px; padding:8px; color:#d5dbe3; }
#aboutTitle { color:#e6ebf1; font-size:22px; font-weight:700; background:transparent; }
#aboutTagline { color:#8d99a8; background:transparent; }
#aboutHeading { color:#6aa8e8; font-weight:600; font-size:12px; background:transparent; }
#aboutClose { background:transparent; border:none; color:#9aa5b2; font-size:14px; padding:4px 9px; }
#aboutClose:hover { background:#8e2a2a; color:#fff; border-radius:6px; }
#infoTitle { color:#e6ebf1; font-weight:600; background:transparent; }
#infoKey { color:#7c8794; font-size:11px; background:transparent; }
#infoVal { color:#d5dbe3; font-size:11px; background:transparent; }
QPushButton { background:#252d38; border:1px solid #2f3947; border-radius:6px; padding:5px 12px; color:#d5dbe3; }
QPushButton:hover { background:#34506f; }
QPushButton:disabled { color:#5c6672; background:#1b2028; }
QDialog { background:#14181e; }
QCheckBox { color:#d5dbe3; spacing:6px; }
QCheckBox::indicator { width:14px; height:14px; border:1px solid #3a4656; border-radius:3px; background:#1b2028; }
QCheckBox::indicator:checked { background:#3d6fa5; }
"""


class PanelDock(QDockWidget):
    """A dock for one side panel. Tells us when the user closes it with its own title-bar button
    (hiding it from code does not count)."""
    closed = Signal(str)

    def __init__(self, key: str, title: str, parent=None):
        super().__init__(title, parent)
        self.key = key

    def closeEvent(self, e):
        self.closed.emit(self.key)
        super().closeEvent(e)


class TabDragOut(QObject):
    """Lets a panel be torn off by dragging its TAB out of the tab strip (Qt only does this itself
    with 'grouped dragging', which we keep off because it merges overlapping floating panels).
    Reordering tabs inside the strip is left entirely to Qt."""
    MARGIN = 36                                      # px beyond the tab strip before we tear off

    def __init__(self, window):
        super().__init__(window)
        self.win = window
        self.bar = None
        self.start = None
        self.text = ""
        self.done = False

    def _is_panel_bar(self, obj) -> bool:
        return (isinstance(obj, QTabBar) and obj.metaObject().className() == "QMainWindowTabBar"
                and obj.window() is self.win)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t not in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease):
            return False
        if not self._is_panel_bar(obj):
            return False
        try:
            if t == QEvent.Type.MouseButtonPress:
                self.done = False
                self.bar = None
                if ev.button() == Qt.MouseButton.LeftButton:
                    i = obj.tabAt(ev.position().toPoint())
                    if i >= 0:
                        self.bar, self.start, self.text = obj, ev.position().toPoint(), obj.tabText(i)
                return False
            if t == QEvent.Type.MouseButtonRelease:
                swallow = self.done
                self.bar = None
                self.done = False
                return swallow
            # mouse move
            if self.done:
                return True
            if self.bar is obj and (ev.buttons() & Qt.MouseButton.LeftButton):
                zone = obj.rect().adjusted(-self.MARGIN, -self.MARGIN, self.MARGIN, self.MARGIN)
                if not zone.contains(ev.position().toPoint()):
                    self.done = True
                    text = self.text
                    QTimer.singleShot(0, lambda: self._tear_off(obj, text))
                    return True
        except RuntimeError:
            pass
        return False

    def _tear_off(self, bar, text):
        """Runs after the current event, because floating the panel can delete the tab strip."""
        from PySide6.QtGui import QCursor, QMouseEvent
        dock = next((d for d in self.win.docks.values() if d.windowTitle().replace("&", "") == text.replace("&", "")), None)
        if dock is None or dock.isFloating():
            return
        try:
            pos = bar.mapFromGlobal(QCursor.pos())
            QApplication.sendEvent(bar, QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(pos),
                                   Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        except RuntimeError:
            pass
        w, h = max(dock.width(), 340), max(dock.height(), 480)
        dock.setFloating(True)
        c = QCursor.pos()
        dock.setGeometry(c.x() - w // 2, c.y() - 14, w, h)      # title bar under the pointer
        dock.show()
        dock.raise_()
        dock.activateWindow()
        h_ = dock.windowHandle()
        if h_ is not None:
            try:
                h_.startSystemMove()                 # keep dragging the new window with the mouse
            except Exception:
                pass


class FavouriteDelegate(QStyledItemDelegate):
    """Paints a small yellow star over the icon of favourite folders in the tree (the model itself is untouched)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.favs: set = set()

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if not self.favs or index.column() != 0:
            return
        model = index.model()
        path = model.filePath(index) if hasattr(model, "filePath") else ""
        if not path or os.path.normcase(os.path.normpath(path)) not in self.favs:
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = option.widget.style() if option.widget else QApplication.style()
        icon = style.subElementRect(QStyle.SE_ItemViewItemDecoration, opt, option.widget)
        painter.save()
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        f = QFont(painter.font())
        f.setPixelSize(12)
        f.setBold(True)
        painter.setFont(f)
        box = QRectF(icon.right() - 9, icon.bottom() - 11, 13, 13)
        painter.setPen(QColor(0, 0, 0, 200))
        painter.drawText(box.translated(0.7, 0.7), Qt.AlignCenter, "★")
        painter.setPen(QColor("#ffd23f"))
        painter.drawText(box, Qt.AlignCenter, "★")
        painter.restore()


class MainWindow(QMainWindow):
    def __init__(self, start: str | None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 820)
        self.settings = QSettings("Gleek3Deek", "Gleek3Deek")
        self.pool = QThreadPool.globalInstance()
        self.token = 0
        self.current_path = ""
        self._tasks: dict[int, LoadTask] = {}
        # tags, colour labels and ratings: one JSON file next to the program (never inside a model file)
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        fallback = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation) or str(Path.home())
        self.library = Library(resolve_library_path(str(base), fallback,
                                                    str(self.settings.value("library_path", "") or "")))
        self._virtual_query = ""
        if self.library.notice or self.library.error:
            QTimer.singleShot(0, lambda: self.statusBar().showMessage(self.library.notice or self.library.error, 15000))

        # ---- left: file tree
        self.fs = QFileSystemModel()
        self.fs.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)
        self.fs.setNameFilters([f"*{e}" for e in sorted(ALL_EXTS)])
        self.fs.setNameFilterDisables(False)  # hide non-3D files
        self.fs.setRootPath("")
        self.tree = QTreeView()
        self.tree.setModel(self.fs)
        self.fav_delegate = FavouriteDelegate(self.tree)
        self.tree.setItemDelegate(self.fav_delegate)
        self.tree.setRootIndex(self.fs.index(""))
        for c in (1, 2, 3):
            self.tree.hideColumn(c)
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAnimated(False)
        self.tree.selectionModel().currentChanged.connect(self._tree_changed)
        self.tree.doubleClicked.connect(self._tree_double)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.fav_label = QLabel("★ Favourites")
        self.fav_label.setObjectName("barLabel")
        self.fav_list = QListWidget()
        self.fav_list.setObjectName("favList")
        self.fav_list.setMaximumHeight(132)
        self.fav_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.fav_list.itemClicked.connect(lambda it: self._open_folder_entry(it.data(Qt.UserRole)))
        self.fav_list.customContextMenuRequested.connect(self._fav_list_menu)
        self.left_panel = QWidget()
        lp = QVBoxLayout(self.left_panel)
        lp.setContentsMargins(0, 0, 0, 0)
        lp.setSpacing(2)
        lp.addWidget(self.fav_label)
        lp.addWidget(self.fav_list)
        lp.addWidget(self.tree, 1)

        # ---- right: gallery page (toolbar + grid) and viewer, stacked
        self.gallery = Gallery()
        self.gallery.open_asset.connect(self.open_asset)
        self.gallery.open_folder.connect(self.goto_folder)
        self.gallery.rename_requested.connect(self._rename_file)
        self.gallery.copy_requested.connect(self._copy_file)
        self.gallery.paste_requested.connect(self._paste_files)
        self.gallery.delete_requested.connect(self._delete_file)
        self.gallery.refresh_thumb_requested.connect(self._refresh_thumbnail)
        self.gallery.refresh_all_requested.connect(self._refresh_all_thumbnails)
        self.gallery.set_library(self.library)
        self.gallery.tags_requested.connect(self._edit_tags)
        self.gallery.metadata_changed.connect(self._library_saved)
        self.thumbs = ThumbnailManager()
        self.thumbs.ready.connect(self.gallery.set_thumb)

        self.gallery_page = QWidget()
        gl = QVBoxLayout(self.gallery_page)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(0)
        bar = QFrame()
        bar.setObjectName("galleryBar")
        bl = QVBoxLayout(bar)                  # two rows: the address bar on top, the tools below it
        bl.setContentsMargins(10, 6, 10, 6)
        bl.setSpacing(6)
        row1, row2 = QHBoxLayout(), QHBoxLayout()
        row1.setSpacing(8)
        row2.setSpacing(8)
        bl.addLayout(row1)
        bl.addLayout(row2)
        self.up_btn = QToolButton()
        self.up_btn.setObjectName("upBtn")
        self.up_btn.setArrowType(Qt.ArrowType.UpArrow)
        self.up_btn.setToolTip("Go to the parent folder  (Alt+Up)")
        self.up_btn.clicked.connect(self._go_up)
        self.address = QLineEdit()
        self.address.setObjectName("addressBar")
        self.address.setPlaceholderText("Type a folder path and press Enter…")
        self.address.setClearButtonEnabled(True)
        self.address.setToolTip("Type or paste a folder path and press Enter  (Alt+D to jump here)")
        self.address.returnPressed.connect(self._address_entered)
        self.address.textEdited.connect(lambda _t: self._address_error(False))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…  tag:rock  rating:>=4  color:red")
        self.search.setToolTip("Words match the file name or its tags.\n"
                               "tag:name   -tag:name   color:red   rating:4   rating:>=3\n"
                               "Use quotes for several words: tag:\"hard surface\"")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(480)
        self.library_btn = QToolButton()
        self.library_btn.setText("Library ▾")
        self.library_btn.setToolTip("Tags, colour labels, ratings and smart folders")
        self.library_btn.setPopupMode(QToolButton.InstantPopup)
        self.library_menu = QMenu(self.library_btn)
        self.library_menu.aboutToShow.connect(self._build_library_menu)
        self.library_btn.setMenu(self.library_menu)
        self.search.textChanged.connect(self.gallery.set_filter)
        self.sort_box = QComboBox()
        self.sort_box.addItems([s[0] for s in SORTS])
        self.sort_box.setCurrentIndex(min(_setting_int(self.settings, "sort_idx", 0), len(SORTS) - 1))
        self.gallery.set_sort(self.sort_box.currentIndex())
        self.sort_box.currentIndexChanged.connect(self._sort_changed)
        self.count_label = QLabel("")
        self.count_label.setObjectName("barLabel")
        self.gallery.counts.connect(self._counts_changed)
        size_label = QLabel("Size")
        size_label.setObjectName("barLabel")
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(64, 192)
        self.size_slider.setFixedWidth(120)
        self.size_slider.setToolTip("Card size")
        card = _setting_int(self.settings, "card_px", 88)
        self.size_slider.setValue(max(64, min(card, 192)))
        self.gallery.set_card_size(self.size_slider.value())
        self.size_slider.valueChanged.connect(self._size_changed)
        row1.addWidget(self.up_btn)
        row1.addWidget(self.address, 1)
        row2.addWidget(self.search, 1)
        row2.addWidget(self.sort_box)
        row2.addSpacing(30)                    # room between the sort box and Library
        row2.addWidget(self.library_btn)
        row2.addStretch(1)
        row2.addWidget(self.count_label)
        row2.addWidget(size_label)
        row2.addWidget(self.size_slider)
        gl.addWidget(bar)
        gl.addWidget(self.gallery)

        self.viewer = Viewer()
        self.viewer.closed.connect(self.close_viewer)
        self.viewer.step.connect(self._step)
        self.viewer.message.connect(lambda m: self.statusBar().showMessage(m, 6000))
        self.viewer.orientation_changed.connect(self.thumbs.refresh)
        self.viewer.about_requested.connect(self.show_about)
        self.viewer.panel_requested.connect(self._show_panel)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.gallery_page)
        self.stack.addWidget(self.viewer)

        split = QSplitter()
        split.addWidget(self.left_panel)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 1060])
        split.setChildrenCollapsible(False)
        holder = QWidget()                           # workspace + a slim edge button that stays visible
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        hl.addWidget(split, 1)
        self.drawer_btn = QToolButton()
        self.drawer_btn.setObjectName("drawerBtn")
        self.drawer_btn.setArrowType(Qt.ArrowType.RightArrow)
        self.drawer_btn.setFixedWidth(18)
        self.drawer_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.drawer_btn.clicked.connect(self._toggle_drawer)
        hl.addWidget(self.drawer_btn)
        self.setCentralWidget(holder)

        # ---- viewer hotkeys: only enabled while the viewer is showing, so the
        #      tree and gallery keep normal keyboard navigation (arrows, type-ahead)
        v = self.viewer
        bindings = [
            ("W", lambda: v.set_mode("wire")), ("P", lambda: v.set_mode("points")),
            ("S", lambda: v.set_mode("surface")), ("M", v.cycle_matcap),
            ("R", v.reset_camera), ("O", v.toggle_orbit), ("B", v.cycle_background),
            ("A", v.act_axes.toggle), ("C", v.act_ortho.toggle), ("U", v.toggle_up_axis),
            ("T", v.toggle_transparency),
            ("F12", v.save_screenshot), ("Shift+F12", v.open_reference_sheet_dialog), ("Ctrl+C", v.copy_screenshot),
            ("Left", lambda: self._step(-1)), ("Right", lambda: self._step(1)),
            ("E", v.open_matcap_editor),
            ("L", v.toggle_environment), ("Shift+L", v.open_environment_panel),
            ("Ctrl+L", v.cycle_lighting_preset),
            ("I", v.toggle_info),
            ("G", v.toggle_grid), ("F", v.fit_view), ("H", v.toggle_turntable),
            ("V", v.cycle_view_channel), ("D", v.toggle_split), ("Shift+D", v.cycle_split_style), ("Shift+U", v.toggle_uv_view), ("Shift+M", v.open_materials_panel), ("Shift+R", v.toggle_measure_mode),
            ("Shift+W", v.toggle_edges), ("Shift+G", v.open_scene_panel),
            ("Esc", self.close_viewer),
        ]
        for i, key in enumerate(("front", "back", "right", "left", "top", "bottom", "iso"), 1):
            bindings.append((str(i), lambda k=key: v.set_view(k)))
        for n in (1, 2, 3):                        # saved camera views
            bindings.append((f"Ctrl+Shift+{n}", lambda n=n: v.save_bookmark(n)))
            bindings.append((f"Alt+{n}", lambda n=n: v.go_bookmark(n)))
        QShortcut(QKeySequence("Alt+D"), self, activated=self._focus_address)
        QShortcut(QKeySequence("Alt+Up"), self, activated=self._go_up)
        self._viewer_shortcuts = [QShortcut(QKeySequence(k), self, activated=fn)
                                  for k, fn in bindings]
        self._build_docks()
        self._build_menus()
        self._sync_shortcuts()

        self.statusBar().setStyleSheet("color:#7c8794;")
        self._restore(start)
        self._drawer_animate_ok = True               # animate from now on, not while starting up

    # ----- toolbar slots
    def _sort_changed(self, idx: int):
        self.settings.setValue("sort_idx", idx)
        self.gallery.set_sort(idx)

    def _size_changed(self, px: int):
        self.settings.setValue("card_px", px)
        self.gallery.set_card_size(px)

    def _counts_changed(self, shown: int, total: int):
        self.count_label.setText(f"{total} models" if shown == total else f"{shown} of {total} models")

    def _build_menus(self):
        """A real menu bar so everything is reachable by mouse, keyboard and screen readers."""
        mb = self.menuBar()
        fm = mb.addMenu("&File")
        act = fm.addAction("Open folder…")
        act.setShortcut(QKeySequence("Ctrl+O"))
        act.triggered.connect(self._choose_folder)
        self.act_export = fm.addAction("Export / convert…")
        self.act_export.setShortcut(QKeySequence("Ctrl+E"))
        self.act_export.triggered.connect(self.viewer.open_export_dialog)
        self.act_export.setEnabled(False)
        fm.addSeparator()
        quit_act = fm.addAction("Quit")
        quit_act.setShortcut(QKeySequence("Ctrl+Q"))
        quit_act.triggered.connect(self.close)
        gm = mb.addMenu("&Go")
        self.go_menu = gm
        gm.addAction("Parent folder\tAlt+Up", self._go_up)
        self.fav_menu = gm.addMenu("&Favourites")
        self.fav_menu.aboutToShow.connect(self._build_fav_menu)
        self.recent_menu = gm.addMenu("&Recent folders")
        self.recent_menu.aboutToShow.connect(self._build_recent_menu)
        self._refresh_favourites()
        pm = mb.addMenu("&Panels")
        self.act_drawer = QAction("Show/Hide Panel", pm, checkable=True)
        self.act_drawer.setShortcut(QKeySequence("Ctrl+B"))
        self.act_drawer.triggered.connect(self._set_drawer_pref)
        pm.addAction(self.act_drawer)
        pm.addSeparator()
        self._panel_actions = {}
        for key, title, _factory in self.DOCK_SPECS:       # same left-to-right order as the tabs
            act = QAction(title, pm, checkable=True)
            act.triggered.connect(lambda checked, k=key: self._set_panel_open(k, checked))
            pm.addAction(act)
            self._panel_actions[key] = act
        pm.addSeparator()
        reset = pm.addAction("Reset panel layout")
        reset.triggered.connect(self._reset_layout)
        hm = mb.addMenu("&Help")
        about = hm.addAction("About " + ABOUT["app_name"])
        about.setShortcut(QKeySequence("F1"))
        about.triggered.connect(self.show_about)

    def show_about(self):
        AboutDialog(self).exec()

    # ----- dockable panels: right edge only, one collapsible drawer -----------------
    # Native QDockWidget does the tabbing and vertical stacking. Panels may only dock on the right.
    # The whole right-hand group slides in and out as a "drawer" (YouTube-style), driven by the
    # edge button, the Panels menu or Ctrl+B, and it collapses automatically in the gallery.
    DOCK_STATE_VERSION = 3                           # bumped: older layouts allowed other edges / grouped floating windows
    DOCK_SPECS = [("materials", "Materials", "materials_panel"),
                  ("matcap", "MatCap", "matcap_editor"),
                  ("environment", "Environment", "environment_panel"),
                  ("scene", "Scene", "scene_panel")]
    DRAWER_DEFAULT_WIDTH = 380

    def _make_dock(self, key: str, title: str, panel) -> "PanelDock":
        scroll = QScrollArea()                       # scrolls cleanly when the dock is short or narrow
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(panel)
        scroll.setMinimumSize(280, 220)              # a panel can never be squeezed to nothing
        dock = PanelDock(key, title, self)
        dock.setObjectName(f"dock_{key}")            # required for saveState / restoreState
        dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)      # right edge only
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable
                         | QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable)   # can float; re-docks right only
        dock.setWidget(scroll)
        dock.closed.connect(self._on_dock_closed)
        return dock

    def _group_docks(self):
        """Default arrangement: one tabbed group on the right, in DOCK_SPECS order, left to right."""
        for dock in self.docks.values():
            if self._docks_added and dock.isFloating():
                dock.setFloating(False)              # bring floating panels home first
            if self.dockWidgetArea(dock) != Qt.DockWidgetArea.NoDockWidgetArea:
                self.removeDockWidget(dock)          # forgets any old stacking or tab order
        first = None
        for key, _title, _factory in self.DOCK_SPECS:
            dock = self.docks[key]
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
            if first is None:
                first = dock
            else:
                self.tabifyDockWidget(first, dock)
            dock.hide()
        self._docks_added = True

    def _build_docks(self):
        # No GroupedDragging: with it Qt merges floating panels that are dropped on top of each other
        # into nested group windows, which shrank/minimised them and broke the drawer bookkeeping.
        # Without it each floating panel stays an independent window with normal OS stacking.
        self.setDockOptions(QMainWindow.DockOption.AllowTabbedDocks
                            | QMainWindow.DockOption.AnimatedDocks)
        self.setTabPosition(Qt.DockWidgetArea.RightDockWidgetArea, QTabWidget.TabPosition.North)
        self.docks = {key: self._make_dock(key, title, getattr(self.viewer, factory)())
                      for key, title, factory in self.DOCK_SPECS}
        valid = [k for k, _t, _f in self.DOCK_SPECS]
        saved = [k for k in str(self.settings.value("open_docks", "")).split(",") if k in valid]
        self._open_keys = set(saved) or set(valid)           # first run: all four tabs
        cur = str(self.settings.value("current_dock", valid[0]))
        self._current_key = cur if cur in valid else valid[0]
        self._drawer_pref = str(self.settings.value("drawer_expanded", "true")).lower() in ("1", "true")
        self._drawer_width = max(280, _setting_int(self.settings, "drawer_width", self.DRAWER_DEFAULT_WIDTH))
        self._drawer_open = None                              # unknown until the first _apply_drawer
        self._drawer_busy = False
        self._drawer_anim = None
        self._drawer_animate_ok = False
        self._docks_added = False
        self._group_docks()
        geo = self.settings.value("window_geometry")
        if geo:
            self.restoreGeometry(geo if isinstance(geo, QByteArray) else QByteArray(geo))
        state = self.settings.value("dock_state")
        if state:
            self.restoreState(state if isinstance(state, QByteArray) else QByteArray(state),
                              self.DOCK_STATE_VERSION)
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._save_layout)
        for dock in self.docks.values():
            dock.visibilityChanged.connect(self._layout_changed)
            dock.dockLocationChanged.connect(self._layout_changed)
            dock.topLevelChanged.connect(lambda floating, k=dock.key: self._on_float_changed(k, floating))
        self.tabifiedDockWidgetActivated.connect(self._on_tab_activated)
        self._tab_dragout = TabDragOut(self)
        QApplication.instance().installEventFilter(self._tab_dragout)

    # -- bookkeeping: which panels the user has open is kept here, not read back from Qt, so
    #    collapsing the drawer (which hides every dock) never forgets the arrangement.
    def _on_tab_activated(self, dock):
        if not self._drawer_busy and isinstance(dock, PanelDock):
            self._current_key = dock.key
            self._layout_changed()

    def _on_dock_closed(self, key: str):
        """The user pressed the dock's own close button."""
        if self._drawer_busy:
            return
        self._open_keys.discard(key)
        if key == self._current_key and self._open_keys:
            self._current_key = next(k for k, _t, _f in self.DOCK_SPECS if k in self._open_keys)
        if not self._open_keys:
            self._set_drawer_pref(False)             # nothing left open: collapse the drawer
        else:
            self._update_drawer_ui()
        self._layout_changed()

    def _on_float_changed(self, key: str, floating: bool):
        """A panel was dragged out into its own window, or dropped back onto the right edge."""
        if self._drawer_busy:
            return
        self._open_keys.add(key)
        # Qt is still in the middle of its own drag when this fires: change nothing about the layout
        # now, only after the event loop has settled.
        QTimer.singleShot(0, lambda k=key, f=floating: self._after_float_changed(k, f))

    def _after_float_changed(self, key: str, floating: bool):
        try:
            dock = self.docks.get(key)
            if dock is None or dock.isFloating() != floating:
                return                               # stale: the panel moved again meanwhile
            if floating:
                dock.raise_()                        # new window comes to the front
            else:
                self._current_key = key
                if not self._drawer_open:
                    self._set_drawer_pref(True)      # dropped onto an empty edge: bring the drawer back
            self._update_drawer_ui()
            self._layout_changed()
        except RuntimeError:
            pass

    def _sync_floating(self):
        """Floating panels follow the viewer: shown with an open model, put away in the gallery."""
        want = self._in_viewer()
        self._drawer_busy = True
        try:
            for key, dock in self.docks.items():
                if dock.isFloating():
                    dock.setVisible(want and key in self._open_keys)
        finally:
            self._drawer_busy = False

    def _in_viewer(self) -> bool:
        return self.stack.currentWidget() is self.viewer

    def _set_docks_visible(self, on: bool):
        """Show or hide the DOCKED panels. Floating panels are their own windows and are left alone."""
        self._drawer_busy = True
        try:
            for key, dock in self.docks.items():
                if dock.isFloating():
                    continue
                if on and key in self._open_keys:
                    dock.show()
                else:
                    dock.hide()
            cur = self.docks[self._current_key]
            if on and self._current_key in self._open_keys and not cur.isFloating():
                cur.raise_()                                     # selects its tab
        finally:
            self._drawer_busy = False

    def _apply_drawer(self, animate: bool = True):
        """Bring the drawer in line with what is wanted: open in the viewer if the user wants it,
        always closed in the gallery."""
        target = self._drawer_pref and self._in_viewer()
        if self._drawer_open is None:                # first call at start-up: no animation
            self._set_docks_visible(target)
            self._drawer_open = target
        elif target != self._drawer_open:
            (self._expand_drawer if target else self._collapse_drawer)(animate)
        self._sync_floating()
        self._update_drawer_ui()

    def _stop_drawer_anim(self):
        if self._drawer_anim is not None:
            try:
                self._drawer_anim.finished.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._drawer_anim.stop()
            self._drawer_anim = None

    def _animate_drawer(self, dock, w0: int, w1: int, done=None):
        """Slide the right-hand column between two widths. The workspace resizes with it."""
        self._stop_drawer_anim()
        anim = QVariantAnimation(self)
        anim.setDuration(180)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(int(w0))
        anim.setEndValue(int(w1))
        anim.valueChanged.connect(lambda v: self.resizeDocks([dock], [int(v)], Qt.Orientation.Horizontal))
        if done is not None:
            anim.finished.connect(done)
        self._drawer_anim = anim
        anim.start()

    def _expand_drawer(self, animate: bool):
        self._stop_drawer_anim()
        if not self._open_keys:
            self._open_keys.add(self.DOCK_SPECS[0][0])
        docked = [k for k, _t, _f in self.DOCK_SPECS if k in self._open_keys and not self.docks[k].isFloating()]
        self._set_docks_visible(True)
        self._drawer_open = True
        if not docked:                               # every open panel is floating: nothing to slide
            return
        lead = self.docks[self._current_key if self._current_key in docked else docked[0]]
        start_w = lead.width() if not lead.isHidden() else 40
        if animate:
            self._animate_drawer(lead, start_w, self._drawer_width)
        else:
            self.resizeDocks([lead], [self._drawer_width], Qt.Orientation.Horizontal)

    def _collapse_drawer(self, animate: bool):
        self._stop_drawer_anim()
        shown = [d for d in self.docks.values() if not d.isHidden() and not d.isFloating()]
        if shown:
            self._drawer_width = max(280, max(d.width() for d in shown))   # remember for next time
        self._drawer_open = False
        if animate and shown:
            self._animate_drawer(shown[0], shown[0].width(), 0, lambda: self._set_docks_visible(False))
        else:
            self._set_docks_visible(False)

    def _update_drawer_ui(self):
        in_viewer = self._in_viewer()
        opened = bool(self._drawer_open)
        self.drawer_btn.setVisible(in_viewer)                 # no panel to bring back in the gallery
        self.drawer_btn.setArrowType(Qt.ArrowType.RightArrow if opened else Qt.ArrowType.LeftArrow)
        self.drawer_btn.setToolTip(("Hide side panel" if opened else "Show side panel") + "  (Ctrl+B)")
        for act, checked in [(self.act_drawer, opened)] + [(a, k in self._open_keys)
                                                           for k, a in self._panel_actions.items()]:
            act.blockSignals(True)
            act.setChecked(checked)
            act.blockSignals(False)
            act.setEnabled(in_viewer)

    def _set_drawer_pref(self, on: bool):
        self._drawer_pref = bool(on)
        self.settings.setValue("drawer_expanded", "true" if on else "false")
        self._apply_drawer(True)
        self._layout_changed()

    def _toggle_drawer(self):
        if self._in_viewer():
            self._set_drawer_pref(not bool(self._drawer_open))

    def _set_panel_open(self, key: str, on: bool):
        dock = self.docks.get(key)
        if dock is None:
            return
        if on:
            self._open_keys.add(key)
            self._current_key = key
            if self._drawer_open:
                self._drawer_busy = True
                dock.show()
                dock.raise_()
                self._drawer_busy = False
            self._set_drawer_pref(True)
        else:
            self._open_keys.discard(key)
            self._drawer_busy = True
            dock.hide()
            self._drawer_busy = False
            if not self._open_keys:
                self._set_drawer_pref(False)
        self._update_drawer_ui()
        self._layout_changed()

    def _show_panel(self, key: str):
        """A panel's own key or button was used: make sure it is open and in front."""
        self._set_panel_open(key, True)

    def _layout_changed(self, *_):
        self._layout_timer.start(600)

    def _save_layout(self):
        shown = [d for d in self.docks.values() if not d.isHidden() and not d.isFloating()]
        if shown and self._drawer_open:
            self._drawer_width = max(280, max(d.width() for d in shown))
        s = self.settings
        s.setValue("dock_state", self.saveState(self.DOCK_STATE_VERSION))
        s.setValue("window_geometry", self.saveGeometry())
        s.setValue("open_docks", ",".join(k for k, _t, _f in self.DOCK_SPECS if k in self._open_keys))
        s.setValue("current_dock", self._current_key)
        s.setValue("drawer_expanded", "true" if self._drawer_pref else "false")
        s.setValue("drawer_width", int(self._drawer_width))

    def _reset_layout(self):
        """Back to the default: Materials, MatCap, Environment, Scene as tabs on the right."""
        self._stop_drawer_anim()
        self._group_docks()
        self._open_keys = {k for k, _t, _f in self.DOCK_SPECS}
        self._current_key = self.DOCK_SPECS[0][0]
        self._drawer_width = self.DRAWER_DEFAULT_WIDTH
        self._drawer_pref = True
        self.settings.remove("dock_state")
        self.settings.setValue("drawer_expanded", "true")
        self._drawer_open = None                     # re-evaluate from scratch, without animation
        self._apply_drawer(False)
        self._layout_changed()
        self.statusBar().showMessage("Panel layout reset", 6000)

    # ----- file operations from the gallery (rename / copy / paste / delete) --------
    @staticmethod
    def _split_name(name: str):
        ext = asset_ext(name)
        return (name[:-len(ext)] if ext else name), ext

    def _refresh_gallery(self, select: str = ""):
        if self.gallery.virtual:
            self._show_query(self._virtual_query, self.gallery.virtual, select=select)
            return
        folder = self.gallery.folder
        if not folder:
            return
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.thumbs.request_batch(self.gallery.populate(folder))
        if select:
            self.gallery.select_path(select)

    def _rename_file(self, path: str):
        folder, old = os.path.split(path)
        base, ext = self._split_name(old)
        label = f"New name (the {ext} ending is kept):" if ext else "New name:"
        new_base, ok = QInputDialog.getText(self, "Rename", label, QLineEdit.Normal, base)
        new_base = new_base.strip()
        if not ok or not new_base or new_base == base:
            return
        if new_base in (".", "..") or any(c in new_base for c in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Rename", 'A file name can\'t contain any of:  \\ / : * ? " < > |')
            return
        dst = os.path.join(folder, new_base + ext)
        if os.path.exists(dst) and os.path.normcase(dst) != os.path.normcase(path):
            QMessageBox.warning(self, "Rename", f"A file called “{new_base + ext}” already exists here.")
            return
        old_cache = self.thumbs._cache_file(path)      # remember the thumbnail before the name changes
        try:
            os.rename(path, dst)
        except OSError as e:
            QMessageBox.warning(self, "Rename", f"Could not rename the file.\n\n{e}")
            return
        self.library.rename(path, dst)                 # keep its tags, colour and rating
        ORIENT.set(dst, ORIENT.get(path))              # keep its Y-up / Z-up choice
        ORIENT.set(path, "Y")
        self.thumbs.adopt(old_cache, dst)              # the renamed file keeps its thumbnail
        if self.current_path == path:
            self.current_path = dst
        self._refresh_gallery(select=dst)
        self.statusBar().showMessage(f"Renamed to {new_base + ext}", 6000)

    def _copy_file(self, path: str):
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(path)])         # lets Explorer/Finder paste it too
        md.setText(path)
        QApplication.clipboard().setMimeData(md)
        self.statusBar().showMessage(f"Copied {os.path.basename(path)}", 6000)

    @staticmethod
    def _unique_path(folder: str, name: str) -> str:
        cand = os.path.join(folder, name)
        if not os.path.exists(cand):
            return cand
        base, ext = MainWindow._split_name(name)
        n = 1
        while os.path.exists(cand):
            cand = os.path.join(folder, f"{base} - Copy" + (f" ({n})" if n > 1 else "") + ext)
            n += 1
        return cand

    def _paste_files(self):
        folder = self.gallery.folder
        md = QApplication.clipboard().mimeData()
        srcs = [u.toLocalFile() for u in md.urls() if u.isLocalFile()] if md is not None and md.hasUrls() else []
        files = [p for p in srcs if os.path.isfile(p)]
        if not folder or not files:
            self.statusBar().showMessage("Nothing to paste: copy a file first", 6000)
            return
        last, done, errors = "", 0, []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for src in files:
                dst = self._unique_path(folder, os.path.basename(src))
                old_cache = self.thumbs._cache_file(src)
                try:
                    shutil.copy2(src, dst)
                    self.thumbs.adopt(old_cache, dst)  # a pasted copy starts with the same thumbnail
                    last, done = dst, done + 1
                except OSError as e:
                    errors.append(f"{os.path.basename(src)}: {e}")
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh_gallery(select=last)
        self.statusBar().showMessage(f"Pasted {done} file{'s' if done != 1 else ''}", 6000)
        if errors:
            QMessageBox.warning(self, "Paste", "Some files could not be copied:\n\n" + "\n".join(errors[:8]))

    def _refresh_thumbnail(self, path: str):
        self.gallery.clear_thumb(path)
        self.thumbs.refresh(path, force=True)
        self.statusBar().showMessage(f"Refreshing the thumbnail for {os.path.basename(path)}…", 6000)

    def _refresh_all_thumbnails(self):
        paths = self.gallery.file_paths()
        for p in paths:
            self.thumbs.forget(p)
        self._refresh_gallery()
        self.statusBar().showMessage(f"Refreshing {len(paths)} thumbnails…", 6000)

    def _delete_file(self, path: str):
        name = os.path.basename(path)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Delete")
        box.setText(f"Move “{name}” to the Recycle Bin / Trash?")
        extra = {".obj": "Its .mtl material file and texture images are not deleted.",
                 ".gltf": "Its .bin and texture files are not deleted."}.get(asset_ext(name))
        if extra:
            box.setInformativeText(extra)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec() != QMessageBox.Yes:
            return
        res = QFile.moveToTrash(path)
        if not (res[0] if isinstance(res, tuple) else bool(res)):
            answer = QMessageBox.question(
                self, "Delete", f"“{name}” could not be moved to the Recycle Bin / Trash.\n\n"
                                "Delete it permanently instead?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            try:
                os.remove(path)
            except OSError as e:
                QMessageBox.warning(self, "Delete", f"Could not delete the file.\n\n{e}")
                return
        if self.current_path == path:
            self.current_path = ""
        self.library.remove(path)
        self._refresh_gallery()
        self.statusBar().showMessage(f"Deleted {name}", 6000)

    # ----- library: tags, colour labels, ratings, smart folders ----------------------------------
    def _library_saved(self):
        if self.library.error:
            self.statusBar().showMessage(self.library.error, 10000)

    def _edit_tags(self, paths: list):
        lib = self.library
        sets = [{t.lower() for t in lib.get(p)["tags"]} for p in paths]
        common = set.intersection(*sets) if sets else set()
        shared = [t for t in lib.get(paths[0])["tags"] if t.lower() in common]
        dlg = TagsDialog(self, len(paths), shared, lib.all_tags())
        if dlg.exec() != QDialog.Accepted:
            return
        typed = split_tags(",".join(dlg.tags()))
        typed_l = {t.lower() for t in typed}
        removed = [t for t in shared if t.lower() not in typed_l]
        added = [t for t in typed if t.lower() not in common]
        if lib.change_tags(paths, removed, added):
            self.gallery._rebuild()
            self.statusBar().showMessage(f"Tags updated for {len(paths)} file{'s' if len(paths) != 1 else ''}", 6000)
        self._library_saved()

    def _show_query(self, query: str, title: str, select: str = ""):
        """A smart-folder view: every library file that matches the saved search, from any folder."""
        self._virtual_query = query
        paths = self.library.find(query)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.thumbs.request_batch(self.gallery.populate_paths(paths, title))
        self.address.setText("")
        self.address.setPlaceholderText(f"Smart folder: {title}   ({query})")
        self._address_error(False)
        if select:
            self.gallery.select_path(select)
        if self.stack.currentWidget() is self.viewer:
            self.close_viewer()
        self.statusBar().showMessage(f"{title}: {len(paths)} file{'s' if len(paths) != 1 else ''}", 8000)

    def _leave_smart(self, folder: str = ""):
        folder = folder or str(self.settings.value("last_dir", str(Path.home())))
        self.address.setPlaceholderText("Type a folder path and press Enter…")
        self.address.setText(os.path.normpath(folder))
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.thumbs.request_batch(self.gallery.populate(folder))

    def _build_library_menu(self):
        m, lib = self.library_menu, self.library
        m.clear()
        if self.gallery.virtual:
            m.addAction("← Back to the folder view", lambda: self._leave_smart(self._current_folder()))
            m.addSeparator()
        text = self.search.text().strip()
        save = m.addAction("Save this search as a smart folder…", self._save_smart)
        save.setEnabled(not query_is_empty(parse_query(text)))
        if lib.smart:
            m.addSeparator()
            for name, query in lib.smart.items():
                m.addAction(f"★ {name}", lambda _=False, n=name, q=query: self._show_query(q, n))
            dm = m.addMenu("Delete a smart folder")
            for name in lib.smart:
                dm.addAction(name, lambda _=False, n=name: self._delete_smart(n))
        m.addSeparator()
        tm = m.addMenu("Browse by tag")
        tags = lib.all_tags()
        for t, n in tags[:60]:
            tm.addAction(f"{t}  ({n})", lambda _=False, t=t: self._show_query(f'tag:"{t}"', f"Tag: {t}"))
        tm.setEnabled(bool(tags))
        cm = m.addMenu("Browse by colour")
        for k, label, _hex in COLORS:
            cm.addAction(label, lambda _=False, k=k, lb=label: self._show_query(f"color:{k}", f"{lb} label"))
        rm = m.addMenu("Browse by rating")
        for n in (5, 4, 3, 2, 1):
            rm.addAction("★" * n + ("  and up" if n < 5 else ""),
                         lambda _=False, n=n: self._show_query(f"rating:>={n}", f"{n}★" + (" and up" if n < 5 else "")))
        m.addSeparator()
        m.addAction("Library file…", self._library_location)

    def _save_smart(self):
        query = self.search.text().strip()
        if query_is_empty(parse_query(query)):
            return
        name, ok = QInputDialog.getText(self, "Smart folder", f"Name for the search “{query}”:",
                                        QLineEdit.Normal, query[:40])
        if ok and name.strip():
            if self.library.save_smart(name, query):
                self.statusBar().showMessage(f"Saved smart folder “{name.strip()}”", 6000)
            self._library_saved()

    def _delete_smart(self, name: str):
        self.library.delete_smart(name)
        self._library_saved()
        self.statusBar().showMessage(f"Deleted smart folder “{name}”", 6000)

    def _library_location(self):
        box = QMessageBox(self)
        box.setWindowTitle("Library file")
        box.setText("Tags, colour labels, ratings and smart folders are stored in this file:")
        box.setInformativeText(f"{self.library.path}\n\nNothing is ever written into your model files. "
                               "A backup copy (.bak) is kept next to it. Back up or move this file to keep your data.")
        choose = box.addButton("Choose another location…", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is not choose:
            return
        new, _ = QFileDialog.getSaveFileName(self, "Library file", self.library.path, "Library (*.json)",
                                             options=QFileDialog.DontConfirmOverwrite)
        if not new:
            return
        if not new.lower().endswith(".json"):
            new += ".json"
        old = self.library.path
        if self.library.move_to(new):
            self.settings.setValue("library_path", new)
            self._refresh_favourites()
            self.gallery._rebuild()
            self.statusBar().showMessage(f"Library file: {new}", 8000)
        else:
            self.library.move_to(old)
            QMessageBox.warning(self, "Library file", self.library.error or "That location could not be used.")

    def _choose_folder(self):
        start = str(self.settings.value("last_dir", str(Path.home())))
        d = QFileDialog.getExistingDirectory(self, "Open folder", start)
        if d:
            self.goto_folder(d)

    def _sync_shortcuts(self):
        on = self.stack.currentWidget() is self.viewer
        self.act_export.setEnabled(on)
        for sc in self._viewer_shortcuts:
            sc.setEnabled(on)
        self._apply_drawer(self._drawer_animate_ok)      # closes in the gallery, reopens in the viewer

    # ----- helpers
    def _restore(self, start: str | None):
        target = start or self.settings.value("last_dir", str(Path.home()))
        if os.path.isfile(target):
            folder, file = os.path.dirname(target), target
        else:
            folder, file = target, None
        if not os.path.isdir(folder):
            folder = str(Path.home())
        self.goto_folder(folder)
        if file:
            self.open_asset(file)

    # ----- address bar
    def _address_error(self, bad: bool):
        self.address.setProperty("bad", bool(bad))
        self.address.style().unpolish(self.address)
        self.address.style().polish(self.address)

    def _current_folder(self) -> str:
        return str(self.settings.value("last_dir", str(Path.home())))

    def _address_entered(self):
        raw = self.address.text().strip().strip('"').strip("'")
        if not raw:
            self.address.setText(self._current_folder())
            self._address_error(False)
            return
        path = os.path.normpath(os.path.expandvars(os.path.expanduser(raw)))
        if os.path.isfile(path):
            self._address_error(False)
            self.goto_folder(os.path.dirname(path))
            self.open_asset(path)
        elif os.path.isdir(path):
            self._address_error(False)
            self.goto_folder(path)
            self.gallery.setFocus()
        else:
            self._address_error(True)
            self.statusBar().showMessage(f"Folder not found: {raw}", 6000)

    def _focus_address(self):
        if self.stack.currentWidget() is self.viewer:
            self.close_viewer()
        self.address.setFocus()
        self.address.selectAll()

    def _go_up(self):
        cur = self._current_folder()
        parent = os.path.dirname(os.path.normpath(cur))
        if parent and parent != cur and os.path.isdir(parent):
            self.goto_folder(parent)

    def goto_folder(self, folder: str):
        self.address.setText(os.path.normpath(folder))
        self._address_error(False)
        idx = self.fs.index(folder)
        if self.gallery.virtual:                       # leave a smart-folder view even if the tree row is unchanged
            self._leave_smart(folder)
        self.tree.setCurrentIndex(idx)   # triggers _tree_changed -> gallery
        self.tree.scrollTo(idx, QAbstractItemView.PositionAtCenter)
        self.tree.expand(idx)

    def _tree_changed(self, cur, _prev):
        path = self.fs.filePath(cur)
        if os.path.isdir(path):
            self.settings.setValue("last_dir", path)
            self._note_recent(path)
            self.address.setText(os.path.normpath(path))
            self.address.setPlaceholderText("Type a folder path and press Enter…")
            self._address_error(False)
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.thumbs.request_batch(self.gallery.populate(path))
            self.statusBar().showMessage(path)
            if self.stack.currentWidget() is self.viewer:
                self.close_viewer()

    # ----- favourite and recent folders -----------------------------------------------------------
    def _recent_list(self) -> list:
        v = self.settings.value("recent_folders", [])
        if isinstance(v, str):
            v = [v] if v else []
        return [str(p) for p in (v or [])]

    def _note_recent(self, path: str):
        self.settings.setValue("recent_folders", push_recent(self._recent_list(), path))

    def _open_folder_entry(self, path: str):
        """Open a favourite or recent folder; one that is gone (an unplugged drive, say) gets a message."""
        if os.path.isdir(path):
            self.goto_folder(path)
        else:
            self.statusBar().showMessage(f"Folder not found: {path}  (is the drive connected?)", 8000)

    def _refresh_favourites(self):
        favs = self.library.fav_paths()
        self.fav_delegate.favs = {os.path.normcase(os.path.normpath(p)) for p in favs}
        self.tree.viewport().update()
        self.fav_list.clear()
        for p in favs:
            it = QListWidgetItem("★ " + (os.path.basename(p.rstrip("\\/")) or p))
            it.setData(Qt.UserRole, p)
            it.setToolTip(p)
            if not os.path.isdir(p):
                it.setForeground(QColor("#6b7480"))
                it.setToolTip(p + "\n(not found right now)")
            self.fav_list.addItem(it)
        self.fav_label.setVisible(bool(favs))
        self.fav_list.setVisible(bool(favs))             # no empty box when there are no favourites

    def _add_favourite(self, folder: str):
        if not folder or not os.path.isdir(folder):
            return
        r = self.library.add_fav(folder)
        if r == "full":
            self.statusBar().showMessage("Favourites are full (20). Remove one first.", 6000)
        elif r == "added":
            self.statusBar().showMessage(f"Added to favourites: {folder}", 5000)
        self._refresh_favourites()
        self._library_saved()

    def _remove_favourite(self, folder: str):
        if self.library.remove_fav(folder):
            self.statusBar().showMessage("Removed from favourites (the folder itself is untouched)", 5000)
        self._refresh_favourites()
        self._library_saved()

    def _tree_menu(self, pos):
        idx = self.tree.indexAt(pos)
        path = self.fs.filePath(idx) if idx.isValid() else ""
        if not path or not os.path.isdir(path):
            return
        menu = QMenu(self)
        if self.library.is_fav(path):
            menu.addAction("Remove from favourites", lambda: self._remove_favourite(path))
        else:
            menu.addAction("Add to favourites", lambda: self._add_favourite(path))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _fav_list_menu(self, pos):
        it = self.fav_list.itemAt(pos)
        if it is None:
            return
        path = it.data(Qt.UserRole)
        menu = QMenu(self)
        menu.addAction("Remove from favourites", lambda: self._remove_favourite(path))
        menu.exec(self.fav_list.viewport().mapToGlobal(pos))

    def _build_fav_menu(self):
        m = self.fav_menu
        m.clear()
        here = self._current_folder()
        if self.library.is_fav(here):
            m.addAction("Remove this folder from favourites", lambda: self._remove_favourite(here))
        else:
            m.addAction("Add this folder to favourites", lambda: self._add_favourite(here))
        favs = self.library.fav_paths()
        if favs:
            m.addSeparator()
            for p in favs:
                label = (os.path.basename(p.rstrip("\\/")) or p) + ("" if os.path.isdir(p) else "  (not found)")
                a = m.addAction("★ " + label, lambda _=False, p=p: self._open_folder_entry(p))
                a.setToolTip(p)
                a.setEnabled(os.path.isdir(p))
            rm = m.addMenu("Remove a favourite")
            for p in favs:
                rm.addAction(p, lambda _=False, p=p: self._remove_favourite(p))

    def _build_recent_menu(self):
        m = self.recent_menu
        m.clear()
        items = self._recent_list()
        for p in items:
            a = m.addAction(p, lambda _=False, p=p: self._open_folder_entry(p))
            a.setEnabled(os.path.isdir(p))
        if not items:
            m.addAction("(none yet)").setEnabled(False)
        else:
            m.addSeparator()
            m.addAction("Clear this list", lambda: self.settings.setValue("recent_folders", []))

    def _tree_double(self, idx):
        path = self.fs.filePath(idx)
        if os.path.isfile(path):
            self.open_asset(path)

    # ----- open / close / step
    def open_asset(self, path: str):
        self.token += 1
        self.current_path = path
        name = os.path.basename(path)
        self.stack.setCurrentWidget(self.viewer)
        self._sync_shortcuts()
        self.viewer.show_loading(name)
        self.setWindowTitle(f"{name} — {APP_NAME}")
        task = LoadTask(self.token, path)
        task.signals.done.connect(self._on_loaded)
        task.signals.failed.connect(self._on_failed)
        self._tasks[self.token] = task   # keep signal QObject alive until delivered
        self.pool.start(task)

    def _step(self, delta: int):
        """Open the previous/next model in the folder (as sorted/filtered in the gallery)."""
        if self.stack.currentWidget() is not self.viewer:
            return
        paths = self.gallery.asset_paths()
        cur_dir = os.path.dirname(self.current_path)
        if self.current_path not in paths:
            paths = scan_assets(cur_dir) if cur_dir else []
        if not paths:
            return
        if self.current_path in paths:
            nxt = paths[(paths.index(self.current_path) + delta) % len(paths)]
        else:
            nxt = paths[0] if delta > 0 else paths[-1]
        self.open_asset(nxt)
        self.gallery.select_path(nxt)

    def _on_loaded(self, token: int, actors, path: str):
        self._tasks.pop(token, None)
        if token != self.token or self.stack.currentWidget() is not self.viewer:
            return
        try:
            self.viewer.show_model(actors, os.path.basename(path), path)
        except Exception as e:
            self.viewer.show_error(f"Render failed:\n{e}")

    def _on_failed(self, token: int, msg: str):
        self._tasks.pop(token, None)
        if token == self.token and self.stack.currentWidget() is self.viewer:
            self.viewer.show_error(msg)

    def close_viewer(self):
        self.token += 1                  # invalidate in-flight loads
        self.viewer.clear_scene()
        self.stack.setCurrentWidget(self.gallery_page)
        self._sync_shortcuts()
        self.setWindowTitle(APP_NAME)
        self.gallery.setFocus()
        if self.current_path:
            self.gallery.select_path(self.current_path)

    def closeEvent(self, e):
        self._save_layout()
        self.thumbs.shutdown()
        self.viewer.shutdown()
        super().closeEvent(e)


def _install_crash_handler():
    """The packaged exe has no console, so surface unexpected errors in a dialog + log file."""
    from PySide6.QtWidgets import QMessageBox
    log = os.path.join(tempfile.gettempdir(), "gleek3deek_crash.log")

    def hook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        try:
            with open(log, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass
        try:
            QMessageBox.critical(None, APP_NAME,
                                 f"Unexpected error:\n\n{value}\n\nDetails were saved to:\n{log}")
        except Exception:
            pass

    sys.excepthook = hook


def main():
    if any(a.startswith("-") and not a.startswith("-psn") for a in sys.argv[1:]):
        from cli import run                       # any option selects the read-only command-line mode
        sys.exit(run(sys.argv[1:]))
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    _install_crash_handler()
    app.setStyleSheet(DARK_QSS)
    start = sys.argv[1] if len(sys.argv) > 1 else None
    win = MainWindow(start)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
