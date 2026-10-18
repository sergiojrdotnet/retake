import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page

    property var missing: {
        const rows = []
        for (let i = 0; i < app.modelsModel.count; i++) {
            const row = app.modelsModel.get(i)
            if (row.role === "vosk" && !row.installed && row.id.indexOf("en-us-small") >= 0)
                rows.push(row)
        }
        return rows
    }

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 80, 720)
        spacing: 22

        RowLayout {
            spacing: 18
            Layout.alignment: Qt.AlignHCenter
            Logo { size: 80 }
            ColumnLayout {
                spacing: 2
                Label { text: "Retake"; font.pixelSize: 40; font.bold: true }
                Label { text: qsTr("Record yourself talking. The retakes are handled for you."); opacity: 0.7 }
            }
        }

        Rectangle {
            visible: page.missing.length > 0
            Layout.fillWidth: true
            implicitHeight: missingRow.implicitHeight + 24
            radius: 8
            color: Qt.rgba(1, 0.8, 0.2, 0.1)
            border.color: theme.yellow
            RowLayout {
                id: missingRow
                anchors.fill: parent
                anchors.margins: 12
                Label { text: qsTr("Voice following needs a speech model (40 MB)."); Layout.fillWidth: true; wrapMode: Text.Wrap }
                Button { text: qsTr("Models…"); onClicked: modelsDialog.open() }
            }
        }

        GridLayout {
            columns: 2
            columnSpacing: 14
            rowSpacing: 14
            Layout.fillWidth: true
            BigButton { title: qsTr("New project"); hint: "Ctrl+N"; detail: qsTr("A course or series; import its scripts"); onClicked: window.openNewProject() }
            BigButton { title: qsTr("Open project"); hint: "Ctrl+O"; detail: qsTr("A .retake file"); onClicked: app.openProjectDialog() }
        }

        ColumnLayout {
            Layout.fillWidth: true
            visible: app.recentProjects.length > 0
            RowLayout {
                Layout.fillWidth: true
                Label { text: qsTr("Recent projects"); opacity: 0.55; font.pixelSize: 13; Layout.fillWidth: true }
                ToolButton {
                    text: qsTr("Clear")
                    font.pixelSize: 12
                    opacity: 0.7
                    onClicked: app.clearRecentProjects()
                }
            }
            Repeater {
                model: app.recentProjects.slice(0, 6)
                delegate: ItemDelegate {
                    id: recentRow
                    required property var modelData
                    Layout.fillWidth: true
                    text: modelData.title + "   ·   " + qsTr("%n script(s)", "", modelData.scripts)
                        + (modelData.duration > 0 ? "   ·   " + Math.floor(modelData.duration / 60) + ":" + String(Math.round(modelData.duration % 60)).padStart(2, "0") : "")
                    rightPadding: removeButton.width + 8
                    ToolTip.visible: hovered && !removeButton.hovered
                    ToolTip.text: modelData.path
                    onClicked: app.openProject(modelData.path)
                    ToolButton {
                        id: removeButton
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        text: "×"
                        font.pixelSize: 16
                        opacity: recentRow.hovered ? 0.8 : 0
                        ToolTip.visible: hovered
                        ToolTip.text: qsTr("Remove from recent projects")
                        onClicked: app.removeRecentProject(recentRow.modelData.path)
                    }
                }
            }
        }

        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 10
            Button { flat: true; text: qsTr("Settings"); onClicked: settingsDialog.open() }
            Button { flat: true; text: qsTr("Models"); onClicked: modelsDialog.open() }
            Button { flat: true; text: qsTr("Projects folder"); onClicked: app.openProjectsFolder() }
            Button { flat: true; text: qsTr("Shortcuts  ?"); onClicked: window.helpVisible = true }
        }
    }
}
