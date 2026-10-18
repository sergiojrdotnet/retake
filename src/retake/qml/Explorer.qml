import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: explorer
    color: Qt.darker(theme.background, 1.08)
    implicitWidth: 290

    signal renameRequested(string itemId, string title)
    signal deleteRecordingsRequested(string itemId, string title)
    signal deleteRecordingRequested(string itemId, int part, string title)

    function icon(kind) {
        return kind === "part" ? "●" : kind === "exports" ? "⇩" : "▤"
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 10
            Label {
                text: app.projectTitle.toUpperCase()
                font.bold: true
                font.pixelSize: 13
                color: theme.accent
                elide: Text.ElideRight
                Layout.fillWidth: true
                ToolTip.visible: titleHover.hovered
                ToolTip.text: app.projectPath
                HoverHandler { id: titleHover }
            }
            ToolButton {
                id: addButton
                text: "+"
                font.pixelSize: 18
                ToolTip.visible: hovered
                ToolTip.text: qsTr("Import scripts, show the folder, close the project")
                onClicked: addMenu.open()
                Menu {
                    id: addMenu
                    y: addButton.height
                    MenuItem { text: qsTr("Import scripts…  (Ctrl+I)"); onTriggered: app.importScriptsDialog() }
                    MenuItem { text: qsTr("Show project folder"); onTriggered: app.revealItem("") }
                    MenuSeparator {}
                    MenuItem { text: qsTr("Close project  (Esc)"); onTriggered: app.closeProject() }
                }
            }
            ToolButton {
                text: "«"
                ToolTip.visible: hovered
                ToolTip.text: qsTr("Hide the explorer (Ctrl+B)")
                onClicked: app.toggleExplorer()
            }
        }

        Label {
            visible: list.count === 0
            Layout.fillWidth: true
            Layout.margins: 14
            wrapMode: Text.Wrap
            opacity: 0.6
            text: qsTr("Empty project. Import scripts with + (Ctrl+I).")
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: app.explorerModel
            ScrollBar.vertical: ScrollBar {}
            delegate: ItemDelegate {
                id: row
                required property int index
                required property string kind
                required property int depth
                required property string id
                required property int part
                required property string title
                required property string detail
                required property bool expanded
                required property bool expandable
                required property bool current
                width: ListView.view.width
                height: 34
                highlighted: current
                leftPadding: 10 + depth * 16
                rightPadding: 10
                onClicked: app.explorerActivate(index)
                contentItem: RowLayout {
                    spacing: 6
                    Label {
                        text: row.expandable ? (row.expanded ? "▾" : "▸") : ""
                        Layout.preferredWidth: 12
                        opacity: 0.7
                        TapHandler { enabled: row.expandable; onTapped: app.setExpanded(row.id, !row.expanded) }
                    }
                    Label {
                        text: explorer.icon(row.kind)
                        color: row.kind === "part" ? theme.red : theme.accent
                        font.pixelSize: row.kind === "part" ? 9 : 13
                        Layout.preferredWidth: 14
                    }
                    Label {
                        text: row.title
                        font.pixelSize: 14
                        font.bold: row.current
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Label { text: row.detail; font.pixelSize: 11; opacity: 0.55 }
                }
                TapHandler {
                    acceptedButtons: Qt.RightButton
                    enabled: row.kind === "script" || row.kind === "part"
                    onTapped: {
                        if (row.kind === "part") {
                            partMenu.itemId = row.id; partMenu.part = row.part; partMenu.partTitle = row.title; partMenu.popup()
                        } else {
                            contextMenu.itemId = row.id; contextMenu.itemTitle = row.title; contextMenu.recorded = row.expandable; contextMenu.popup()
                        }
                    }
                }
            }
        }
    }

    Menu {
        id: contextMenu
        property string itemId
        property string itemTitle
        property bool recorded
        MenuItem { text: qsTr("Open in the prompter"); onTriggered: app.openItem(contextMenu.itemId, "prompter") }
        MenuItem { text: qsTr("Open in the studio"); onTriggered: app.openItem(contextMenu.itemId, "studio") }
        MenuSeparator {}
        MenuItem { text: qsTr("Rename…"); onTriggered: explorer.renameRequested(contextMenu.itemId, contextMenu.itemTitle) }
        MenuItem { text: qsTr("Re-import from the original file"); onTriggered: app.reimportItem(contextMenu.itemId) }
        MenuItem { text: qsTr("Show in Files"); onTriggered: app.revealItem(contextMenu.itemId) }
        MenuSeparator {}
        MenuItem { text: qsTr("Delete recordings…"); enabled: contextMenu.recorded; onTriggered: explorer.deleteRecordingsRequested(contextMenu.itemId, contextMenu.itemTitle) }
        MenuItem { text: qsTr("Remove from project"); onTriggered: app.removeItem(contextMenu.itemId) }
    }

    Menu {
        id: partMenu
        property string itemId
        property int part
        property string partTitle
        MenuItem { text: qsTr("Open in the studio"); onTriggered: app.openItem(partMenu.itemId, "part:" + partMenu.part) }
        MenuItem { text: qsTr("Play the raw recording"); onTriggered: app.playRecording(partMenu.itemId, partMenu.part) }
        MenuSeparator {}
        MenuItem { text: qsTr("Delete this recording…"); onTriggered: explorer.deleteRecordingRequested(partMenu.itemId, partMenu.part, partMenu.partTitle) }
    }
}
