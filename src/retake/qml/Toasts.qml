import QtQuick
import QtQuick.Controls

Item {
    id: toasts

    ListModel { id: messages }

    function push(kind, text) {
        if (!text)
            return
        for (let i = 0; i < messages.count; i++)
            if (messages.get(i).text === text)
                return
        messages.append({ kind: kind, text: text, born: Date.now() })
        if (messages.count > 4)
            messages.remove(0)
    }

    Connections {
        target: app
        function onNotice(kind, text) { toasts.push(kind, text) }
    }
    Connections {
        target: editor
        function onMessage(kind, text) { toasts.push(kind, text) }
    }

    Timer {
        interval: 500
        running: messages.count > 0
        repeat: true
        onTriggered: {
            const now = Date.now()
            for (let i = messages.count - 1; i >= 0; i--) {
                const item = messages.get(i)
                if (now - item.born > (item.kind === "error" ? 7000 : 3500))
                    messages.remove(i)
            }
        }
    }

    Column {
        anchors.bottom: parent.bottom
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottomMargin: 120
        spacing: 8
        Repeater {
            model: messages
            delegate: Rectangle {
                required property string kind
                required property string text
                width: Math.min(toasts.width - 80, label.implicitWidth + 32)
                height: label.implicitHeight + 18
                radius: 8
                color: kind === "error" ? Qt.rgba(0.6, 0.12, 0.12, 0.95) : Qt.rgba(0.08, 0.08, 0.08, 0.92)
                border.color: kind === "error" ? theme.red : kind === "off-script" ? theme.yellow : "transparent"
                anchors.horizontalCenter: parent ? parent.horizontalCenter : undefined
                Label {
                    id: label
                    anchors.centerIn: parent
                    width: Math.min(implicitWidth, toasts.width - 112)
                    text: parent.text
                    wrapMode: Text.Wrap
                    color: "white"
                }
            }
        }
    }
}
