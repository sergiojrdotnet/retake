import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 80, 560)
        spacing: 18
        Label { text: app.projectTitle; font.pixelSize: 30; font.bold: true }
        Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            opacity: 0.7
            text: qsTr("Import the scripts for this project; each one gets its own recordings, edit and exports. Pick one in the explorer to start.")
        }
        RowLayout {
            spacing: 12
            Button { text: qsTr("Import scripts…"); highlighted: true; onClicked: app.importScriptsDialog() }
            Button { text: qsTr("Free recording"); onClicked: app.newFreeRecording() }
            Button { text: qsTr("Show explorer"); visible: !app.explorerVisible; onClicked: app.toggleExplorer() }
        }
    }
}
