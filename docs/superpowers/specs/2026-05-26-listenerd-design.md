# listenerd — Design (MVP)

**Datum:** 2026-05-26
**Status:** Draft, Review ausstehend
**Autor:** Lukas + Claude (Brainstorming)

## Ziel

Ein lokal laufender Daemon (`listenerd`), der **automatisch** jeden Audio-Call auf
macOS erkennt, aufzeichnet und transkribiert. Output ist eine Markdown-Datei pro
Meeting mit Speaker-getaggtem Transcript und automatischer Zusammenfassung —
plattformagnostisch (Teams, Zoom, Google Meet, Gather, Discord, FaceTime, …),
weil die Erkennung über System-Mikrofon-Aktivität läuft, nicht über App-Integration.

## Motivation

- **Privacy:** Audio + Transcript verlassen den Rechner nie (kein SaaS-Bot, kein
  Cloud-Whisper).
- **Eigentum:** Einmal gebaut, dauerhaft genutzt — kein 10-30 €/Monat-Abo.
- **Integration:** Markdown-Output ist Source of Truth, beliebig in Obsidian /
  Notion / eigene Tools weiterverwendbar (V2-Sache).

## Non-Goals (MVP)

- Live-Transcription während des Calls (Post-Processing nach Call-Ende reicht).
- Multi-Speaker-Diarization über `Me`/`Others` hinaus (kein `pyannote`).
- Web-UI, SQLite-Index, Volltextsuche.
- Auto-Start bei Login (Aufruf via `listenerd` CLI im Terminal).
- Sprecher-Identifikation per Voice-Embedding.
- Output nach Notion / Obsidian / SQLite / Mehrere Targets.
- Cross-Plattform — nur macOS (Apple Silicon).

## Architektur

```
[Watcher] ──► [Recorder] ──► [Processor]
  mic on?       2× WAV         WAV → text → markdown
```

Ein einziger Python-Prozess mit drei Stages, die als simple Pipeline verkettet
sind. Stages tauschen ausschließlich über Dateisystem aus (Session-Directory),
keine Inter-Process-Kommunikation, kein Queue, kein State außerhalb von Files.

### Stages

**Watcher** — pollt CoreAudio alle ~1 s über `pyobjc` (`AudioObjectGetPropertyData`
mit `kAudioDevicePropertyDeviceIsRunningSomewhere` auf dem Default-Input-Device).
- Mic-Aktivität an → Session-Dir anlegen, Recorder triggern.
- Mic-Aktivität >10 s aus → Recorder stoppen, Processor triggern.

**Recorder** — öffnet während einer Session **zwei** parallele Audio-Streams via
`sounddevice`:
- `mic.wav` ← Default-Input-Device (deine Stimme)
- `system.wav` ← BlackHole-2ch-Device (System-Audio-Loopback, alle anderen)

Beide Streams: 16 kHz mono, 16-bit PCM — direkt Whisper-tauglich, keine
Konvertierung nötig.

**Processor** — wird nach Session-Ende einmal ausgeführt:
1. `whisper-cli` auf `mic.wav` und `system.wav` (parallel via `subprocess`),
   Segment-Timestamps via `--output-json`.
2. Merge der zwei JSON-Transcripts → ein chronologischer Stream, jedes Segment
   getaggt mit `Me` oder `Others`.
3. Ollama-Call (`ollama run <model>`) für Summary + Action Items.
4. Render Markdown nach `~/Meetings/YYYY-MM-DD-HHMM-meeting.md`.
5. Audio-Files löschen oder behalten (config).

### False-Positive-Filter

`whisper-locally` (anderes Tool von Lukas) öffnet das Mic kurzzeitig per
Push-to-Talk und würde sonst eine Aufnahme triggern. Filter:

- Sessions mit Dauer < **30 s** werden verworfen (kein Output, Audio-Files
  gelöscht). Diktat-Bursts sind typisch 2-15 s; echte Meetings sind länger.

V2 könnte zusätzlich prüfen, ob System-Audio gleichzeitig aktiv ist (Meeting =
beides aktiv, Diktat = nur Mic). MVP nicht.

