"""Distinct row focus and explicit cart selection."""
from PySide6.QtCore import Qt, QItemSelectionModel
from PySide6.QtWidgets import QTableWidget, QCheckBox


class ToggleRowTable(QTableWidget):
    doubleClickChecks = False
    folderColumn = -1
    def mousePressEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        self._row_was_selected = index.isValid() and self.selectionModel().isRowSelected(index.row(), index.parent())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if not index.isValid() or event.button() != Qt.LeftButton:
            return super().mouseDoubleClickEvent(event)
        if index.column() == self.folderColumn:
            self.cellDoubleClicked.emit(index.row(), index.column())
            event.accept()
            return
        check = self.cellWidget(index.row(), 0)
        if self.doubleClickChecks and isinstance(check, QCheckBox):
            check.setChecked(not check.isChecked())
            selected = check.isChecked()
        else:
            selected = not getattr(self, '_row_was_selected', False)
        self.selectionModel().select(index, (QItemSelectionModel.ClearAndSelect if selected else QItemSelectionModel.Deselect) | QItemSelectionModel.Rows)
        event.accept()
