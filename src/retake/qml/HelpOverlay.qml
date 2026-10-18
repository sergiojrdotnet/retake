import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: overlay
    property string page: "start"
    color: theme.background

    // [what it does, key, voice actions from the language pack]
    property var sessionKeys: [
        [qsTr("Record / pause / resume"), "Space", ["record", "pause", "resume"]],
        [qsTr("Rehearse (nothing is kept)"), "Shift+Space", ["rehearse"]],
        [qsTr("Retake the sentence"), "R", ["again"]],
        [qsTr("Next sentence"), "→  PgDn", ["next"]],
        [qsTr("Previous sentence"), "←  PgUp", ["back"]],
        [qsTr("Mark a spot"), "M", ["mark"]],
        [qsTr("Listen to the word"), "L", ["listen"]],
        [qsTr("Hear any word"), "", ["say"]],
        [qsTr("Flag the word for practice"), "F", []],
        [qsTr("Drill the warned words (this sentence, or the last)"), "D", ["drill"]],
        [qsTr("Word drill: skip this word"), "S", ["skip"]],
        [qsTr("Word drill: never coach this word"), "N", ["uncoach"]],
        [qsTr("Stop and open the editor"), "Enter", ["stop"]],
        [qsTr("Prompter mode: scroll, step, card, page"), "V", []],
        [qsTr("Layout: full, focus, lens"), "Tab  1–3", []],
        [qsTr("Check the script"), "P", []],
        [qsTr("Move the prompter to its sentence  ·  right-click: listen, flag, coach"), qsTr("Click word"), []],
    ]

    function phrases(actions) {
        const voice = app.voiceCommands
        if (!voice.enabled || actions.length === 0)
            return "—"
        const out = []
        for (const action of actions) {
            if (action === "say") {
                for (const prefix of voice.say)
                    out.push(prefix + " " + qsTr("<word>"))
            } else {
                for (const phrase of voice.actions[action] || [])
                    out.push(phrase)
            }
        }
        return out.length ? out.join("  ·  ") : "—"
    }

    property var editorKeys: [
        ["Space", qsTr("Play / pause (through the cuts when they show)")],
        ["←  →", qsTr("Move 1 s (Shift 5 s, Alt 0.2 s)")],
        ["[  ]", qsTr("Previous / next edge or marker, in timeline order")],
        ["0–9", qsTr("Jump to 0–90% of the edit")],
        [qsTr("Click clip"), qsTr("Select its sentence (Shift range, Ctrl add)")],
        ["R", qsTr("Re-record the selected sentences (pickups)")],
        ["T  Shift+T", qsTr("Older / newer take of this sentence (or click one in the side panel)")],
        ["S", qsTr("Split at the playhead")],
        ["X  Del", qsTr("Remove clip, or restore a gap")],
        ["Ctrl+Space", qsTr("Clip start to playhead")],
        ["Alt+Space", qsTr("Clip end to playhead")],
        ["A", qsTr("Reset to the automatic cut")],
        ["Z", qsTr("Zoom to clip / out")],
        ["V", qsTr("Show each take whole, its cuts greyed")],
        ["Ctrl+=  Ctrl+-  Ctrl+0", qsTr("Zoom in / out / fit (Ctrl+wheel at the mouse)")],
        ["Ctrl+Z  Ctrl+Shift+Z", qsTr("Undo / redo")],
        ["F", qsTr("Save the frame under the playhead as a PNG (out/)")],
        ["Ctrl+E  Ctrl+S", qsTr("Export again with the last choices")],
    ]
    property var globalKeys: [
        ["Ctrl+N", qsTr("New project")],
        ["Ctrl+O", qsTr("Open project")],
        ["Ctrl+I", qsTr("Import scripts")],
        ["Ctrl+Tab", qsTr("Switch between Record and Studio")],
        ["Ctrl+B", qsTr("Show / hide the explorer")],
        ["Ctrl+,", qsTr("Settings")],
        ["Ctrl+M", qsTr("Models")],
        ["Esc", qsTr("Close the project")],
        ["?", qsTr("This help")],
        ["Q", qsTr("Quit")],
    ]

    MouseArea { anchors.fill: parent; onClicked: window.helpVisible = false }

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 80, 860)
        spacing: 18
        Label { text: overlay.page === "session" ? qsTr("Keyboard and voice") : qsTr("Keyboard"); font.pixelSize: 26; font.bold: true }
        GridLayout {
            visible: overlay.page === "session"
            columns: 3
            columnSpacing: 28
            rowSpacing: 6
            Layout.fillWidth: true
            Label { text: qsTr("Action"); opacity: 0.5; font.pixelSize: 12 }
            Label { text: qsTr("Key"); opacity: 0.5; font.pixelSize: 12 }
            Label {
                text: app.voiceCommands.enabled ? qsTr("Say “%1 …”").arg(app.voiceCommands.wake) : qsTr("Voice commands are off")
                opacity: 0.5
                font.pixelSize: 12
                Layout.fillWidth: true
            }
            Repeater {
                model: overlay.page === "session" ? overlay.sessionKeys : []
                delegate: Label {
                    required property var modelData
                    required property int index
                    Layout.row: index + 1
                    Layout.column: 0
                    text: modelData[0]
                    opacity: 0.9
                }
            }
            Repeater {
                model: overlay.page === "session" ? overlay.sessionKeys : []
                delegate: Label {
                    required property var modelData
                    required property int index
                    Layout.row: index + 1
                    Layout.column: 1
                    text: modelData[1] || "—"
                    color: modelData[1] ? theme.accent : theme.foreground
                    opacity: modelData[1] ? 1 : 0.4
                    font.family: "monospace"
                }
            }
            Repeater {
                model: overlay.page === "session" ? overlay.sessionKeys : []
                delegate: Label {
                    required property var modelData
                    required property int index
                    Layout.row: index + 1
                    Layout.column: 2
                    Layout.fillWidth: true
                    text: overlay.phrases(modelData[2])
                    opacity: text === "—" ? 0.4 : 0.85
                    wrapMode: Text.Wrap
                }
            }
        }
        GridLayout {
            columns: 2
            columnSpacing: 36
            rowSpacing: 6
            Repeater {
                model: (overlay.page === "editor" ? overlay.editorKeys : []).concat(overlay.globalKeys)
                delegate: RowLayout {
                    required property var modelData
                    spacing: 14
                    Label { text: modelData[0]; color: theme.accent; font.family: "monospace"; Layout.preferredWidth: 170 }
                    Label { text: modelData[1]; opacity: 0.9 }
                }
            }
        }
        Label {
            visible: overlay.page === "session" && app.voiceCommands.enabled
            text: qsTr("Pause briefly before the wake word. Commands and their wake word live in the language pack; change the wake word in Settings → Controls.")
            wrapMode: Text.Wrap
            Layout.fillWidth: true
            opacity: 0.6
        }
    }
}
