import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RetakeDialog {
    id: dialog
    title: qsTr("Settings")
    width: Math.min(parent.width - 60, 900)
    height: Math.min(parent.height - 60, 680)
    standardButtons: Dialog.Close
    onOpened: { app.refreshDevices(); refreshUncoached() }

    property var languageOptions: app.languages.map(l => [l.code, l.name])

    property bool phoneMode: app.settings.camera.source === "phone"
    property int historyVersion: 0
    property var uncoached: []
    function refreshUncoached() { uncoached = app.uncoachedWords() }
    Connections { target: app; function onUncoachedChanged() { dialog.refreshUncoached() } }
    // The detected camera the phone settings refer to, by id or by facing.
    property var phoneCamera: {
        const choice = String(app.settings.phone.camera || "back")
        const cameras = app.phoneCameras
        return cameras.find(c => c.id === choice) || cameras.find(c => c.facing === choice) || null
    }

    property bool customCamera: false
    property var cameraOptions: [["none", qsTr("None (audio only)")]]
        .concat(app.videoCameras.map(c => ["device:" + c.id, c.description]))
        .concat([["phone", qsTr("Android phone (USB)")], ["other", qsTr("Other device…")]])
    property string cameraChoice: {
        const camera = app.settings.camera
        if (camera.source === "phone")
            return "phone"
        if (camera.source !== "device")
            return "none"
        const match = app.videoCameras.find(c => camera.device ? c.id === camera.device : c.default)
        return match && !customCamera ? "device:" + match.id : "other"
    }

    function chooseCamera(value) {
        customCamera = value === "other"
        if (value === "none" || value === "phone") {
            app.setSetting("camera", "source", value)
        } else if (value === "other") {
            app.setSetting("camera", "source", "device")
        } else {
            app.setSetting("camera", "device", value.slice("device:".length))
            app.setSetting("camera", "source", "device")
        }
    }

    RetakeDialog {
        id: clearHistoryDialog
        title: qsTr("Clear the coach history?")
        width: Math.min(dialog.width - 60, 520)
        standardButtons: Dialog.Yes | Dialog.Cancel
        Label {
            anchors.left: parent.left
            anchors.right: parent.right
            wrapMode: Text.Wrap
            text: qsTr("Every word's scores and misses, and the words flagged for practice, are forgotten. Your Not coached list stays.")
        }
        onAccepted: {
            app.clearPracticeHistory()
            dialog.historyVersion += 1
        }
    }

    function openTab(index) {
        tabs.currentIndex = index
        open()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 10

        TabBar {
            id: tabs
            Layout.fillWidth: true
            TabButton { text: qsTr("Session") }
            TabButton { text: qsTr("Prompter") }
            TabButton { text: qsTr("Coach") }
            TabButton { text: qsTr("Recording") }
            TabButton { text: qsTr("Engines") }
            TabButton { text: qsTr("Controls") }
            TabButton { text: qsTr("Editing") }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabs.currentIndex

            ScrollView {
                ColumnLayout {
                    width: dialog.availableWidth - 20
                    spacing: 14
                    SettingHeader { text: qsTr("Languages") }
                    SettingRow { label: qsTr("Script language"); section: "general"; key: "script_language"; options: dialog.languageOptions; hint: qsTr("Language you read in") }
                    SettingRow { label: qsTr("Native language"); section: "general"; key: "native_language"; options: dialog.languageOptions; hint: qsTr("Used for respelling and typical mistakes") }
                    SettingRow { label: qsTr("Interface language"); section: "general"; key: "ui_language"; options: [["auto", qsTr("System")]].concat(dialog.languageOptions); hint: qsTr("Applies after restart") }
                    SettingHeader { text: qsTr("Projects") }
                    SettingRow { label: qsTr("Projects folder"); section: "general"; key: "projects_dir"; type: "text" }
                    SettingHeader { text: qsTr("Sound cues") }
                    SettingRow { label: qsTr("Sound cues"); section: "sounds"; key: "enabled"; type: "switch"; hint: qsTr("Start, pause, stop, required retake, voice command heard, end of script") }
                    SettingRow { label: qsTr("Cue volume"); section: "sounds"; key: "volume"; type: "slider"; from: 0.05; to: 1.0; step: 0.05; decimals: 2; visible: !!(app.settings.sounds && app.settings.sounds.enabled) }
                }
            }

            ScrollView {
                ColumnLayout {
                    width: dialog.availableWidth - 20
                    spacing: 14
                    SettingHeader { text: qsTr("Display") }
                    SettingRow { label: qsTr("Mode"); section: "prompter"; key: "mode"; hint: qsTr("V cycles while recording")
                        options: [["scroll", qsTr("Scroll: glides with your voice")], ["step", qsTr("Step: moves a line at a time")], ["card", qsTr("Card: current sentence, next below")], ["page", qsTr("Page: one paragraph at a time")]] }
                    SettingRow { label: qsTr("Font size"); section: "prompter"; key: "font_size"; type: "slider"; from: 20; to: 96 }
                    SettingRow { label: qsTr("Line width"); section: "prompter"; key: "line_width"; type: "slider"; from: 0.4; to: 1.0; step: 0.02; decimals: 2 }
                    SettingRow { label: qsTr("Reading line"); section: "prompter"; key: "reading_line"; type: "slider"; from: 0.1; to: 0.6; step: 0.01; decimals: 2; hint: qsTr("Height of the line you read from") }
                    SettingRow { label: qsTr("A line per sentence"); section: "prompter"; key: "sentence_lines"; type: "switch"; hint: qsTr("Each sentence starts on a new line, so its whole shape shows before you read it") }
                    SettingRow { label: qsTr("Mirror"); section: "prompter"; key: "mirror"; type: "switch"; hint: qsTr("For teleprompter glass") }
                    SettingRow { label: qsTr("Animations"); section: "prompter"; key: "animation"; type: "switch" }
                    SettingRow { label: qsTr("Show cues and pauses"); section: "prompter"; key: "show_cues"; type: "switch" }
                    SettingHeader { text: qsTr("Pronunciation guides") }
                    SettingRow { label: qsTr("IPA"); section: "guides"; key: "ipa"; type: "switch"; hint: "/ˈæɡrəɡət/" }
                    SettingRow { label: qsTr("English respelling"); section: "guides"; key: "respell"; type: "switch"; hint: "AG-ruh-guht" }
                    SettingRow { label: qsTr("Native respelling"); section: "guides"; key: "native"; type: "switch"; hint: "ÉG-râ-gât" }
                    SettingRow { label: qsTr("Show guides on"); section: "guides"; key: "scope"
                        options: [["all", qsTr("Every word")], ["hard", qsTr("Hard words")], ["flagged", qsTr("Flagged words only")]] }
                }
            }

            ScrollView {
                ColumnLayout {
                    width: dialog.availableWidth - 20
                    spacing: 14
                    SettingHeader { text: qsTr("Scoring") }
                    SettingRow { label: qsTr("Pronunciation coach"); section: "coach"; key: "enabled"; type: "switch" }
                    SettingRow { label: qsTr("Warn below"); section: "coach"; key: "threshold"; type: "slider"; from: 20; to: 90; hint: qsTr("Words scoring below this show up in the coach panel") }
                    SettingRow { label: qsTr("Require a retake below"); section: "coach"; key: "require"; type: "slider"
                        from: 0; to: app.settings.coach.threshold; zeroText: qsTr("Off")
                        hint: qsTr("A word under this score rejects the take and sends you back to the sentence start. All the way left is off; it can't go above Warn") }
                    SettingRow { label: qsTr("Feedback"); section: "coach"; key: "timing"
                        options: [["live", qsTr("Live, after each sentence")], ["review", qsTr("Review at the end (pickups)")]] }
                    SettingHeader { text: qsTr("Takes") }
                    SettingRow { label: qsTr("Skipped or changed words"); section: "strictness"; key: "deviations"
                        hint: qsTr("When you skip a word of the script or say another one")
                        options: [["accept", qsTr("Accept")], ["warn", qsTr("Warn")], ["require", qsTr("Require a retake")]] }
                    SettingHeader { text: qsTr("Drill"); visible: (app.settings.coach.require || 0) > 0 }
                    SettingRow { label: qsTr("Drill the failed word"); section: "coach"; key: "drill_times"; type: "slider"
                        from: 0; to: 5; zeroText: qsTr("Off"); visible: (app.settings.coach.require || 0) > 0
                        hint: qsTr("Hear the word and say it this many times in a row, then read the sentence again. All the way left is off") }
                    SettingHeader { text: qsTr("Words") }
                    SettingRow { label: qsTr("Auto-flag after misses"); section: "coach"; key: "auto_flag_misses"; type: "slider"; from: 1; to: 10 }
                    Label { text: qsTr("Not coached (names and words never scored, drilled or given guides)"); opacity: 0.6; topPadding: 8; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 6
                        Repeater {
                            model: dialog.uncoached
                            delegate: Rectangle {
                                required property var modelData
                                implicitWidth: chip.implicitWidth + 10
                                implicitHeight: chip.implicitHeight + 4
                                radius: 12
                                color: Qt.lighter(theme.surface, 1.35)
                                RowLayout {
                                    id: chip
                                    anchors.centerIn: parent
                                    spacing: 2
                                    Label { text: modelData; leftPadding: 6 }
                                    ToolButton {
                                        text: "×"
                                        implicitWidth: 26
                                        implicitHeight: 26
                                        ToolTip.visible: hovered
                                        ToolTip.text: qsTr("Coach it again")
                                        onClicked: app.setCoached(modelData, true)
                                    }
                                }
                            }
                        }
                        Label { visible: dialog.uncoached.length === 0; text: qsTr("None yet. Right-click a word in the prompter, or press N in a drill."); opacity: 0.5 }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        TextField {
                            id: uncoachField
                            Layout.fillWidth: true
                            placeholderText: qsTr("Add a word, e.g. a name")
                            onAccepted: { app.setCoached(text, false); text = "" }
                        }
                        Button { text: qsTr("Add"); enabled: uncoachField.text.trim() !== ""; onClicked: { app.setCoached(uncoachField.text, false); uncoachField.text = "" } }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: qsTr("Words you keep missing"); opacity: 0.6; topPadding: 8; Layout.fillWidth: true }
                        Button { text: qsTr("Clear history…"); onClicked: clearHistoryDialog.open() }
                    }
                    Repeater {
                        model: dialog.opened && dialog.historyVersion >= 0 ? app.drillList() : []
                        delegate: Label {
                            required property var modelData
                            text: modelData.word + "  ·  " + modelData.misses + "/" + modelData.attempts
                            font.pixelSize: 13
                        }
                    }
                }
            }

            ScrollView {
                ColumnLayout {
                    width: dialog.availableWidth - 20
                    spacing: 14
                    SettingHeader { text: qsTr("Microphone") }
                    SettingRow { label: qsTr("Microphone"); section: "audio"; key: "input"
                        options: [["default", qsTr("System default")]].concat(app.audioSources.map(s => [s.name, s.description])) }
                    SettingRow { label: qsTr("Channels"); section: "audio"; key: "channels"; hint: qsTr("For a mono mic on a stereo interface pick its side")
                        options: [["mix", qsTr("Mix")], ["left", qsTr("Left")], ["right", qsTr("Right")]] }
                    SettingRow { label: qsTr("Sample rate"); section: "audio"; key: "sample_rate"
                        options: [[0, "48 kHz"], [44100, "44.1 kHz"], [48000, "48 kHz"], [96000, "96 kHz"]] }

                    SettingHeader { text: qsTr("Camera") }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 16
                        ColumnLayout {
                            Layout.preferredWidth: 260
                            spacing: 0
                            Label { text: qsTr("Camera") }
                            Label { text: qsTr("Records the video of each recording; the sound always comes from the microphone"); font.pixelSize: 12; opacity: 0.5; wrapMode: Text.Wrap; Layout.preferredWidth: 260 }
                        }
                        ComboBox {
                            Layout.fillWidth: true
                            model: dialog.cameraOptions.map(o => o[1])
                            currentIndex: Math.max(0, dialog.cameraOptions.findIndex(o => o[0] === dialog.cameraChoice))
                            onActivated: (index) => dialog.chooseCamera(dialog.cameraOptions[index][0])
                        }
                    }
                    SettingRow { label: qsTr("Device"); section: "camera"; key: "device"; type: "text"; visible: dialog.cameraChoice === "other"
                        hint: qsTr("A video device path or id, e.g. /dev/video2") }
                    SettingRow { label: qsTr("Codec"); section: "camera"; key: "codec"; visible: app.settings.camera.source === "device"
                        options: [["auto", qsTr("Automatic (H.264, H.265 if the GPU refuses)")], ["h264", "H.264"], ["h265", "H.265"]] }

                    SettingHeader { text: qsTr("Android phone"); visible: dialog.phoneMode }
                    SettingRow { label: qsTr("Phone"); section: "phone"; key: "serial"; visible: dialog.phoneMode
                        hint: qsTr("Each phone keeps its own camera settings")
                        options: [["", qsTr("Automatic (first connected)")]].concat(app.phoneDevices.map(d => [d.serial, d.label])) }
                    SettingRow { label: qsTr("Camera"); section: "phone"; key: "camera"; visible: dialog.phoneMode
                        options: app.phoneCameras.length ? app.phoneCameras.map(c => [c.id, c.label])
                                                         : [["back", qsTr("Back (main)")], ["front", qsTr("Front")], ["external", qsTr("External")]] }
                    SettingRow { label: qsTr("Resolution"); section: "phone"; key: "size"; visible: dialog.phoneMode
                        options: dialog.phoneCamera ? dialog.phoneCamera.sizes.map(o => [o.value, o.label])
                                                    : [["3840x2160", "3840 × 2160 (16:9)"], ["1920x1080", "1920 × 1080 (16:9)"]] }
                    SettingRow { label: qsTr("Frame rate"); section: "phone"; key: "fps"; visible: dialog.phoneMode
                        options: dialog.phoneCamera ? dialog.phoneCamera.fps.map(o => [o.value, o.label]) : [[30, "30"]] }
                    SettingRow { label: qsTr("Codec"); section: "phone"; key: "codec"; visible: dialog.phoneMode
                        options: [["h265", qsTr("H.265 (better quality per bit)")], ["h264", "H.264"]] }
                    SettingRow { label: qsTr("Bit rate"); section: "phone"; key: "bitrate"; visible: dialog.phoneMode
                        options: [["20M", "20 Mb/s"], ["40M", qsTr("40 Mb/s (4K)")], ["80M", qsTr("80 Mb/s (4K, highest)")]] }
                    SettingRow { label: qsTr("Container"); section: "phone"; key: "container"; visible: dialog.phoneMode
                        options: [["mkv", qsTr("MKV (survives a crash or unplugging)")], ["mp4", qsTr("MP4 (plays everywhere; unreadable if cut off)")]] }
                    SettingRow { label: qsTr("Shape"); section: "phone"; key: "shape"; visible: dialog.phoneMode
                        hint: qsTr("Portrait records 9:16, like Reels and Shorts; stand the phone upright")
                        options: [["landscape", qsTr("Landscape 16:9 (phone sideways)")], ["portrait", qsTr("Portrait 9:16 (phone upright)")]] }
                    SettingRow { label: qsTr("Upside down"); section: "phone"; key: "flip"; type: "switch"; visible: dialog.phoneMode; hint: qsTr("If the picture comes out upside down") }
                    SettingRow { label: qsTr("Preview while recording"); section: "phone"; key: "preview"; type: "switch"; visible: dialog.phoneMode
                        hint: qsTr("Keeps the camera panel live during recording by decoding the full-size video: heavy at 4K, and the picture may lag") }
                    RowLayout {
                        visible: dialog.phoneMode
                        Layout.fillWidth: true
                        Button { text: qsTr("Check phone"); onClicked: phoneStatus.text = app.phoneStatus() }
                        Button {
                            text: app.detectingPhoneCameras ? qsTr("Detecting…") : qsTr("Detect cameras")
                            enabled: !app.detectingPhoneCameras
                            onClicked: app.detectPhoneCameras()
                        }
                        Label { id: phoneStatus; Layout.fillWidth: true; wrapMode: Text.Wrap; opacity: 0.75 }
                    }
                }
            }

            ScrollView {
                ColumnLayout {
                    width: dialog.availableWidth - 20
                    spacing: 14
                    SettingHeader { text: qsTr("Hardware") }
                    SettingRow { label: qsTr("Preset"); section: "engines"; key: "preset"; hint: qsTr("Restart the engine to apply")
                        options: [["auto", qsTr("Automatic")], ["nvidia", qsTr("NVIDIA GPU")], ["amd", qsTr("AMD GPU")], ["cpu", qsTr("CPU only")], ["light", qsTr("Light (no pronunciation scoring)")]] }
                    SettingRow { label: qsTr("Device"); section: "engines"; key: "device"; options: [["auto", qsTr("Automatic")], ["cuda", "GPU"], ["cpu", "CPU"]] }
                    SettingRow { label: qsTr("CPU threads"); section: "engines"; key: "threads"; type: "slider"; from: 1; to: 16 }
                    SettingHeader { text: qsTr("Models") }
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: qsTr("The model for each job (voice following, commands, scoring…) is chosen in Models."); opacity: 0.7; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Button { text: qsTr("Models…"); highlighted: true; onClicked: modelsDialog.open() }
                    }
                    SettingHeader { text: qsTr("Status") }
                    Repeater {
                        model: Object.keys(app.engines)
                        delegate: Label {
                            required property string modelData
                            property var info: app.engines[modelData]
                            text: modelData + ": " + info.engine + " · " + info.state + (info.detail ? " · " + info.detail : "")
                            color: info.state === "error" ? theme.red : theme.foreground
                            opacity: 0.8
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                    RowLayout {
                        Button { text: qsTr("Restart engine"); highlighted: app.enginePending; enabled: !app.recording; onClicked: app.restartEngine() }
                    }
                }
            }

            ScrollView {
                ColumnLayout {
                    width: dialog.availableWidth - 20
                    spacing: 14
                    SettingHeader { text: qsTr("Voice commands") }
                    SettingRow { label: qsTr("Voice commands"); section: "voice"; key: "enabled"; type: "switch"; hint: qsTr("Restart the engine to apply") }
                    SettingRow { label: qsTr("Wake word"); section: "voice"; key: "wake_word"; type: "text"; hint: qsTr("Empty uses the language default (retake / diretor)") }
                    SettingHeader { text: qsTr("Foot pedal") }
                    SettingRow { label: qsTr("Foot pedal device"); section: "controls"; key: "pedal_device"; type: "text"; hint: qsTr("/dev/input/by-id/… (needs the input group)") }
                    SettingRow { label: qsTr("Grab the pedal"); section: "controls"; key: "pedal_grab"; type: "switch"; hint: qsTr("Its keys never reach other apps; applies after restart") }
                }
            }

            ScrollView {
                ColumnLayout {
                    width: dialog.availableWidth - 20
                    spacing: 14
                    SettingHeader { text: qsTr("Auto edit") }
                    SettingRow { label: qsTr("Keep"); section: "edit"; key: "keep"; options: [["last", qsTr("Newest good take")], ["best", qsTr("Best scored take")]] }
                    SettingRow { label: qsTr("Extra speech"); section: "strictness"; key: "extra_speech"; hint: qsTr("What Auto edit does with speech that isn't in the script")
                        options: [["keep", qsTr("Keep it")], ["between", qsTr("Drop between sentences")], ["strict", qsTr("Strict: also fillers inside sentences")]] }
                    SettingRow { label: qsTr("Handle before"); section: "edit"; key: "handle_before"; type: "slider"; from: 0; to: 0.5; step: 0.01; decimals: 2 }
                    SettingRow { label: qsTr("Handle after"); section: "edit"; key: "handle_after"; type: "slider"; from: 0; to: 0.8; step: 0.01; decimals: 2 }
                    SettingRow { label: qsTr("Longest pause kept"); section: "edit"; key: "max_pause"; type: "slider"; from: 0.2; to: 2.0; step: 0.05; decimals: 2 }
                    SettingRow { label: qsTr("Pause between sentences"); section: "edit"; key: "sentence_pause"; type: "slider"; from: 0.1; to: 1.5; step: 0.05; decimals: 2; hint: qsTr("Silence where a cut joins two takes, taken from the room around them") }
                    SettingRow { label: qsTr("Audio crossfade (ms)"); section: "edit"; key: "crossfade_ms"; type: "slider"; from: 0; to: 80 }
                }
            }
        }
    }
}
