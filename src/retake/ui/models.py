from __future__ import annotations

from PySide6.QtCore import Property, QAbstractListModel, QByteArray, QModelIndex, Qt, Signal, Slot


class DictListModel(QAbstractListModel):
    countChanged = Signal()

    def __init__(self, roles: list[str], parent=None):
        super().__init__(parent)
        self._roles = roles
        self._role_ids = {Qt.UserRole + 1 + i: name for i, name in enumerate(roles)}
        self._items: list[dict] = []

    def roleNames(self):
        return {role: QByteArray(name.encode()) for role, name in self._role_ids.items()}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        name = self._role_ids.get(role)
        return self._items[index.row()].get(name) if name else None

    def set_items(self, items: list[dict]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()
        self.countChanged.emit()

    def update(self, row: int, values: dict) -> None:
        if 0 <= row < len(self._items):
            self._items[row].update(values)
            index = self.index(row, 0)
            self.dataChanged.emit(index, index)

    def append(self, item: dict) -> None:
        self.beginInsertRows(QModelIndex(), len(self._items), len(self._items))
        self._items.append(item)
        self.endInsertRows()
        self.countChanged.emit()

    def items(self) -> list[dict]:
        return self._items

    @Slot(int, result="QVariant")
    def get(self, row: int):
        return self._items[row] if 0 <= row < len(self._items) else None

    def _count(self):
        return len(self._items)

    count = Property(int, _count, notify=countChanged)
