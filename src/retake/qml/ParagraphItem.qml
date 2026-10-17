import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: item
    required property var prompter
    required property int paragraph
    required property string section
    required property int sectionLevel
    required property string kind
    required property string note
    required property var sentences
    spacing: prompter.fontSize * 0.35

    property var tokens: {
        const result = []
        for (const sentence of sentences)
            for (const token of sentence.tokens)
                result.push(Object.assign({ sentence: sentence.index }, token))
        return result
    }

    Label {
        visible: item.section !== ""
        text: item.section
        width: parent.width
        font.pixelSize: Math.max(13, item.prompter.fontSize * (item.sectionLevel <= 1 ? 0.5 : 0.42))
        font.capitalization: Font.AllUppercase
        font.letterSpacing: 2
        color: theme.accent
        opacity: 0.75
        topPadding: item.prompter.fontSize * 0.5
    }

    Rectangle {
        visible: item.kind === "adlib"
        width: parent.width
        height: adlibText.implicitHeight + 28
        radius: 10
        color: "transparent"
        border.color: theme.accent
        border.width: 1
        opacity: item.sentences.length && item.sentences[0].index === app.currentSentence ? 1 : 0.5
        Label {
            id: adlibText
            anchors.fill: parent
            anchors.margins: 14
            wrapMode: Text.Wrap
            font.pixelSize: item.prompter.fontSize * 0.55
            text: qsTr("Ad-lib") + (item.note ? ":  " + item.note : "")
            color: theme.foreground
        }
    }

    Flow {
        visible: item.kind !== "adlib"
        width: parent.width
        spacing: item.prompter.fontSize * 0.28
        Repeater {
            model: item.tokens
            delegate: TokenItem {
                required property var modelData
                token: modelData
                prompter: item.prompter
            }
        }
    }
}