## Komponenten

```
listenerd/
├── pyproject.toml          # uv-managed, analog whisper-locally
├── README.md               # Setup-Anleitung: BlackHole, whisper-cpp, ollama
├── config.example.toml     # Vorlage, kopiert nach ~/.config/listenerd/
├── listenerd/
│   ├── __init__.py
│   ├── __main__.py         # CLI: `listenerd` startet den Daemon-Loop
│   ├── watcher.py          # CoreAudio-Polling, Session-Lifecycle
│   ├── recorder.py         # Dual-Stream Aufnahme via sounddevice
│   ├── transcribe.py       # whisper-cli subprocess + JSON-Parse
│   ├── merge.py            # 2 Transcripts → ein Me/Others-Stream
│   ├── summarize.py        # Ollama subprocess
│   ├── writer.py           # Markdown-Renderer
│   └── config.py           # TOML-Config laden + Defaults
└── tests/
    └── test_merge.py       # deterministisch, läuft ohne Audio
```

Wiederverwendung aus `~/dev/ai-engineer/whisper-locally/main.py`:
- Whisper-Binary-Discovery (`which whisper-cli` + Homebrew-Fallbacks).
- `GGML_METAL_PATH_RESOURCES`-Env-Var-Setup für Metal-Beschleunigung.
- Modell-Pfad-Convention (`~/models/ggml-<model>.bin`).

## Datenfluss (eines Calls)

```
1. Lukas öffnet Teams/Zoom/Meet, joint Meeting
2. macOS aktiviert Default-Input-Device
3. Watcher (1s-Poll) sieht is_running=true
   → mkdir ~/Meetings/.sessions/2026-05-26T1430/
   → triggert Recorder
4. Recorder schreibt parallel mic.wav + system.wav
5. Meeting endet, Mic geht aus
6. Watcher wartet 10s Cooldown
7. Watcher schließt Recorder
8. Session-Dauer-Check:
   < 30s → rm -r session_dir, return
   ≥ 30s → triggert Processor
9. Processor:
   a. whisper-cli auf mic.wav → mic.json
   b. whisper-cli auf system.wav → system.json
   c. merge.py: chronologische Segment-Liste mit Me/Others-Tags
   d. summarize.py: ollama run <model> mit Transcript → summary + actions
   e. writer.py: rendert ~/Meetings/2026-05-26-1430-meeting.md
   f. (per Config) rm -r session_dir
```

## Konfiguration

`~/.config/listenerd/config.toml`:

```toml
[whisper]
model = "small"              # base | small | large-v3-turbo
language = "auto"

[ollama]
model = "llama3.1:8b"        # muss via `ollama pull` installiert sein
summary_prompt = "default"   # oder Pfad zu eigenem Prompt-File

[audio]
mic_device = "default"       # Name oder "default"
system_device = "BlackHole 2ch"
sample_rate = 16000

[session]
cooldown_seconds = 10        # wie lange Mic aus, bevor Session endet
min_duration_seconds = 30    # Sessions kürzer als das werden verworfen

[output]
meetings_dir = "~/Meetings"
keep_audio = false           # nach Markdown-Generation WAVs löschen?
```

## Markdown-Output (Spec)

Dateiname: `~/Meetings/YYYY-MM-DD-HHMM-meeting.md`

```markdown
---
date: 2026-05-26T14:30:00
duration: 00:42:18
source: listenerd
whisper_model: small
ollama_model: llama3.1:8b
---

## Summary

[3-5 Sätze, generiert von Ollama]

## Action Items

- [ ] [von Ollama extrahiert, leer falls keine]

## Transcript

**Me** (00:00:12): Hallo zusammen …
**Others** (00:00:18): Hi Lukas …
**Me** (00:00:24): …
```

## Error Handling (MVP-pragmatisch)

