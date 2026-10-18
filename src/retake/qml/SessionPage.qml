import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    property var panels: app.panels
    property bool strip: panels.strip === true
    // The coach panel only says "off" when the coach is disabled; its room goes to the takes instead.
    property bool coachShown: panels.coach === true && app.settings.coach.enabled === true
    // No camera chosen in Settings → Recording: no camera panel.
    property bool cameraShown: panels.camera === true && app.cameraSource !== "none"
    property bool sidebar: !strip && (coachShown || panels.takes || cameraShown)

    RowLayout {
        anchors.fill: parent
        anchors.margins: page.strip ? 0 : 10
        spacing: 10

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            Prompter {
                anchors.fill: parent
                visible: !page.strip
            }
            CardView {
                anchors.fill: parent
                visible: page.strip
                compact: true
            }

            ReadyHint { anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 18 }
            DrillCard { anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 18 }
        }

        ColumnLayout {
            visible: page.sidebar
            Layout.fillWidth: false
            Layout.preferredWidth: Math.min(520, page.width * 0.36)
            Layout.maximumWidth: Math.min(520, page.width * 0.36)
            Layout.fillHeight: true
            spacing: 10

            Panel {
                title: qsTr("Camera")
                visible: page.cameraShown
                Layout.fillWidth: true
                // Portrait phone recordings get a tall panel so the preview keeps the recording's shape.
                Layout.preferredHeight: (app.phonePortrait ? Math.min(width * 16 / 9, page.height * 0.72) : width * 9 / 16) + 34
                CameraPreview { anchors.fill: parent }
            }
            Panel {
                title: qsTr("Coach")
                visible: page.coachShown
                Layout.fillWidth: true
                Layout.fillHeight: true
                CoachPanel { anchors.fill: parent }
            }
            Panel {
                title: app.rehearsal ? qsTr("Takes · rehearsal, not saved") : qsTr("Takes")
                visible: page.panels.takes === true
                Layout.fillWidth: true
                // Compact: the camera and the coach need the room more; the list scrolls.
                Layout.preferredHeight: 150
                Layout.fillHeight: !page.coachShown
                TakesPanel { anchors.fill: parent }
            }
        }
    }
}
