import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: panel
    property string title
    default property alias content: body.data
    radius: 8
    color: theme.surface

    Label {
        id: heading
        text: panel.title
        font.pixelSize: 12
        font.capitalization: Font.AllUppercase
        font.letterSpacing: 1.2
        opacity: 0.5
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: 10
    }
    Item {
        id: body
        anchors.fill: parent
        anchors.topMargin: panel.title ? 30 : 8
        anchors.margins: 8
        clip: true
    }
}