| Fehler | Verhalten |
|---|---|
| BlackHole-Device nicht gefunden beim Start | Daemon startet nicht, klare Fehlermeldung mit Setup-Hinweis. |
| Recording-Fehler mitten in Session | Log, Session als korrupt markieren, kein Markdown. |
| `whisper-cli` exit != 0 | Log mit stderr, WAVs behalten, Markdown skippen. |
| Ollama nicht erreichbar | Markdown wird trotzdem geschrieben, Summary-Sektion enthält `[summary failed: <reason>]`. Transcript ist da. |
| Disk full | Recorder stoppt, Log, kein Halb-Output. |
| Daemon-Crash | Manueller Restart nötig (MVP — V2: launchd Keep-Alive). |

Kein Retry-Mechanismus, kein State-Recovery, keine Cloud-Sync. MVP.

## Abhängigkeiten

**System (einmaliges Setup):**
- macOS 13+ (Apple Silicon getestet)
- Homebrew: `brew install whisper-cpp blackhole-2ch ollama`
- Whisper-Modell: `~/models/ggml-small.bin` (oder gewünscht)
- Ollama-Modell: `ollama pull llama3.1:8b`
- macOS Audio MIDI Setup: Multi-Output-Device (Headphones + BlackHole) als
  System-Output konfigurieren — sonst hört man im Call nichts mehr.

**Python (via uv):**
- `sounddevice`
- `numpy`
- `pyobjc-framework-CoreAudio` (für Mic-Activity-Detection)
- `tomli` (oder `tomllib` ab Python 3.11)

Keine direkte Abhängigkeit zu `faster-whisper`, `pyannote.audio`,
`anthropic`-SDK, Web-Frameworks — alles bewusst aus dem MVP raus.

## Testing-Strategie

- **`test_merge.py`** — Merge-Logik ist deterministisch und kritisch (falsche
  Reihenfolge → Transcript wird unleserlich). Unit-Tests mit synthetischen
  Segment-Listen.
- **Smoke-Test manuell** — eine kurze Beispiel-Aufnahme (10 min Selbstgespräch
  mit Pausen + System-Audio) durch die volle Pipeline laufen lassen.
- Keine End-to-End-Tests mit echter Mic-Erkennung im MVP — zu spröde.

## Offene Risiken / Annahmen

1. **BlackHole-Setup-Friction:** User muss Multi-Output-Device manuell im macOS
   Audio MIDI Setup konfigurieren. README muss das mit Screenshots erklären.
2. **CoreAudio-Polling-Robustheit:** Wenn User Default-Input-Device während
   eines Calls wechselt (z.B. AirPods rein/raus), könnte Watcher die Session
   verlieren. Risiko akzeptiert für MVP.
3. **Whisper-Qualität bei System-Audio:** Komprimiertes Meeting-Audio (Teams,
   Zoom) ist tonal anders als sauberes Mic-Audio. `small`-Modell könnte für
   `system.wav` schlechter performen. Falls Problem: separates Modell pro Spur
   konfigurierbar machen — V2.
4. **Ollama-Latenz:** `llama3.1:8b` auf M1/M2 braucht für 60-min-Transcript
   spürbar Zeit. Falls untragbar: kleineres Modell oder Truncation des
   Transcripts im Prompt.

## V2 / Future Work

In Reihenfolge wahrscheinlicher Nützlichkeit:

1. Echte Multi-Speaker-Diarization via `pyannote.audio` (HuggingFace-Token).
2. Sprecher-Identifikation per Voice-Embedding-DB (Lukas, häufige
   Gesprächspartner).
3. Notion-API / Obsidian-Vault-Push als zweites Output-Target.
4. SQLite + Embeddings-Index für Semantic Search über Meeting-Archiv.
5. Auto-Start bei Login via `launchd` plist.
6. Kalender-Integration: Meeting-Titel + Teilnehmer aus Google/Outlook
   auslesen und in Frontmatter.
7. Native Swift-Daemon mit `ScreenCaptureKit` als Drop-in-Replacement der
   Audio-Capture-Schicht — entfernt die BlackHole-Setup-Friction.
8. Web-UI (`localhost:8787`) zum Durchsuchen / Editieren.
