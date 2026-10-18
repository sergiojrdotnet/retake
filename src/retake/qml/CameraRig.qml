import QtQuick
import QtMultimedia

// The camera chosen in Settings → Recording (any video device but the phone): it feeds the camera
// panel and records the part's video, with the microphone for lining it up with the audio.
Item {
    id: rig
    property bool wanted: app.cameraSource === "device" && app.page === "session"
    property alias output: frames
    property bool hasCamera: app.cameraAllowed && devices.videoInputs.length > 0

    MediaDevices { id: devices }

    function pickDevice() {
        const wanted = app.settings.camera.device || ""
        for (const device of devices.videoInputs) {
            if (wanted && (String(device.id) === wanted || device.description === wanted))
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
        videoOutput: frames
        audioInput: audio
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
                        app.setSetting("camera", "codec", "h265")
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
            recorder.attempt = app.settings.camera.codec === "h265" ? 1 : 0
            recorder.outputLocation = "file://" + path
            recorder.record()
        }
        function onCameraStop() {
            recorder.stopping = true
            recorder.stop()
        }
    }

    // Never shown: the camera panel copies its frames (app.forwardFrames), so the camera keeps
    // running while the layout swaps panels in and out.
    VideoOutput {
        id: frames
        visible: false
    }
}
