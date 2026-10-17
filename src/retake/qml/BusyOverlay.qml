import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: overlay
    property string text
    property string hint
    property bool fadeIn: false
    visible: text !== ""
    color: Qt.alpha(theme.background, 0.85)

    // An animator runs on the render thread, so it plays while the GUI thread is busy; the slow start
    // keeps quick jobs from flashing the overlay.
    OpacityAnimator {
        target: overlay
        from: 0
        to: 1
        duration: 450
        easing.type: Easing.InQuint
        running: overlay.visible && overlay.fadeIn
    }

    MouseArea { anchors.fill: parent; hoverEnabled: true }
    ColumnLayout {
        anchors.centerIn: parent
        spacing: 16
        BusyIndicator { running: overlay.visible; Layout.alignment: Qt.AlignHCenter; Layout.preferredWidth: 64; Layout.preferredHeight: 64 }
        Label { text: overlay.text; font.pixelSize: 18; Layout.alignment: Qt.AlignHCenter }
        Label { visible: overlay.hint !== ""; text: overlay.hint; opacity: 0.6; Layout.alignment: Qt.AlignHCenter }
    }
}
