# listenerd MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python daemon for macOS that auto-detects active calls (via mic-activity), records mic + system audio as two tracks, transcribes both with whisper.cpp, merges them into a Me/Others-tagged transcript, generates a summary via local Ollama, and writes Markdown to `~/Meetings/`.

**Architecture:** Single Python process, three logical stages (Watcher → Recorder → Processor) communicating via filesystem (per-session directories). Bottom-up TDD for pure logic (config, merge, writer), subprocess-mocking for external CLIs (whisper-cli, ollama), and manual smoke-tests for audio I/O.

**Tech Stack:** Python 3.11+, `uv` (package manager), `sounddevice` (audio I/O), `pyobjc-framework-CoreAudio` (mic detection), `whisper-cpp` CLI (subprocess), `ollama` CLI (subprocess), BlackHole 2ch (system-audio loopback).

**Reference spec:** `docs/superpowers/specs/2026-05-26-listenerd-design.md`

---

## Task 0: Project Bootstrap

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `listenerd/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Initialize uv project**

Run from `/Users/lukas/dev/listenerd`:

```bash
uv init --package --name listenerd --python 3.11
```

This creates `pyproject.toml`, a placeholder `src/listenerd/`, and `.python-version`. We'll move source out of `src/` to match the spec layout.

- [ ] **Step 2: Reshape to spec layout**

```bash
rm -rf src
mkdir -p listenerd tests
touch listenerd/__init__.py tests/__init__.py
```

- [ ] **Step 3: Write `pyproject.toml`**

Overwrite with:

```toml
[project]
name = "listenerd"
version = "0.1.0"
description = "Local-first auto-recording + transcription daemon for macOS calls"
requires-python = ">=3.11"
dependencies = [
    "sounddevice>=0.4.6",
    "numpy>=1.26",
    "pyobjc-framework-CoreAudio>=10.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
]

[project.scripts]
listenerd = "listenerd.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["listenerd"]
```

- [ ] **Step 4: Write `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
dist/
build/
~/Meetings/
.DS_Store
```

- [ ] **Step 5: Install deps and verify import**

```bash
uv sync --extra dev
uv run python -c "import listenerd; print('ok')"
```

Expected: `ok`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore listenerd/__init__.py tests/__init__.py uv.lock .python-version
git commit -m "chore: bootstrap listenerd Python project"
```

---

## Task 1: Config Module (TDD)

**Files:**
- Create: `listenerd/config.py`
- Create: `tests/test_config.py`
- Create: `config.example.toml`

- [ ] **Step 1: Write failing test for defaults**

Create `tests/test_config.py`:

```python
from pathlib import Path
from listenerd.config import Config, load_config


def test_load_config_returns_defaults_when_no_file(tmp_path):
    missing = tmp_path / "nonexistent.toml"
    cfg = load_config(missing)
    assert cfg.whisper_model == "small"
    assert cfg.ollama_model == "llama3.1:8b"
    assert cfg.system_device == "BlackHole 2ch"
    assert cfg.sample_rate == 16000
    assert cfg.cooldown_seconds == 10
    assert cfg.min_duration_seconds == 30
    assert cfg.keep_audio is False


def test_load_config_overrides_from_toml(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[whisper]\n'
        'model = "large-v3-turbo"\n'
        '[output]\n'
        'keep_audio = true\n'
    )
    cfg = load_config(cfg_file)
    assert cfg.whisper_model == "large-v3-turbo"
    assert cfg.keep_audio is True
    # Unspecified fields keep defaults:
    assert cfg.ollama_model == "llama3.1:8b"


def test_meetings_dir_is_expanded(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[output]\nmeetings_dir = "~/CustomMeetings"\n')
    cfg = load_config(cfg_file)
    assert cfg.meetings_dir == Path.home() / "CustomMeetings"
    assert cfg.meetings_dir.is_absolute()
```

- [ ] **Step 2: Run test, verify it fails**

```bash
uv run pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'listenerd.config'`.

- [ ] **Step 3: Implement `listenerd/config.py`**

```python
"""Configuration loading. TOML with defaults."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    whisper_model: str = "small"
    whisper_language: str = "auto"
    ollama_model: str = "llama3.1:8b"
    ollama_summary_prompt: str = "default"
    mic_device: str = "default"
    system_device: str = "BlackHole 2ch"
    sample_rate: int = 16000
    cooldown_seconds: int = 10
    min_duration_seconds: int = 30
    meetings_dir: Path = field(default_factory=lambda: Path.home() / "Meetings")
    keep_audio: bool = False


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()

    with path.open("rb") as f:
        data = tomllib.load(f)

    whisper = data.get("whisper", {})
    ollama = data.get("ollama", {})
    audio = data.get("audio", {})
    session = data.get("session", {})
    output = data.get("output", {})

    meetings_dir = Path(output.get("meetings_dir", "~/Meetings")).expanduser().resolve()

    return Config(
        whisper_model=whisper.get("model", "small"),
        whisper_language=whisper.get("language", "auto"),
        ollama_model=ollama.get("model", "llama3.1:8b"),
        ollama_summary_prompt=ollama.get("summary_prompt", "default"),
        mic_device=audio.get("mic_device", "default"),
        system_device=audio.get("system_device", "BlackHole 2ch"),
        sample_rate=audio.get("sample_rate", 16000),
        cooldown_seconds=session.get("cooldown_seconds", 10),
        min_duration_seconds=session.get("min_duration_seconds", 30),
        meetings_dir=meetings_dir,
        keep_audio=output.get("keep_audio", False),
    )
```

- [ ] **Step 4: Run test, verify it passes**

```bash
uv run pytest tests/test_config.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Write `config.example.toml`**

```toml
# Copy to ~/.config/listenerd/config.toml and edit.

