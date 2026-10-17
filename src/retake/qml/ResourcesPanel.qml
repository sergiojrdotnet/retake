import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Flickable {
    id: panel
    property var r: app.resources
    contentHeight: grid.implicitHeight
    clip: true

    function bar(value) { return Math.max(0, Math.min(1, (value || 0) / 100)) }

    ColumnLayout {
        id: grid
        width: panel.width
        spacing: 6

        Repeater {
            model: [
                [qsTr("CPU"), panel.r.cpu, panel.r.cpu + "%"],
                [qsTr("GPU"), panel.r.gpu, panel.r.gpu === null || panel.r.gpu === undefined ? qsTr("n/a") : panel.r.gpu + "%"],
                [qsTr("Encoder"), panel.r.encoder, panel.r.encoder === null || panel.r.encoder === undefined ? qsTr("n/a") : panel.r.encoder + "%"],
            ]
            delegate: RowLayout {
                required property var modelData
                Layout.fillWidth: true
                Label { text: modelData[0]; Layout.preferredWidth: 64; font.pixelSize: 12; opacity: 0.7 }
                Rectangle {
                    Layout.fillWidth: true
                    height: 6
                    radius: 3
                    color: Qt.darker(theme.surface, 1.4)
                    Rectangle { width: parent.width * panel.bar(modelData[1]); height: parent.height; radius: 3; color: theme.accent }
                }
                Label { text: modelData[2]; Layout.preferredWidth: 46; horizontalAlignment: Text.AlignRight; font.pixelSize: 12 }
            }
        }
        Label { text: qsTr("RAM %1 (%2 GB free)").arg(panel.r.ram).arg(panel.r.ram_available_gb); font.pixelSize: 12 }
        Label { visible: !!panel.r.vram; text: qsTr("VRAM %1  ·  %2 °C").arg(panel.r.vram).arg(panel.r.temperature); font.pixelSize: 12 }
        Label { text: qsTr("Disk: %1 left  ·  writing %2 MB/s").arg(panel.r.disk_minutes > 120 ? Math.round(panel.r.disk_minutes / 60) + " h" : panel.r.disk_minutes + " min").arg(panel.r.disk_write); font.pixelSize: 12 }
        Label {
            visible: panel.r.latency !== undefined && Object.keys(panel.r.latency).length > 0
            text: panel.r.latency ? qsTr("Latency: ") + Object.keys(panel.r.latency).map(k => k + " " + panel.r.latency[k] + "s").join("  ·  ") : ""
            font.pixelSize: 12
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }
        Label { text: qsTr("Processes"); font.pixelSize: 11; opacity: 0.5; topPadding: 4 }
        Repeater {
            model: panel.r.processes ? Object.keys(panel.r.processes) : []
            delegate: Label {
                required property string modelData
                property var p: panel.r.processes[modelData]
                text: modelData + ": " + Math.round(p.cpu) + "% CPU  ·  " + Math.round(p.rss_mb) + " MB" + (p.vram_mb > 0 ? "  ·  " + Math.round(p.vram_mb) + " MB VRAM" : "")
                font.pixelSize: 12
            }
        }
        Label { visible: !!panel.r.gpu_processes && panel.r.gpu_processes.length > 0; text: qsTr("Using the GPU"); font.pixelSize: 11; opacity: 0.5; topPadding: 4 }
        Repeater {
            model: panel.r.gpu_processes || []
            delegate: Label {
                required property var modelData
                text: modelData.name + " (" + modelData.pid + "): " + modelData.memory_mb + " MB"
                font.pixelSize: 12
            }
        }
        Repeater {
            model: panel.r.warnings || []
            delegate: Label {
                required property string modelData
                text: "⚠ " + modelData
                color: theme.yellow
                font.pixelSize: 12
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
        }
    }
}
