# listenerd

Local-first meeting recorder for macOS. One menu-bar click captures your
microphone + system audio, transcribes both with `whisper.cpp`, summarizes
locally via Ollama, and writes a Markdown note to `~/Meetings/`.

Works with anything that uses the system audio (Teams, Zoom, Meet, Slack
huddles, Gather, Discord, plain phone calls bridged over the Mac, …).

**Everything runs on your machine.** No network calls. No cloud.

---

## TL;DR

```bash
# 1. Install deps
brew install whisper-cpp blackhole-2ch ollama

# 2. Pull models
mkdir -p ~/models && curl -L -o ~/models/ggml-large-v3-turbo.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin
ollama pull gemma4:latest

# 3. Set up the project
git clone <this repo> ~/dev/listenerd && cd ~/dev/listenerd
uv sync
cp config.example.toml ~/.config/listenerd/config.toml

# 4. Run it manually to grant Mic permission
uv run listenerd record   # speak briefly, Ctrl-C to stop

# 5. (Optional) Wire up the SwiftBar menu-bar control — see "SwiftBar setup".
```

After every recording you'll get `~/Meetings/YYYY-MM-DD-HHMM-meeting.md`.

---

## One-time setup

### 1. System dependencies

```bash
brew install whisper-cpp blackhole-2ch ollama
```

Start the Ollama service (one-time): `open -a Ollama` or `ollama serve &`.

### 2. Whisper model

Models live at `~/models/ggml-<name>.bin`. Recommended: **`large-v3-turbo`**
(best quality/speed tradeoff, ~1.6 GB).

```bash
mkdir -p ~/models
curl -L -o ~/models/ggml-large-v3-turbo.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin
```

Smaller alternatives if you're tight on disk: `base` (148 MB, weak),
`small` (470 MB, decent), `medium` (1.5 GB, good).

### 3. Ollama model

```bash
ollama pull gemma4:latest      # 9.6 GB — strong on DE + EN
# or for max quality (slower):
# ollama pull gemma4:26b       # 17 GB
```

### 4. Multi-Output Device (so system audio gets captured)

You want to *hear* the call AND let `listenerd` capture what the other side
says. BlackHole is the virtual cable that does this — but you need to route
your system output through both your speakers/headphones AND BlackHole.

1. Open **Audio MIDI Setup** (`/Applications/Utilities/Audio MIDI Setup.app`).
2. Bottom-left **+** → **Create Multi-Output Device**.
3. Tick **your real output** (speakers / AirPods / headphones) **AND
   BlackHole 2ch**.
4. Enable **Drift Correction** on the Bluetooth device (if any).
5. Right-click the new device in the left sidebar → **Use This Device For
   Sound Output**.

In your meeting app (Teams/Zoom/Slack/…):
- **Input** = your normal mic (AirPods, MacBook mic, …)
- **Output** = the Multi-Output Device

Sanity check:

```bash
system_profiler SPAudioDataType | grep BlackHole   # should list it
```

### 5. Configure

```bash
mkdir -p ~/.config/listenerd
cp config.example.toml ~/.config/listenerd/config.toml
$EDITOR ~/.config/listenerd/config.toml
```

The defaults in `config.example.toml` match the recommended setup above.

---

## Running it

### Manual mode (recommended — full control)

```bash
uv run listenerd record       # starts recording immediately
# … speak / let the meeting run …
# Ctrl-C                        # stops, transcribes, summarizes, writes .md
```

`SIGTERM` works the same as `Ctrl-C` — useful for stopping from another
terminal: `pkill -TERM -f "listenerd record"`.

### Auto mode (experimental)

```bash
uv run listenerd              # = listenerd watch
```

Polls CoreAudio for mic activity. Starts a session when anything opens the
mic, stops 10 s after the mic goes idle. Brittle in practice — the manual
mode is more reliable.

### SwiftBar setup (menu-bar start/stop button)

