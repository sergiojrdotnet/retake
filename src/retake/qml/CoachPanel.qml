import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Flickable {
    id: panel
    property var coach: app.coach
    property var flagged: coach.flagged || []
    property var deviations: coach.deviations || []
    contentHeight: content.implicitHeight
    clip: true

    ColumnLayout {
        id: content
        width: panel.width
        spacing: 12

        Label {
            visible: app.review.queue !== undefined
            text: app.review.queue ? qsTr("Pickups: %1 of %2").arg(app.review.index + 1).arg(app.review.queue.length) : ""
            color: theme.accent
            font.bold: true
        }
        Label {
            visible: panel.flagged.length === 0 && panel.deviations.length === 0
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            opacity: 0.55
            text: app.engines.scorer && app.engines.scorer.engine === "wav2vec2"
                  ? qsTr("Words that need another try show up here after each sentence.")
                  : qsTr("Pronunciation scoring is off (install PyTorch and the wav2vec2 model). Skipped or changed words still show up here.")
        }

        Repeater {
            model: panel.flagged
            delegate: Rectangle {
                required property var modelData
                Layout.fillWidth: true
                implicitHeight: entry.implicitHeight + 20
                radius: 8
                color: Qt.lighter(theme.surface, 1.2)
                ColumnLayout {
                    id: entry
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 4
                    RowLayout {
                        Label { text: modelData.text; font.pixelSize: 24; font.bold: true }
                        Label { text: Math.round(modelData.score); color: modelData.score < 35 ? theme.red : theme.yellow; font.pixelSize: 13 }
                        Item { Layout.fillWidth: true }
                        Button { text: qsTr("Listen"); onClicked: app.listenTo(modelData.text) }
                        Button { text: qsTr("Don't coach"); flat: true; onClicked: app.setCoached(modelData.text, false) }
                    }
                    Label { visible: !!modelData.respell; text: modelData.respell || ""; color: theme.accent; font.pixelSize: 17 }
                    Label { visible: !!modelData.native; text: modelData.native || ""; color: theme.yellow; font.pixelSize: 15 }
                    Label {
                        text: qsTr("expected %1  ·  heard /%2/").arg(modelData.ipa || ("/" + modelData.expected + "/")).arg(modelData.heard)
                        font.pixelSize: 12
                        opacity: 0.6
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                    }
                    Repeater {
                        model: modelData.patterns || []
                        delegate: Label {
                            required property var modelData
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            font.pixelSize: 13
                            text: "• " + modelData.title + ": " + modelData.description
                            opacity: 0.85
                        }
                    }
                }
            }
        }

        Repeater {
            model: panel.deviations
            delegate: Label {
                required property var modelData
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: modelData.kind === "skipped" ? qsTr("Skipped “%1”").arg(modelData.text) : qsTr("Said “%1” instead of “%2”").arg(modelData.heard).arg(modelData.text)
                color: theme.yellow
            }
        }

        Label {
            visible: panel.flagged.length > 0 || panel.deviations.length > 0
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            opacity: 0.6
            font.pixelSize: 13
            text: qsTr("Say “%1, again” or press R to read it again.").arg(app.settings.voice.wake_word || "retake")
        }
    }
}
