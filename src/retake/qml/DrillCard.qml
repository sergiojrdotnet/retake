import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: card
    property var drill: app.drill
    property var voice: app.voiceCommands

    function spoken(action) {
        const phrases = voice.enabled && voice.actions ? voice.actions[action] || [] : []
        return phrases.length ? qsTr("or say “%1, %2”").arg(voice.wake).arg(phrases[0]) : ""
    }
    visible: drill.active === true
    width: Math.min(parent ? parent.width - 40 : 640, 680)
    implicitHeight: content.implicitHeight + 28
    radius: 10
    color: Qt.lighter(theme.surface, 1.15)
    border.color: theme.red
    border.width: 2

    ColumnLayout {
        id: content
        anchors.fill: parent
        anchors.margins: 14
        spacing: 8

        RowLayout {
            spacing: 14
            Label { text: card.drill.text || ""; font.pixelSize: 32; font.bold: true; color: theme.red }
            Label { visible: !!card.drill.ipa; text: card.drill.ipa || ""; font.pixelSize: 18; color: theme.accent }
            Label { visible: !!card.drill.respell; text: card.drill.respell || ""; font.pixelSize: 18; color: theme.accent }
            Label { visible: !!card.drill.native; text: card.drill.native || ""; font.pixelSize: 16; color: theme.yellow }
            Item { Layout.fillWidth: true }
            Label {
                visible: (card.drill.remaining || 0) > 0
                text: qsTr("+%1 more").arg(card.drill.remaining || 0)
                opacity: 0.6
            }
        }

        Repeater {
            model: card.drill.patterns || []
            delegate: Label {
                required property var modelData
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: qsTr("Typical: %1").arg(modelData.title)
                opacity: 0.8
            }
        }

        RowLayout {
            spacing: 10
            Label { text: qsTr("Say it %1 times in a row").arg(card.drill.times || 0); font.pixelSize: 16 }
            Repeater {
                model: card.drill.times || 0
                delegate: Label {
                    required property int index
                    text: index < (card.drill.passes || 0) ? "✓" : "○"
                    color: index < (card.drill.passes || 0) ? theme.green : theme.muted
                    font.pixelSize: 22
                    font.bold: true
                }
            }
            Item { Layout.fillWidth: true }
            Label {
                visible: (card.drill.lastScore ?? -1) >= 0
                text: qsTr("last try: %1").arg(card.drill.lastScore)
                opacity: 0.7
            }
        }

        Label {
            text: card.drill.listening ? qsTr("Your turn: say the word") : qsTr("Listen…")
            color: card.drill.listening ? theme.accent : theme.foreground
            font.pixelSize: 15
        }

        Flow {
            Layout.fillWidth: true
            spacing: 18
            Repeater {
                model: [["L", qsTr("hear it again"), "listen"], ["S", qsTr("skip this word"), "skip"], ["N", qsTr("don't coach this word"), "uncoach"]]
                delegate: RowLayout {
                    required property var modelData
                    spacing: 6
                    Rectangle {
                        implicitWidth: key.implicitWidth + 12
                        implicitHeight: key.implicitHeight + 4
                        radius: 4
                        color: Qt.lighter(theme.surface, 1.5)
                        Label { id: key; anchors.centerIn: parent; text: modelData[0]; font.bold: true }
                    }
                    Label { text: modelData[1]; opacity: 0.75 }
                    Label { visible: text !== ""; text: card.spoken(modelData[2]); opacity: 0.5; font.italic: true }
                }
            }
        }
    }
}
