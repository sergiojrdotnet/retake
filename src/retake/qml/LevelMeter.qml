import QtQuick
import QtQuick.Controls

Item {
    id: meter
    property var level: app.level
    property var peaks: level.peak || [-90]
    property var rms: level.rms || [-90]
    property var holds: []

    function fraction(db) { return Math.max(0, Math.min(1, (db + 60) / 60)) }

    Timer {
        interval: 1500
        running: true
        repeat: true
        onTriggered: meter.holds = []
    }
    onPeaksChanged: {
        const next = meter.holds.slice()
        for (let i = 0; i < peaks.length; i++)
            next[i] = Math.max(next[i] === undefined ? -90 : next[i], peaks[i])
        meter.holds = next
    }

    Column {
        anchors.fill: parent
        spacing: 4
        Repeater {
            model: meter.peaks.length
            delegate: Rectangle {
                required property int index
                width: parent.width
                height: Math.max(6, (meter.height - 4 * (meter.peaks.length - 1)) / meter.peaks.length)
                radius: 3
                color: Qt.darker(theme.surface, 1.4)
                Rectangle {
                    height: parent.height
                    radius: 3
                    width: parent.width * meter.fraction(meter.rms[index])
                    color: meter.rms[index] > -6 ? theme.red : meter.rms[index] > -18 ? theme.yellow : theme.green
                    Behavior on width { NumberAnimation { duration: 60 } }
                }
                Rectangle {
                    width: 2
                    height: parent.height
                    x: parent.width * meter.fraction(meter.holds[index] === undefined ? -90 : meter.holds[index]) - 1
                    color: theme.foreground
                    opacity: 0.8
                }
            }
        }
    }
    Rectangle {
        visible: meter.level.clip === true
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: 38; height: 18; radius: 4
        color: theme.red
        Label { anchors.centerIn: parent; text: qsTr("CLIP"); font.pixelSize: 10; font.bold: true }
    }
}
