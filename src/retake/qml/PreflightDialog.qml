import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RetakeDialog {
    id: dialog
    title: qsTr("Script check")
    width: Math.min(parent.width - 60, 760)
    height: Math.min(parent.height - 60, 560)
    standardButtons: Dialog.Close

    ColumnLayout {
        anchors.fill: parent
        spacing: 10
        Label {
            text: app.preflightIssues.length === 0 ? qsTr("Everything looks ready.") : qsTr("%n thing(s) to look at before recording", "", app.preflightIssues.length)
            font.bold: true
        }
        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 6
            model: app.preflightIssues
            delegate: Item {
                required property var modelData
                width: ListView.view.width
                height: issueRow.implicitHeight + 4
                RowLayout {
                    id: issueRow
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 10
                    Rectangle {
                        width: 8; height: 8; radius: 4
                        color: modelData.severity === "error" ? theme.red : modelData.severity === "warning" ? theme.yellow : theme.muted
                    }
                    Label {
                        text: modelData.message
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                        opacity: modelData.severity === "info" ? 0.7 : 1
                    }
                    Button {
                        visible: modelData.word !== "" && modelData.kind === "pronunciation"
                        text: qsTr("Listen")
                        flat: true
                        onClicked: app.listenTo(modelData.word)
                    }
                }
            }
        }
        Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            opacity: 0.55
            font.pixelSize: 12
            text: qsTr("Fix a pronunciation inline with {word|IPA}, or add “word<TAB>IPA” to the .lexicon.tsv file next to the script.")
        }
        RowLayout {
            Button { text: qsTr("Check again"); onClicked: app.runPreflight() }
            Button { text: qsTr("Models…"); onClicked: modelsDialog.open() }
        }
    }
}
