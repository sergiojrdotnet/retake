import QtQuick
import QtQuick.Controls
import QtMultimedia

Rectangle {
    id: preview
    color: "black"
    radius: 6
    clip: true

    VideoOutput {
        id: output
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectFit
    }

    Component.onCompleted: {
        app.forwardFrames(cameraRig.output, output)
        app.setPhoneOutput(output)
    }

    Label {
        anchors.centerIn: parent
        visible: app.phoneMode ? !app.phonePreviewActive : !cameraRig.hasCamera
        text: !app.phoneMode ? qsTr("No camera found")
            : !app.phoneLoopback ? qsTr("The phone preview needs the virtual camera: Settings → Recording → Check phone")
            : app.recording && !app.settings.phone.preview ? qsTr("The phone is recording; its preview is off while it does (Settings → Recording)")
            : qsTr("Waiting for the phone camera…")
        wrapMode: Text.Wrap
        horizontalAlignment: Text.AlignHCenter
        width: parent.width - 24
        opacity: 0.6
    }
}
