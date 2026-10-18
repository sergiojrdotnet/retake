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

    // One run of words for the paragraph, or one per sentence when each sentence starts a line.
    property var lines: {
        const result = []
        for (const sentence of sentences) {
            if (!result.length || prompter.sentenceLines)
                result.push([])
            for (const token of sentence.tokens)
                result[result.length - 1].push(Object.assign({ sentence: sentence.index }, token))
        }
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

    Repeater {
        model: item.kind !== "adlib" ? item.lines : []
        delegate: Flow {
            required property var modelData
            width: item.width
            spacing: item.prompter.fontSize * 0.28
            Repeater {
                model: modelData
                delegate: TokenItem {
                    required property var modelData
                    token: modelData
                    prompter: item.prompter
                }
            }
        }
    }
}
