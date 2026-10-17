import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RetakeDialog {
    id: dialog
    property string location: ""
    property bool done: false
    property alias projectName: name.text
    title: qsTr("New project")
    width: Math.min(parent.width - 60, 600)
    standardButtons: Dialog.Ok | Dialog.Cancel
    onOpened: {
        done = false
        name.text = ""
        location = app.projectFolderFor("")
        name.forceActiveFocus()
    }
    onAccepted: {
        if (done || name.text.trim() === "")
            return
        done = true
        app.newProject(name.text.trim(), location)
    }

    Connections {
        target: app
        function onProjectLocationChosen(path) { dialog.location = path }
    }

    ColumnLayout {
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: 12
        TextField {
            id: name
            Layout.fillWidth: true
            placeholderText: qsTr("e.g. Event Store Course")
            onAccepted: if (!dialog.done) dialog.accept()
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Label { text: qsTr("Location"); opacity: 0.7 }
            Label {
                text: dialog.location
                elide: Text.ElideMiddle
                Layout.fillWidth: true
                ToolTip.visible: locationHover.hovered
                ToolTip.text: dialog.location
                HoverHandler { id: locationHover }
            }
            Button { text: qsTr("Change…"); onClicked: app.chooseProjectLocation(dialog.location) }
        }
        Label {
            visible: name.text.trim() !== ""
            text: qsTr("Creates %1").arg(dialog.location + "/" + name.text.trim())
            font.pixelSize: 12
            opacity: 0.55
            elide: Text.ElideMiddle
            Layout.fillWidth: true
        }
    }
}