[whisper]
model = "small"              # base | small | large-v3-turbo
language = "auto"

[ollama]
model = "llama3.1:8b"
summary_prompt = "default"

[audio]
mic_device = "default"
system_device = "BlackHole 2ch"
sample_rate = 16000

[session]
cooldown_seconds = 10
min_duration_seconds = 30

[output]
meetings_dir = "~/Meetings"
keep_audio = false
```

- [ ] **Step 6: Commit**

```bash
git add listenerd/config.py tests/test_config.py config.example.toml
git commit -m "feat(config): add TOML-based config loader with defaults"
```

---

## Task 2: Merge Module (TDD)

**Files:**
- Create: `listenerd/merge.py`
- Create: `tests/test_merge.py`

Segments use millisecond offsets (matches `whisper-cli --output-json` `offsets` field).

- [ ] **Step 1: Write failing tests**

Create `tests/test_merge.py`:

```python
from listenerd.merge import Segment, TaggedSegment, merge_segments


def test_merge_empty_inputs_returns_empty():
    assert merge_segments([], []) == []


def test_merge_only_mic_segments_tags_all_me():
    mic = [Segment(0, 1000, "hello"), Segment(2000, 3000, "world")]
    result = merge_segments(mic, [])
    assert result == [
        TaggedSegment(0, 1000, "hello", "Me"),
        TaggedSegment(2000, 3000, "world", "Me"),
    ]


def test_merge_only_system_segments_tags_all_others():
    system = [Segment(500, 1500, "hi")]
    result = merge_segments([], system)
    assert result == [TaggedSegment(500, 1500, "hi", "Others")]


def test_merge_interleaves_chronologically():
    mic = [Segment(0, 1000, "I say first"), Segment(3000, 4000, "I say third")]
    system = [Segment(1500, 2500, "they say second")]
    result = merge_segments(mic, system)
    assert [s.text for s in result] == [
        "I say first",
        "they say second",
        "I say third",
    ]
    assert [s.speaker for s in result] == ["Me", "Others", "Me"]


def test_merge_ties_break_with_mic_first():
    mic = [Segment(1000, 2000, "me")]
    system = [Segment(1000, 2000, "others")]
    result = merge_segments(mic, system)
    assert result[0].speaker == "Me"
    assert result[1].speaker == "Others"


def test_merge_strips_whitespace_in_text():
    mic = [Segment(0, 1000, "  hello  ")]
    result = merge_segments(mic, [])
    assert result[0].text == "hello"


def test_merge_drops_segments_with_empty_text():
    mic = [Segment(0, 1000, ""), Segment(2000, 3000, "real")]
    system = [Segment(1500, 1600, "   ")]
    result = merge_segments(mic, system)
    assert len(result) == 1
    assert result[0].text == "real"
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
uv run pytest tests/test_merge.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `listenerd/merge.py`**

```python
"""Merge two whisper transcripts (mic + system) into a chronological
Me/Others-tagged stream."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Speaker = Literal["Me", "Others"]


@dataclass(frozen=True)
class Segment:
    """Whisper segment with millisecond offsets from recording start."""
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class TaggedSegment:
    start_ms: int
    end_ms: int
    text: str
    speaker: Speaker


def merge_segments(mic: list[Segment], system: list[Segment]) -> list[TaggedSegment]:
    """Merge mic and system segments chronologically.

    - mic segments are tagged "Me", system as "Others".
    - Ties on start_ms break with Me first (mic comes from this user).
    - Empty or whitespace-only segments are dropped.
    - Surrounding whitespace in text is stripped.
    """
    tagged: list[TaggedSegment] = []
    for seg in mic:
        text = seg.text.strip()
        if text:
            tagged.append(TaggedSegment(seg.start_ms, seg.end_ms, text, "Me"))
    for seg in system:
        text = seg.text.strip()
        if text:
            tagged.append(TaggedSegment(seg.start_ms, seg.end_ms, text, "Others"))

    # Stable sort: (start_ms, 0 for Me / 1 for Others) gives Me-first ties.
    tagged.sort(key=lambda s: (s.start_ms, 0 if s.speaker == "Me" else 1))
    return tagged
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
uv run pytest tests/test_merge.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add listenerd/merge.py tests/test_merge.py
git commit -m "feat(merge): chronologically merge mic + system transcripts"
```

---

## Task 3: Writer Module (TDD)

**Files:**
- Create: `listenerd/writer.py`
- Create: `tests/test_writer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_writer.py`:

