import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// The takes of the sentence under the playhead (or the one selected): the one in use, and the others
// to switch to. Rejected takes come last; the coach rejects a whole take for one word.
Rectangle {
    id: panel
    property int sentence: -1
    property var choices: ({})
    signal chosen(int take)
    color: theme.surface
    radius: 6

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8

        Label {
            text: panel.sentence >= 0 ? qsTr("Sentence %1").arg(panel.sentence + 1) : qsTr("Takes")
            font.bold: true
            font.pixelSize: 15
        }
        Label {
            visible: text !== ""
            text: panel.sentence >= 0 ? (panel.choices.text || "") : qsTr("Click a sentence on the timeline to see its takes")
            wrapMode: Text.Wrap
            maximumLineCount: 4
            elide: Text.ElideRight
            font.pixelSize: 12
            opacity: 0.65
            Layout.fillWidth: true
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 2
            model: panel.choices.takes || []
            delegate: ItemDelegate {
                id: row
                required property var modelData
                width: list.width
                highlighted: modelData.inUse
                onClicked: panel.chosen(modelData.take)
                ToolTip.visible: hovered && modelData.text !== ""
                ToolTip.text: modelData.text + (modelData.stale ? "\n" + qsTr("Recorded before the sentence was reworded") : "")
                contentItem: RowLayout {
                    spacing: 10
                    Label {
                        text: row.modelData.inUse ? "●" : "○"
                        color: row.modelData.inUse ? theme.accent : theme.foreground
                        opacity: row.modelData.inUse ? 1 : 0.5
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Label { text: qsTr("Take %1").arg(row.modelData.number); font.bold: row.modelData.inUse }
                            Label {
                                visible: row.modelData.score >= 0
                                text: row.modelData.score
                                color: row.modelData.score < (app.settings.coach.threshold || 0) ? theme.yellow : theme.foreground
                                opacity: 0.85
                            }
                            Label { visible: row.modelData.flagged > 0; text: "⚑" + row.modelData.flagged; color: theme.red }
                            Label { visible: row.modelData.stale; text: "⟳"; opacity: 0.7 }
                            Item { Layout.fillWidth: true }
                            Label { text: qsTr("%1 s").arg(row.modelData.duration.toFixed(1)); font.pixelSize: 12; opacity: 0.55 }
                        }
                        Label {
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                            font.pixelSize: 11
                            color: row.modelData.status === "rejected" ? theme.red : theme.foreground
                            opacity: row.modelData.status === "rejected" ? 0.85 : 0.55
                            text: row.modelData.status === "rejected"
                                  ? [row.modelData.recorded, qsTr("rejected") + (row.modelData.reason ? ": " + row.modelData.reason : "")].filter(s => s).join("  ·  ")
                                  : row.modelData.recorded
                        }
                    }
                }
            }
        }

        Label {
            visible: list.count > 1
            text: qsTr("Click a take to use it and hear it · T / Shift+T steps through them")
            wrapMode: Text.Wrap
            font.pixelSize: 11
            opacity: 0.45
            Layout.fillWidth: true
        }
    }
}