If you use [SwiftBar](https://swiftbar.app), you get a one-click
start/stop control in the menu bar:

```bash
# 1. Symlink the plugin into your SwiftBar plugin dir
ln -s "$PWD/extras/swiftbar/listenerd.3s.sh" \
      ~/.config/swiftbar/Plugins/listenerd.3s.sh

# (Adjust path if your SwiftBar plugin dir is elsewhere — check
#  SwiftBar → Preferences → Plugin Folder.)

# 2. On first start, macOS will prompt for Microphone permission for
#    "listenerd". Click Allow. (See "How it works" below for why.)
```

You'll see `⚪︎` in the menu bar when idle, `🔴 REC` while recording.
Submenu has *Start/Stop*, *Open Meetings folder*, *Tail log*.

---

## How it works

```
SwiftBar → open -a listenerd-recorder.app
            (the .app bundle is the TCC owner — has its own Mic permission)
                │
                ▼
           uv run listenerd record
                │
                ├── records mic.wav   (default input)
                └── records system.wav (BlackHole 2ch)
                                       │
                ─── on Ctrl-C / SIGTERM ───
                                       │
                                       ▼
                         whisper-cli on each WAV (parallel)
                                       │
                                       ▼
                               merge into timeline
                              (Me = mic, Others = system)
                                       │
                                       ▼
                       ollama run gemma4 → SUMMARY + ACTION_ITEMS
                                       │
                                       ▼
                          write ~/Meetings/YYYY-MM-DD-HHMM-meeting.md
```

### Why the `.app` bundle?

macOS TCC (the privacy system) decides whether a process can access the
microphone based on the *responsible app* — usually the GUI app that started
the process tree. If SwiftBar spawns a python subprocess, the responsible
app is SwiftBar, which doesn't have Mic permission → the recording is
silently filled with zeroes (no error, no log line — just silent WAVs).

The trick is `extras/listenerd-recorder.app`: a tiny LSUIElement app bundle
(no dock icon, no window) with its own `NSMicrophoneUsageDescription` in
`Info.plist`. SwiftBar opens *that* via `open -a`, macOS asks the user once
for Mic permission, and the recorder gets real audio.

---

## Configuration reference

See `config.example.toml` for the full annotated config.

Key knobs:
- `whisper.model` — `base` | `small` | `medium` | `large-v3-turbo`
- `whisper.language` — `auto` or a code like `de`, `en`
- `ollama.model` — any installed Ollama model
- `output.keep_audio` — `false` (default, deletes WAVs after the .md is
  written) or `true` (keeps them in `<meetings_dir>/.sessions/`)

---

## Troubleshooting

### Silent WAVs (mic.wav / system.wav peak = 0)

- **From SwiftBar**: the `.app` bundle wasn't opened or doesn't have Mic
  permission yet. Run `uv run listenerd record` from a terminal once first
  to bootstrap. Check System Settings → Privacy & Security → Microphone
  for `listenerd`.
- **system.wav is silent**: your System Output isn't routed through the
  Multi-Output Device. See setup step 4.

### Whisper transcribes nothing

`mic.wav` is too quiet. Boost your input gain in System Settings → Sound →
Input, or move closer to the mic. RMS should be ≥ 500 for reliable
recognition. Verify with:

```python
import wave, numpy as np
with wave.open("/Users/you/Meetings/.sessions/<id>/mic.wav") as w:
    d = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
print("peak", int(np.max(np.abs(d))), "rms", float(np.sqrt(np.mean(d.astype(np.float32)**2))))
```

### `whisper-cli not found`

`brew install whisper-cpp`. Verify with `which whisper-cli`.

### `ggml_abort` / crash mid-transcription

Whisper model file is corrupt or incomplete (e.g. an interrupted download).
Re-download:

```bash
rm ~/models/ggml-large-v3-turbo.bin
curl -L -o ~/models/ggml-large-v3-turbo.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin
```

### Ollama summary is `[summary failed]`

Ollama service not running. `open -a Ollama` or `ollama serve` in a
terminal.

### "BlackHole 2ch" missing in Audio MIDI Setup

`brew reinstall blackhole-2ch`, then reboot.

---

## Privacy

- **Nothing leaves your machine.** Audio is processed by local
  `whisper.cpp` (CPU/Metal) and local Ollama. The only network calls are
  optional model downloads (Whisper from Hugging Face, Ollama models from
  ollama.com) — those happen during setup, never during a meeting.
- **Recording the other side of a call may be illegal where you live.**
  Check your jurisdiction. Inform participants.

---

## Project layout

```
listenerd/
  __main__.py         — CLI entry; record / watch / process_session pipeline
  config.py           — TOML config loader
  recorder.py         — dual sounddevice streams → mic.wav + system.wav
  watcher.py          — CoreAudio mic-activity polling (auto mode)
  transcribe.py       — whisper-cli wrapper
  merge.py            — interleaves mic & system segments, filters noise tokens
  summarize.py        — ollama wrapper + summary/action-items parser
  writer.py           — Markdown rendering

bin/listenerd-ctl                   — start/stop/status shell helper
bin/listenerd-record.command        — debug launcher (opens a Terminal window)
extras/listenerd-recorder.app       — headless .app for TCC-correct Mic access
extras/swiftbar/listenerd.3s.sh     — SwiftBar plugin
config.example.toml                 — annotated default config
tests/                              — pytest unit tests
```

---

## License

MIT.