```python
from datetime import datetime
from listenerd.merge import TaggedSegment
from listenerd.writer import MeetingDoc, render_markdown


def test_render_includes_frontmatter():
    doc = MeetingDoc(
        started_at=datetime(2026, 5, 26, 14, 30, 0),
        duration_seconds=2538,  # 42:18
        whisper_model="small",
        ollama_model="llama3.1:8b",
        summary="A quick sync.",
        action_items=["Follow up with Anna"],
        segments=[],
    )
    md = render_markdown(doc)
    assert "---" in md
    assert "date: 2026-05-26T14:30:00" in md
    assert "duration: 00:42:18" in md
    assert "source: listenerd" in md
    assert "whisper_model: small" in md


def test_render_includes_summary_and_action_items():
    doc = MeetingDoc(
        started_at=datetime(2026, 5, 26, 14, 30, 0),
        duration_seconds=60,
        whisper_model="small",
        ollama_model="llama3.1:8b",
        summary="A quick sync about Q3.",
        action_items=["Send slides to Bob", "Schedule next review"],
        segments=[],
    )
    md = render_markdown(doc)
    assert "## Summary" in md
    assert "A quick sync about Q3." in md
    assert "## Action Items" in md
    assert "- [ ] Send slides to Bob" in md
    assert "- [ ] Schedule next review" in md


def test_render_action_items_none_marker_when_empty():
    doc = MeetingDoc(
        started_at=datetime(2026, 5, 26, 14, 30, 0),
        duration_seconds=60,
        whisper_model="small",
        ollama_model="llama3.1:8b",
        summary="Chat.",
        action_items=[],
        segments=[],
    )
    md = render_markdown(doc)
    assert "## Action Items" in md
    assert "(none)" in md


def test_render_summary_failure_marker():
    doc = MeetingDoc(
        started_at=datetime(2026, 5, 26, 14, 30, 0),
        duration_seconds=60,
        whisper_model="small",
        ollama_model="llama3.1:8b",
        summary=None,  # Ollama failed
        action_items=[],
        segments=[],
    )
    md = render_markdown(doc)
    assert "[summary failed]" in md


def test_render_transcript_formats_speaker_and_timestamp():
    doc = MeetingDoc(
        started_at=datetime(2026, 5, 26, 14, 30, 0),
        duration_seconds=60,
        whisper_model="small",
        ollama_model="llama3.1:8b",
        summary="x",
        action_items=[],
        segments=[
            TaggedSegment(12_000, 17_000, "Hallo zusammen", "Me"),
            TaggedSegment(18_000, 22_000, "Hi Lukas", "Others"),
            TaggedSegment(3_725_000, 3_730_000, "Bis bald", "Me"),
        ],
    )
    md = render_markdown(doc)
    assert "**Me** (00:00:12): Hallo zusammen" in md
    assert "**Others** (00:00:18): Hi Lukas" in md
    assert "**Me** (01:02:05): Bis bald" in md
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
uv run pytest tests/test_writer.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `listenerd/writer.py`**

```python
"""Render a meeting document to Markdown."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from listenerd.merge import TaggedSegment


@dataclass(frozen=True)
class MeetingDoc:
    started_at: datetime
    duration_seconds: int
    whisper_model: str
    ollama_model: str
    summary: Optional[str]            # None = Ollama failed
    action_items: list[str]
    segments: list[TaggedSegment]


def _format_hms(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def render_markdown(doc: MeetingDoc) -> str:
    lines: list[str] = []

    # Frontmatter
    lines.append("---")
    lines.append(f"date: {doc.started_at.isoformat(timespec='seconds')}")
    lines.append(f"duration: {_format_hms(doc.duration_seconds)}")
    lines.append("source: listenerd")
    lines.append(f"whisper_model: {doc.whisper_model}")
    lines.append(f"ollama_model: {doc.ollama_model}")
    lines.append("---")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    if doc.summary is None:
        lines.append("[summary failed]")
    else:
        lines.append(doc.summary.strip())
    lines.append("")

    # Action items
    lines.append("## Action Items")
    lines.append("")
    if not doc.action_items:
        lines.append("(none)")
    else:
        for item in doc.action_items:
            lines.append(f"- [ ] {item}")
    lines.append("")

    # Transcript
    lines.append("## Transcript")
    lines.append("")
    for seg in doc.segments:
        ts = _format_hms(seg.start_ms // 1000)
        lines.append(f"**{seg.speaker}** ({ts}): {seg.text}")

    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
uv run pytest tests/test_writer.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add listenerd/writer.py tests/test_writer.py
git commit -m "feat(writer): render MeetingDoc to Markdown"
```

---

## Task 4: Transcribe Module (TDD with subprocess mock)

**Files:**
- Create: `listenerd/transcribe.py`
- Create: `tests/test_transcribe.py`
- Create: `tests/fixtures/sample_whisper_output.json`

Whisper.cpp `--output-json` writes JSON next to the WAV. Expected shape (relevant
fields):

```json
{
  "transcription": [
    {"offsets": {"from": 0, "to": 4000}, "text": "Hello."},
    {"offsets": {"from": 4000, "to": 8000}, "text": "World."}
  ]
}
```

- [ ] **Step 1: Create fixture file**

Create `tests/fixtures/sample_whisper_output.json`:

```json
{
  "transcription": [
    {"offsets": {"from": 0, "to": 4000}, "text": "Hallo zusammen."},
    {"offsets": {"from": 4000, "to": 8000}, "text": " Wie geht es euch?"}
  ]
}
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_transcribe.py`:

```python
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from listenerd.merge import Segment
from listenerd.transcribe import (
    TranscribeError,
    parse_whisper_json,
    transcribe_wav,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_whisper_output.json"


def test_parse_whisper_json_returns_segments():
    segments = parse_whisper_json(FIXTURE.read_text())
    assert segments == [
        Segment(0, 4000, "Hallo zusammen."),
        Segment(4000, 8000, " Wie geht es euch?"),
    ]


def test_parse_whisper_json_handles_empty_transcription():
    assert parse_whisper_json('{"transcription": []}') == []


def test_transcribe_wav_invokes_whisper_cli(tmp_path, monkeypatch):
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"fake")
    json_out = wav.with_suffix(".wav.json")
    json_out.write_text(FIXTURE.read_text())

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        "listenerd.transcribe.find_whisper_binary",
        lambda: "/opt/homebrew/bin/whisper-cli",
    )

    result = transcribe_wav(wav, model="small", language="auto")

    assert len(calls) == 1
    cmd = calls[0]
    assert "/opt/homebrew/bin/whisper-cli" in cmd
    assert "-m" in cmd
    assert "-f" in cmd
    assert str(wav) in cmd
    assert "--output-json" in cmd
    assert result[0].text == "Hallo zusammen."


def test_transcribe_wav_raises_on_nonzero_exit(tmp_path, monkeypatch):
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"fake")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        "listenerd.transcribe.find_whisper_binary",
        lambda: "/opt/homebrew/bin/whisper-cli",
    )

    with pytest.raises(TranscribeError, match="boom"):
        transcribe_wav(wav, model="small", language="auto")
```

- [ ] **Step 3: Run tests, verify they fail**

```bash
uv run pytest tests/test_transcribe.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 4: Implement `listenerd/transcribe.py`**

```python
"""Wrap whisper.cpp's whisper-cli for transcription."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from listenerd.merge import Segment


