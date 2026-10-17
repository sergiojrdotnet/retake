# retake — Feature Spec

Solo talking recordings on Linux with the retakes handled for you. Records lossless audio and optional screen + camera, takes voice commands, marks retakes as you go and proposes the edit when you ask, in a built-in trim editor. With a script it adds a voice-following prompter, pronunciation guidance and coaching for non-native speakers.

Status: v0.1 implemented; GPU paths (faster-whisper, NVENC, gpu-screen-recorder) await testing on a free GPU.

## Decisions

| Topic | Decision |
|---|---|
| Session types | Scripted (prompter) and free (no script); both in v1 |
| Build vs adopt | Build our own; no existing Linux tool covers tracking + pronunciation + retakes + recording |
| Name | `retake` — binary, package, `.desktop` file and Wayland app id |
| Stack | Python + PySide6 / Qt Quick (native Wayland); three processes — UI, recorder, engine — so an engine crash never stops a recording |
| UI conventions | Omarchy app style: live theme accent, keyboard-first, `?` shortcut overlay; Hype/Monologue/Omacut (MIT) as reference code |
| Delivery | Everything ships before first use (single delivery) |
| Pronunciation guides | Configurable: IPA, English respelling, Portuguese respelling, any combination; scope all / hard words / flagged |
| Speech engines | Pluggable and configurable per preset; local-only in v1 |
| Voice commands | Wake word + command; wake word configurable |
| Recording | Lossless audio in-app; video optional |
| Video content | Screen + camera picture-in-picture, screen only, or camera only (Monologue parity) |
| Video backend | Built-in (gpu-screen-recorder) by default; OBS optional for scenes, filters and compositing |
| Camera (built-in) | Own camera window on the captured screen, resized by layout cues or keys |
| Script-driven video | Camera layout cues (built-in) or scene switching (OBS); chapter per section |
| Editing | Recording only places markers; Auto edit runs on demand in Studio's full trim editor; Render produces rough cut + timeline |
| Retake policy default | Warn and let the speaker decide (strict mode available) |
| Publishing | AUR |
| Dependencies | Base package depends only on official Arch repo packages and stays light (no PyTorch); PyTorch (Silero, pronunciation scoring) and AUR engines are optional upgrades |
| Goal | Good enough for Omarchy to ship in place of Monologue; public open-source repo |
| Languages | Language-agnostic core with language packs; v1 ships English script pack, pt-BR native pack, en/pt UI |
| License | MIT (allows reuse of Hype/Monologue/Omacut code with attribution) |

## Recording types

Markers, commands and editing never assume a script; in a free session the live transcript plays the script's role.

| | Scripted | Free |
|---|---|---|
| Main screen | Prompter | Camera preview, mic level meter, live transcript |
| Sentence boundaries | Script sentences | Pauses + transcript punctuation (pauses only with the base Vosk engine) |
| "Again" / `R` | Back to sentence start | Mark the sentence in progress rejected, re-say it |
| Implicit retakes | Tracker jumps back in the script | Near-duplicate consecutive sentence; earlier attempt marked rejected |
| Pronunciation coaching | Against the script | Against the intended text inferred from the transcript (needs faster-whisper) |
| Chapters | `#` sections | "Mark" command / `M` |
| Outputs | Rough cut, timeline, captions, chapters, narration | Same |

## 1. Script

- Markdown input. Conventions borrowed from Fountain and broadcast/voice-over practice:
  - `#`, `##` sections: shown as dividers, never tracked; each becomes a chapter
  - `[[note]]`: hidden from the prompter
  - `(CUE)`: delivery cue, shown dimmed, not tracked
  - `(CAMERA: full|corner|off)`: camera layout change fired when tracking reaches that point (built-in backend)
  - `(SCENE: Name)`: OBS scene switch fired when tracking reaches that point (OBS backend)
  - `(AD-LIB)` … `(/AD-LIB)`: intentional improvisation; speech inside is never off-script
  - `/` short pause, `//` long pause: shown as pause marks, not tracked
  - `{word|ˈipa}`: inline pronunciation override
  - Fenced code blocks: ignored
- Sidecar lexicon (`<script>.lexicon.tsv`): word, IPA override, flagged — keeps the script clean for repeated terms
- Live reload when the script file changes
- Pre-flight check before a session:
  - Words with no dictionary pronunciation (acronyms, CLI names) → fix list
  - Known heteronyms (e.g. "aggregate" noun/verb, "read", "live") → confirm reading
  - Wake word appearing in the script → warning
  - Cues the selected backend can't honour; unknown OBS scene names

