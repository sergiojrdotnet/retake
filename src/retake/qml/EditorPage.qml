import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import Retake 1.0

Item {
    id: page
    signal exportRequested(string kind)
    property real playhead: 0
    property real userPps: 0
    property real pps: userPps > 0 ? userPps : fitPps
    property real fitPps: Math.max(2, (timelineFlick.width - 20) / Math.max(1, timelineDuration))
    // The timeline is the script: the edit as it plays, kept clips back to back. V shows what was cut:
    // each take in use whole, still in script order, its cuts greyed. With nothing kept, the raw
    // recording shows on its own clock.
    property bool fullView: false
    property bool rawView: emptyEdit
    property bool blockView: fullView && !emptyEdit
    property var segments: editor.segments
    property var rows: rawView ? [] : (blockView ? editor.blocks : segments)
    property real rowsDuration: rows.length ? rows[rows.length - 1].editStart + rows[rows.length - 1].end - rows[rows.length - 1].start : 0
    property real timelineDuration: rawView ? editor.sourceDuration : rowsDuration
    property int focusSentence: selected.length === 1 ? selected[0] : editor.sentenceAt(playhead)
    // The script's sections as bands over the rows: each from its first sentence on the timeline to
    // its last (in script order a section's sentences sit together).
    property var chapters: {
        const bySentence = editor.scriptSections.bySentence || []
        const titles = editor.scriptSections.titles || []
        const bands = []
        for (const row of rows) {
            const section = row.sentence >= 0 && row.sentence < bySentence.length ? bySentence[row.sentence] : -1
            const end = row.editStart + row.end - row.start
            const last = bands.length ? bands[bands.length - 1] : null
            if (section >= 0 && (!last || last.section !== section)) {
                bands.push({ section: section, title: titles[section], start: row.editStart, end: end, sentences: [row.sentence] })
            } else if (last) {
                last.end = end
                if (row.sentence >= 0 && last.sentences.indexOf(row.sentence) < 0)
                    last.sentences.push(row.sentence)
            }
        }
        return bands
    }
    property real playheadPos: timelineX(playhead, true)
    property bool zoomed: false
    property bool playing: player.playbackState === MediaPlayer.PlayingState || resumeAfterLoad
    property bool emptyEdit: editor.loaded && editor.editDuration <= 0
    property bool nothingRecorded: editor.loaded && editor.sourceDuration <= 0
    property var parts: editor.parts
    property int partIndex: -1
    property real pendingTime: -1
    property bool seeking: false
    property bool syncingPicture: false
    property string pendingSource: ""
    property bool resumeAfterLoad: false
    property int currentRow: -1
    property real startAt: 0
    property var selected: []
    property int anchorSentence: -1
    property bool partHasVideo: partIndex >= 0 && partIndex < parts.length && parts[partIndex].hasVideo

    function clock(seconds) {
        const total = Math.max(0, seconds)
        const m = Math.floor(total / 60)
        const s = total - m * 60
        return m + ":" + (s < 10 ? "0" : "") + s.toFixed(1)
    }

    function partFor(t) {
        for (let i = 0; i < parts.length; i++) {
            if (t >= parts[i].start && t < parts[i].end)
                return i
        }
        return parts.length - 1
    }

    // Video may have had its waiting and pauses cut out: each segment says how the audio maps onto it.
    function offsetAt(part, local) {
        const segments = part.segments || []
        for (const segment of segments) {
            if (local < segment.end)
                return segment.offset
        }
        return segments.length ? segments[segments.length - 1].offset : part.videoOffset
    }

    function videoTime(part, local) {
        return local - offsetAt(part, local)
    }

    // The picture follows the audio: same part, same moment, through the video's time map.
    // Moving the picture makes it announce "loaded" again at once, which calls back in here.
    function syncPicture(force) {
        if (syncingPicture || partIndex < 0 || !partHasVideo || picture.mediaStatus === MediaPlayer.LoadingMedia || picture.mediaStatus === MediaPlayer.NoMedia)
            return
        syncingPicture = true
        try {
            const part = parts[partIndex]
            const local = (pendingTime >= 0 ? pendingTime - part.start : player.position / 1000)
            const target = videoTime(part, local)
            if (target < 0) {
                if (picture.playbackState === MediaPlayer.PlayingState)
                    picture.pause()
                if (picture.position !== 0)
                    picture.position = 0
                return
            }
            if (force || Math.abs(picture.position / 1000 - target) > 0.25)
                picture.position = target * 1000
            if (player.playbackState === MediaPlayer.PlayingState && picture.playbackState !== MediaPlayer.PlayingState)
                picture.play()
            else if (player.playbackState !== MediaPlayer.PlayingState && picture.playbackState === MediaPlayer.PlayingState)
                picture.pause()
        } finally {
            syncingPicture = false
        }
    }

    // Recording time to timeline time, the rows laid back to back; -1 when that moment isn't shown.
    function viewTime(t) {
        for (const row of rows) {
            if (t >= row.start && t < row.end)
                return row.editStart + (t - row.start)
        }
        return -1
    }

    function sourceTime(e) {
        for (const row of rows) {
            if (e < row.editStart + (row.end - row.start))
                return row.start + Math.max(0, e - row.editStart)
        }
        return rows.length ? rows[rows.length - 1].end : 0
    }

    // Where a recording moment sits on the timeline; a moment not shown is -1, or, with `nearest`,
    // the start of the next row.
    function timelineX(t, nearest) {
        if (rawView)
            return t * pps
        const e = viewTime(t)
        if (e >= 0 || !nearest)
            return e < 0 ? -1 : e * pps
        const next = rows.filter(s => s.start >= t).sort((a, b) => a.start - b.start)[0]
        return (next ? next.editStart : rowsDuration) * pps
    }

    function timeAtX(x) {
        return rawView ? x / pps : sourceTime(Math.max(0, x / pps))
    }

    // Previous / next clip edge, take or marker, in the order the timeline shows them.
    function jumpEdge(direction) {
        if (rawView) {
            seek(editor.nextEdge(playhead, direction))
            return
        }
        const points = []
        for (const row of rows)
            points.push(row.editStart, row.editStart + row.end - row.start)
        const marks = editor.markPoints()
        if (blockView) {
            for (const clip of editor.clips)
                marks.push(clip.start, clip.end)
        }
        for (const t of marks) {
            const e = viewTime(t)
            if (e >= 0)
                points.push(e)
        }
        points.sort((a, b) => a - b)
        const now = playheadPos / pps
        const target = direction > 0 ? points.find(p => p > now + 0.02) : points.slice().reverse().find(p => p < now - 0.02)
        seek(sourceTime(target === undefined ? (direction > 0 ? rowsDuration : 0) : target))
    }

    // 0-9: that tenth of the timeline.
    function jumpToTenth(tenth) {
        if (rawView)
            seek(editor.sourceDuration * tenth / 10)
        else
            seek(sourceTime(rowsDuration * tenth / 10))
    }

    function toggleView() {
        fullView = !fullView
        currentRow = -1
        Qt.callLater(() => { timelineFlick.contentX = Math.max(0, Math.min(timelineFlick.contentWidth - timelineFlick.width, playheadPos - timelineFlick.width * 0.3)) })
    }

    function seek(t) {
        playhead = Math.max(0, Math.min(editor.sourceDuration, t))
        const x = timelineX(playhead, true)
        if (x < timelineFlick.contentX || x > timelineFlick.contentX + timelineFlick.width - 40)
            timelineFlick.contentX = Math.max(0, x - timelineFlick.width * 0.3)
        if (parts.length === 0)
            return
        const i = partFor(playhead)
        if (i !== partIndex) {
            resumeAfterLoad = player.playbackState === MediaPlayer.PlayingState || resumeAfterLoad
            partIndex = i
            pendingTime = playhead
            pendingSource = parts[i].audioUrl
            player.source = pendingSource
            picture.source = parts[i].hasVideo ? parts[i].videoUrl : ""
            return
        }
        if (pendingTime >= 0) {
            pendingTime = playhead
            return
        }
        // Moving the player reports the new position at once, rounded to the millisecond and so a hair
        // before a clip's start; reacting to that report would look for the clip again, endlessly.
        seeking = true
        player.position = Math.max(0, (playhead - parts[i].start) * 1000)
        seeking = false
        syncPicture(true)
    }

    function nudge(delta) {
        if (rawView) {
            seek(playhead + delta)
            return
        }
        seek(sourceTime(Math.max(0, playheadPos / pps + delta)))
    }

    // Zooming keeps the moment under the mouse, or the playhead, at the same place on screen.
    function zoomTo(newPps, anchorX) {
        const time = (timelineFlick.contentX + anchorX) / pps
        userPps = Math.max(fitPps, Math.min(400, newPps))
        zoomed = userPps > fitPps + 0.01
        timelineFlick.contentX = Math.max(0, Math.min(timelineFlick.contentWidth - timelineFlick.width, time * pps - anchorX))
    }

    function playheadX() {
        const x = playheadPos - timelineFlick.contentX
        return x >= 0 && x <= timelineFlick.width ? x : timelineFlick.width / 2
    }

    function zoomBy(factor) { zoomTo(pps * factor, playheadX()) }

    function zoomFit() {
        userPps = 0
        zoomed = false
        timelineFlick.contentX = 0
    }

    function toggleZoom() {
        if (zoomed) {
            zoomFit()
            return
        }
        const clip = editor.clipAt(playhead)
        if (!clip) {
            zoomBy(4)
            return
        }
        userPps = Math.max(fitPps, Math.min(400, (timelineFlick.width - 80) / Math.max(1, clip.end - clip.start)))
        zoomed = true
        timelineFlick.contentX = Math.max(0, Math.min(timelineFlick.contentWidth - timelineFlick.width, timelineX(clip.start, true) - 40))
    }

    function play() {
        if (pendingTime >= 0) {
            resumeAfterLoad = true
        } else {
            player.play()
            syncPicture(true)
        }
    }

    function pause() {
        resumeAfterLoad = false
        player.pause()
        picture.pause()
    }

    function togglePlay() {
        if (playing) {
            pause()
            return
        }
        if (rawView) {
            if (playhead >= editor.sourceDuration - 0.05)
                seek(0)
            play()
            return
        }
        let index = rows.findIndex(r => playhead >= r.start && playhead < r.end - 0.01)
        if (index < 0 || playheadPos >= (rowsDuration - 0.05) * pps)
            index = playheadPos >= (rowsDuration - 0.05) * pps || playhead <= 0.05 ? 0 : nextRowAfter(playhead)
        if (index < 0 || !rows.length)
            return
        if (!(playhead >= rows[index].start && playhead < rows[index].end - 0.01))
            seek(rows[index].start)
        currentRow = index
        play()
    }

    function nextRowAfter(t) {
        let best = -1
        for (let i = 0; i < rows.length; i++) {
            if (rows[i].start >= t && (best < 0 || rows[i].start < rows[best].start))
                best = i
        }
        return best
    }

    // Playback walks the rows in timeline order: in the edit view the kept clips, in V each whole
    // take, cuts included.
    function advance(t) {
        if (rawView) {
            const part = parts[partIndex]
            if (t >= part.end - 0.02) {
                if (partIndex + 1 < parts.length)
                    seek(parts[partIndex + 1].start)
                else
                    pause()
            }
            return
        }
        if (currentRow < 0 || currentRow >= rows.length || t < rows[currentRow].start - 0.25 || t > rows[currentRow].end + 0.5)
            currentRow = rows.findIndex(r => t >= r.start && t < r.end)
        if (currentRow >= 0 && t >= rows[currentRow].end - 0.01) {
            currentRow = currentRow + 1 < rows.length ? currentRow + 1 : -1
            if (currentRow >= 0)
                seek(rows[currentRow].start)
            else
                pause()
        } else if (currentRow < 0) {
            const next = nextRowAfter(t)
            if (next < 0) {
                pause()
            } else {
                currentRow = next
                seek(rows[next].start)
            }
        }
    }

    function useTake(take) {
        const start = editor.useTake(take)
        if (start < 0)
            return
        currentRow = -1
        seek(start + 0.001)
        play()
    }

    function selectSentence(sentence, mouse) {
        if (sentence < 0)
            return
        let next = selected.slice()
        if (mouse.modifiers & Qt.ShiftModifier && anchorSentence >= 0) {
            next = []
            for (let s = Math.min(anchorSentence, sentence); s <= Math.max(anchorSentence, sentence); s++)
                next.push(s)
        } else if (mouse.modifiers & Qt.ControlModifier) {
            const at = next.indexOf(sentence)
            if (at >= 0)
                next.splice(at, 1)
            else
                next.push(sentence)
            anchorSentence = sentence
        } else {
            next = next.length === 1 && next[0] === sentence ? [] : [sentence]
            anchorSentence = sentence
        }
        selected = next.sort((a, b) => a - b)
    }

    function rerecordTargets() {
        if (selected.length)
            return selected
        const sentence = editor.sentenceAt(playhead)
        return sentence >= 0 ? [sentence] : []
    }

    function rerecord() {
        const targets = rerecordTargets()
        if (!editor.hasScript || targets.length === 0) {
            app.notice("info", qsTr("Pick a sentence: click its clip, Shift+click for a range"))
            return
        }
        pause()
        app.rerecord(targets)
    }

    Connections {
        target: editor
        function onLoadedChanged() {
            page.userPps = 0
            page.zoomed = false
            page.selected = []
            page.anchorSentence = -1
            page.partIndex = -1
            page.pendingTime = -1
            page.resumeAfterLoad = false
            page.currentRow = -1
            page.startAt = 0
            // A source set to the URL it already has never reloads nor reports "loaded", and the file
            // may have been recorded again under the same name.
            player.source = ""
            picture.source = ""
            Qt.callLater(() => page.seek(page.startAt))
        }
    }

    Connections {
        target: app
        function onSeekEditor(t) {
            page.startAt = t
            Qt.callLater(() => page.seek(page.startAt))
        }
    }

    // Qt fixes an output's device when it's created; binding it keeps playback on the current default
    // (a headset plugged in later) instead of the speaker that was the default at startup.
    MediaDevices { id: outputs }

    // What you hear is the part's master recording; the video plays muted and follows it.
    MediaPlayer {
        id: player
        audioOutput: AudioOutput { device: outputs.defaultAudioOutput }
        onMediaStatusChanged: {
            // Swapping the source first reports on the old file; wait for the one asked for.
            const ready = mediaStatus === MediaPlayer.LoadedMedia || mediaStatus === MediaPlayer.BufferedMedia
            if (ready && page.pendingTime >= 0 && String(source) === page.pendingSource) {
                const t = page.pendingTime
                page.pendingTime = -1
                position = Math.max(0, (t - page.parts[page.partIndex].start) * 1000)
                if (page.resumeAfterLoad) {
                    page.resumeAfterLoad = false
                    play()
                } else {
                    pause()
                }
                page.syncPicture(true)
            } else if (mediaStatus === MediaPlayer.EndOfMedia && page.partIndex >= 0) {
                page.advance(page.parts[page.partIndex].end)
            }
        }
        onPositionChanged: (position) => {
            if (page.seeking || playbackState !== MediaPlayer.PlayingState || page.pendingTime >= 0 || page.partIndex < 0)
                return
            const t = page.parts[page.partIndex].start + position / 1000
            page.playhead = t
            page.advance(t)
            page.syncPicture(false)
        }
    }

    MediaPlayer {
        id: picture
        videoOutput: video
        onMediaStatusChanged: {
            if (mediaStatus === MediaPlayer.LoadedMedia)
                page.syncPicture(true)
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Label {
                text: qsTr("Edit  %1  of  %2").arg(page.clock(editor.editDuration)).arg(page.clock(editor.sourceDuration))
                font.pixelSize: 16
                font.bold: true
            }
            Label {
                visible: page.fullView && !page.emptyEdit
                text: page.blockView ? qsTr("Whole takes, cuts greyed · V goes back") : qsTr("Raw recording · V goes back")
                color: theme.accent
                font.pixelSize: 12
            }
            Label {
                visible: page.emptyEdit && !page.nothingRecorded
                text: qsTr("Nothing is kept: every take was rejected. Space plays the raw recording; X on a take keeps it.")
                color: theme.yellow
                font.pixelSize: 12
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
            Item { Layout.fillWidth: true }
            Button {
                visible: editor.staleSentences.length > 0
                text: qsTr("Re-record changed (%1)").arg(editor.staleSentences.length)
                onClicked: { page.pause(); app.rerecord(editor.staleSentences) }
                ToolTip.visible: hovered
                ToolTip.text: qsTr("These sentences were reworded after you recorded them: %1").arg(editor.staleSentences.map(s => "S" + (s + 1)).join(", "))
            }
            Button {
                visible: editor.hasScript
                enabled: !page.nothingRecorded
                text: page.selected.length > 1 ? qsTr("Re-record %n sentence(s)", "", page.selected.length) : qsTr("Re-record")
                onClicked: page.rerecord()
                ToolTip.visible: hovered
                ToolTip.text: qsTr("R · records the selected sentences again (click a clip to select, Shift+click for a range)")
            }
            Button {
                text: qsTr("Reset edit")
                enabled: !page.nothingRecorded && editor.canReset
                onClicked: editor.resetEdit()
                ToolTip.visible: hovered
                ToolTip.text: qsTr("A · back to the automatic cut with the current edit settings; Ctrl+Z brings your changes back")
            }
            Button { text: qsTr("Undo"); enabled: editor.canUndo; onClicked: editor.undo() }
            Button { text: qsTr("Redo"); enabled: editor.canRedo; onClicked: editor.redo() }
            Button {
                id: exportButton
                text: editor.rendering ? qsTr("Rendering %1%").arg(Math.round(editor.renderProgress * 100)) : qsTr("Export…")
                enabled: !editor.rendering && !page.nothingRecorded
                onClicked: exportMenu.open()
                ToolTip.visible: hovered && !exportMenu.visible
                ToolTip.text: qsTr("Ctrl+E exports the video (or the audio) again with your last choices")
                Menu {
                    id: exportMenu
                    y: exportButton.height
                    width: 280
                    x: exportButton.width - width
                    MenuItem { text: qsTr("Video…"); enabled: editor.hasVideo; onTriggered: page.exportRequested("video") }
                    MenuItem { text: qsTr("Audio…"); onTriggered: page.exportRequested("audio") }
                    MenuItem { text: qsTr("Captions…"); onTriggered: page.exportRequested("captions") }
                    MenuItem { text: qsTr("Timeline…"); onTriggered: page.exportRequested("timeline") }
                    MenuSeparator {}
                    MenuItem { text: qsTr("Script timing (JSON)"); enabled: editor.hasScript; onTriggered: editor.render("sentences") }
                    MenuItem { text: qsTr("Audacity labels"); onTriggered: editor.render("labels") }
                    MenuItem { text: qsTr("Raw recording + markers (OTIO)"); onTriggered: editor.render("raw") }
                    MenuSeparator {}
                    MenuItem { text: qsTr("Open output folder"); onTriggered: editor.openOutput() }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 8

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: "black"
                radius: 6
                VideoOutput {
                    id: video
                    anchors.fill: parent
                    visible: page.partHasVideo
                }
                Label {
                    anchors.centerIn: parent
                    visible: !page.partHasVideo && !page.nothingRecorded
                    text: (editor.hasVideo ? qsTr("No video in this part  ·  %1") : qsTr("Audio only  ·  %1")).arg(page.clock(page.playhead))
                    font.pixelSize: 28
                    opacity: 0.5
                }
                ColumnLayout {
                    anchors.centerIn: parent
                    visible: page.nothingRecorded
                    spacing: 10
                    Label { text: qsTr("Nothing recorded for this script yet"); font.pixelSize: 24; Layout.alignment: Qt.AlignHCenter }
                    Label { text: qsTr("Switch to Record (Ctrl+Tab) and press Space."); opacity: 0.6; Layout.alignment: Qt.AlignHCenter }
                    Button { text: qsTr("Go to Record"); highlighted: true; Layout.alignment: Qt.AlignHCenter; onClicked: app.showView("record") }
                }
                Label {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.margins: 10
                    text: page.clock(page.playhead)
                    font.family: "monospace"
                    font.pixelSize: 16
                    color: "white"
                }
            }

            SentencePanel {
                visible: editor.hasScript && !page.nothingRecorded
                Layout.preferredWidth: 320
                Layout.fillHeight: true
                sentence: page.focusSentence
                choices: page.focusSentence >= 0 ? (page.segments, editor.sentenceChoices(page.focusSentence)) : ({})
                onChosen: (take) => page.useTake(take)
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 280
            radius: 6
            color: theme.surface

            Flickable {
                id: timelineFlick
                anchors.fill: parent
                anchors.margins: 6
                contentWidth: Math.max(width, page.timelineDuration * page.pps + 40)
                contentHeight: height
                clip: true
                flickableDirection: Flickable.HorizontalFlick
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AlwaysOn }

                Item {
                    id: lanes
                    width: timelineFlick.contentWidth
                    height: timelineFlick.height - 14

                    property real laneChapters: page.chapters.length ? 24 : 0
                    property real laneFilm: editor.hasVideo ? 44 : 0
                    property real yWave: laneChapters + laneFilm + 4
                    property real waveHeight: 70
                    property real yClips: yWave + waveHeight + 4
                    property real yTakes: yClips + 26
                    property real yMarkers: yTakes + 30
                    property real yWords: yMarkers + 26

                    Repeater {
                        model: editor.thumbnails
                        delegate: Image {
                            required property var modelData
                            x: page.timelineX(modelData.time, false)
                            y: lanes.laneChapters
                            height: 40
                            width: 71
                            fillMode: Image.PreserveAspectCrop
                            source: modelData.url
                            asynchronous: true
                            visible: x >= 0 && x + width >= timelineFlick.contentX - 100 && x <= timelineFlick.contentX + timelineFlick.width + 100
                        }
                    }

                    Repeater {
                        model: page.chapters
                        delegate: Rectangle {
                            id: band
                            required property var modelData
                            required property int index
                            property color tint: theme.accent
                            x: modelData.start * page.pps
                            width: Math.max(2, (modelData.end - modelData.start) * page.pps)
                            height: 20
                            radius: 3
                            z: 3
                            color: Qt.rgba(tint.r, tint.g, tint.b, index % 2 ? 0.16 : 0.28)
                            Rectangle { width: 2; height: parent.height; color: band.tint }
                            Label {
                                // Stays in view at the left edge while a long chapter scrolls past.
                                x: Math.max(6, Math.min(timelineFlick.contentX - band.x + 6, band.width - width - 6))
                                width: Math.min(implicitWidth, band.width - 12)
                                anchors.verticalCenter: parent.verticalCenter
                                text: band.modelData.title
                                elide: Text.ElideRight
                                font.pixelSize: 11
                                font.bold: true
                                visible: band.width > 24
                            }
                            MouseArea {
                                anchors.fill: parent
                                onClicked: {
                                    page.selected = band.modelData.sentences.slice().sort((a, b) => a - b)
                                    page.anchorSentence = page.selected[0]
                                    page.seek(page.sourceTime(band.modelData.start) + 0.001)
                                }
                            }
                            ToolTip.visible: chapterHover.hovered
                            ToolTip.text: band.modelData.title + "\n" + qsTr("Click to select its %n sentence(s); R re-records them", "", band.modelData.sentences.length)
                            HoverHandler { id: chapterHover }
                        }
                    }

                    Waveform {
                        visible: page.rawView
                        x: timelineFlick.contentX
                        y: lanes.yWave
                        width: timelineFlick.width
                        height: lanes.waveHeight
                        key: editor.peaksKey
                        perSecond: 100
                        viewStart: timelineFlick.contentX / page.pps
                        viewEnd: (timelineFlick.contentX + timelineFlick.width) / page.pps
                        color: Qt.rgba(1, 1, 1, 0.25)
                        keptColor: theme.accent
                        kept: editor.clips
                    }

                    // Each row draws its own stretch of the waveform, cut to the visible window so a long
                    // row at high zoom never needs a huge texture. In V, what was cut from a take is grey.
                    Repeater {
                        model: page.rows
                        delegate: Waveform {
                            required property var modelData
                            property real fromX: Math.max(modelData.editStart * page.pps, timelineFlick.contentX)
                            property real toX: Math.min((modelData.editStart + modelData.end - modelData.start) * page.pps, timelineFlick.contentX + timelineFlick.width)
                            visible: toX > fromX
                            x: fromX
                            y: lanes.yWave
                            width: Math.max(1, toX - fromX)
                            height: lanes.waveHeight
                            key: editor.peaksKey
                            perSecond: 100
                            viewStart: modelData.start + (fromX / page.pps - modelData.editStart)
                            viewEnd: modelData.start + (toX / page.pps - modelData.editStart)
                            color: page.blockView ? Qt.rgba(1, 1, 1, 0.25) : theme.accent
                            keptColor: theme.accent
                            kept: page.blockView ? editor.clips : []
                        }
                    }

                    Repeater {
                        model: page.rows.slice(1)
                        delegate: Rectangle {
                            required property var modelData
                            x: modelData.editStart * page.pps
                            width: 1
                            height: lanes.yTakes + 24
                            color: theme.foreground
                            opacity: 0.35
                        }
                    }

                    Repeater {
                        model: page.rawView && page.parts.length > 1 ? page.parts : []
                        delegate: Item {
                            required property var modelData
                            x: modelData.start * page.pps
                            width: Math.max(1, (modelData.end - modelData.start) * page.pps)
                            height: lanes.height
                            Rectangle { width: 1; height: parent.height; color: theme.accent; opacity: 0.6 }
                            Label {
                                x: 4
                                y: lanes.yClips - 2
                                text: modelData.label
                                font.pixelSize: 10
                                color: theme.accent
                                visible: parent.width > 60
                                z: 2
                            }
                        }
                    }

                    Repeater {
                        model: page.rawView || page.blockView ? editor.clips : page.segments
                        delegate: Rectangle {
                            required property var modelData
                            property bool isSelected: modelData.sentence >= 0 && page.selected.indexOf(modelData.sentence) >= 0
                            x: page.blockView ? page.timelineX(modelData.start, false) : (page.rawView ? modelData.start : modelData.editStart) * page.pps
                            visible: x >= 0
                            width: Math.max(2, (modelData.end - modelData.start) * page.pps)
                            y: lanes.yClips
                            height: 22
                            radius: 4
                            z: 3
                            color: modelData.kind === "adlib" ? Qt.darker(theme.accent, 1.6) : Qt.darker(theme.accent, 1.25)
                            border.width: isSelected ? 2 : 1
                            border.color: isSelected ? theme.yellow : modelData.start <= page.playhead && page.playhead < modelData.end ? "white" : "transparent"
                            MouseArea {
                                anchors.fill: parent
                                onClicked: (mouse) => {
                                    page.selectSentence(modelData.sentence, mouse)
                                    page.seek(modelData.start + 0.001)
                                }
                            }
                            Label {
                                anchors.fill: parent
                                anchors.leftMargin: 4
                                verticalAlignment: Text.AlignVCenter
                                text: modelData.sentence >= 0 ? "S" + (modelData.sentence + 1) : modelData.kind
                                font.pixelSize: 11
                                color: "black"
                                elide: Text.ElideRight
                                visible: parent.width > 24
                            }
                        }
                    }

                    Repeater {
                        model: page.rawView ? editor.takes : page.rows.filter(s => s.number > 0)
                        delegate: Rectangle {
                            required property var modelData
                            x: (page.rawView ? modelData.start : modelData.editStart) * page.pps
                            width: Math.max(2, (modelData.end - modelData.start) * page.pps)
                            y: lanes.yTakes
                            height: 24
                            radius: 4
                            color: modelData.status === "complete" ? Qt.rgba(0.27, 0.65, 0.35, modelData.chosen ? 0.75 : 0.3) : Qt.rgba(0.9, 0.28, 0.3, 0.35)
                            Label {
                                anchors.fill: parent
                                anchors.leftMargin: 4
                                verticalAlignment: Text.AlignVCenter
                                font.pixelSize: 11
                                elide: Text.ElideRight
                                text: (modelData.sentence >= 0 ? "S" + (modelData.sentence + 1) + " T" + modelData.number : "#" + modelData.id) + (modelData.score >= 0 ? "  " + modelData.score : "") + (modelData.flagged > 0 ? "  ⚑" + modelData.flagged : "") + (modelData.skipped > 0 ? " (" + qsTr("%1 skipped").arg(modelData.skipped) + ")" : "") + (modelData.stale ? "  ⟳" : "")
                                visible: parent.width > 30
                            }
                            ToolTip.visible: takeHover.hovered
                            ToolTip.text: modelData.text + (modelData.reason ? "\n" + modelData.reason : "") + (modelData.stale ? "\n" + qsTr("Recorded before the sentence was reworded") : "")
                            HoverHandler { id: takeHover }
                        }
                    }

                    Repeater {
                        model: editor.markers
                        delegate: Rectangle {
                            required property var modelData
                            property color tint: modelData.kind === "chapter" || modelData.kind === "mark" ? "#5b8def"
                                : modelData.kind === "command" || modelData.kind === "tts" || modelData.kind === "pause" ? "#888888"
                                : modelData.kind === "off-script" || modelData.kind === "filler" ? theme.yellow
                                : modelData.kind === "flag" || modelData.kind === "screen" ? theme.red : "#b58ee8"
                            x: page.timelineX(modelData.start, false)
                            visible: x >= 0
                            width: Math.max(3, (modelData.end - modelData.start) * page.pps)
                            y: lanes.yMarkers
                            height: 20
                            radius: 3
                            color: Qt.rgba(tint.r, tint.g, tint.b, 0.55)
                            ToolTip.visible: markerHover.hovered
                            ToolTip.text: modelData.kind + (modelData.label ? ": " + modelData.label : "")
                            HoverHandler { id: markerHover }
                        }
                    }

                    Repeater {
                        model: {
                            if (page.pps <= 120)
                                return []
                            const from = (timelineFlick.contentX - 100) / page.pps
                            const to = (timelineFlick.contentX + timelineFlick.width + 100) / page.pps
                            if (page.rawView)
                                return editor.words.filter(w => w.end >= from && w.start <= to)
                            const shown = page.rows.filter(s => s.editStart + s.end - s.start >= from && s.editStart <= to)
                            return editor.words.filter(w => shown.some(s => w.start >= s.start && w.start < s.end))
                        }
                        delegate: Label {
                            required property var modelData
                            x: page.timelineX(modelData.start, false)
                            y: lanes.yWords
                            text: modelData.text
                            font.pixelSize: 11
                            color: modelData.score >= 0 && modelData.score < 55 ? theme.red : theme.foreground
                            opacity: 0.75
                        }
                    }

                    Rectangle {
                        x: page.playheadPos
                        width: 2
                        height: parent.height
                        color: "white"
                    }

                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.LeftButton
                        onPressed: (mouse) => page.seek(page.timeAtX(mouse.x))
                        onPositionChanged: (mouse) => { if (pressed) page.seek(page.timeAtX(mouse.x)) }
                    }
                }
            }

            // Above the timeline, not inside it: the Flickable would take the wheel for scrolling first.
            MouseArea {
                anchors.fill: timelineFlick
                acceptedButtons: Qt.NoButton
                onWheel: (wheel) => {
                    const delta = wheel.angleDelta.y !== 0 ? wheel.angleDelta.y : wheel.pixelDelta.y
                    if (!(wheel.modifiers & Qt.ControlModifier) || delta === 0) {
                        wheel.accepted = false
                        return
                    }
                    page.zoomTo(page.pps * Math.pow(1.0015, delta), wheel.x)
                }
            }

            Item {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.margins: 8
                opacity: 0.4
                Repeater {
                    model: [[lanes.yClips, qsTr("edit")], [lanes.yTakes, qsTr("takes")], [lanes.yMarkers, qsTr("markers")]]
                    delegate: Label {
                        required property var modelData
                        y: modelData[0]
                        text: modelData[1]
                        font.pixelSize: 10
                    }
                }
            }
        }
    }
}