class TranscribeError(RuntimeError):
    pass


def find_whisper_binary() -> str:
    bin_path = shutil.which("whisper-cli")
    if bin_path:
        return bin_path
    for candidate in ("/opt/homebrew/bin/whisper-cli", "/usr/local/bin/whisper-cli"):
        if Path(candidate).is_file():
            return candidate
    raise TranscribeError(
        "whisper-cli not found. Install with: brew install whisper-cpp"
    )


def _metal_env() -> dict[str, str]:
    env = os.environ.copy()
    try:
        prefix = subprocess.check_output(
            ["brew", "--prefix", "whisper-cpp"], text=True
        ).strip()
        if prefix:
            env["GGML_METAL_PATH_RESOURCES"] = f"{prefix}/share/whisper-cpp"
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return env


def parse_whisper_json(text: str) -> list[Segment]:
    data = json.loads(text)
    return [
        Segment(
            start_ms=int(item["offsets"]["from"]),
            end_ms=int(item["offsets"]["to"]),
            text=item["text"],
        )
        for item in data.get("transcription", [])
    ]


def transcribe_wav(wav_path: Path, *, model: str, language: str) -> list[Segment]:
    """Run whisper-cli on a WAV file and return parsed segments.

    whisper-cli writes <wav_path>.json next to the input when --output-json is set.
    """
    binary = find_whisper_binary()
    model_path = Path.home() / "models" / f"ggml-{model}.bin"
    if not model_path.exists():
        raise TranscribeError(
            f"Whisper model not found: {model_path}. "
            f"Download from https://huggingface.co/ggerganov/whisper.cpp"
        )

    json_out = wav_path.with_suffix(".wav.json")
    cmd = [
        binary,
        "-m", str(model_path),
        "-f", str(wav_path),
        "-l", language,
        "--output-json",
        "--output-file", str(wav_path.with_suffix("")),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, env=_metal_env()
    )
    if result.returncode != 0:
        raise TranscribeError(result.stderr or "whisper-cli failed")

    if not json_out.exists():
        raise TranscribeError(f"Expected JSON output not found: {json_out}")

    return parse_whisper_json(json_out.read_text())
```

- [ ] **Step 5: Run tests, verify they pass**

```bash
uv run pytest tests/test_transcribe.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add listenerd/transcribe.py tests/test_transcribe.py tests/fixtures/sample_whisper_output.json
git commit -m "feat(transcribe): wrap whisper-cli with JSON-segment parser"
```

---

## Task 5: Summarize Module (TDD with subprocess mock)

**Files:**
- Create: `listenerd/summarize.py`
- Create: `tests/test_summarize.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_summarize.py`:

```python
import subprocess
from unittest.mock import MagicMock

import pytest

from listenerd.merge import TaggedSegment
from listenerd.summarize import (
    SummaryResult,
    format_transcript_for_prompt,
    parse_ollama_response,
    summarize,
)


def test_format_transcript_groups_speaker_and_text():
    segments = [
        TaggedSegment(0, 1000, "Hallo", "Me"),
        TaggedSegment(1500, 2500, "Hi", "Others"),
        TaggedSegment(3000, 4000, "Wie gehts", "Me"),
    ]
    formatted = format_transcript_for_prompt(segments)
    assert "Me: Hallo" in formatted
    assert "Others: Hi" in formatted
    assert "Me: Wie gehts" in formatted


def test_parse_ollama_response_extracts_summary_and_actions():
    response = """SUMMARY:
Wir haben Q3-Ziele besprochen und Termine fixiert.

ACTION_ITEMS:
- Anna schickt Slides bis Freitag
- Bob plant das Follow-up Meeting
"""
    result = parse_ollama_response(response)
    assert "Q3-Ziele" in result.summary
    assert result.action_items == [
        "Anna schickt Slides bis Freitag",
        "Bob plant das Follow-up Meeting",
    ]


def test_parse_ollama_response_handles_no_action_items():
    response = """SUMMARY:
Kurzes Update-Gespräch.

ACTION_ITEMS:
(none)
"""
    result = parse_ollama_response(response)
    assert result.action_items == []


def test_summarize_invokes_ollama_with_model(monkeypatch):
    segments = [TaggedSegment(0, 1000, "Hello", "Me")]

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="SUMMARY:\nTest.\n\nACTION_ITEMS:\n(none)\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = summarize(segments, model="llama3.1:8b")

    assert captured["cmd"] == ["ollama", "run", "llama3.1:8b"]
    assert "Me: Hello" in captured["input"]
    assert result.summary.strip() == "Test."
    assert result.action_items == []


def test_summarize_returns_none_summary_on_ollama_failure(monkeypatch):
    segments = [TaggedSegment(0, 1000, "Hello", "Me")]

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="connection refused")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = summarize(segments, model="llama3.1:8b")
    assert result.summary is None
    assert result.action_items == []
    assert "connection refused" in result.error
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
uv run pytest tests/test_summarize.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `listenerd/summarize.py`**

