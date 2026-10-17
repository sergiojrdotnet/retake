<p align="center">
  <img src="src/retake/assets/retake.svg" width="128" alt="Retake">
</p>

<h1 align="center">Retake</h1>

<p align="center">
  <strong>Record yourself talking. The retakes are handled for you.</strong><br>
  A voice-following teleprompter, pronunciation coach, recorder and editor for Linux.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/platform-Linux%20%C2%B7%20Wayland-informational" alt="Linux, Wayland">
  <img src="https://img.shields.io/badge/runs-100%25%20local-success" alt="Runs locally">
</p>

<!-- Demo video goes here -->

<!-- Screenshot: prompter with pronunciation guides -->

---

Recording a talk, a tutorial or a study case alone usually means juggling a prompter, a recorder and an editor, then spending an hour cutting out the stumbles. Retake does all three in one window:

- **The prompter follows your voice.** It scrolls as you read, highlights the next word and never moves while you're silent.
- **Retakes are marked, not cut.** Say *“retake, again”*, press `R`, or just start the sentence over. Retake marks the bad take and keeps recording.
- **Auto edit builds the cut.** When you stop, it proposes an edit that keeps the last good take of every sentence and drops retakes, voice commands and long pauses. Review it in the built-in trim editor, then export.
- **Pronunciation coaching for non-native speakers.** Pronunciation guides above hard words (IPA, English respelling and respelling in your own language), plus a coach that tells you which word to try again and why, and, if you want it strict, makes you drill a missed word until it's right before reading the sentence again.

Everything runs on your machine. Audio never leaves it.

## Contents

