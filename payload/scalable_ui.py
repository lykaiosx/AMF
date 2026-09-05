"""Layouts and cart rendering that do not allocate a widget for every torrent."""
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QRect, QSize
from PySide6.QtWidgets import QLayout, QComboBox, QStyledItemDelegate, QStyle


def bounded_results(pool, function, items, progress, width=8):
    from concurrent.futures import wait, FIRST_COMPLETED
    from PySide6.QtWidgets import QApplication
    remaining = iter(items)
    pending = set()
    def fill():
        while len(pending) < width:
            item = next(remaining, None)
            if item is None: break
            pending.add(pool.submit(function, item))
    fill()
    while pending:
        QApplication.processEvents()
        if progress.wasCanceled():
            for future in pending: future.cancel()
            return
        done, _ = wait(pending, timeout=.05, return_when=FIRST_COMPLETED)
        for future in done:
            pending.remove(future)
            yield future
        fill()

DESTINATIONS = ['Games', 'Movie', 'Series', 'Anime Movie', 'Anime Series', 'Music', 'Books']


class FlowLayout(QLayout):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(8)

    def addItem(self, item): self.items.append(item)
    def count(self): return len(self.items)
    def itemAt(self, i): return self.items[i] if 0 <= i < len(self.items) else None
    def takeAt(self, i): return self.items.pop(i) if 0 <= i < len(self.items) else None
    def addStretch(self, *args): pass
    def addSpacing(self, *args): pass
    def expandingDirections(self): return Qt.Orientations(Qt.Orientation(0))
    def hasHeightForWidth(self): return True
    def heightForWidth(self, width): return self.arrange(QRect(0, 0, width, 0), True)
    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect, False)
    def sizeHint(self): return self.minimumSize()
    def minimumSize(self):
        size = QSize()
        for item in self.items: size = size.expandedTo(item.minimumSize())
        return size
    def arrange(self, rect, test):
        x, y, height = rect.x(), rect.y(), 0
        for item in self.items:
            if item.isEmpty(): continue
            size = item.sizeHint()
            if x > rect.x() and x + size.width() > rect.right() + 1:
                x, y, height = rect.x(), y + height + self.spacing(), 0
            if not test: item.setGeometry(QRect(x, y, min(size.width(), rect.width()), size.height()))
            x += size.width() + self.spacing()
            height = max(height, size.height())
        return y + height - rect.y()


class CartModel(QAbstractTableModel):
    headers = ['Title', 'Source', 'Release Scope', 'Destination', 'Resolution',
               'Language', 'Size', 'Seeds', 'Status', 'Save Location', 'Link']
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.rows = []
    def reset_rows(self, rows):
        self.beginResetModel()
        self.rows = list(rows)  # stable row count while the cart is edited
        self.endResetModel()
    def rowCount(self, parent=QModelIndex()): return 0 if parent.isValid() else len(self.rows)
    def columnCount(self, parent=QModelIndex()): return 0 if parent.isValid() else len(self.headers)
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return self.headers[section] if orientation == Qt.Horizontal else section + 1
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows): return None
        item, col = self.rows[index.row()], index.column()
        if role == Qt.ToolTipRole:
            if col == 8: return item.get('last_error', '')
            if col == 9: return 'Double-click to choose a custom folder.'
            if col == 3: return 'Double-click to change destination.'
        if role not in (Qt.DisplayRole, Qt.EditRole, Qt.ToolTipRole): return None
        keys = ['title', 'source', 'scope', 'type', 'resolution', 'language', 'size', 'seeders', 'cart_status', 'save_path', 'link']
        value = item.get(keys[col])
        if col == 2: value = value or item.get('kind')
        if col == 8: value = value or 'Ready'
        if col == 9:
            value = self.owner.effective_item_save_path(item)
            if item.get('save_path_custom'): value += ' • custom'
        if col == 10: value = value or item.get('local_torrent_path')
        return str(value) if value is not None else 'Unknown'
    def flags(self, index):
        flags = super().flags(index)
        return flags | Qt.ItemIsEditable if index.column() == 3 else flags
    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or index.column() != 3 or value not in DESTINATIONS: return False
        self.owner.cart_destination_changed(index.row(), value)
        self.dataChanged.emit(self.index(index.row(), 3), self.index(index.row(), 9))
        return True


class DestinationDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        editor = QComboBox(parent)
        editor.addItems(DESTINATIONS)
        return editor
    def setEditorData(self, editor, index): editor.setCurrentText(index.data(Qt.EditRole))
    def setModelData(self, editor, model, index): model.setData(index, editor.currentText())
