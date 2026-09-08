"""Shared popup geometry and read-only cell painting."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QListView, QStyledItemDelegate, QStyle, QStyleOptionViewItem

class PlainCellDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        option = QStyleOptionViewItem(option)
        option.state &= ~QStyle.State_HasFocus
        super().paint(painter, option, index)

class ChoiceBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        view = QListView(self)
        view.setObjectName('choicePopup')
        view.setSpacing(0)
        view.setItemDelegate(PlainCellDelegate(view))
        self.setView(view)
    def showPopup(self):
        width = max((self.fontMetrics().horizontalAdvance(self.itemText(i)) for i in range(self.count())), default=0) + 40
        self.view().setMinimumWidth(max(self.width(), width))
        super().showPopup()
