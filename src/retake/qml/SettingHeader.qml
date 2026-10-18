import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    property alias text: label.text
    Layout.fillWidth: true
    Layout.topMargin: 8
    spacing: 4

    Label {
        id: label
        font.pixelSize: 12
        font.bold: true
        font.capitalization: Font.AllUppercase
        font.letterSpacing: 0.8
        color: theme.accent
    }
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: 1
        color: Qt.rgba(1, 1, 1, 0.08)
    }
}
