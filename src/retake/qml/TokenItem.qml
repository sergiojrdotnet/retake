import QtQuick
import QtQuick.Controls

Item {
    id: item
    required property var token
    required property var prompter
    property var guides: prompter && prompter.guides ? prompter.guides : app.settings.guides
    property real fontSize: prompter ? prompter.fontSize : 40
    property bool isWord: token.kind === "word"
    property bool currentSentence: token.sentence === app.currentSentence
    property bool spoken: isWord && token.word <= app.currentWord
    property bool next: isWord && token.word === app.currentWord + 1
    property bool showGuide: isWord && token.guide === true
    property string mark: isWord && !!prompter && !!prompter.wordMarks ? (prompter.wordMarks[String(token.word)] || "") : ""
    property color markColor: mark === "red" ? theme.red : theme.yellow
    property bool cues: prompter && prompter.showCues !== undefined ? prompter.showCues : app.settings.prompter.show_cues
    property real guideSize: Math.max(11, fontSize * 0.36)
    property int guideRows: (guides.ipa ? 1 : 0) + (guides.respell ? 1 : 0) + (guides.native ? 1 : 0)
    property real lineHeight: fontSize * 1.28 + guideRows * guideSize * 1.32

    implicitWidth: isWord ? wordColumn.implicitWidth : (visible ? other.implicitWidth : 0)
    implicitHeight: lineHeight
    width: implicitWidth
    height: implicitHeight
    visible: isWord || cues || token.kind === "pause" || token.kind === "text"
    opacity: currentSentence ? 1.0 : 0.38

    Behavior on opacity { enabled: item.prompter && item.prompter.animate !== undefined ? item.prompter.animate : app.settings.prompter.animation === true; NumberAnimation { duration: 180 } }

    Component.onCompleted: if (isWord && prompter && prompter.register) prompter.register(token.word, item)
    Component.onDestruction: if (isWord && prompter && prompter.unregister) prompter.unregister(token.word, item)

    Column {
        id: wordColumn
        visible: item.isWord
        anchors.bottom: parent.bottom
        spacing: 0
        Label {
            visible: item.guides.ipa === true
            text: item.showGuide ? (item.token.ipa || "") : ""
            font.pixelSize: item.guideSize
            height: item.guideSize * 1.32
            color: theme.accent
            opacity: 0.85
            anchors.horizontalCenter: parent.horizontalCenter
        }
        Label {
            visible: item.guides.respell === true
            text: item.showGuide ? (item.token.respell || "") : ""
            font.pixelSize: item.guideSize
            height: item.guideSize * 1.32
            color: theme.accent
            opacity: 0.85
            anchors.horizontalCenter: parent.horizontalCenter
        }
        Label {
            visible: item.guides.native === true
            text: item.showGuide ? (item.token.native || "") : ""
            font.pixelSize: item.guideSize
            height: item.guideSize * 1.32
            color: theme.yellow
            opacity: 0.85
            anchors.horizontalCenter: parent.horizontalCenter
        }
        Text {
            id: wordText
            text: item.token.text || ""
            font.pixelSize: item.fontSize
            font.bold: item.token.emphasis === true
            color: item.mark !== "" ? item.markColor : item.next ? theme.accent : theme.foreground
            opacity: item.spoken && item.currentSentence && item.mark === "" ? 0.45 : 1.0
            anchors.horizontalCenter: parent.horizontalCenter
            Rectangle {
                visible: item.next || item.mark !== ""
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.bottom
                height: 3
                radius: 1.5
                color: item.mark !== "" ? item.markColor : theme.accent
            }
            Rectangle {
                visible: item.token.flagged === true
                width: 7; height: 7; radius: 3.5
                color: theme.red
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.rightMargin: -6
            }
        }
    }

    Label {
        id: other
        visible: !item.isWord
        anchors.bottom: parent.bottom
        text: item.token.kind === "text" ? item.token.text
              : item.token.kind === "pause" ? (item.token.value === "long" ? "//" : "/")
              : item.token.kind === "scene" ? "▣ " + item.token.value
              : item.token.kind === "camera" ? "◉ " + item.token.value
              : "(" + item.token.text + ")"
        font.pixelSize: item.token.kind === "pause" || item.token.kind === "text" ? item.fontSize : item.fontSize * 0.5
        font.italic: item.token.kind === "cue"
        font.bold: item.token.kind === "pause"
        color: item.token.kind === "pause" ? theme.accent : item.token.kind === "text" ? theme.foreground : theme.muted
        bottomPadding: item.token.kind === "pause" || item.token.kind === "text" ? 0 : item.fontSize * 0.18
    }

    MouseArea {
        anchors.fill: parent
        enabled: item.isWord
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.PointingHandCursor
        onClicked: (mouse) => {
            if (mouse.button === Qt.RightButton && item.prompter && item.prompter.openWordMenu) item.prompter.openWordMenu(item.token)
            else if (mouse.button === Qt.RightButton) app.listenTo(item.token.text.replace(/[.,;:!?"'()]/g, ""))
            else app.toggleFlag(item.token.word)
        }
        onDoubleClicked: app.jumpTo(item.token.sentence)
    }
}
