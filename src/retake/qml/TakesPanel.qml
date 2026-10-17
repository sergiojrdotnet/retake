import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ListView {
    id: list
    model: app.takesModel
    clip: true
    spacing: 4
    onCountChanged: Qt.callLater(() => list.positionViewAtEnd())

    delegate: Rectangle {
        required property int id
        required property int sentence
        required property int number
        required property string status
        required property string reason
        required property int score
        required property var flagged
        required property string text
        width: list.width
        height: 34
        radius: 6
        color: Qt.lighter(theme.surface, 1.15)
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            spacing: 10
            Rectangle {
                width: 8; height: 8; radius: 4
                color: status === "complete" ? theme.green : status === "rejected" ? theme.red : theme.yellow
            }
            Label { text: sentence >= 0 ? qsTr("S%1 · T%2").arg(sentence + 1).arg(number) : qsTr("#%1").arg(id); font.family: "monospace"; font.pixelSize: 13 }
            Label { text: reason; opacity: 0.55; font.pixelSize: 12; visible: reason !== "" }
            Label { Layout.fillWidth: true; text: parent.parent.text; elide: Text.ElideRight; opacity: 0.6; font.pixelSize: 12 }
            Label { visible: score >= 0; text: score; color: score < 55 ? theme.yellow : theme.green; font.pixelSize: 12 }
        }
    }
}
