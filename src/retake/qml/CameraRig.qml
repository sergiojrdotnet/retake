import QtQuick
import QtQuick.Window
import QtMultimedia

Item {
    id: rig
    property string backend: app.videoBackend
    property bool wanted: !app.phoneMode && app.page === "session" && (backend === "builtin" || backend === "camera" || app.panels.camera === true)
    property alias output: windowOutput
    property bool hasCamera: app.cameraAllowed && devices.videoInputs.length > 0

    MediaDevices { id: devices }

    function pickDevice() {
        const wantedPath = app.settings.video.camera_device || ""
        for (const device of devices.videoInputs) {
            if (wantedPath && (String(device.id) === wantedPath || device.description === wantedPath))
                return device
        }
        return devices.defaultVideoInput
    }

    function pickAudio() {
        const wanted = app.settings.audio.input || "default"
        for (const device of devices.audioInputs) {
            if (String(device.id) === wanted)
                return device
        }
        return devices.defaultAudioInput
    }

    function bestFormat(device) {
        let best = null
        for (const format of device.videoFormats) {
            if (format.maxFrameRate < 24)
                continue
            const pixels = format.resolution.width * format.resolution.height
            const bestPixels = best ? best.resolution.width * best.resolution.height : 0
            if (!best || pixels > bestPixels || (pixels === bestPixels && Math.abs(format.maxFrameRate - 30) < Math.abs(best.maxFrameRate - 30)))
                best = format
        }
        return best
    }

    Camera {
        id: camera
        active: rig.wanted && rig.hasCamera
        cameraDevice: rig.pickDevice()
        onCameraDeviceChanged: {
            const format = rig.bestFormat(cameraDevice)
            if (format)
                cameraFormat = format
        }
        onErrorOccurred: (error, message) => app.notice("error", qsTr("Camera: %1").arg(message))
    }

    CaptureSession {
        id: capture
        camera: camera
        videoOutput: windowOutput
        audioInput: rig.backend === "camera" ? audio : null
        recorder: MediaRecorder {
            id: recorder
            // Qt's bundled FFmpeg has no software H.264 encoder, and some GPUs refuse the
            // high-bit-depth H.264 Qt asks for camera frames; H.265 is the fallback that encodes there.
            property var codecs: [MediaFormat.VideoCodec.H264, MediaFormat.VideoCodec.H265]
            property int attempt: 0
            property bool stopping: false
            property bool retryPending: false
            quality: MediaRecorder.HighQuality
            mediaFormat {
                fileFormat: MediaFormat.MPEG4
                videoCodec: recorder.codecs[recorder.attempt]
                audioCodec: MediaFormat.AudioCodec.AAC
            }
            onRecorderStateChanged: {
                if (recorderState === MediaRecorder.RecordingState) {
                    app.cameraRecordingStarted(actualLocation.toString())
                } else if (recorderState === MediaRecorder.StoppedState && retryPending) {
                    retryPending = false
                    if (!stopping)
                        record()
                } else if (recorderState === MediaRecorder.StoppedState && stopping) {
                    app.cameraRecordingFinished()
                }
            }
            onErrorOccurred: (error, message) => {
                if (!stopping && error === MediaRecorder.ResourceError && attempt + 1 < codecs.length) {
                    attempt += 1
                    retryPending = true
                    if (codecs[attempt] === MediaFormat.VideoCodec.H265)
                        app.setSetting("video", "camera_codec", "h265")
                    if (recorderState === MediaRecorder.StoppedState) {
                        retryPending = false
                        record()
                    }
                    return
                }
                app.notice("error", qsTr("Camera recording: %1").arg(message))
            }
        }
    }
    AudioInput {
        id: audio
        device: rig.pickAudio()
    }

    Connections {
        target: app
        function onCameraRecord(path) {
            recorder.stopping = false
            recorder.attempt = app.settings.video.camera_codec === "h265" ? 1 : 0
            recorder.outputLocation = "file://" + path
            recorder.record()
        }
        function onCameraStop() {
            recorder.stopping = true
            recorder.stop()
        }
        function onCameraChanged() { if (cameraWindow.visible) app.placeCamera() }
    }

    Window {
        id: cameraWindow
        title: "Retake camera"
        width: 480
        height: 270
        color: "black"
        flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus
        visible: rig.wanted && rig.backend === "builtin" && app.cameraLayout !== "off" && rig.hasCamera
        onVisibleChanged: if (visible) app.placeCamera()
        VideoOutput {
            id: windowOutput
            anchors.fill: parent
            fillMode: VideoOutput.PreserveAspectCrop
        }
    }
}