```python
"""Generate summary + action items via local Ollama."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from listenerd.merge import TaggedSegment


PROMPT_TEMPLATE = """\
You are a meeting note-taker. Below is a transcript from a meeting. Two speakers
are present: "Me" (the user) and "Others" (everyone else).

Produce output in this exact format:

SUMMARY:
<3-5 sentences summarizing the conversation>

ACTION_ITEMS:
- <each action item on its own line>
- ...

If there are no action items, write "(none)" on the line after ACTION_ITEMS:.

Transcript:
{transcript}
"""


@dataclass(frozen=True)
class SummaryResult:
    summary: Optional[str]              # None if Ollama failed
    action_items: list[str] = field(default_factory=list)
    error: Optional[str] = None


def format_transcript_for_prompt(segments: list[TaggedSegment]) -> str:
    return "\n".join(f"{seg.speaker}: {seg.text}" for seg in segments)


def parse_ollama_response(response: str) -> SummaryResult:
    summary_match = re.search(
        r"SUMMARY:\s*(.+?)(?:\n\s*ACTION_ITEMS:|$)",
        response,
        re.DOTALL,
    )
    actions_match = re.search(r"ACTION_ITEMS:\s*(.+?)$", response, re.DOTALL)

    summary = summary_match.group(1).strip() if summary_match else None

    action_items: list[str] = []
    if actions_match:
        for line in actions_match.group(1).splitlines():
            line = line.strip()
            if not line or line == "(none)":
                continue
            if line.startswith("- "):
                action_items.append(line[2:].strip())
            elif line.startswith("-"):
                action_items.append(line[1:].strip())

    return SummaryResult(summary=summary, action_items=action_items)


def summarize(segments: list[TaggedSegment], *, model: str) -> SummaryResult:
    prompt = PROMPT_TEMPLATE.format(transcript=format_transcript_for_prompt(segments))

    result = subprocess.run(
        ["ollama", "run", model],
        input=prompt,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return SummaryResult(
            summary=None,
            action_items=[],
            error=result.stderr.strip() or "ollama exited non-zero",
        )

    parsed = parse_ollama_response(result.stdout)
    return parsed
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
uv run pytest tests/test_summarize.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add listenerd/summarize.py tests/test_summarize.py
git commit -m "feat(summarize): call local Ollama for summary + action items"
```

---

## Task 6: Recorder Module (smoke-tested, not fully TDD)

**Files:**
- Create: `listenerd/recorder.py`
- Create: `tests/test_recorder.py`

Recording is heavy I/O against real hardware. We unit-test what we can (filename
construction, sample-to-frame math) and add one smoke-integration test that
opens the streams against the default devices for 0.5s and verifies WAVs land
on disk.

- [ ] **Step 1: Write tests**

Create `tests/test_recorder.py`:

```python
import wave
from pathlib import Path

import pytest

from listenerd.recorder import Recorder, RecordingPaths


def test_recording_paths_layout(tmp_path):
    paths = RecordingPaths(session_dir=tmp_path)
    assert paths.mic == tmp_path / "mic.wav"
    assert paths.system == tmp_path / "system.wav"


@pytest.mark.smoke
def test_recorder_writes_two_wavs(tmp_path):
    """Smoke test: opens real audio streams, writes 0.5s, verifies WAVs.

    Skipped unless --smoke flag is set, because it touches real hardware.
    Run with: uv run pytest -m smoke
    """
    paths = RecordingPaths(session_dir=tmp_path)
    rec = Recorder(
        paths=paths,
        mic_device=None,           # default input
        system_device=None,        # use default for smoke; BlackHole in real use
        sample_rate=16000,
    )
    rec.start()
    import time; time.sleep(0.5)
    rec.stop()

    assert paths.mic.exists()
    assert paths.system.exists()
    with wave.open(str(paths.mic), "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
```

Also update `pyproject.toml` to register the `smoke` marker. Add to the bottom:

```toml
[tool.pytest.ini_options]
markers = [
    "smoke: hardware-touching smoke tests (run with -m smoke)",
]
```

- [ ] **Step 2: Run unit test, verify it fails**

```bash
uv run pytest tests/test_recorder.py::test_recording_paths_layout -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `listenerd/recorder.py`**

```python
"""Dual-stream audio recorder. Writes mic + system to two WAV files."""
from __future__ import annotations

import queue
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd


@dataclass(frozen=True)
class RecordingPaths:
    session_dir: Path

    @property
    def mic(self) -> Path:
        return self.session_dir / "mic.wav"

    @property
    def system(self) -> Path:
        return self.session_dir / "system.wav"


class _WavWriter:
    def __init__(self, path: Path, sample_rate: int):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._wav = wave.open(str(path), "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(sample_rate)
        self._lock = threading.Lock()

    def write(self, samples: np.ndarray) -> None:
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        pcm = np.clip(samples * 32767, -32768, 32767).astype(np.int16)
        with self._lock:
            self._wav.writeframes(pcm.tobytes())

    def close(self) -> None:
        with self._lock:
            self._wav.close()


class Recorder:
    """Concurrent recording from two input devices into two WAV files."""

    def __init__(
        self,
        paths: RecordingPaths,
        *,
        mic_device: Optional[str],
        system_device: Optional[str],
        sample_rate: int,
    ):
        self.paths = paths
        self.sample_rate = sample_rate
        self._mic_device = mic_device
        self._system_device = system_device
        self._mic_stream: Optional[sd.InputStream] = None
        self._system_stream: Optional[sd.InputStream] = None
        self._mic_writer: Optional[_WavWriter] = None
        self._system_writer: Optional[_WavWriter] = None

    def start(self) -> None:
        self.paths.session_dir.mkdir(parents=True, exist_ok=True)
        self._mic_writer = _WavWriter(self.paths.mic, self.sample_rate)
        self._system_writer = _WavWriter(self.paths.system, self.sample_rate)

        def mic_cb(indata, frames, t, status):
            self._mic_writer.write(indata.copy())

        def system_cb(indata, frames, t, status):
            self._system_writer.write(indata.copy())

        self._mic_stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            device=self._mic_device,
            callback=mic_cb,
        )
        self._system_stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            device=self._system_device,
            callback=system_cb,
        )
        self._mic_stream.start()
        self._system_stream.start()

    def stop(self) -> None:
        for stream in (self._mic_stream, self._system_stream):
            if stream is not None:
                stream.stop()
                stream.close()
        for writer in (self._mic_writer, self._system_writer):
            if writer is not None:
                writer.close()
        self._mic_stream = self._system_stream = None
        self._mic_writer = self._system_writer = None
