import QtQuick
import QtQuick.Controls

Item {
    id: card
    property bool compact: false
    property var cardData: app.card
    property real fontSize: compact ? Math.min(app.settings.prompter.font_size, Math.max(18, height / 6)) : app.settings.prompter.font_size * 1.15
    clip: true

    function tokens(sentence) {
        if (!sentence)
            return []
        return sentence.tokens.map(token => Object.assign({ sentence: sentence.index }, token))
    }

    QtObject {
        id: cardScale
        property real fontSize: card.fontSize
        function register() {}
        function unregister() {}
    }
    QtObject {
        id: smallScale
        property real fontSize: card.fontSize * 0.6
        function register() {}
        function unregister() {}
    }

    Column {
        width: parent.width * (card.compact ? 0.94 : app.settings.prompter.line_width)
        anchors.centerIn: parent
        spacing: card.fontSize * 0.6

        Flow {
            width: parent.width
            visible: !card.compact && !!card.cardData.previous
            spacing: smallScale.fontSize * 0.3
            opacity: 0.6
            Repeater {
                model: card.tokens(card.cardData.previous)
                delegate: TokenItem { required property var modelData; token: modelData; prompter: smallScale }
            }
        }
        Rectangle {
            visible: !!card.cardData.current && card.cardData.current.kind === "adlib"
            width: parent.width
            height: 60
            radius: 10
            color: "transparent"
            border.color: theme.accent
            Label { anchors.centerIn: parent; text: qsTr("Ad-lib — talk freely, then read on"); color: theme.accent; font.pixelSize: card.fontSize * 0.5 }
        }
        Flow {
            width: parent.width
            spacing: card.fontSize * 0.3
            Repeater {
                model: card.tokens(card.cardData.current)
                delegate: TokenItem { required property var modelData; token: modelData; prompter: cardScale }
            }
        }
        Flow {
            width: parent.width
            visible: card.cardData.next !== null && card.cardData.next !== undefined
            spacing: smallScale.fontSize * 0.3
            Repeater {
                model: card.tokens(card.cardData.next)
                delegate: TokenItem { required property var modelData; token: modelData; prompter: smallScale; opacity: 0.5 }
            }
        }
    }

}
