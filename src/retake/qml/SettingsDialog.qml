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

    property bool phoneMode: app.settings.video.backend === "phone"
    property var uncoached: []
    function refreshUncoached() { uncoached = app.uncoachedWords() }
    Connections { target: app; function onUncoachedChanged() { dialog.refreshUncoached() } }
    // The detected camera the phone settings refer to, by id or by facing.
    property var phoneCamera: {
        const choice = String(app.settings.video.phone_camera || "back")
        const cameras = app.phoneCameras
        return cameras.find(c => c.id === choice) || cameras.find(c => c.facing === choice) || null
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
                    SettingRow { label: qsTr("Script language"); section: "general"; key: "script_language"; options: dialog.languageOptions; hint: qsTr("Language you read in") }
                    SettingRow { label: qsTr("Native language"); section: "general"; key: "native_language"; options: dialog.languageOptions; hint: qsTr("Used for respelling and typical mistakes") }
                    SettingRow { label: qsTr("Interface language"); section: "general"; key: "ui_language"; options: [["auto", qsTr("System")]].concat(dialog.languageOptions); hint: qsTr("Applies after restart") }
                    SettingRow { label: qsTr("Projects folder"); section: "general"; key: "projects_dir"; type: "text" }
                    SettingRow { label: qsTr("Extra speech"); section: "strictness"; key: "extra_speech"; hint: qsTr("What Auto edit does with speech that isn't in the script")
                        options: [["keep", qsTr("Keep it")], ["between", qsTr("Drop between sentences")], ["strict", qsTr("Strict: also fillers inside sentences")]] }
                    SettingRow { label: qsTr("Skipped or changed words"); section: "strictness"; key: "deviations"
                        options: [["accept", qsTr("Accept")], ["warn", qsTr("Warn")], ["require", qsTr("Require a retake")]] }
                    SettingRow { label: qsTr("Sound cues"); section: "sounds"; key: "enabled"; type: "switch"; hint: qsTr("Start, pause, stop, required retake, voice command heard, end of script") }
                    SettingRow { label: qsTr("Cue volume"); section: "sounds"; key: "volume"; type: "slider"; from: 0.05; to: 1.0; step: 0.05; decimals: 2; visible: !!(app.settings.sounds && app.settings.sounds.enabled) }
                }
            }

            ScrollView {
                ColumnLayout {
                    width: dialog.availableWidth - 20
                    spacing: 14
                    SettingRow { label: qsTr("Mode"); section: "prompter"; key: "mode"; hint: qsTr("V cycles while recording")
                        options: [["scroll", qsTr("Scroll: glides with your voice")], ["step", qsTr("Step: moves a line at a time")], ["card", qsTr("Card: current sentence, next below")], ["page", qsTr("Page: one paragraph at a time")]] }
                    SettingRow { label: qsTr("Font size"); section: "prompter"; key: "font_size"; type: "slider"; from: 20; to: 96 }
                    SettingRow { label: qsTr("Line width"); section: "prompter"; key: "line_width"; type: "slider"; from: 0.4; to: 1.0; step: 0.02; decimals: 2 }
                    SettingRow { label: qsTr("Reading line"); section: "prompter"; key: "reading_line"; type: "slider"; from: 0.1; to: 0.6; step: 0.01; decimals: 2; hint: qsTr("Height of the line you read from") }
                    SettingRow { label: qsTr("Mirror"); section: "prompter"; key: "mirror"; type: "switch"; hint: qsTr("For teleprompter glass") }
                    SettingRow { label: qsTr("Animations"); section: "prompter"; key: "animation"; type: "switch" }
                    SettingRow { label: qsTr("Show cues and pauses"); section: "prompter"; key: "show_cues"; type: "switch" }
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
                    SettingRow { label: qsTr("Pronunciation coach"); section: "coach"; key: "enabled"; type: "switch" }
                    SettingRow { label: qsTr("Warn below"); section: "coach"; key: "threshold"; type: "slider"; from: 20; to: 90; hint: qsTr("Words scoring below this show up in the coach panel") }
                    SettingRow { label: qsTr("Require a retake below"); section: "coach"; key: "require"; type: "slider"
                        from: 0; to: app.settings.coach.threshold; zeroText: qsTr("Off")
                        hint: qsTr("A word under this score rejects the take and sends you back to the sentence start. All the way left is off; it can't go above Warn") }
                    SettingRow { label: qsTr("Drill the failed word"); section: "coach"; key: "drill"; type: "switch"
                        visible: (app.settings.coach.require || 0) > 0
                        hint: qsTr("Hear the word and say it until it passes, then read the sentence again") }
                    SettingRow { label: qsTr("Times in a row"); section: "coach"; key: "drill_times"; type: "slider"; from: 1; to: 5
                        visible: (app.settings.coach.require || 0) > 0 && app.settings.coach.drill === true }
                    SettingRow { label: qsTr("Feedback"); section: "coach"; key: "timing"
                        options: [["live", qsTr("Live, after each sentence")], ["review", qsTr("Review at the end (pickups)")]] }
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
                    Label { text: qsTr("Words you keep missing"); opacity: 0.6; topPadding: 8 }
                    Repeater {
                        model: dialog.opened ? app.drillList() : []
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
                    SettingRow { label: qsTr("Microphone"); section: "audio"; key: "input"
                        options: [["default", qsTr("System default")]].concat(app.audioSources.map(s => [s.name, s.description])) }
                    SettingRow { label: qsTr("Channels"); section: "audio"; key: "channels"; hint: qsTr("For a mono mic on a stereo interface pick its side")
                        options: [["mix", qsTr("Mix")], ["left", qsTr("Left")], ["right", qsTr("Right")]] }
                    SettingRow { label: qsTr("Sample rate"); section: "audio"; key: "sample_rate"
                        options: [[0, "48 kHz"], [44100, "44.1 kHz"], [48000, "48 kHz"], [96000, "96 kHz"]] }
                    SettingRow { label: qsTr("Video"); section: "video"; key: "backend"
                        options: [["none", qsTr("Audio only")], ["builtin", qsTr("Screen + camera (gpu-screen-recorder)")], ["camera", qsTr("Camera only")], ["phone", qsTr("Phone camera (Android over USB, scrcpy)")], ["obs", qsTr("OBS")]] }
                    SettingRow { label: qsTr("Phone"); section: "video"; key: "phone_serial"; visible: dialog.phoneMode
                        hint: qsTr("Each phone keeps its own camera settings")
                        options: [["", qsTr("Automatic (first connected)")]].concat(app.phoneDevices.map(d => [d.serial, d.label])) }
                    SettingRow { label: qsTr("Camera"); section: "video"; key: "phone_camera"; visible: dialog.phoneMode
                        options: app.phoneCameras.length ? app.phoneCameras.map(c => [c.id, c.label])
                                                         : [["back", qsTr("Back (main)")], ["front", qsTr("Front")], ["external", qsTr("External")]] }
                    SettingRow { label: qsTr("Resolution"); section: "video"; key: "phone_size"; visible: dialog.phoneMode
                        options: dialog.phoneCamera ? dialog.phoneCamera.sizes.map(o => [o.value, o.label])
                                                    : [["3840x2160", "3840 × 2160 (16:9)"], ["1920x1080", "1920 × 1080 (16:9)"]] }
                    SettingRow { label: qsTr("Frame rate"); section: "video"; key: "phone_fps"; visible: dialog.phoneMode
                        options: dialog.phoneCamera ? dialog.phoneCamera.fps.map(o => [o.value, o.label]) : [[30, "30"]] }
                    SettingRow { label: qsTr("Codec"); section: "video"; key: "phone_codec"; visible: dialog.phoneMode
                        options: [["h265", qsTr("H.265 (better quality per bit)")], ["h264", "H.264"]] }
                    SettingRow { label: qsTr("Bit rate"); section: "video"; key: "phone_bitrate"; visible: dialog.phoneMode
                        options: [["20M", "20 Mb/s"], ["40M", qsTr("40 Mb/s (4K)")], ["80M", qsTr("80 Mb/s (4K, highest)")]] }
                    SettingRow { label: qsTr("Shape"); section: "video"; key: "phone_shape"; visible: dialog.phoneMode
                        hint: qsTr("Portrait records 9:16, like Reels and Shorts; stand the phone upright")
                        options: [["landscape", qsTr("Landscape 16:9 (phone sideways)")], ["portrait", qsTr("Portrait 9:16 (phone upright)")]] }
                    SettingRow { label: qsTr("Upside down"); section: "video"; key: "phone_flip"; type: "switch"; visible: dialog.phoneMode; hint: qsTr("If the picture comes out upside down") }
                    SettingRow { label: qsTr("Preview while recording"); section: "video"; key: "phone_preview"; type: "switch"; visible: dialog.phoneMode
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
                    SettingRow { label: qsTr("Screen to record"); section: "video"; key: "capture"; visible: app.settings.video.backend === "builtin"
                        options: [["", qsTr("Another monitor than this window")], ["portal", qsTr("Ask each time (portal)")]].concat(app.monitors.map(m => ["monitor:" + m.name, m.name + "  " + m.size])) }
                    SettingRow { label: qsTr("Frame rate"); section: "video"; key: "fps"; visible: app.settings.video.backend === "builtin"; options: [[30, "30"], [60, "60"]] }
                    SettingRow { label: qsTr("Camera layout"); section: "video"; key: "camera_layout"; visible: app.settings.video.backend === "builtin"
                        options: [["corner", qsTr("Corner")], ["small", qsTr("Small corner")], ["full", qsTr("Full screen")], ["off", qsTr("Off")]] }
                    SettingRow { label: qsTr("Camera device"); section: "video"; key: "camera_device"; type: "text"; visible: ["builtin", "camera"].indexOf(app.settings.video.backend) >= 0 }
                    SettingRow { label: qsTr("OBS host"); section: "video"; key: "obs_host"; type: "text"; visible: app.settings.video.backend === "obs" }
                    SettingRow { label: qsTr("OBS port"); section: "video"; key: "obs_port"; type: "text"; visible: app.settings.video.backend === "obs" }
                    SettingRow { label: qsTr("OBS password"); section: "video"; key: "obs_password"; type: "password"; visible: app.settings.video.backend === "obs" }
                    RowLayout {
                        visible: app.settings.video.backend === "obs"
                        Button { text: qsTr("Test connection"); onClicked: app.refreshObs() }
                        Label { text: app.obsScenes.length ? qsTr("Scenes: %1").arg(app.obsScenes.join(", ")) : ""; opacity: 0.6; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
            }

            ScrollView {
                ColumnLayout {
                    width: dialog.availableWidth - 20
                    spacing: 14
                    SettingRow { label: qsTr("Preset"); section: "engines"; key: "preset"; hint: qsTr("Restart the engine to apply")
                        options: [["auto", qsTr("Automatic")], ["nvidia", qsTr("NVIDIA GPU")], ["amd", qsTr("AMD GPU")], ["cpu", qsTr("CPU only")], ["light", qsTr("Light (no pronunciation scoring)")]] }
                    SettingRow { label: qsTr("Device"); section: "engines"; key: "device"; options: [["auto", qsTr("Automatic")], ["cuda", "GPU"], ["cpu", "CPU"]] }
                    SettingRow { label: qsTr("CPU threads"); section: "engines"; key: "threads"; type: "slider"; from: 1; to: 16 }
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: qsTr("The model for each job (voice following, commands, scoring…) is chosen in Models."); opacity: 0.7; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Button { text: qsTr("Models…"); highlighted: true; onClicked: modelsDialog.open() }
                    }
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
                    SettingRow { label: qsTr("Voice commands"); section: "voice"; key: "enabled"; type: "switch"; hint: qsTr("Restart the engine to apply") }
                    SettingRow { label: qsTr("Wake word"); section: "voice"; key: "wake_word"; type: "text"; hint: qsTr("Empty uses the language default (retake / diretor)") }
                    SettingRow { label: qsTr("Foot pedal device"); section: "controls"; key: "pedal_device"; type: "text"; hint: qsTr("/dev/input/by-id/… (needs the input group)") }
                    SettingRow { label: qsTr("Grab the pedal"); section: "controls"; key: "pedal_grab"; type: "switch"; hint: qsTr("Its keys never reach other apps; applies after restart") }
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        opacity: 0.7
                        text: qsTr("While the recorded app has focus, Retake can't see your keys. Bind Hyprland keys to “retake ctl next”, “retake ctl again”… The button copies a ready-to-paste snippet.")
                    }
                    Button { text: qsTr("Copy Hyprland snippet"); enabled: app.hyprlandAvailable; onClicked: app.copyHyprlandSnippet() }
                }
            }

            ScrollView {
                ColumnLayout {
                    width: dialog.availableWidth - 20
                    spacing: 14
                    SettingRow { label: qsTr("Keep"); section: "edit"; key: "keep"; options: [["last", qsTr("Last good take")], ["best", qsTr("Best scored take")]] }
                    SettingRow { label: qsTr("Order"); section: "edit"; key: "order"; options: [["source", qsTr("As recorded")], ["script", qsTr("Script order")]] }
                    SettingRow { label: qsTr("Handle before"); section: "edit"; key: "handle_before"; type: "slider"; from: 0; to: 0.5; step: 0.01; decimals: 2 }
                    SettingRow { label: qsTr("Handle after"); section: "edit"; key: "handle_after"; type: "slider"; from: 0; to: 0.8; step: 0.01; decimals: 2 }
                    SettingRow { label: qsTr("Longest pause kept"); section: "edit"; key: "max_pause"; type: "slider"; from: 0.2; to: 2.0; step: 0.05; decimals: 2 }
                    SettingRow { label: qsTr("Audio crossfade (ms)"); section: "edit"; key: "crossfade_ms"; type: "slider"; from: 0; to: 80 }
                    SettingRow { label: qsTr("Normalize loudness"); section: "edit"; key: "normalize"; type: "switch" }
                    SettingRow { label: qsTr("Loudness target (LUFS)"); section: "edit"; key: "loudness"; type: "slider"; from: -24; to: -12; step: 0.5; decimals: 1 }
                    SettingRow { label: qsTr("Auto edit when recording stops"); section: "edit"; key: "auto_on_stop"; type: "switch" }
                }
            }
        }
    }
}
