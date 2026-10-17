import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: explorer
    color: Qt.darker(theme.background, 1.08)
    implicitWidth: 290

    signal renameRequested(string itemId, string title)
    signal deleteRecordingsRequested(string itemId, string title)

    function icon(kind) {
        return kind === "part" ? "●" : kind === "edit" ? "✎" : kind === "exports" ? "⇩" : kind === "free" ? "◉" : "▤"
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
                ToolTip.text: qsTr("Import scripts or start a free recording")
                onClicked: addMenu.open()
                Menu {
                    id: addMenu
                    y: addButton.height
                    MenuItem { text: qsTr("Import scripts…  (Ctrl+I)"); onTriggered: app.importScriptsDialog() }
                    MenuItem { text: qsTr("New free recording  (Ctrl+N)"); onTriggered: app.newFreeRecording() }
                    MenuSeparator {}
                    MenuItem { text: qsTr("Show project folder"); onTriggered: app.revealItem("") }
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
            text: qsTr("Empty project. Import scripts with + (Ctrl+I), or start a free recording.")
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
                height: kind === "group" ? 30 : 34
                enabled: kind !== "group"
                highlighted: current
                leftPadding: 10 + depth * 16
                rightPadding: 10
                onClicked: app.explorerActivate(index)
                contentItem: RowLayout {
                    spacing: 6
                    Label {
                        visible: row.kind !== "group"
                        text: row.expandable ? (row.expanded ? "▾" : "▸") : ""
                        Layout.preferredWidth: 12
                        opacity: 0.7
                        TapHandler { enabled: row.expandable; onTapped: app.setExpanded(row.id, !row.expanded) }
                    }
                    Label {
                        visible: row.kind !== "group"
                        text: explorer.icon(row.kind)
                        color: row.kind === "part" ? theme.red : theme.accent
                        font.pixelSize: row.kind === "part" ? 9 : 13
                        Layout.preferredWidth: 14
                    }
                    Label {
                        text: row.kind === "group" ? row.title.toUpperCase() : row.title
                        font.pixelSize: row.kind === "group" ? 11 : 14
                        font.bold: row.current
                        opacity: row.kind === "group" ? 0.5 : 1
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Label { text: row.detail; font.pixelSize: 11; opacity: 0.55 }
                }
                TapHandler {
                    acceptedButtons: Qt.RightButton
                    enabled: row.kind === "script" || row.kind === "free"
                    onTapped: { contextMenu.itemId = row.id; contextMenu.itemTitle = row.title; contextMenu.isScript = row.kind === "script"; contextMenu.recorded = row.expandable; contextMenu.popup() }
                }
            }
        }
    }

    Menu {
        id: contextMenu
        property string itemId
        property string itemTitle
        property bool isScript
        property bool recorded
        MenuItem { text: qsTr("Open in the prompter"); enabled: contextMenu.isScript; onTriggered: app.openItem(contextMenu.itemId, "prompter") }
        MenuItem { text: qsTr("Open in the studio"); onTriggered: app.openItem(contextMenu.itemId, "studio") }
        MenuSeparator {}
        MenuItem { text: qsTr("Rename…"); onTriggered: explorer.renameRequested(contextMenu.itemId, contextMenu.itemTitle) }
        MenuItem { text: qsTr("Re-import from the original file"); enabled: contextMenu.isScript; onTriggered: app.reimportItem(contextMenu.itemId) }
        MenuItem { text: qsTr("Show in Files"); onTriggered: app.revealItem(contextMenu.itemId) }
        MenuSeparator {}
        MenuItem { text: qsTr("Delete recordings…"); enabled: contextMenu.recorded; onTriggered: explorer.deleteRecordingsRequested(contextMenu.itemId, contextMenu.itemTitle) }
        MenuItem { text: qsTr("Remove from project"); onTriggered: app.removeItem(contextMenu.itemId) }
    }
}
