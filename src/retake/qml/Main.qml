import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1280
    height: 820
    minimumWidth: 640
    minimumHeight: 360
    visible: true
    title: "Retake"
    color: theme.background

    Material.theme: Material.Dark
    Material.accent: theme.accent
    Material.background: theme.background
    Material.foreground: theme.foreground
    Material.primary: theme.surface
    font.pixelSize: 15

    property bool helpVisible: false
    property bool quitConfirmed: false
    property bool editorPage: app.page === "editor"
    property bool sessionPage: app.page === "session"

    header: StatusBar {}

    RowLayout {
        anchors.fill: parent
        spacing: 0
        Explorer {
            id: explorerPane
            Layout.fillHeight: true
            Layout.preferredWidth: implicitWidth
            visible: app.hasProject && app.explorerVisible && app.page !== "start"
            onRenameRequested: (itemId, title) => inputDialog.ask(qsTr("Rename"), "rename", itemId, title)
            onDeleteRecordingsRequested: (itemId, title) => { deleteDialog.itemId = itemId; deleteDialog.itemTitle = title; deleteDialog.open() }
        }
        Rectangle {
            visible: explorerPane.visible
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            color: Qt.rgba(1, 1, 1, 0.06)
        }
        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: app.page === "start" ? 0 : app.page === "session" ? 1 : app.page === "editor" ? 2 : 3
            StartPage {}
            SessionPage { id: sessionPage }
            EditorPage { id: editorView; objectName: "editorPage" }
            ProjectPage {}
        }
    }

    CameraRig { id: cameraRig }

    BusyOverlay {
        anchors.fill: parent
        text: app.finishing
        hint: qsTr("Your recording is safe on disk; this only prepares it for editing.")
    }
    BusyOverlay {
        anchors.fill: parent
        text: app.opening
        fadeIn: true
    }
    BusyOverlay {
        anchors.fill: parent
        text: app.startingVideo
        hint: qsTr("Recording starts as soon as it's ready.")
    }

    Toasts { anchors.fill: parent }
    HelpOverlay { anchors.fill: parent; visible: window.helpVisible; page: app.page }
    SettingsDialog { id: settingsDialog; objectName: "settingsDialog" }
    PreflightDialog { id: preflightDialog; objectName: "preflightDialog" }
    ModelsDialog { id: modelsDialog; objectName: "modelsDialog" }
    NewProjectDialog { id: newProjectDialog }
    RetakeDialog {
        id: deleteDialog
        property string itemId
        property string itemTitle
        title: qsTr("Delete the recordings of “%1”?").arg(itemTitle)
        standardButtons: Dialog.Yes | Dialog.Cancel
        width: Math.min(parent.width - 60, 560)
        Label {
            anchors.left: parent.left
            anchors.right: parent.right
            wrapMode: Text.Wrap
            text: qsTr("Every recording, take, the edit and the exports go to the trash. The script stays, ready to record again.")
        }
        onAccepted: app.deleteRecordings(itemId)
    }
    InputDialog {
        id: inputDialog
        onSubmitted: (action, target, text) => {
            if (action === "rename")
                app.renameItem(target, text)
        }
    }

    function openNewProject() {
        newProjectDialog.open()
    }

    RetakeDialog {
        id: quitDialog
        title: app.recording ? qsTr("Stop recording and quit?") : qsTr("Quit without saving the edit?")
        standardButtons: Dialog.Yes | Dialog.No
        onAccepted: { window.quitConfirmed = true; app.shutdown(); Qt.quit() }
    }

    Connections {
        target: app
        function onRaiseWindow() { window.raise(); window.requestActivate() }
    }

    onClosing: (close) => {
        if (!window.quitConfirmed && !app.canQuit()) {
            close.accepted = false
            quitDialog.open()
        }
    }

    function anyDialogOpen() {
        return settingsDialog.opened || preflightDialog.opened || modelsDialog.opened || quitDialog.opened || inputDialog.opened || newProjectDialog.opened || deleteDialog.opened
    }

    Shortcut { sequences: ["?", "F1"]; context: Qt.ApplicationShortcut; onActivated: window.helpVisible = !window.helpVisible }
    Shortcut { sequence: "Esc"; context: Qt.ApplicationShortcut; enabled: window.helpVisible; onActivated: window.helpVisible = false }
    Shortcut { sequence: "Q"; context: Qt.ApplicationShortcut; enabled: !window.anyDialogOpen(); onActivated: window.close() }
    Shortcut { sequence: "Ctrl+Q"; context: Qt.ApplicationShortcut; onActivated: window.close() }
    Shortcut { sequence: "Ctrl+O"; context: Qt.ApplicationShortcut; enabled: !app.recording; onActivated: app.openProjectDialog() }
    Shortcut { sequence: "Ctrl+Shift+O"; context: Qt.ApplicationShortcut; enabled: !app.recording; onActivated: app.openScriptDialog() }
    Shortcut { sequence: "Ctrl+Shift+N"; context: Qt.ApplicationShortcut; enabled: !app.recording; onActivated: window.openNewProject() }
    Shortcut { sequence: "Ctrl+N"; context: Qt.ApplicationShortcut; enabled: !app.recording; onActivated: app.startFree() }
    Shortcut { sequence: "Ctrl+I"; context: Qt.ApplicationShortcut; enabled: !app.recording && app.hasProject; onActivated: app.importScriptsDialog() }
    Shortcut { sequence: "Ctrl+B"; context: Qt.ApplicationShortcut; enabled: app.hasProject; onActivated: app.toggleExplorer() }
    Shortcut { sequence: "Ctrl+,"; context: Qt.ApplicationShortcut; onActivated: settingsDialog.open() }
    Shortcut { sequence: "Ctrl+M"; context: Qt.ApplicationShortcut; onActivated: modelsDialog.open() }
    Shortcut { sequence: "Esc"; context: Qt.ApplicationShortcut; enabled: !window.helpVisible && !app.recording && app.page !== "start" && !window.anyDialogOpen(); onActivated: app.pickupPending ? app.cancelPickup() : app.goStart() }

    Shortcut { sequence: "Space"; context: Qt.ApplicationShortcut; enabled: window.sessionPage && !window.anyDialogOpen(); onActivated: app.action("toggle_pause") }
    Shortcut { sequence: "Shift+Space"; context: Qt.ApplicationShortcut; enabled: window.sessionPage && !app.recording; onActivated: app.rehearse() }
    Shortcut { sequences: ["Return", "Enter"]; context: Qt.ApplicationShortcut; enabled: window.sessionPage && app.recording && !window.anyDialogOpen(); onActivated: app.stop() }
    Shortcut { sequences: ["Right", "PgDown"]; context: Qt.ApplicationShortcut; enabled: window.sessionPage; onActivated: app.action("next") }
    Shortcut { sequences: ["Left", "PgUp"]; context: Qt.ApplicationShortcut; enabled: window.sessionPage; onActivated: app.action("back") }
    Shortcut { sequences: ["R", "F5"]; context: Qt.ApplicationShortcut; enabled: window.sessionPage && !window.anyDialogOpen(); onActivated: app.action("again") }
    Shortcut { sequence: "M"; context: Qt.ApplicationShortcut; enabled: window.sessionPage && !window.anyDialogOpen(); onActivated: app.action("mark") }
    Shortcut { sequence: "L"; context: Qt.ApplicationShortcut; enabled: window.sessionPage && !window.anyDialogOpen(); onActivated: app.action("listen") }
    Shortcut { sequence: "F"; context: Qt.ApplicationShortcut; enabled: window.sessionPage && !window.anyDialogOpen(); onActivated: app.flagCurrent() }
    Shortcut { sequence: "D"; context: Qt.ApplicationShortcut; enabled: window.sessionPage && app.drill.active !== true && !window.anyDialogOpen(); onActivated: app.action("drill") }
    Shortcut { sequence: "S"; context: Qt.ApplicationShortcut; enabled: window.sessionPage && app.drill.active === true && !window.anyDialogOpen(); onActivated: app.action("skip") }
    Shortcut { sequence: "N"; context: Qt.ApplicationShortcut; enabled: window.sessionPage && app.drill.active === true && !window.anyDialogOpen(); onActivated: app.action("uncoach") }
    Shortcut { sequence: "V"; context: Qt.ApplicationShortcut; enabled: window.sessionPage && !window.anyDialogOpen(); onActivated: app.cycleDisplayMode() }
    Shortcut { sequence: "P"; context: Qt.ApplicationShortcut; enabled: window.sessionPage && !app.recording && !window.anyDialogOpen(); onActivated: { app.runPreflight(); preflightDialog.open() } }
    Shortcut { sequence: "C"; context: Qt.ApplicationShortcut; enabled: window.sessionPage && !window.anyDialogOpen(); onActivated: app.setCameraLayout(app.cameraLayout === "corner" ? "full" : app.cameraLayout === "full" ? "off" : "corner") }
    Shortcut { sequence: "Tab"; context: Qt.ApplicationShortcut; enabled: window.sessionPage && !window.anyDialogOpen(); onActivated: app.cycleLayout(1) }
    Shortcut { sequence: "Backtab"; context: Qt.ApplicationShortcut; enabled: window.sessionPage && !window.anyDialogOpen(); onActivated: app.cycleLayout(-1) }
    Shortcut { sequence: "1"; context: Qt.ApplicationShortcut; enabled: window.sessionPage && !window.anyDialogOpen(); onActivated: app.setLayout("full") }
    Shortcut { sequence: "2"; context: Qt.ApplicationShortcut; enabled: window.sessionPage && !window.anyDialogOpen(); onActivated: app.setLayout("focus") }
    Shortcut { sequence: "3"; context: Qt.ApplicationShortcut; enabled: window.sessionPage && !window.anyDialogOpen(); onActivated: app.setLayout("lens") }

    Shortcut { sequence: "Space"; context: Qt.ApplicationShortcut; enabled: window.editorPage && !window.anyDialogOpen(); onActivated: editorView.togglePlay() }
    Shortcut { sequence: "Right"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editorView.nudge(1) }
    Shortcut { sequence: "Left"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editorView.nudge(-1) }
    Shortcut { sequence: "Shift+Right"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editorView.nudge(5) }
    Shortcut { sequence: "Shift+Left"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editorView.nudge(-5) }
    Shortcut { sequence: "Alt+Right"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editorView.nudge(0.2) }
    Shortcut { sequence: "Alt+Left"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editorView.nudge(-0.2) }
    Shortcut { sequence: "]"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editorView.seek(editor.nextEdge(editorView.playhead, 1)) }
    Shortcut { sequence: "["; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editorView.seek(editor.nextEdge(editorView.playhead, -1)) }
    Shortcut { sequence: "T"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editor.cycleTake(editorView.playhead) }
    Shortcut { sequence: "R"; context: Qt.ApplicationShortcut; enabled: window.editorPage && !window.anyDialogOpen(); onActivated: editorView.rerecord() }
    Shortcut { sequence: "S"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editor.split(editorView.playhead) }
    Shortcut { sequences: ["X", "Delete"]; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editor.removeAt(editorView.playhead) }
    Shortcut { sequence: "Ctrl+Space"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editor.setEdge("start", editorView.playhead) }
    Shortcut { sequence: "Alt+Space"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editor.setEdge("end", editorView.playhead) }
    Shortcut { sequence: "A"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editor.autoEdit() }
    Shortcut { sequence: "Z"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editorView.toggleZoom() }
    Shortcut { sequence: "V"; context: Qt.ApplicationShortcut; enabled: window.editorPage && !window.anyDialogOpen(); onActivated: editorView.toggleView() }
    Shortcut { sequence: "Ctrl+Tab"; context: Qt.ApplicationShortcut; enabled: (window.sessionPage || window.editorPage) && !window.anyDialogOpen(); onActivated: app.toggleView() }
    Shortcut { sequences: ["Ctrl+=", "Ctrl++"]; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editorView.zoomBy(1.5) }
    Shortcut { sequence: "Ctrl+-"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editorView.zoomBy(1 / 1.5) }
    Shortcut { sequence: "Ctrl+0"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editorView.zoomFit() }
    Shortcut { sequence: "Ctrl+Z"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editor.undo() }
    Shortcut { sequence: "Ctrl+Shift+Z"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editor.redo() }
    Shortcut { sequence: "Ctrl+S"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editor.save() }
    Shortcut { sequence: "Ctrl+E"; context: Qt.ApplicationShortcut; enabled: window.editorPage; onActivated: editor.render(editor.hasVideo ? "video" : "narration-flac") }
}
