import QtQuick
import QtQuick.Controls

Rectangle {
    id: panel
    radius: 8
    color: theme.surface
    property real fontSize: Math.max(18, app.settings.prompter.font_size * 0.6)

    ListView {
        id: list
        anchors.fill: parent
        anchors.margins: 18
        model: app.transcriptModel
        spacing: 12
        clip: true
        footer: Label {
            width: list.width
            text: app.partial
            visible: app.partial !== ""
            font.pixelSize: panel.fontSize
            font.italic: true
            opacity: 0.6
            wrapMode: Text.Wrap
            topPadding: 12
        }
        delegate: Label {
            required property var model
            width: list.width
            text: model.text
            wrapMode: Text.Wrap
            font.pixelSize: panel.fontSize
            font.strikeout: model.status === "rejected"
            opacity: model.status === "rejected" ? 0.35 : 1
            color: theme.foreground
        }
        onCountChanged: Qt.callLater(() => list.positionViewAtEnd())
    }

    Label {
        anchors.centerIn: parent
        visible: list.count === 0 && app.partial === ""
        text: app.recording ? qsTr("Listening…") : qsTr("Free session: just talk. Say “%1, again” or press R to redo the last sentence.").arg(app.settings.voice.wake_word || "retake")
        opacity: 0.55
        wrapMode: Text.Wrap
        width: parent.width * 0.8
        horizontalAlignment: Text.AlignHCenter
    }
}