```

- [ ] **Step 4: Run unit test, verify it passes**

```bash
uv run pytest tests/test_recorder.py::test_recording_paths_layout -v
```

Expected: 1 passed.

- [ ] **Step 5: Run smoke test manually**

```bash
uv run pytest tests/test_recorder.py -v -m smoke
```

Expected: Either passes (mic accessible) or fails with a clear audio-permission
error you can address by granting mic access to the terminal in System Settings.

- [ ] **Step 6: Commit**

```bash
git add listenerd/recorder.py tests/test_recorder.py pyproject.toml
git commit -m "feat(recorder): dual-stream mic + system WAV recorder"
```

---

## Task 7: Watcher Module (logic TDD + manual CoreAudio check)

**Files:**
- Create: `listenerd/watcher.py`
- Create: `tests/test_watcher.py`

The CoreAudio polling is hardware-touched, but the **state machine** (session
start/stop logic, cooldown handling) is pure and TDD-able.

- [ ] **Step 1: Write failing tests for state machine**

Create `tests/test_watcher.py`:

```python
from listenerd.watcher import SessionState, SessionStateMachine


def test_initial_state_is_idle():
    sm = SessionStateMachine(cooldown_seconds=10)
    assert sm.state == SessionState.IDLE


def test_mic_on_transitions_to_recording():
    sm = SessionStateMachine(cooldown_seconds=10)
    event = sm.tick(now=100.0, mic_on=True)
    assert sm.state == SessionState.RECORDING
    assert event == "start"


def test_already_recording_no_event():
    sm = SessionStateMachine(cooldown_seconds=10)
    sm.tick(now=100.0, mic_on=True)
    event = sm.tick(now=101.0, mic_on=True)
    assert sm.state == SessionState.RECORDING
    assert event is None


def test_mic_off_during_recording_enters_cooldown():
    sm = SessionStateMachine(cooldown_seconds=10)
    sm.tick(now=100.0, mic_on=True)
    event = sm.tick(now=200.0, mic_on=False)
    assert sm.state == SessionState.COOLDOWN
    assert event is None


def test_mic_on_during_cooldown_returns_to_recording():
    sm = SessionStateMachine(cooldown_seconds=10)
    sm.tick(now=100.0, mic_on=True)
    sm.tick(now=200.0, mic_on=False)  # cooldown
    event = sm.tick(now=205.0, mic_on=True)
    assert sm.state == SessionState.RECORDING
    assert event is None


def test_cooldown_expires_emits_stop():
    sm = SessionStateMachine(cooldown_seconds=10)
    sm.tick(now=100.0, mic_on=True)
    sm.tick(now=200.0, mic_on=False)        # enter cooldown at t=200
    event = sm.tick(now=211.0, mic_on=False) # 11s later, cooldown expired
    assert sm.state == SessionState.IDLE
    assert event == "stop"


def test_session_duration_tracked():
    sm = SessionStateMachine(cooldown_seconds=10)
    sm.tick(now=100.0, mic_on=True)
    sm.tick(now=200.0, mic_on=False)
    sm.tick(now=211.0, mic_on=False)
    assert sm.last_session_duration_seconds == 100  # 200 - 100
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
uv run pytest tests/test_watcher.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `listenerd/watcher.py`**