## 2. Main screen

### Layouts

Panels: prompter, live transcript, camera preview, mic level meter, coach (flagged words, guides, listen), takes list, resources, status bar (REC, elapsed time, take count, backend status, resource summary — always visible).

Preset layouts, cycled with `Tab` / `Shift+Tab` or jumped to with `1`–`5`:

| # | Layout | Panels | Default for |
|---|---|---|---|
| 1 | Prompter | Prompter full window | Scripted sessions |
| 2 | Coach | Prompter (or transcript) + coach side panel | Coached sessions |
| 3 | Monitor | Camera preview large, level meter, transcript strip | Free sessions |
| 4 | Studio | Live: prompter/transcript, camera, takes, coach, meter, resources in a grid. Edit: trim editor (§10) | Setup, editing |
| 5 | Strip | Current sentence only, compact window under the webcam | Eye-line during camera shots |

```
1 Prompter            2 Coach               3 Monitor             4 Studio              5 Strip
+-----------------+   +-----------+-----+   +-----------------+   +--------+--------+   +-----------------+
| REC 03:12  T4   |   | REC ...         |   | REC ...         |   | REC ...         |   | Next we flush…  |
|                 |   |           |flag |   |                 |   | prompt | camera |   +-----------------+
|  …we flush the  |   | prompter  |word |   |     camera      |   |        |        |
|  ▶ snapshot to  |   |           |/ipa/|   |                 |   +--------+--------+
|  the store…     |   |           |🔊   |   | ▁▃▅▇ level      |   | takes  | coach  |
|                 |   |           |     |   | transcript…     |   |        | ▁▃▅▇   |
+-----------------+   +-----------+-----+   +-----------------+   +--------+--------+
```

- Individual panels toggle on top of any preset from the `?` overlay / layout menu; custom arrangements save as named layouts
- Last layout remembered per session type
- The camera preview and the camera window on the captured monitor share one camera stream (one device, two outputs)

### Resource monitor

Several models run at once (tracking, commands, scorer, TTS) next to a video encoder, so consumption is always visible:

- Status bar (always on): GPU %, VRAM used/total, CPU %, RAM, disk left as recording time
- Resources panel:
  - System: CPU, RAM/swap, GPU utilization, VRAM, temperature, throttling, video encoder (NVENC) load, disk free and write rate
  - Per process: UI, engine, recorder (gpu-screen-recorder / OBS) and other GPU consumers (e.g. an LLM server holding VRAM)
  - Per engine: loaded model, VRAM/RAM footprint, inference latency, real-time factor, tracking lag (speech → highlight), queue depth, audio dropouts
- Pre-flight: estimated VRAM/RAM of the selected preset vs what's free; when it won't fit, says which processes hold the memory and suggests a lighter preset
- Live warnings (VRAM near full, latency over budget, throttling, low disk, dropped audio) in the status bar, never interrupting the recording; optional automatic downgrade (e.g. tracking falls back to Vosk)
- Resource timeline saved with the session (`resources.csv`) to explain glitches afterwards
- Sources: NVML (`python-nvidia-ml-py`) and psutil, both in official repos; AMD via sysfs; Intel limited without privileges — the panel says what it can't see

### Prompter display modes

Display modes, switchable at runtime (hotkey `V`) and set per preset:

| Mode | Behaviour | Best for |
|---|---|---|
| Scroll | Continuous glide, voice-paced; current word stays on the reading line | Classic prompter feel, long paragraphs |
| Step | Holds still, then snaps one line forward with a short animation when the line is done | Less motion, easier to read guides |
| Card | Current sentence large, next sentence previewed below (optional previous above) | Camera eye-line, coaching, retakes |
| Page | Slide-like page per paragraph or section, flips when finished | Structured scripts, overview while speaking |

Shared options:

- Reading line position, context lines before/after, transition animation on/off
- Word highlight (spoken / current / upcoming), font, size, line width, margins
- Mirror (horizontal flip) for prompter glass
- Show/hide cues and pause marks
- Pronunciation guides rendered above each word (stacked rows when several modes are on)
- Window intended for the laptop screen under the webcam; screen capture targets another monitor

## 3. Pronunciation guides

- Internal representation: phoneme sequence with stress (ARPAbet-like)
- Sources: CMUdict, espeak-ng fallback, lexicon and inline overrides (IPA parsed into the same representation)
- Renderers: IPA, English respelling (`AG-ri-git`), Portuguese respelling (`É-gri-guit`)
- Scope: all words / hard words (multi-syllable, out-of-dictionary, lexicon entries) / flagged only
- Click a word (or `F`) to flag/unflag; flags persist in the lexicon

