import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RetakeDialog {
    id: dialog
    title: qsTr("Models")
    width: Math.min(parent.width - 60, 860)
    height: Math.min(parent.height - 60, 720)
    standardButtons: Dialog.Close

    function jobRow(title) {
        for (let i = 0; i < app.modelJobs.count; i++) {
            const row = app.modelJobs.get(i)
            if (row.jobTitle === title)
                return row
        }
        return null
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            opacity: 0.65
            text: qsTr("Pick what each job uses. Models download to ~/.local/share/retake/models.")
        }
        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 4
            model: app.modelJobs
            ScrollBar.vertical: ScrollBar {}
            section.property: "jobTitle"
            section.delegate: ColumnLayout {
                required property string section
                property var info: dialog.jobRow(section)
                width: ListView.view.width
                spacing: 2
                Item { implicitHeight: 10 }
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: section.toUpperCase(); font.bold: true; font.pixelSize: 13; color: theme.accent }
                    Item { Layout.fillWidth: true }
                    Label { text: info ? qsTr("Uses: %1").arg(info.uses) : ""; font.pixelSize: 12; opacity: 0.7 }
                }
                Label { text: info ? info.jobHint : ""; font.pixelSize: 12; opacity: 0.55; Layout.fillWidth: true; wrapMode: Text.Wrap }
                Item { implicitHeight: 2 }
            }
            delegate: Rectangle {
                id: row
                required property string job
                required property string value
                required property string title
                required property string detail
                required property string model
                required property bool installed
                required property bool available
                required property bool builtin
                required property bool selected
                required property real progress
                property bool usable: installed && available
                width: ListView.view.width
                height: 50
                radius: 6
                color: selected ? Qt.alpha(theme.accent, 0.14) : theme.surface
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 4
                    anchors.rightMargin: 10
                    spacing: 10
                    RadioButton {
                        checked: row.selected
                        enabled: row.usable
                        onClicked: app.selectJobOption(row.job, row.value)
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        opacity: row.usable ? 1 : 0.6
                        Label { text: row.title; font.bold: row.selected }
                        Label { visible: text !== ""; text: row.detail; font.pixelSize: 12; opacity: 0.6; elide: Text.ElideRight; Layout.fillWidth: true }
                    }
                    ProgressBar { visible: row.progress >= 0; value: row.progress; Layout.preferredWidth: 140 }
                    Label { visible: !row.builtin && row.installed; text: qsTr("Installed"); color: theme.green; font.pixelSize: 12 }
                    Button {
                        visible: !row.builtin && !row.installed && row.progress < 0
                        enabled: row.available
                        text: qsTr("Download")
                        onClicked: app.downloadModel(row.model)
                    }
                    Button {
                        visible: !row.builtin && row.installed
                        enabled: !row.selected
                        flat: true
                        text: qsTr("Remove")
                        onClicked: app.removeModel(row.model)
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    z: -1
                    enabled: row.usable
                    onClicked: app.selectJobOption(row.job, row.value)
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label {
                visible: app.enginePending
                text: qsTr("Changes apply when the engine restarts.")
                color: theme.yellow
                Layout.fillWidth: true
            }
            Item { visible: !app.enginePending; Layout.fillWidth: true }
            Button {
                text: qsTr("Restart engine")
                highlighted: app.enginePending
                enabled: !app.recording
                onClicked: app.restartEngine()
            }
        }
    }
}