```python
"""Watch for mic activity on macOS and run a session state machine."""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from typing import Optional


class SessionState(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    COOLDOWN = "cooldown"


@dataclass
class SessionStateMachine:
    """Pure state machine driven by tick(now, mic_on).

    Emits "start" when session starts, "stop" when cooldown expires.
    """

    cooldown_seconds: int
    state: SessionState = SessionState.IDLE
    _session_start: Optional[float] = None
    _session_end: Optional[float] = None
    _cooldown_start: Optional[float] = None
    last_session_duration_seconds: Optional[int] = None

    def tick(self, *, now: float, mic_on: bool) -> Optional[str]:
        if self.state == SessionState.IDLE:
            if mic_on:
                self.state = SessionState.RECORDING
                self._session_start = now
                return "start"
            return None

        if self.state == SessionState.RECORDING:
            if not mic_on:
                self.state = SessionState.COOLDOWN
                self._cooldown_start = now
                self._session_end = now
            return None

        # COOLDOWN
        if mic_on:
            self.state = SessionState.RECORDING
            self._cooldown_start = None
            self._session_end = None
            return None
        if now - (self._cooldown_start or now) >= self.cooldown_seconds:
            self.state = SessionState.IDLE
            duration = (self._session_end or now) - (self._session_start or now)
            self.last_session_duration_seconds = int(duration)
            self._session_start = self._session_end = self._cooldown_start = None
            return "stop"
        return None


def mic_is_active() -> bool:
    """Check whether macOS default input device is currently in use.

    Uses CoreAudio kAudioDevicePropertyDeviceIsRunningSomewhere.
    """
    # Lazy-import so test runs (which don't poll hardware) stay cheap.
    from CoreAudio import (  # type: ignore
        AudioObjectGetPropertyData,
        AudioObjectPropertyAddress,
        kAudioHardwarePropertyDefaultInputDevice,
        kAudioObjectPropertyScopeGlobal,
        kAudioObjectPropertyElementMaster,
        kAudioObjectSystemObject,
        kAudioDevicePropertyDeviceIsRunningSomewhere,
    )
    # NOTE: pyobjc-framework-CoreAudio exposes these constants. If the import
    # surface differs on your install, see the manual smoke test below for
    # an alternate implementation using `lsof | grep coreaudiod`.
    import ctypes

    addr = AudioObjectPropertyAddress(
        kAudioHardwarePropertyDefaultInputDevice,
        kAudioObjectPropertyScopeGlobal,
        kAudioObjectPropertyElementMaster,
    )
    device_id = ctypes.c_uint32(0)
    size = ctypes.c_uint32(ctypes.sizeof(device_id))
    AudioObjectGetPropertyData(
        kAudioObjectSystemObject, addr, 0, None, ctypes.byref(size), ctypes.byref(device_id)
    )

    addr2 = AudioObjectPropertyAddress(
        kAudioDevicePropertyDeviceIsRunningSomewhere,
        kAudioObjectPropertyScopeGlobal,
        kAudioObjectPropertyElementMaster,
    )
    running = ctypes.c_uint32(0)
    size2 = ctypes.c_uint32(ctypes.sizeof(running))
    AudioObjectGetPropertyData(
        device_id.value, addr2, 0, None, ctypes.byref(size2), ctypes.byref(running)
    )
    return running.value == 1
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
uv run pytest tests/test_watcher.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Manual CoreAudio smoke check**

Run this from a Python REPL to confirm `mic_is_active()` works on the actual
machine. If pyobjc-CoreAudio constants are not available as imported above,
fall back to the simpler `lsof`-based check below — replace the body of
`mic_is_active()`:

```python
def mic_is_active() -> bool:
    import subprocess
    result = subprocess.run(
        ["lsof", "+c", "0", "/dev/audio"],
        capture_output=True, text=True
    )
    # If anything but coreaudiod is holding an audio device, mic is in use.
    lines = [l for l in result.stdout.splitlines() if l and "coreaudiod" not in l]
    return len(lines) > 1  # >1 because first line is the header
```

Manual test: Open QuickTime → New Audio Recording → press record. Then in
another terminal:

```bash
uv run python -c "from listenerd.watcher import mic_is_active; print(mic_is_active())"
```

Expected: `True` while recording, `False` after stopping.

- [ ] **Step 6: Commit**

```bash
git add listenerd/watcher.py tests/test_watcher.py
git commit -m "feat(watcher): mic-activity detector + session state machine"
```

---

## Task 8: Main Daemon Loop

**Files:**
- Create: `listenerd/__main__.py`

This wires everything together. No unit tests — exercised via the smoke test in
Task 9.

- [ ] **Step 1: Implement `listenerd/__main__.py`**

```python
"""listenerd daemon: detect calls, record, transcribe, summarize, write."""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from listenerd.config import Config, load_config
from listenerd.merge import merge_segments
from listenerd.recorder import Recorder, RecordingPaths
from listenerd.summarize import summarize
from listenerd.transcribe import TranscribeError, transcribe_wav
from listenerd.watcher import SessionStateMachine, mic_is_active
from listenerd.writer import MeetingDoc, render_markdown


log = logging.getLogger("listenerd")


def process_session(session_dir: Path, started_at: datetime, duration_s: int, cfg: Config) -> None:
    """Run the full post-recording pipeline on a finished session."""
    paths = RecordingPaths(session_dir=session_dir)

    if duration_s < cfg.min_duration_seconds:
        log.info("Session %s too short (%ds < %ds), discarding",
                 session_dir.name, duration_s, cfg.min_duration_seconds)
        shutil.rmtree(session_dir, ignore_errors=True)
        return

    log.info("Transcribing session %s (%ds)", session_dir.name, duration_s)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            mic_future = pool.submit(
                transcribe_wav, paths.mic,
                model=cfg.whisper_model, language=cfg.whisper_language,
            )
            sys_future = pool.submit(
                transcribe_wav, paths.system,
                model=cfg.whisper_model, language=cfg.whisper_language,
            )
            mic_segments = mic_future.result()
            sys_segments = sys_future.result()
    except TranscribeError as e:
        log.error("Transcription failed: %s. Keeping WAVs in %s", e, session_dir)
        return

    merged = merge_segments(mic_segments, sys_segments)
    log.info("Generating summary with %s", cfg.ollama_model)
    summary_result = summarize(merged, model=cfg.ollama_model)

    doc = MeetingDoc(
        started_at=started_at,
        duration_seconds=duration_s,
        whisper_model=cfg.whisper_model,
        ollama_model=cfg.ollama_model,
        summary=summary_result.summary,
        action_items=summary_result.action_items,
        segments=merged,
    )

    cfg.meetings_dir.mkdir(parents=True, exist_ok=True)
    out_path = cfg.meetings_dir / f"{started_at.strftime('%Y-%m-%d-%H%M')}-meeting.md"
    out_path.write_text(render_markdown(doc))
    log.info("Wrote %s", out_path)

    if not cfg.keep_audio:
        shutil.rmtree(session_dir, ignore_errors=True)