## 4. Speech engines (pluggable)

| Role | Engine | Tier | Does |
|---|---|---|---|
| Voice activity | Silero VAD | Base | Speech vs silence: gates ASR (no hallucination on silence), sentence ends, take boundaries, command isolation |
| Tracking ASR | Vosk | Base | Streaming words → prompter position, live transcript; no punctuation |
| Tracking ASR | faster-whisper | Optional | Better on accented speech, punctuation, word timestamps; intended text for free-session coaching |
| Commands | Vosk closed grammar | Base | Only `<wake word>, <command>` can be output → few false triggers |
| Pronunciation scorer | wav2vec2 phoneme CTC (`facebook/wav2vec2-lv-60-espeak-cv-ft`) | Base | Heard phonemes per word vs expected → word scores; forced alignment → word boundaries for cuts |
| Pronunciation scorer | ASR miscue only | Base | No model; skipped/substituted words from tracking |
| Reference voice | espeak-ng | Base | "Listen" / "how do I say"; 100+ languages, robotic |
| Reference voice | Piper | Optional | Natural native voice |

Guides themselves are not AI: CMUdict (English, with stress) → IPA/respellings, espeak-ng G2P fallback.

| Engine | Package (source) | License engine / model | Runs on | Model / footprint |
|---|---|---|---|---|
| Silero VAD | `python-pytorch` (extra) + downloaded model | MIT / MIT | CPU | ~2 MB |
| Vosk | `python-vosk` (extra) | Apache-2.0 / Apache-2.0 | CPU | `small-en-us-0.15` 40 MB (~300 MB RAM); `en-us-0.22-lgraph` 128 MB |
| Vosk commands | same | same | CPU | `small-en-us-0.15`, `small-pt-0.3` 31 MB; must be small/dynamic-graph (big models can't load grammars) |
| faster-whisper | `python-faster-whisper` + `python-ctranslate2` (AUR) | MIT / MIT | CUDA (cuBLAS + cuDNN, extra) or CPU int8 | `small.en` ~0.5 GB VRAM, `large-v3-turbo` int8 ~1.5–2 GB (estimates) |
| wav2vec2 | `python-pytorch{,-cuda,-rocm}` + `python-safetensors` (extra); own model code (torchaudio/transformers not packaged) | BSD / Apache-2.0 | CUDA, ROCm or CPU | 315M params: ~1.3 GB fp32, ~0.65 GB fp16 |
| espeak-ng | `espeak-ng` (extra), subprocess | GPL-3.0 | CPU | few MB |
| Piper | `piper-tts-bin` (AUR) | MIT / per voice | CPU | ~60 MB per voice; presets list permissive voices only |

Hardware presets:

| Preset | Tracking | Scorer | Reference voice |
|---|---|---|---|
| NVIDIA | faster-whisper (CUDA) | wav2vec2 CUDA fp16 | Piper |
| AMD | Vosk | wav2vec2 ROCm | Piper / espeak-ng |
| CPU-only | Vosk | wav2vec2 CPU (runs after each sentence) | espeak-ng |

Concurrency:

| Engine | Runs | Where |
|---|---|---|
| Silero VAD | Continuously (30 ms frames) | CPU |
| Tracking ASR | While speech is present (faster-whisper re-decodes the sentence window ~every 0.5 s; Vosk streams) | GPU / CPU |
| Command recognizer | Continuously, in parallel with tracking on the same audio | CPU |
| Scorer | Once per finished sentence (~0.1–0.3 s on GPU) | GPU / CPU |
| TTS | On request | CPU |

- One thread per engine; native libraries (Vosk, ctranslate2, PyTorch) release the GIL, so they truly run in parallel
- GPU priority queue: tracking > scorer; the scorer mostly lands in the pause after a sentence
- Video encoding uses NVENC, a separate hardware block, so it barely competes with inference

Processes:

| Process | Owns | Dependencies |
|---|---|---|
| Recorder | Audio capture, lossless file, 16 kHz audio to the engine over a reconnectable Unix socket | No ML |
| Engine | All models, GPU queue | PyTorch, Vosk, optional faster-whisper/Piper |
| UI | PySide6 window, video backend control, session logic (tracker, takes, coach) | Qt |

- Engine crash: recording continues, UI shows the engine down and restarts it; only tracking pauses meanwhile

- Engines and models selected through named presets in a config file, switchable from the UI
- Model download/management page with footprint estimates
- Small protocol clients written in-house instead of unpackaged libraries: gpu-screen-recorder IPC, obs-websocket v5, OpenTimelineIO JSON

Risks to verify first:

- ctranslate2 officially targets CUDA 12 + cuDNN 9; the system has CUDA 13.4. Test the AUR build early; fallback is a private venv with CUDA 12 wheels outside the package
- VRAM: turbo + wav2vec2 + Silero ≈ 2.5 GB fits 6 GB alone, not next to an LLM server holding 3.3 GB → `small.en`
- Big Vosk models need up to 16 GB RAM and can't do grammars; FalaBrazil pt model is GPL-3.0 (download-only, never bundled)

## 5. Tracking

- Mic → VAD-gated audio → tracking ASR on the current sentence window → fuzzy word alignment to the script → position events
- Tolerates skipped words, filler words and ad-libs; never advances on silence
- Manual override always wins (keys / voice)

### Script strictness (scripted sessions)

Off-script speech = VAD-detected speech with no aligned script words (independent of the transcript, since Whisper tends to omit fillers). It gets an `off-script` marker with its transcript; Auto edit acts on it per setting.

| Setting | Options | Default |
|---|---|---|
| Extra speech | Keep / Drop between sentences / Strict (also fillers, repeated words, insertions inside sentences) | Drop between sentences |
| Deviations (substituted or skipped words) | Accept / Warn / Require retake | Warn |

- Strict inside-sentence cuts can sound choppy and show as camera jump cuts; crossfades soften them
- Live "off-script" indicator; the prompter holds position and resumes when the speaker returns to the script
- Filler lists come from the language pack; free sessions can use them for filler removal only

## 6. Coaching

- Per sentence after it ends: skipped/substituted words and low pronunciation scores
- Problem words shown with their guide and a "listen" button (TTS reference)
- Policy, configurable: warn (default) / require retake / log only; adjustable score threshold
- "How do I say ___" mid-sentence: the partial sentence becomes a rejected take, the command and the TTS playback are excluded, the prompter rewinds and waits for a full re-read
- Retake restart point, configurable: sentence start (default, natural intonation) or last pause mark/comma (finer cuts, splice risk)
- Implicit retakes: when the speaker stumbles and restarts the sentence without any command, the tracker detects the jump back and marks the partial take rejected
- Coach is a per-session toggle, independent of session type
- Practice history per word; repeatedly missed words become flagged automatically
- Drill list export
- Rehearsal mode: full flow, nothing kept

Free-session coaching (no script):

- Intended text: Whisper transcript (its language model normalizes toward what the speaker meant)
- Actual sounds: wav2vec2 phoneme recognition on the same audio (no language model)
- Flags: expected phonemes of the intended words vs heard phonemes, plus words Whisper itself was unsure of
- Native-language error catalog (from the native pack) weights likely L1 errors, e.g. for pt-BR: vowel length (beach/bitch, sheet/shit), TH → t/d/f, vowel epenthesis, "-ed" as an extra syllable, initial R as H, stress shifts
- Retake verified as the same sentence (near-duplicate match) with the flagged word fixed, then it's marked as the preferred take
- Known blind spot: a mispronunciation that Whisper hears as a different real word becomes the reference and passes; context and the error catalog catch common cases only
- Strictness targets intelligibility, not native-likeness; adjustable
- Timing, configurable: live after each sentence (default; video stays consistent) or end-of-session review where flagged sentences become a mini-script for pickups (fine for audio; breaks lip sync when the camera is visible, so the app warns)

## 7. Controls

During screen-capture demos keyboard focus sits in the recorded app (terminal, browser), so in-window shortcuts alone never reach the prompter. Controls must work without focus:

- Global shortcuts through the XDG GlobalShortcuts portal (supported by Hyprland), or Hyprland binds calling a control CLI
- Foot pedal / clicker read directly via evdev and grabbed exclusively, so its keys never leak into the recorded app
- Voice commands (below), focus-independent by nature

Keys (in-window defaults; global variants use a modifier):

| Key | Action |
|---|---|
| Space | Record / pause / resume |
| Shift+Space | Rehearse |
| Enter | Stop and open the editor |
| → / PgDn | Next sentence |
| ← / PgUp | Previous sentence |
| R | Retake current sentence |
| M | Mark spot |
| L | Listen to current/flagged word |
| F | Flag current word |
| V | Cycle prompter display mode |
| Tab / Shift+Tab, 1–5 | Main-screen layouts |
| C | Camera layout |
| P | Script check |
| Esc | Back to start / close overlay |
| ? | Shortcut overlay |
| Q | Quit (asks first while recording or with an unsaved edit) |

Voice commands, `<wake word>, <command>`, phrases configurable:

- again · next · back · pause · resume · mark · stop · "how do I say ___"
- Must be isolated by ~0.5 s of silence; recognized by the closed-grammar recognizer in parallel with tracking
- Command audio labelled and dropped by Auto edit
- Feedback is visual only by default (a speaker beep would leak into the recording)

## 8. Recording

- Continuous lossless capture (FLAC, device native rate) from the selected input; never stops on retakes
- Crash-safe incremental writing; an interrupted recording is recovered as a part when the project opens
- Every take labelled: sentence, take number, scores, accepted/rejected; command segments labelled excluded

Session modes:

| Mode | Needs | Available |
|---|---|---|
| Audio only | Microphone | Everything except video; camera and scene cues hidden |
| Audio + video (built-in) | gpu-screen-recorder (official repos, preinstalled on Omarchy) | Everything except OBS scenes |
| Camera only | Camera + microphone (Qt Multimedia recorder, like Monologue) | Everything except screen capture and scenes |
| Audio + video (OBS) | OBS with obs-websocket enabled | Everything except camera layout cues (OBS scenes replace them) |

- Audio only is the default until video is enabled; if the chosen video backend is unavailable, the session start says so and offers audio only

## 9. Video backends

Built-in (default) — gpu-screen-recorder, the recorder Omarchy's own screen capture uses:

- Captures a monitor or region with mic audio as sync reference; hardware encoding (NVENC/VAAPI) with CPU fallback
- Controlled over its JSON IPC socket (`-ipc`): start, stop (returns the file path), pause
- `-write-first-frame-ts` gives the exact start time for sync with the app's audio
- Camera shown in the app's own window (Qt Multimedia) on the captured monitor; layouts full / corner / off, switched by `(CAMERA: …)` cues or keys, placed through Hyprland
- Prompter window stays on a monitor that isn't captured (laptop screen under the webcam)

OBS (optional) — obs-websocket v5:

- Start/stop recording with the session
- Scene switching from `(SCENE: …)` cues, undoable by key
- Connection status and scene list visible in the UI; pre-flight validates cue scene names

## 10. Markers, editing and exports

Nothing is cut during recording. The session file stays continuous and untouched; every decision is a marker until the speaker asks for an edit.

Markers (written live to `takes.json`):

- Take start/end with sentence id and take number
- Retake reason: voice command, implicit restart, coach warning
- Command segments and TTS playback
- Pronunciation scores and flagged words
- Chapters (sections / "mark"), camera layout and scene changes

Studio → Edit (full trim editor, Monologue-like; its MIT QML filmstrip/trim UI adapted, backend rewritten in Python):

- Timeline: waveform, video filmstrip, transcript, marker lanes (incl. off-script with its transcript, one-click restore), take lanes per sentence
- Auto edit (on demand; optional "auto edit on stop" setting, off by default) proposes an edit decision list from rules:
  - keep the last good take per sentence (or best score)
  - drop rejected takes, commands, TTS playback, silences over a threshold
  - drop off-script speech per the strictness setting (§5)
  - handles around cuts, optional camera crossfades
  - flag screen state that changed during a dropped take (e.g. a command already typed)
- Review: A/B takes of a sentence, swap the chosen take, nudge boundaries, restore dropped segments
- Free trimming anywhere: split, remove, restore into gaps, move clip edges to playhead, ripple, undo/redo
- Re-run Auto edit with other rules at any time; the edit is saved as `edit.json`, originals never modified (atomic saves)
- Preview playback of the edit with synced audio and video

Edit keys (active only in the Edit view; Monologue conventions):

| Key | Action |
|---|---|
| Space | Play / pause |
| ← / → | Move playhead 1 s (Shift 5 s, Alt 0.2 s) |
| [ / ] | Previous / next marker or clip edge |
| T | Cycle take for the sentence under the playhead |
| S | Split at playhead |
| X / Delete | Remove clip; restore when on a gap |
| Ctrl+Space / Alt+Space | Clip start / end to playhead |
| A | Auto edit |
| Z | Zoom to clip / zoom out |
| Ctrl+Z / Ctrl+Shift+Z | Undo / redo |
| Ctrl+S | Save edit |
| Ctrl+E | Render |

Render (from the approved edit):

- Sync video with the app's audio from the recorder's first-frame timestamp; cross-correlating the audio tracks as fallback (and for OBS)
- Rough cut: ffmpeg cuts from audio and video, re-encoded with NVENC; chapters written from section timestamps
- Clean narration audio as FLAC/WAV/Opus/MP3, optional loudness normalization (ffmpeg `loudnorm`, e.g. −16 LUFS), chapters in FLAC/Opus metadata and MP3 ID3
- Editable timeline: OpenTimelineIO (`.otio`) for DaVinci Resolve and Kdenlive, markers included
- WebVTT/SRT captions with word timing rebased to the edit, Audacity label track
- Raw export: the untouched recording plus markers (OTIO / Audacity labels) for editing entirely elsewhere

## 11. Languages

Three independent settings:

| Setting | Drives |
|---|---|
| Script language | Tracking model, G2P/lexicon, scorer reference phonemes, TTS voice, sentence/word segmentation |
| Native language | Respelling renderer (phoneme → native orthography table), L1 error catalog for coaching; IPA works for everyone |
| UI language | Qt translations (`qsTr` + `.ts`), voice command phrases and wake word |

- Language pack = tracking model + command grammar + lexicons + respelling table + L1 error catalog + filler words + TTS voice + UI translation; data-only, community-contributable
- No hard-coded English: CMUdict is the English lexicon, espeak-ng the fallback for other languages
- Unsegmented scripts (Chinese, Japanese, Thai) need a word segmenter; RTL handled by Qt
- Pronunciation scoring quality is validated for English only; other languages flagged as uncalibrated in the UI

## 12. Distribution

- AUR package `retake`: binary entry point, `.desktop` file, icon, `optdepends` for AUR engines
- Models downloaded on first use into `~/.local/share/retake/models`, never packaged
- Later candidates: Omarchy package repo PR, bar-widget plugin (on-air light, take count, pause) for the Omarchy plugin marketplace

## Projects

A project is a course or series: a folder with a `.retake` file (JSON: title, languages, capture settings, items and their parts). Scripts are imported (copied into `scripts/`); each script, and each free recording, is an item with its own folder.

- An item is recorded over one or more **parts** (`part-00N.flac`, `video/part-00N.mp4`). Parts sit end to end on one virtual timeline, so takes, markers and the edit use a single clock; rendering reads each piece from its own part.
- Opening a script puts the prompter on the first sentence without a good take; the next recording becomes a new part of the same item.
- **Pickups**: in the studio, select sentences and press `R`; the prompter queues just those sentences, records a pickup part, and the new takes replace those sentences' clips in the edit (other hand edits stay).
- Scripts with more than one part always play in script order.
- `item/script.md` is a snapshot of the script the takes refer to; if the imported script changes, the next recording re-points takes by sentence text and sets aside takes whose sentence is gone.
- A crash leaves `part-00N.flac` and `part-00N.takes.json`; opening the project recovers them as a part.

```
<Project>/
  <Project>.retake
  scripts/ep1.md, ep1.lexicon.tsv
  ep1/
    script.md             snapshot the takes refer to
    part-001.flac …       recordings and pickups
    part-001.resources.csv
    takes.json            takes and markers of all parts, on the item timeline
    edit.json             edit decision list (Auto edit + manual changes)
    video/part-001.mp4 …  screen or camera per part (or a link to the OBS file)
    out/                  narration, rough cut, timeline.otio, captions, sentences.json
  free-<timestamp>/       free recordings, same layout
```

## Environment notes

- GPU: RTX 1000 Ada 6 GB — tracking ASR, scorer and TTS run locally
- Audio: Burr-Brown USB audio interface via PipeWire
- Monitors: laptop eDP-1 (prompter, under webcam), DP-5 2560×1440 and HDMI-A-1 (capture targets)
- gpu-screen-recorder 6.1.3, OBS 32.2.2, DaVinci Resolve 21, espeak-ng 1.52, ffmpeg installed

## Out of scope (v1)

- External engines — cloud APIs (e.g. Azure unscripted pronunciation assessment, streaming STT, TTS), OpenAI-compatible servers on another machine, LLM helpers (respellings, explanations); the engine interface is role-based and transport-agnostic so they can be added without redesign
- Own screen encoder (gpu-screen-recorder does it)
- Mobile / remote control from phone
- Omarchy package repo submission and bar-widget plugin
- Language packs beyond English script + pt-BR native
