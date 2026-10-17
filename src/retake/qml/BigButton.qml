import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

AbstractButton {
    id: button
    property string title
    property string detail
    property string hint
    Layout.fillWidth: true
    implicitHeight: 110
    hoverEnabled: true

    background: Rectangle {
        radius: 10
        color: button.hovered ? Qt.lighter(theme.surface, 1.25) : theme.surface
        border.color: button.hovered ? theme.accent : "transparent"
        border.width: 1
    }
    contentItem: ColumnLayout {
        spacing: 6
        Label { text: button.title; font.pixelSize: 19; font.bold: true; Layout.leftMargin: 16; Layout.topMargin: 12 }
        Label { text: button.detail; opacity: 0.65; Layout.leftMargin: 16; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Item { Layout.fillHeight: true }
        Label { text: button.hint; opacity: 0.4; font.pixelSize: 12; Layout.leftMargin: 16; Layout.bottomMargin: 10 }
    }
}
