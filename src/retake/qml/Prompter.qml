import QtQuick
import QtQuick.Controls

Item {
    id: root
    clip: true

    property var prompter: app.settings.prompter
    // Read once here for every word: each read of app.settings converts the whole settings map.
    property var guides: app.settings.guides
    property bool showCues: prompter.show_cues
    property bool animate: prompter.animation === true
    property var wordMarks: app.wordMarks
    property string mode: app.displayMode
    property real fontSize: prompter.font_size
    property real readingLine: prompter.reading_line
    property var wordItems: ({})
    property int lastLineY: -1

    transform: Scale { origin.x: root.width / 2; xScale: root.prompter.mirror ? -1 : 1 }

    function register(index, item) { wordItems[index] = item }

    function openWordMenu(token) {
        wordMenu.word = token.word
        wordMenu.text = token.text.replace(/[.,;:!?"'()]/g, "")
        wordMenu.flagged = token.flagged === true
        wordMenu.coached = app.isCoached(token.word)
        wordMenu.popup()
    }

    Menu {
        id: wordMenu
        property int word: -1
        property string text: ""
        property bool flagged: false
        property bool coached: true
        MenuItem { text: qsTr("Listen to “%1”").arg(wordMenu.text); onTriggered: app.listenTo(wordMenu.text) }
        MenuItem { text: wordMenu.flagged ? qsTr("Unflag") : qsTr("Flag for practice"); onTriggered: app.toggleFlag(wordMenu.word) }
        MenuItem { text: wordMenu.coached ? qsTr("Don't coach this word") : qsTr("Coach this word again"); onTriggered: app.toggleCoached(wordMenu.word) }
    }
    function unregister(index, item) { if (wordItems[index] === item) delete wordItems[index] }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        property var guides: app.settings.guides
        property real guideSize: Math.max(11, root.fontSize * 0.36)
        property int rows: (guides.ipa ? 1 : 0) + (guides.respell ? 1 : 0) + (guides.native ? 1 : 0)
        y: root.height * root.readingLine + rows * guideSize * 1.32 - root.fontSize * 0.1
        height: root.fontSize * 1.5
        color: Qt.rgba(1, 1, 1, 0.035)
        visible: root.mode === "scroll" || root.mode === "step"
    }

    Flickable {
        id: flick
        anchors.fill: parent
        visible: root.mode === "scroll" || root.mode === "step"
        contentWidth: width
        contentHeight: column.height + height
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick

        NumberAnimation on contentY {
            id: glide
            running: false
            easing.type: Easing.OutCubic
        }

        Column {
            id: column
            width: flick.width * root.prompter.line_width
            x: (flick.width - width) / 2
            topPadding: flick.height * root.readingLine
            spacing: root.fontSize * 0.9
            Repeater {
                model: app.paragraphModel
                delegate: ParagraphItem {
                    width: column.width
                    prompter: root
                }
            }
        }
    }

    Item {
        id: pageView
        anchors.fill: parent
        visible: root.mode === "page"
        property var row: app.paragraphModel.count > 0 ? app.paragraphModel.get(app.currentParagraph) : null
        Loader {
            id: pageLoader
            active: pageView.visible && pageView.row !== null
            width: parent.width * root.prompter.line_width
            anchors.centerIn: parent
            sourceComponent: ParagraphItem {
                width: pageLoader.width
                prompter: root
                paragraph: pageView.row.paragraph
                section: pageView.row.section
                sectionLevel: pageView.row.sectionLevel
                kind: pageView.row.kind
                note: pageView.row.note
                sentences: pageView.row.sentences
            }
            onLoaded: fade.restart()
            NumberAnimation { id: fade; target: pageLoader; property: "opacity"; from: 0.2; to: 1; duration: root.prompter.animation ? 220 : 0 }
        }
        Connections {
            target: app
            function onPositionChanged() { pageView.row = app.paragraphModel.count > 0 ? app.paragraphModel.get(app.currentParagraph) : null }
        }
    }

    CardView {
        anchors.fill: parent
        visible: root.mode === "card"
    }

    function follow() {
        if (!(mode === "scroll" || mode === "step"))
            return
        const target = wordItems[app.currentWord + 1] || wordItems[app.currentWord]
        if (!target)
            return
        const point = target.mapToItem(column, 0, 0)
        const desired = Math.max(0, point.y - flick.height * readingLine)
        if (mode === "step") {
            const lineY = Math.round(point.y)
            if (lineY === lastLineY)
                return
            lastLineY = lineY
        }
        glide.stop()
        if (!prompter.animation) {
            flick.contentY = desired
            return
        }
        glide.from = flick.contentY
        glide.to = desired
        glide.duration = mode === "step" ? 260 : 520
        glide.start()
    }

    Connections {
        target: app
        function onPositionChanged() { Qt.callLater(root.follow) }
        function onScriptChanged() { root.lastLineY = -1; flick.contentY = 0 }
    }
    onModeChanged: { lastLineY = -1; Qt.callLater(follow) }
    onHeightChanged: Qt.callLater(follow)
}
