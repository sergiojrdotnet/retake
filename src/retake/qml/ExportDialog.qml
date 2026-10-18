import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RetakeDialog {
    id: dialog
    property string kind: "video"
    property var shape: ({})
    property var choices: app.settings.export || ({})
    property bool lossless: ["flac", "wav", "alac"].indexOf(choices.audio_format) >= 0
    property string encoder: visible && kind === "video" ? editor.videoEncoder(choices.video_format || "") : ""
    title: ({ video: qsTr("Export video"), audio: qsTr("Export audio"), captions: qsTr("Export captions"), timeline: qsTr("Export timeline") })[kind] || ""
    width: Math.min(parent.width - 60, 680)
    standardButtons: Dialog.Ok | Dialog.Cancel
    onOpened: standardButton(Dialog.Ok).text = qsTr("Export")
    onAccepted: editor.render(kind)

    function show(which) {
        kind = which
        if (which === "video")
            shape = editor.videoShape()
        open()
    }

    function evenScaled(side, shortSide) {
        return Math.max(2, Math.round(side * shortSide / Math.min(shape.width, shape.height) / 2) * 2)
    }

    function sizeOptions() {
        if (!shape.width)
            return [[0, qsTr("As recorded")]]
        const options = [[0, qsTr("As recorded (%1 × %2)").arg(shape.width).arg(shape.height)]]
        for (const side of [2160, 1440, 1080, 720, 480]) {
            if (side < Math.min(shape.width, shape.height))
                options.push([side, evenScaled(shape.width, side) + " × " + evenScaled(shape.height, side)])
        }
        return options
    }

    function fpsOptions() {
        const options = [[0, shape.fps ? qsTr("As recorded (%1)").arg(shape.fps) : qsTr("As recorded")]]
        for (const fps of [60, 50, 30, 25, 24]) {
            if (!shape.fps || fps < shape.fps - 0.5)
                options.push([fps, String(fps)])
        }
        return options
    }

    ColumnLayout {
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: 14

        SettingRow {
            visible: dialog.kind === "video"
            label: qsTr("Format"); section: "export"; key: "video_format"
            options: [
                ["mp4-h264", qsTr("MP4 · H.264 (plays everywhere)")],
                ["mp4-hevc", qsTr("MP4 · HEVC (about half the size)")],
                ["mp4-av1", qsTr("MP4 · AV1 (smallest; newer players)")],
                ["webm-vp9", qsTr("WebM · VP9 (for the web; slow to encode)")],
                ["mov-prores", qsTr("MOV · ProRes (for editing; very large)")]
            ]
        }
        SettingRow { visible: dialog.kind === "video"; label: qsTr("Resolution"); section: "export"; key: "video_size"; options: dialog.sizeOptions() }
        SettingRow { visible: dialog.kind === "video"; label: qsTr("Frame rate"); section: "export"; key: "video_fps"; options: dialog.fpsOptions() }
        SettingRow {
            visible: dialog.kind === "video"
            label: qsTr("Quality"); section: "export"; key: "video_quality"
            hint: dialog.choices.video_format === "mov-prores" ? qsTr("ProRes 422 HQ, 422 or LT") : ""
            options: [["high", qsTr("High")], ["balanced", qsTr("Balanced")], ["small", qsTr("Smaller file")]]
        }
        SettingRow {
            visible: dialog.kind === "video" && dialog.choices.video_format !== "mov-prores"
            label: qsTr("Audio bit rate"); section: "export"; key: "video_audio_bitrate"
            hint: dialog.choices.video_format === "webm-vp9" ? qsTr("Opus") : qsTr("AAC")
            options: [["128k", "128 kb/s"], ["192k", "192 kb/s"], ["256k", "256 kb/s"], ["320k", "320 kb/s"]]
        }
        SettingRow {
            visible: dialog.kind === "video"
            label: qsTr("Burn in captions"); section: "export"; key: "burn_captions"; type: "switch"
            hint: qsTr("Draws the captions into the picture, with the line layout from Export captions")
        }

        SettingRow {
            visible: dialog.kind === "audio"
            label: qsTr("Format"); section: "export"; key: "audio_format"
            options: [
                ["flac", qsTr("FLAC (lossless)")],
                ["wav", qsTr("WAV (lossless, uncompressed)")],
                ["alac", qsTr("ALAC (lossless, for Apple)")],
                ["mp3", "MP3"],
                ["aac", "AAC (M4A)"],
                ["opus", "Opus"],
                ["vorbis", "Ogg Vorbis"]
            ]
        }
        SettingRow {
            visible: dialog.kind === "audio" && !dialog.lossless
            label: qsTr("Bit rate"); section: "export"; key: "audio_bitrate"
            options: [["96k", "96 kb/s"], ["128k", "128 kb/s"], ["192k", "192 kb/s"], ["256k", "256 kb/s"], ["320k", "320 kb/s"]]
        }
        SettingRow {
            visible: dialog.kind === "audio" && dialog.lossless
            label: qsTr("Bit depth"); section: "export"; key: "audio_depth"
            options: [[24, qsTr("24-bit")], [16, qsTr("16-bit (CD)")]]
        }
        SettingRow {
            visible: dialog.kind === "audio"
            label: qsTr("Sample rate"); section: "export"; key: "audio_rate"
            options: [[0, qsTr("As recorded")], [48000, "48 kHz"], [44100, qsTr("44.1 kHz (CD)")]]
        }
        SettingRow {
            visible: dialog.kind === "audio"
            label: qsTr("Channels"); section: "export"; key: "audio_channels"
            options: [[0, qsTr("As recorded")], [1, qsTr("Mono")], [2, qsTr("Stereo")]]
        }

        SettingRow {
            visible: dialog.kind === "video" || dialog.kind === "audio"
            label: qsTr("Loudness"); section: "export"; key: "loudness"
            hint: qsTr("Evens out the level to a standard target, measured over the whole export")
            options: [
                [0, qsTr("As recorded")],
                [-14, qsTr("−14 LUFS (YouTube, Spotify)")],
                [-16, qsTr("−16 LUFS (podcasts, Apple)")],
                [-23, qsTr("−23 LUFS (broadcast, EBU R128)")]
            ]
        }
        SettingRow {
            visible: dialog.kind === "video" || (dialog.kind === "audio" && dialog.choices.audio_format !== "wav")
            label: qsTr("Chapters"); section: "export"; key: "chapters"; type: "switch"
            hint: qsTr("One per script section, plus the marks you dropped while recording")
        }

        SettingRow {
            visible: dialog.kind === "captions"
            label: qsTr("Format"); section: "export"; key: "captions_format"
            options: [
                ["srt", qsTr("SRT (YouTube, most players)")],
                ["vtt", qsTr("WebVTT (web players)")],
                ["vtt-words", qsTr("WebVTT, word by word (karaoke)")],
                ["txt", qsTr("Transcript (plain text)")]
            ]
        }
        SettingRow {
            visible: dialog.kind === "captions" && dialog.choices.captions_format !== "txt"
            label: qsTr("Characters per line"); section: "export"; key: "caption_line"
            hint: qsTr("Also used for captions burned into a video")
            options: [[32, qsTr("32 (portrait, phones)")], [37, "37"], [42, qsTr("42 (landscape, the usual)")]]
        }
        SettingRow {
            visible: dialog.kind === "captions" && dialog.choices.captions_format !== "txt"
            label: qsTr("Lines per caption"); section: "export"; key: "caption_lines"
            options: [[1, "1"], [2, "2"]]
        }

        SettingRow {
            visible: dialog.kind === "timeline"
            label: qsTr("Format"); section: "export"; key: "timeline_format"
            hint: qsTr("Links to the original recordings, cut as in the edit, with your markers")
            options: [
                ["otio", qsTr("OpenTimelineIO (Resolve, Kdenlive)")],
                ["fcpxml", qsTr("Final Cut Pro 7 XML (Premiere, Resolve, Kdenlive, Shotcut)")],
                ["edl", qsTr("CMX 3600 EDL (any editor; cuts only)")]
            ]
        }

        Label {
            visible: dialog.encoder !== ""
            text: dialog.encoder.endsWith("_nvenc") ? qsTr("Encoded on the GPU (%1)").arg(dialog.encoder)
                                                    : qsTr("Encoded on the CPU (%1)").arg(dialog.encoder)
            font.pixelSize: 12
            opacity: 0.55
        }
        Label {
            text: dialog.visible ? (dialog.choices, qsTr("Saves out/%1").arg(editor.exportName(dialog.kind))) : ""
            font.pixelSize: 12
            opacity: 0.55
            elide: Text.ElideMiddle
            Layout.fillWidth: true
        }
    }
}
