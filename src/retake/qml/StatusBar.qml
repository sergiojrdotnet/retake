import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// One line when the window is wide enough; otherwise two: where you are and the engines on top,
// switching and the meters underneath.
Rectangle {
    id: bar
    implicitHeight: lines.implicitHeight + 10
    color: Qt.darker(theme.background, 1.15)

    property var r: app.resources
    property string place: app.page === "editor" ? app.itemTitle
                         : app.page === "session" ? app.scriptTitle : ""
    // On one line the switch sits in the middle, so each side gets half of what's left around it.
    property real sideWidth: Math.max(whereAmI.implicitWidth, engines.implicitWidth + metersWide.implicitWidth + help.implicitWidth + 2 * 14)
    property real oneLineWidth: 2 * sideWidth + switcherWide.implicitWidth + 2 * 24 + 22
    property bool twoLines: width - 22 < oneLineWidth

    function clock(seconds) {
        const total = Math.max(0, Math.floor(seconds))
        const m = Math.floor(total / 60)
        const s = total % 60
        return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s
    }

    // Status lights keep their meaning whatever the theme: some palettes have a grey-green "green".
    function engineColor(state) {
        return state === "ready" ? "#3fb950" : state === "error" ? "#f85149" : "#e3b341"
    }

    function meterColor(percent) {
        return percent >= 92 ? "#f85149" : percent >= 75 ? "#e3b341" : theme.accent
    }

    // A pill of options with the current one filled in.
    component Segmented: Rectangle {
        id: pill
        property var options: []
        property string current: ""
        property bool locked: false
        property string lockedTip: ""
        signal picked(string value)
        implicitWidth: row.implicitWidth + 6
        implicitHeight: 28
        radius: 14
        color: Qt.lighter(theme.surface, 1.35)
        opacity: locked ? 0.5 : 1
        Row {
            id: row
            anchors.centerIn: parent
            spacing: 2
            Repeater {
                model: pill.options
                delegate: Rectangle {
                    required property var modelData
                    property bool active: pill.current === modelData.value
                    width: label.implicitWidth + 26
                    height: 22
                    radius: 11
                    color: active ? theme.accent : hover.hovered && !pill.locked ? Qt.lighter(theme.surface, 1.7) : "transparent"
                    Label {
                        id: label
                        anchors.centerIn: parent
                        text: modelData.text
                        font.pixelSize: 13
                        font.bold: parent.active
                        color: parent.active ? theme.background : theme.foreground
                    }
                    HoverHandler { id: hover; cursorShape: parent.active || pill.locked ? Qt.ArrowCursor : Qt.PointingHandCursor }
                    TapHandler { enabled: !parent.active && !pill.locked; onTapped: pill.picked(modelData.value) }
                    ToolTip.visible: hover.hovered
                    ToolTip.text: pill.locked ? pill.lockedTip : modelData.tip
                }
            }
        }
    }

    Component {
        id: switcherComponent
        RowLayout {
            spacing: 10
            // How the recording page is laid out; only there.
            Segmented {
                visible: app.page === "session"
                current: app.layout
                options: [
                    { value: "full", text: qsTr("Full"), tip: qsTr("1 · prompter with camera, coach and takes") },
                    { value: "focus", text: qsTr("Focus"), tip: qsTr("2 · only the prompter") },
                    { value: "lens", text: qsTr("Lens"), tip: qsTr("3 · one sentence at a time, for a window under the camera") },
                ]
                onPicked: (value) => app.setLayout(value)
            }
            // Record and Studio for the open script, always one click (or Ctrl+Tab) apart.
            Segmented {
                visible: app.hasProject && (app.page === "session" || app.page === "editor")
                current: app.page === "editor" ? "studio" : "record"
                locked: app.recording
                lockedTip: qsTr("Stop the recording first (Enter)")
                options: [
                    { value: "record", text: "●  " + qsTr("Record"), tip: qsTr("Ctrl+Tab switches between Record and Studio") },
                    { value: "studio", text: "✎  " + qsTr("Studio"), tip: qsTr("Ctrl+Tab switches between Record and Studio") },
                ]
                onPicked: (value) => app.showView(value)
            }
        }
    }

    Component {
        id: metersComponent
        RowLayout {
            spacing: 12
            Row {
                visible: app.page === "session"
                spacing: 6
                Label { text: qsTr("MIC"); font.pixelSize: 11; opacity: 0.6; anchors.verticalCenter: parent.verticalCenter }
                LevelMeter { width: 110; height: 16; anchors.verticalCenter: parent.verticalCenter }
            }
            Row {
                visible: bar.r.cpu !== undefined
                spacing: 9
                Repeater {
                    model: [
                        [qsTr("CPU"), bar.r.cpu, qsTr("CPU %1% of %2 threads").arg(bar.r.cpu).arg(bar.r.cpu_threads)],
                        [qsTr("RAM"), bar.r.ram_pct, qsTr("RAM %1 used, %2 GB free").arg(bar.r.ram).arg(bar.r.ram_available_gb)],
                        [qsTr("GPU"), bar.r.gpu, qsTr("GPU %1%").arg(bar.r.gpu) + (bar.r.temperature !== null && bar.r.temperature !== undefined ? "  ·  " + Math.round(bar.r.temperature) + " °C" : "") + (bar.r.gpu_name ? "\n" + bar.r.gpu_name : "")],
                        [qsTr("VRAM"), bar.r.vram_pct, qsTr("VRAM %1 used").arg(bar.r.vram)],
                    ]
                    delegate: Row {
                        required property var modelData
                        visible: modelData[1] !== null && modelData[1] !== undefined
                        spacing: 4
                        Label { text: modelData[0]; font.pixelSize: 11; opacity: 0.6; anchors.verticalCenter: parent.verticalCenter }
                        Rectangle {
                            width: 6
                            height: 20
                            radius: 2
                            anchors.verticalCenter: parent.verticalCenter
                            color: Qt.lighter(theme.surface, 1.6)
                            Rectangle {
                                anchors.bottom: parent.bottom
                                width: parent.width
                                height: parent.height * Math.max(0, Math.min(1, (modelData[1] || 0) / 100))
                                radius: 2
                                color: bar.meterColor(modelData[1] || 0)
                            }
                        }
                        ToolTip.visible: meterHover.hovered
                        ToolTip.text: modelData[2] + "\n" + qsTr("Click for details")
                        HoverHandler { id: meterHover }
                    }
                }
                TapHandler { onTapped: resources.visible ? resources.close() : resources.open() }
            }
            Label {
                visible: app.recording && bar.r.disk_minutes !== undefined
                text: bar.r.disk_minutes > 120 ? qsTr("disk %1 h").arg(Math.round(bar.r.disk_minutes / 60)) : qsTr("disk %1 min").arg(bar.r.disk_minutes)
                font.pixelSize: 12
                color: bar.r.disk_minutes < 30 ? theme.red : theme.foreground
                opacity: 0.7
            }
            Label {
                visible: bar.r.warnings !== undefined && bar.r.warnings.length > 0
                text: "⚠"
                color: theme.yellow
                font.pixelSize: 15
                ToolTip.visible: warnHover.hovered
                ToolTip.text: visible ? bar.r.warnings.join("\n") : ""
                HoverHandler { id: warnHover }
                TapHandler { onTapped: resources.open() }
            }
        }
    }

    ColumnLayout {
        id: lines
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 8
        anchors.topMargin: 5
        anchors.bottomMargin: 5
        spacing: 2

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 30
            spacing: 14

            RowLayout {
                id: whereAmI
                spacing: 12
                Layout.fillWidth: true
                Layout.maximumWidth: implicitWidth
                Rectangle {
                    width: 12
                    height: 12
                    radius: 6
                    visible: app.recording
                    color: app.state === "paused" ? theme.yellow : app.rehearsal ? theme.accent : theme.red
                    SequentialAnimation on opacity {
                        running: app.recording && app.state !== "paused"
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.35; duration: 700 }
                        NumberAnimation { to: 1.0; duration: 700 }
                    }
                }
                Label {
                    visible: app.recording
                    font.bold: true
                    font.family: "monospace"
                    text: (app.state === "paused" ? qsTr("PAUSED") : app.rehearsal ? qsTr("REHEARSAL") : app.state === "review" ? qsTr("PICKUPS") : qsTr("REC")) + "  " + bar.clock(app.sessionTime)
                }
                Label {
                    visible: text !== ""
                    text: app.hasProject && (app.page === "session" || app.page === "editor") ? app.projectTitle + (bar.place ? "  ›" : "") : ""
                    opacity: 0.6
                    elide: Text.ElideRight
                    Layout.maximumWidth: 260
                }
                // Only as wide as it needs, so the sentence counter sits right after it.
                Label {
                    visible: bar.place !== ""
                    text: bar.place
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                    Layout.maximumWidth: implicitWidth
                    Layout.minimumWidth: 60
                }
                Label {
                    visible: app.page === "session" && app.hasScript && app.progress.total > 0
                    text: qsTr("sentence %1/%2").arg(app.progress.index).arg(app.progress.total)
                    opacity: 0.6
                }
                Label {
                    visible: app.page === "session" && app.takesModel.count > 0
                    text: app.rehearsal ? qsTr("%n rehearsal take(s), not saved", "", app.takesModel.count) : qsTr("%n take(s)", "", app.takesModel.count)
                    opacity: 0.6
                }
            }

            Item { Layout.fillWidth: true }

            Row {
                id: engines
                spacing: 12
                Repeater {
                    model: [["tracking", qsTr("following")], ["commands", qsTr("commands")], ["scorer", qsTr("coach")], ["tts", qsTr("voice")]]
                    delegate: Row {
                        required property var modelData
                        property var info: app.engines[modelData[0]]
                        visible: info !== undefined
                        spacing: 5
                        Rectangle {
                            width: 8
                            height: 8
                            radius: 4
                            anchors.verticalCenter: parent.verticalCenter
                            color: info ? bar.engineColor(info.state) : theme.muted
                        }
                        Label {
                            text: modelData[1]
                            font.pixelSize: 12
                            opacity: info && info.state === "ready" ? 0.9 : 0.6
                            ToolTip.visible: hover.hovered
                            ToolTip.text: info ? info.engine + ": " + info.state + (info.detail ? " — " + info.detail : "") : ""
                            HoverHandler { id: hover }
                        }
                    }
                }
            }

            Loader { id: metersWide; sourceComponent: metersComponent; visible: !bar.twoLines }

            ToolButton {
                id: help
                text: "?"
                font.bold: true
                implicitHeight: 30
                onClicked: window.helpVisible = !window.helpVisible
            }
        }

        RowLayout {
            visible: bar.twoLines
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            spacing: 12
            Loader { sourceComponent: switcherComponent; active: bar.twoLines }
            Item { Layout.fillWidth: true }
            Loader { sourceComponent: metersComponent; active: bar.twoLines }
        }
    }

    Loader {
        id: switcherWide
        sourceComponent: switcherComponent
        visible: !bar.twoLines
        x: Math.round((bar.width - width) / 2)
        y: lines.y + Math.round((30 - height) / 2)
    }

    Popup {
        id: resources
        x: bar.width - width - 8
        y: bar.height + 4
        width: 340
        height: 300
        padding: 12
        ResourcesPanel { anchors.fill: parent }
    }
}
