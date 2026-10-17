import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    modal: true
    anchors.centerIn: parent
    padding: 20
    topPadding: 12

    background: Rectangle {
        color: theme.surface
        radius: 14
        border.color: Qt.rgba(1, 1, 1, 0.08)
    }

    header: Label {
        text: dialog.title
        font.pixelSize: 20
        font.bold: true
        padding: 20
        bottomPadding: 4
        background: null
    }

    footer: DialogButtonBox {
        standardButtons: dialog.standardButtons
        background: null
        onAccepted: dialog.accept()
        onRejected: dialog.reject()
    }

    Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.55) }
}
