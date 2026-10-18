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
    // A portrait camera keeps most of the height, so the coach and the takes share one panel as tabs.
    property bool tabbed: cameraShown && app.phonePortrait && coachShown && panels.takes === true
    property string tab: "coach"

    Connections {
        target: app
        function onCoachChanged() {
            if ((app.coach.flagged || []).length || (app.coach.deviations || []).length)
                page.tab = "coach"
        }
    }

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
                Layout.preferredHeight: (app.phonePortrait ? Math.min(width * 16 / 9, page.height * (page.tabbed ? 0.6 : 0.72)) : width * 9 / 16) + 34
                CameraPreview { anchors.fill: parent }
            }
            Panel {
                title: qsTr("Coach")
                visible: page.coachShown && !page.tabbed
                Layout.fillWidth: true
                Layout.fillHeight: true
                CoachPanel { anchors.fill: parent }
            }
            Panel {
                title: app.rehearsal ? qsTr("Takes · rehearsal, not saved") : qsTr("Takes")
                visible: page.panels.takes === true && !page.tabbed
                Layout.fillWidth: true
                // Compact: the camera and the coach need the room more; the list scrolls.
                Layout.preferredHeight: 150
                Layout.fillHeight: !page.coachShown
                TakesPanel { anchors.fill: parent }
            }
            Panel {
                visible: page.tabbed
                Layout.fillWidth: true
                Layout.fillHeight: true
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 10
                    RowLayout {
                        Layout.leftMargin: 2
                        spacing: 16
                        Repeater {
                            model: [
                                { key: "coach", text: qsTr("Coach") },
                                { key: "takes", text: app.rehearsal ? qsTr("Takes · rehearsal, not saved") : qsTr("Takes") },
                            ]
                            delegate: Label {
                                required property var modelData
                                property bool current: page.tab === modelData.key
                                text: modelData.text
                                font.pixelSize: 12
                                font.capitalization: Font.AllUppercase
                                font.letterSpacing: 1.2
                                font.bold: current
                                color: current ? theme.accent : theme.foreground
                                opacity: current ? 1 : 0.5
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: page.tab = modelData.key
                                }
                            }
                        }
                    }
                    StackLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        currentIndex: page.tab === "coach" ? 0 : 1
                        CoachPanel {}
                        TakesPanel {}
                    }
                }
            }
        }
    }
}
