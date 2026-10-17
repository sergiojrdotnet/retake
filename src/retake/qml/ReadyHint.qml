import QtQuick
import QtQuick.Controls

Rectangle {
    visible: !app.recording && app.page === "session"
    radius: 18
    color: app.pickupPending ? Qt.alpha(theme.accent, 0.25) : Qt.rgba(0, 0, 0, 0.55)
    border.color: app.pickupPending ? theme.accent : "transparent"
    // Never wider than the prompter: on a narrow window the hint wraps instead of running off the edge.
    width: Math.min(hint.implicitWidth + 36, parent ? parent.width - 24 : hint.implicitWidth + 36)
    height: hint.height + 16
    Label {
        id: hint
        anchors.centerIn: parent
        width: parent.width - 36
        wrapMode: Text.Wrap
        horizontalAlignment: Text.AlignHCenter
        text: app.pickupPending
            ? qsTr("Pickups: %1  ·  Space to record them  ·  Esc goes back to the studio").arg((app.review.queue || []).map(s => "S" + (s + 1)).join(", "))
            : qsTr("Space to record  ·  Shift+Space to rehearse  ·  P to check the script  ·  ? for shortcuts")
        opacity: 0.85
    }
}