- [Features](#features)
- [Install](#install)
- [Quick start](#quick-start)
- [Writing a script](#writing-a-script)
- [Recording](#recording)
- [Voice commands](#voice-commands)
- [Keyboard](#keyboard)
- [Controlling Retake from anywhere](#controlling-retake-from-anywhere)
- [Pronunciation coach](#pronunciation-coach)
- [Editing and exports](#editing-and-exports)
- [Speech engines](#speech-engines)
- [Languages](#languages)
- [Command line](#command-line)
- [Files](#files)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Credits](#credits)

## Features

| | |
|---|---|
| **Projects** | A project is a course or series: import its scripts, record each one over as many days as you like, re-record single sentences from the studio, and export per script. A collapsible explorer (`Ctrl+B`) shows every script with its recordings, edit and exports. |
| **Scripted or free recordings** | Read from a Markdown script, or just talk: in free recordings the live transcript takes the script's place and repeated sentences count as retakes. |
| **Prompter modes** | Scroll (glides with your voice), step (one line at a time), card (current sentence big, next one below) and page (one paragraph at a time). Mirror mode for teleprompter glass. |
| **Layouts** | **Full** (the prompter with the camera, coach and takes beside it), **Focus** (only the prompter, at full width) and **Lens** (one sentence at a time, for a small window right under the camera). Switch with `Tab`, or `1`–`3`. The top bar always shows the microphone and the machine's meters. |
| **Recording** | Lossless FLAC of your microphone, always. Optional video: screen + camera with gpu-screen-recorder, camera only, an Android phone's camera over USB, or OBS. `Space` waits until the video is recording, so the first words always have picture. |
| **Script cues** | `(CAMERA: full)` resizes the camera picture-in-picture, `(SCENE: Terminal)` switches OBS scenes, `#` sections become chapters. |
| **Strict scripts** | Speech that isn't in the script is marked, so Auto edit can drop asides between sentences, or even fillers inside them. |
| **Record ⇄ Studio** | A switch in the top bar (`Ctrl+Tab`) goes between recording and editing the open script; a script with nothing recorded yet opens an empty studio. |
| **Studio editor** | Waveform, filmstrip, takes, markers and transcript on one timeline, showing the edit as it plays (`V` switches to the whole recording, removed parts greyed, to restore them). Pick another take for a sentence with `T`, split, trim, undo. |
| **Exports** | Video (MP4, H.264 or HEVC), narration (FLAC, WAV, Opus, MP3) with chapters and optional loudness normalization, an OpenTimelineIO timeline for DaVinci Resolve or Kdenlive, captions (WebVTT, SRT) and Audacity labels. |
| **Resource monitor** | Meters in the top bar for CPU, RAM, GPU, VRAM and the microphone; click them for the video encoder, temperatures, disk time left and how far behind each speech engine is, so you know before it hurts. |
| **No privileges** | Runs as your user. No sudo, no daemons. |

<!-- Screenshot: studio editor -->

## Install

### Arch Linux / Omarchy (AUR)

```sh
yay -S retake
```

Optional extras, installed separately:

| Package | Adds |
|---|---|
| `python-pytorch` (or `python-pytorch-cuda`, `python-pytorch-rocm`) | Pronunciation scoring and better speech detection |
| `scrcpy` | Android phone as camera |
| `gpu-screen-recorder` | Screen + camera recording (already on Omarchy) |
| `python-faster-whisper` (AUR) | More accurate voice following on NVIDIA GPUs |
| `piper-tts-bin` (AUR) | A natural reference voice instead of espeak-ng |
| `python-websockets` | OBS control |
| `python-nvidia-ml-py` | NVIDIA GPU monitoring |
| `python-evdev` | Exclusive foot pedal input |

### From source

```sh
git clone https://github.com/sergiojrdotnet/retake
cd retake
bin/dev            # creates .venv, installs dependencies, runs Retake
bin/install        # or build and install it as a pacman package
```

### First run

Voice following needs a speech model. The start page offers it, or from a terminal:

```sh
retake models pull vosk-en-us-small-0.15     # 40 MB, voice commands
retake models pull vosk-en-us-0.22-lgraph    # 128 MB, more accurate voice following
retake models pull wav2vec2-espeak-cv        # 1.3 GB, pronunciation scoring (needs PyTorch)
retake doctor                                # checks tools, models and engines
```

Models are stored in `~/.local/share/retake/models`.

## Quick start

1. Write a script in Markdown (or use any `.md` file you already have).
2. `retake talk.md`, or open Retake and choose **Quick project from a script** (`Ctrl+Shift+O`). For a course, choose **New project** (`Ctrl+Shift+N`) and import its scripts with **+** in the explorer (`Ctrl+I`).
3. Press `P` to check the script: unknown words, words with two pronunciations, cues that won't work.
4. Press `Space` and start reading. The prompter follows you.
5. Stumbled? Say *“retake, again”* or press `R`, and read the sentence again.
6. Press `Enter` to stop. The studio opens with an automatic edit.
7. Not happy with a sentence? Click its clip (Shift+click for a range) and press `R`: Retake goes back to the prompter with just those sentences, records them, and swaps the new takes into your edit.
8. Press `Ctrl+E` to render, or use **Export…** for the other formats.

No script? Press `Ctrl+N` for a free recording and just talk.

## Writing a script

Scripts are plain Markdown with a few conventions borrowed from screenwriting (Fountain) and voice-over practice:

```markdown
# Event Store Study Case

## Introduction

(SCENE: Camera) Hi, I'm Sergio. / Today we **aggregate** the event store snapshots.
(SMILE) We flush the {cache|kæʃ} to disk // and measure P99 latency.

(CAMERA: corner) Next, the results.

(AD-LIB)
Talk about the dashboard freely.
(/AD-LIB)

[[Note to self: slow down here]]
```

| Markup | Meaning |
|---|---|
| `#`, `##` | Sections. Shown as dividers, never read, and each becomes a chapter. |
| `(SMILE)`, `[Cold open, on camera]` | Stage directions: capitalised parentheses and anything in square brackets are shown dimmed and never read. Lowercase parentheses are read normally. |
| `(SCENE: Name)` | Switch the OBS scene when your voice reaches this point. |
| `(CAMERA: full\|corner\|small\|off)` | Change the camera picture-in-picture at this point. |
| `/` and `//` | Short and long pause marks. |
| `**word**`, `*word*` | Emphasis. |
| `{word\|IPA}` | Pronunciation override for this occurrence. |
| `{US$ 1,180\|=eleven hundred eighty dollars}` | Spoken form: show the written text, follow (and coach) the words you'll actually say. |
| `(AD-LIB)` … `(/AD-LIB)` | Intentional improvisation: never treated as off-script. |
| `[[note]]`, `<!-- -->`, `/* */` | Hidden from the prompter. |
| `[[id: scene-id]]` right under a heading | Stable id for that section, carried into the exports. |
| `[[b3]]`, `[[key: value]]` | Beat (or any key) for the following sentences of the section, carried into the exports. |
| Code blocks, Markdown tables | Ignored. |
| `→`, `≈`, `US$` and other symbols | Shown, never read. |

Pronunciations you reuse go in a file next to the script, `talk.lexicon.tsv` (tab-separated; the last column lists how you might say it, alternatives separated by `|`):

```
# word	ipa	flagged	spoken
kubernetes	kuːbərˈnɛtiːz
nsenter	ˈɛnˌsɛntər
tikv	ˈtaɪˌkeɪˈviː		tie kay vee|tee kay vee
gib			gibibytes|gigabytes
cache		yes
read	riːd
```

An IPA in the lexicon replaces the dictionary for every occurrence in that script, for the guide, the pronunciation score and the reference voice (Piper says that exact pronunciation, so a word drill never plays the other reading of a heteronym). Use it to pick the usual reading of a heteronym, then mark the exceptions inline (`{read|rɛd}`). Possessives reuse the base row: `tikv's` needs no line of its own.

Numbers, acronyms and units are matched the way people say them: `2026` matches “twenty twenty-six”, `P99` matches “p ninety-nine”, `10k` matches “ten k” or “ten thousand”.

## Recording

**Audio** is always recorded losslessly (24-bit FLAC) from the microphone you pick in Settings, and never stops for retakes. Pick the left or right channel if your mic sits on one side of a stereo interface.

**Video** is optional (Settings → Recording):

| Mode | How | Notes |
|---|---|---|
| Audio only | – | The default. |
| Screen + camera | gpu-screen-recorder captures a monitor; Retake shows your camera in its own window on that monitor | Camera layouts: corner, small, full, off. Keep the prompter on a different monitor, under your webcam. Hardware encoding (NVENC/VAAPI). |
| Camera only | Qt Multimedia, like Omarchy's Monologue | Highest resolution at about 30 fps. |
| Phone camera | An Android phone over USB, through [scrcpy](https://github.com/Genymobile/scrcpy) (`pacman -S scrcpy`) | Records the phone's camera at its largest size (up to 4K, H.265 at 40–80 Mb/s) straight to `video/part-00N.mkv`. Needs Android 12+ and USB debugging; keep the mic on the laptop, the phone's own mic is recorded only to sync. For the phone in Retake's camera panel (also before you press `Space`), set up a virtual camera once: `sudo pacman -S v4l2loopback-dkms`, then `options v4l2loopback video_nr=42 card_label="Retake phone"` in `/etc/modprobe.d/v4l2loopback.conf`, `v4l2loopback` in `/etc/modules-load.d/v4l2loopback.conf`, and `sudo modprobe v4l2loopback`. Settings → Recording → *Check phone* prints these commands. Retake reads each phone's cameras (*Detect cameras*) and offers only the sizes and frame rates they support, including high-speed modes; settings are remembered per phone, and *Shape* switches between landscape 16:9 and portrait 9:16. The phone keeps recording through pauses; when a part finishes, any pause longer than 4 s is cut out of the phone video losslessly, with a time map that keeps it in sync. |
| OBS | obs-websocket 5 (built into OBS 28+) | Scenes from `(SCENE: …)` cues, chapters per section. |

`Space` waits for the video to start recording ("Starting the video recording…"), then starts the audio and the prompter; if the video fails or takes longer than 25 s, Retake records audio only and says so. Video is synced to the audio automatically (first-frame timestamp, refined by matching the audio tracks).

**Rehearsal** (`Shift+Space`) runs everything, coach included, without keeping anything.

**Long scripts:** press `Space` to pause between scenes (paused parts are dropped by Auto edit), or stop and come back another day: opening the script again puts the prompter on the first sentence without a good take, and the next recording joins the same script. The studio shows every recording of a script on one timeline and plays the edit in script order.

**Pickups:** in the studio, select sentences (click a clip, Shift+click for a range, Ctrl+click to add) and press `R` or **Re-record**. The prompter walks through just those sentences; when the last one is done Retake returns to the studio with the new takes in place and the rest of your edit untouched.

## Voice commands

Say the wake word, a short pause, then the command. The default wake word is **retake** (Portuguese UI: **diretor**). Change it in Settings → Controls. `?` lists every command next to its key.

Accents are expected: the native language pack lists how the wake word tends to come out (a Brazilian *retake* often sounds like “he take”), and commands are also picked out of Whisper's transcript, which copes with accents better than the small command model.

| Say | Does |
|---|---|
| “retake, again” | Retake the sentence you're on, or the one you just finished |
| “retake, next” / “back” | Move to the next or previous sentence |
| “retake, pause” / “resume” | Pause and resume tracking (the paused part is dropped by Auto edit) |
| “retake, mark” | Mark a spot (a chapter in free recordings) |
| “retake, say it” | Hear the word you're on, or the one the coach flagged |
| “retake, how do I say *latency*” | Hear any word of the current sentence |
| “retake, drill it” | Drill the warned words of this sentence (or the previous one), then read it again |
| “retake, skip it” | In a word drill, skip the word |
| “retake, don't coach it” | In a word drill, never coach the word again |
| “retake, camera full” / “corner” / “off” | Change the camera layout |
| “retake, stop recording” | Stop |

Commands are recognized by a separate recognizer that can only hear these phrases, and only when they're set off by silence, so reading a sentence that contains “again” won't trigger anything. Command audio is dropped from the edit.

## Keyboard

Press `?` at any time for the overlay.

**Recording**

| Key | Action |
|---|---|
| `Space` | Record / pause / resume |
| `Shift+Space` | Rehearse |
| `Enter` | Stop and open the editor |
| `→` `PgDn` / `←` `PgUp` | Next / previous sentence |
| `R` | Retake |
| `M` | Mark |
| `L` | Listen to the word |
| `F` | Flag the word for practice |
| `V` | Prompter mode: scroll, step, card, page |
| `Tab`, `1`–`3` | Layout: full, focus, lens |
| `C` | Camera: corner, full, off |
| `P` | Check the script |
| Click / right-click / double-click a word | Flag it / menu: listen, flag, don't coach / jump to its sentence |
| `D` | Drill the warned words of this sentence (or the previous one), then read it again |
| `S` / `N` (during a word drill) | Skip the word / never coach it |

**Studio**

| Key | Action |
|---|---|
| `Space` | Play / pause (skips what's cut) |
| `←` `→` | Move 1 s (`Shift` 5 s, `Alt` 0.2 s) |
| `[` `]` | Previous / next edge or marker |
| Click a clip | Select its sentence (`Shift` range, `Ctrl` add) |
| `R` | Re-record the selected sentences, or the one under the playhead |
| `T` | Next take for the sentence under the playhead |
| `S` | Split |
| `X`, `Delete` | Remove a clip, or restore a gap |
| `Ctrl+Space` / `Alt+Space` | Move the clip start / end to the playhead |
| `A` | Auto edit |
| `Z` | Zoom to the clip / zoom out |
| `V` | Edit view (only what's kept, back to back) / the whole recording with the removed parts greyed |
| `Ctrl+=` / `Ctrl+-` / `Ctrl+0` | Zoom the timeline in / out / to fit (`Ctrl`+wheel zooms at the mouse) |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / redo |
| `Ctrl+S` | Save the edit |
| `Ctrl+E` | Render the video (the narration when there is no video) |

**Everywhere:** `Ctrl+Shift+N` new project, `Ctrl+Shift+O` quick project from a script, `Ctrl+O` open project, `Ctrl+I` import scripts, `Ctrl+N` free recording, `Ctrl+Tab` Record ⇄ Studio (also the switch in the top bar), `Ctrl+B` explorer, `Ctrl+,` settings, `Ctrl+M` models, `Esc` back, `Q` quit.

Presentation clickers and USB foot pedals send `PgUp`/`PgDn`, so they work while Retake has focus.

## Controlling Retake from anywhere

During a screen recording your keyboard focus is in the app you're demoing, so Retake can't see its own shortcuts. Two ways around that, neither needs root:

**Hyprland key bindings** that call `retake ctl`. Settings → Controls → *Copy Hyprland snippet*, or `retake hyprland`, gives you:

```lua
-- ~/.config/hypr/bindings.lua (Omarchy)
o.bind("SUPER + ALT + RIGHT", "Retake: next sentence", "retake ctl next")
o.bind("SUPER + ALT + LEFT", "Retake: previous sentence", "retake ctl back")
o.bind("SUPER + ALT + R", "Retake: retake", "retake ctl again")
o.bind("SUPER + ALT + SPACE", "Retake: pause or resume", "retake ctl toggle-pause")
o.bind("SUPER + ALT + M", "Retake: mark", "retake ctl mark")

-- Keep the camera window floating and pinned, and hide the prompter from screen sharing
o.window({ title = "^Retake camera$" }, { float = true, pin = true, no_initial_focus = true, no_dim = true, border_size = 0 })
o.window({ class = "^retake$", title = "^Retake$" }, { no_screen_share = true })
```

`retake ctl` accepts `next`, `back`, `again`, `pause`, `resume`, `toggle-pause`, `mark`, `listen`, `flag`, `record`, `rehearse`, `stop`, `camera-full`, `camera-corner`, `camera-off`, `layout <full|focus|lens>` and `show`.

**A foot pedal that only Retake hears.** Point Settings → Controls → *Foot pedal device* at its `/dev/input/by-id/…` entry and enable *Grab the pedal*. Reading input devices needs your user in the `input` group (`sudo usermod -aG input $USER`, once); this is the only feature that needs a one-time privileged step, and it's off by default.

## Pronunciation coach

After every sentence, Retake scores each word you said and shows the ones worth another try, with:

- the pronunciation in IPA, English respelling and respelling in your native language (`aggregate`: /ˈæɡrəɡət/, AG-ruh-guht, ÉG-râ-gât),
- what it expected and what it heard,
- the typical mistake for speakers of your language, when it recognizes one (for Brazilian Portuguese: long vs short *i* in beach/bitch, *th* sounds, an extra vowel after final consonants, *-ed* as an extra syllable, English R, final L, and more),
- a **Listen** button with a reference voice.

| Setting | Options |
|---|---|
| Warn below | Score below which a word shows up in the coach panel (55) |
| Require a retake below | Off, or a lower score under which a word rejects the take and sends you back to the start of the sentence |
| Drill the failed word | On by default once a Require level is set |
| Times in a row | How many passes in a row the drill wants (3) |
| Feedback | Live after each sentence, or review at the end and re-record only the flagged sentences (pickups) |

**Word drill.** When a word scores under the Require level, Retake plays a cue right away, turns the word red in the prompter and opens a drill card with its pronunciation. It says the word, you say it; each try is scored on its own and needs to reach the Warn level. Retake says the word again before every try, and a miss starts the count over. After enough passes in a row, the prompter goes back to the start of the sentence. Several failed words are drilled in reading order. `L` (or *retake, say it*) hears it again, `S` (or *retake, skip it*) skips the word, and the take shows it as skipped in the studio. `D` (or *retake, drill it*) drills on demand: the words warned about in the current sentence, or in the previous one if the current has none, then the sentence is read again. The drill is recorded but marked, so Auto edit cuts it like a pause. The word stays red until the sentence gets a passing take; words that only missed the Warn level turn yellow the same way.

**Names and words you don't want coached.** Right-click a word in the prompter → *Don't coach this word*, press `N` (or say *retake, don't coach it*) in a drill, or use *Don't coach* in the coach panel: the word is never scored, drilled or given guides again, in any project, and the prompter still follows it. Settings → Coach lists these words, where you can add or remove them. A script's lexicon can mark words too: `off` in its fifth column, `coach` (header `# word	ipa	flagged	spoken	coach`).

Words you keep missing are flagged automatically, so their guides show up next time. Settings → Coach lists them.

**How it works:** a phoneme recognizer (wav2vec2, trained on espeak phonemes) transcribes the sounds you actually made, and Retake compares them, word by word, with the expected pronunciation. In free recordings, the intended text comes from the transcript.

**Limits:** the scoring is a calibrated estimate, not a model trained on rated learner speech, and it's only calibrated for English. It aims at being understood, not at sounding native: adjust the Warn and Require levels to your voice (Settings → Coach). Very short function words (*the*, *to*, *a*…) aren't scored.

## Editing and exports

Nothing is cut while you record. Every take, retake, command, pause, off-script remark and coach warning becomes a marker, and the editor turns them into a proposed cut when you ask (`A`, or automatically on stop if you enable it).

Auto edit rules (Settings → Editing):

- keep the **last good take** of each sentence, or the **best scored** one,
- drop rejected takes, voice commands, reference playback and pauses,
- drop speech that isn't in the script: keep it, drop it **between sentences** (default) or be **strict** and drop fillers inside sentences too,
- short handles around every cut, pauses shortened to a maximum, optional audio crossfades,
- output in script order (always, once a script has more than one recording) or in recording order.

The studio saves your changes to `edit.json`. Recordings are never modified.

| Export | File |
|---|---|
| Video | `out/video.mp4` (H.264 at the camera's full size, hardware encoded when possible) |
| Video, HEVC | `out/video-hevc.mp4` (H.265, about half the size at the same quality) |
| Narration | `out/narration.flac`, `.wav`, `.opus`, `.mp3`, with chapters |
| Timeline | `out/timeline.otio`: import into DaVinci Resolve or Kdenlive, markers included |
| Captions | `out/captions.vtt`, `out/captions.srt`, timed to the edit |
| Labels | `out/labels.txt` for Audacity |
| Script timing | `out/sentences.json`: every sentence, beat and section with its edited (and source) times, words and your `[[id]]`/`[[b…]]` metadata, for driving other pipelines |
| Raw | `out/raw.otio` + labels: the untouched recording with every marker, to edit elsewhere |

Headless: `retake render <project.retake> --item ep1 --auto --targets cut,mp3,timeline,captions,sentences`.

## Speech engines

Engines are picked automatically for your hardware. To choose yourself, open Models (`Ctrl+M`): it lists each job (voice following, voice commands, speech detection, pronunciation scoring, reference voice) with the models and built-in engines that can do it, where you download, remove and pick. Settings → Engines keeps the preset, device and threads. If Whisper can't use the GPU, voice following falls back to Vosk and says so.

| Job | Base (official repos) | Optional |
|---|---|---|
| Voice following | Vosk | faster-whisper (CUDA) |
| Voice commands | Vosk with a closed grammar | – |
| Speech detection | Energy detector | Silero VAD (PyTorch) |
| Pronunciation scoring | Word check only | wav2vec2 phonemes (PyTorch) |
| Reference voice | espeak-ng | Piper |

| Preset | Voice following | Scoring | Voice |
|---|---|---|---|
| NVIDIA | faster-whisper on the GPU | wav2vec2 on the GPU | Piper |
| AMD | Vosk | wav2vec2 with ROCm | Piper or espeak-ng |
| CPU only | Vosk | wav2vec2 on the CPU | espeak-ng |
| Light | Vosk | word check only | espeak-ng |

The speech engine runs in its own process and the recorder in another, so a crash in the engine never stops a recording; Retake restarts it. If voice following falls behind on a busy CPU, it skips ahead and tells you. The meters in the top bar show CPU, RAM, GPU and VRAM (yellow near the limit, red at it); click them for who's using what, temperatures and disk writes.

On NVIDIA, scoring runs on the GPU only with a CUDA build of PyTorch: `python-pytorch-cuda` for the package; `bin/dev` installs the CUDA 12 build (the same cuBLAS and cuDNN faster-whisper uses) together with faster-whisper when it builds its environment. On the CPU a sentence takes 0.5–2 s to score; on a laptop RTX it takes under 0.1 s. Speech detection stays on the CPU, where its tiny model is faster.

Each part's `part-NNN.resources.csv` records CPU, RAM, GPU, VRAM, disk writes and engine delays every second. The engine also keeps a log per run of the app in `~/.local/state/retake/log/engine-*.log` (the last 10): which model loaded on which device and how long it took, warnings, errors, and every time following fell behind.

## Languages

Three independent settings: the language you **read**, your **native** language (for respelling and typical mistakes) and the **interface** language.

Version 0.1 ships English scripts, Brazilian Portuguese as a native language, and an English or Portuguese interface. Everything language-specific lives in a language pack, a single TOML file: speech models, command phrases and wake word, abbreviations, fillers, function words, heteronyms, the phoneme → spelling table for respelling, and the catalog of typical mistakes. Drop a pack into `~/.local/share/retake/languages/` to add or override one; see `src/retake/languages/pt-BR.toml` for the format. Contributions welcome.

## Command line

```
retake [file]                 open the app; a .retake file opens that project, a .md script opens (or creates) its quick project
retake free                   start a free recording
retake check <script> [--guides]   check a script; list pronunciation guides
retake guide <word>…          print IPA and respellings
retake ctl <action>           control the running app
retake render <project> [--item ID] [--auto] [--targets cut,narration,mp3,opus,wav,timeline,captions,labels,sentences]
retake projects [script.md] [--items] [--json]   list projects; with a script, the items imported from it and their sentences.json
retake models [list|pull <id>|remove <id>]
retake doctor [--no-gpu]      check tools, models and engines
retake hyprland               print the Hyprland snippet
```

## Files

| Path | What |
|---|---|
| `~/.config/retake/config.toml` | Settings |
| `~/.local/share/retake/models/` | Speech models |
| `~/.local/share/retake/practice.json` | Words you've practised and flagged |
| `~/Videos/Retake/<project>/` | New projects go here by default (Settings → Session); **New project** lets you pick any other folder |

A project is a folder with a `.retake` file in it: open that file (or double-click it once Retake is installed). Scripts are copied into the project when you import them, and each script gets its own folder with every recording, the edit and the exports. Everything lives inside the project folder, so you can move, copy or archive it.

```
Event Store Course/
├── Event Store Course.retake    the project: its scripts and their recordings
├── scripts/                     imported copies (edit them here)
│   ├── ep1.md
│   └── ep1.lexicon.tsv
├── ep1/                         one folder per script
│   ├── script.md                snapshot the takes refer to
│   ├── part-001.flac            a recording
│   ├── part-002.flac            a later recording, or pickups
│   ├── takes.json               takes and markers of every part, on one timeline
│   ├── edit.json                your edit
│   ├── video/part-001.mp4       screen or camera, per part
│   └── out/                     exports: video.mp4, narration.flac, sentences.json…
└── free-2026-10-17_101400/      free recordings: same layout, no script
```

If a script changes after you've recorded it (edited in `scripts/`, or **Re-import from the original file**), Retake re-points the earlier takes when you next open it: sentences are matched in order, a sentence that kept at least half of its words counts as reworded, and one moved elsewhere is still found. Takes on reworded sentences stay in the edit, marked ⟳, and **Re-record changed** in the studio queues exactly those sentences as pickups; Auto edit prefers a newer take when there is one. Only takes whose sentence is gone are set aside (still restorable with `X`). Projects can live anywhere: moved or created elsewhere, they're found through your recent projects. **Re-import from the original file** (right-click in the explorer) copies the file you imported again. `retake projects ep1.md --json` finds the items imported from a script, with their `out/sentences.json`. To start a script over, right-click it in the explorer → *Delete recordings…*: its recordings, takes, edit and exports go to the trash and the script stays.

## Troubleshooting

- **The prompter doesn't move.** Check the top bar: *following* must be green. Pick and install a model in Models (`Ctrl+M`), then *Restart engine*. Watch the microphone meter in the top bar.
- **Voice commands never trigger.** Pause briefly before the wake word. Make sure the wake word isn't in your script (`P` warns about it).
- **Voice following lags.** Another app is using the CPU or GPU: click the meters in the top bar. Choose a lighter preset or a smaller Whisper model.
- **No screen recording.** `retake doctor` checks gpu-screen-recorder. On Omarchy it's preinstalled.
- **The wrong microphone is recorded.** Pick it in Settings → Recording; the list comes from PipeWire.

## Development

```sh
bin/dev                 # run from the checkout
bin/test                # unit tests (no audio devices or GPU needed)
CUDA_VISIBLE_DEVICES= .venv/bin/python tests/integration_engine.py   # engine end to end, on the CPU
```

Code map:

```
src/retake/
  script/      Markdown parser, number/acronym normalization, lexicon
  phonetics/   CMUdict, espeak-ng, IPA ↔ phonemes, syllables, respelling
  languages/   language packs (TOML)
  project.py   projects, scripts and their recording parts
  session/     tracker (alignment), takes and markers, coach, free recordings, preflight
  engine/      speech engine process: VAD, Vosk, Whisper, wav2vec2 scorer, TTS
  audio/       recorder process (PipeWire capture, FLAC, resampling)
  video/       gpu-screen-recorder, OBS, Hyprland
  edit/        edit decision list, Auto edit, ffmpeg rendering, exports
  monitor/     resource monitor
  control/     retake ctl, foot pedal
  ui/ qml/     PySide6 + Qt Quick interface
```

Translations: `pyside6-lupdate src/retake/qml/*.qml src/retake/ui/modeljobs.py src/retake/ui/controller.py -ts src/retake/i18n/retake_<lang>.ts`, translate, then `bin/dev` compiles them.

## Credits

Retake stands on great open-source work: [Vosk](https://alphacephei.com/vosk/) and Kaldi, [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [wav2vec2 phoneme recognition](https://huggingface.co/facebook/wav2vec2-lv-60-espeak-cv-ft) by Meta AI, [Silero VAD](https://github.com/snakers4/silero-vad), [espeak-ng](https://github.com/espeak-ng/espeak-ng), [Piper](https://github.com/rhasspy/piper) and the LJSpeech voice, the [CMU Pronouncing Dictionary](https://github.com/cmusphinx/cmudict), [gpu-screen-recorder](https://git.dec05eba.com/gpu-screen-recorder/about/), [FFmpeg](https://ffmpeg.org), [Qt](https://www.qt.io) and [PySide6](https://doc.qt.io/qtforpython/). The look and keyboard conventions follow [Omarchy](https://omarchy.org)'s apps, Hype, Monologue and Omacut.

Released under the [MIT license](LICENSE). The CMU Pronouncing Dictionary is distributed under its own BSD-style license (`src/retake/languages/cmudict.LICENSE`).