def daemon_loop(cfg: Config) -> None:
    sessions_root = cfg.meetings_dir / ".sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)

    sm = SessionStateMachine(cooldown_seconds=cfg.cooldown_seconds)
    recorder: Recorder | None = None
    session_started_at: datetime | None = None
    session_dir: Path | None = None

    log.info("listenerd started. Watching for mic activity…")
    try:
        while True:
            now = time.monotonic()
            event = sm.tick(now=now, mic_on=mic_is_active())

            if event == "start":
                session_started_at = datetime.now()
                session_dir = sessions_root / session_started_at.strftime("%Y-%m-%dT%H%M%S")
                paths = RecordingPaths(session_dir=session_dir)
                recorder = Recorder(
                    paths=paths,
                    mic_device=None if cfg.mic_device == "default" else cfg.mic_device,
                    system_device=cfg.system_device,
                    sample_rate=cfg.sample_rate,
                )
                recorder.start()
                log.info("Recording session %s", session_dir.name)

            elif event == "stop":
                if recorder is not None:
                    recorder.stop()
                if session_dir is not None and session_started_at is not None:
                    duration_s = sm.last_session_duration_seconds or 0
                    process_session(session_dir, session_started_at, duration_s, cfg)
                recorder = None
                session_dir = None
                session_started_at = None

            time.sleep(1.0)
    except KeyboardInterrupt:
        log.info("Stopping…")
        if recorder is not None:
            recorder.stop()


def main() -> int:
    parser = argparse.ArgumentParser(prog="listenerd")
    parser.add_argument(
        "--config", type=Path,
        default=Path.home() / ".config" / "listenerd" / "config.toml",
        help="Path to config.toml (defaults applied if missing).",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config(args.config)
    log.debug("Config: %s", cfg)

    try:
        daemon_loop(cfg)
    except Exception as e:
        log.exception("Fatal: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Sanity-check imports compile**

```bash
uv run python -c "from listenerd.__main__ import main; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add listenerd/__main__.py
git commit -m "feat: wire watcher + recorder + processor into daemon"
```

---

## Task 9: README + End-to-End Smoke Test

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

````markdown
# listenerd

Local-first auto-recording + transcription daemon for macOS calls.

Detects active calls via system mic-activity (works for Teams, Zoom, Meet,
Gather, Discord, anything), records mic + system audio as two tracks,
transcribes both locally with `whisper.cpp`, generates a summary via local
Ollama, and writes Markdown to `~/Meetings/`.

## One-Time Setup

### 1. System dependencies

```bash
brew install whisper-cpp blackhole-2ch ollama
```

### 2. Whisper model

Download a model into `~/models/`:

```bash
mkdir -p ~/models
curl -L -o ~/models/ggml-small.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
```

### 3. Ollama model

```bash
ollama pull llama3.1:8b
```

### 4. BlackHole multi-output

So you still **hear** the call while it's being captured:

1. Open **Audio MIDI Setup** (`/Applications/Utilities/Audio MIDI Setup.app`).
2. **+** → **Create Multi-Output Device**.
3. Check **your headphones/speakers** AND **BlackHole 2ch**.
4. macOS menu bar → set this Multi-Output device as your **System Output**.
5. In Teams/Zoom/etc., keep your mic as input; the multi-output is the speaker.

Verify: `system_profiler SPAudioDataType | grep BlackHole` should list it.

### 5. Mic permission

The first time you run `listenerd` macOS will prompt for microphone access.
Grant it (or pre-grant via System Settings → Privacy → Microphone).

## Install

```bash
git clone <this repo> ~/dev/listenerd
cd ~/dev/listenerd
uv sync
```

## Configure

```bash
mkdir -p ~/.config/listenerd
cp config.example.toml ~/.config/listenerd/config.toml
$EDITOR ~/.config/listenerd/config.toml
```

## Run

```bash
uv run listenerd
# or with verbose logging:
uv run listenerd -v
```

Leave it running. Join a call. It auto-records. After you hang up, wait ~10s
for cooldown + transcription + summary, then find `~/Meetings/<date>-meeting.md`.

## How it works

```
[Watcher]  pollt CoreAudio: mic on?
    │
    ▼
[Recorder] schreibt mic.wav + system.wav (BlackHole) parallel
    │
    ▼
[Processor] whisper.cpp → merge → ollama → Markdown
```

See `docs/superpowers/specs/2026-05-26-listenerd-design.md` for the full spec.

## Troubleshooting

- **"BlackHole 2ch" device not found** — Audio MIDI Setup → ensure BlackHole
  appears under Input. If not, re-install: `brew reinstall blackhole-2ch`,
  then reboot.
- **Sessions get triggered when you use `whisper-locally`** — the 30s minimum
  duration filter discards bursts. Adjust `min_duration_seconds` in config
  if needed.
- **No system audio in recording** — your System Output isn't routed through
  BlackHole. See setup step 4.

## License

MIT.
````

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest -v
```

Expected: All non-smoke tests pass (config + merge + writer + transcribe +
summarize + watcher + recorder unit-only).

- [ ] **Step 3: Manual smoke test**

1. Open Audio MIDI Setup, confirm BlackHole multi-output is system output.
2. Run `uv run listenerd -v`.
3. Open Teams/Meet/Zoom, join a test meeting alone (or with a buddy for 1-2 minutes).
4. Speak into the mic. Play a YouTube video in the background to seed
   "Others"-side audio.
5. End the meeting, wait for cooldown + processing.
6. Check `~/Meetings/` for a fresh `YYYY-MM-DD-HHMM-meeting.md`.
7. Verify the file has: frontmatter, non-empty Summary, sensible Transcript
   with `**Me**` and `**Others**` segments.

Note any rough edges in a follow-up issue. Common ones:
- Whisper language mis-detection → set `language` explicitly in config.
- Ollama summary too short / too long → tune the prompt in `summarize.py`.
- Mic-activity detection too eager → raise `min_duration_seconds`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup, run, and troubleshooting"
```

---

## Done

At this point:
- All unit tests green
- Manual smoke test confirms end-to-end works
- Repo is committable, runnable, and matches the spec

V2 / Future Work (see spec) starts from here.
