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
            : app.recording && !app.settings.video.phone_preview ? qsTr("The phone is recording; its preview is off while it does (Settings → Recording)")
            : qsTr("Waiting for the phone camera…")
        wrapMode: Text.Wrap
        horizontalAlignment: Text.AlignHCenter
        width: parent.width - 24
        opacity: 0.6
    }

    Row {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 8
        spacing: 6
        visible: app.videoBackend === "builtin"
        Repeater {
            model: [["corner", qsTr("Corner")], ["full", qsTr("Full")], ["off", qsTr("Off")]]
            delegate: Button {
                required property var modelData
                text: modelData[1]
                flat: app.cameraLayout !== modelData[0]
                highlighted: app.cameraLayout === modelData[0]
                font.pixelSize: 12
                onClicked: app.setCameraLayout(modelData[0])
            }
        }
    }
}
