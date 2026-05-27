import json
import struct
import subprocess
import wave
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from listenerd.merge import Segment
from listenerd.transcribe import (
    TranscribeError,
    is_silent_wav,
    parse_whisper_json,
    transcribe_wav,
)


def _write_wav(path: Path, samples: list[int], rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))

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
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: b"")
    monkeypatch.setattr(
        "listenerd.transcribe.find_whisper_binary",
        lambda: "/opt/homebrew/bin/whisper-cli",
    )
    monkeypatch.setattr("listenerd.transcribe._model_exists", lambda p: True)

    result = transcribe_wav(wav, model="small", language="auto")

    assert len(calls) == 1
    cmd = calls[0]
    assert "/opt/homebrew/bin/whisper-cli" in cmd
    assert "-m" in cmd
    assert "-f" in cmd
    assert str(wav) in cmd
    assert "--output-json" in cmd
    assert result[0].text == "Hallo zusammen."


def test_is_silent_wav_true_for_all_zero(tmp_path):
    wav = tmp_path / "silent.wav"
    _write_wav(wav, [0] * 16000)  # 1 second of silence
    assert is_silent_wav(wav) is True


def test_is_silent_wav_false_for_loud_audio(tmp_path):
    wav = tmp_path / "loud.wav"
    _write_wav(wav, [5000] * 16000)  # well above threshold
    assert is_silent_wav(wav) is False


def test_is_silent_wav_false_for_quiet_but_audible(tmp_path):
    wav = tmp_path / "quiet.wav"
    # 100 is below "loud" but above the 64 silence threshold
    _write_wav(wav, [100] * 16000)
    assert is_silent_wav(wav) is False


def test_is_silent_wav_handles_unreadable_file(tmp_path):
    wav = tmp_path / "garbage.wav"
    wav.write_bytes(b"not a wav")
    # Bad file: don't classify as silent — let whisper itself error.
    assert is_silent_wav(wav) is False


def test_transcribe_wav_skips_silent_track(tmp_path, monkeypatch):
    wav = tmp_path / "silent.wav"
    _write_wav(wav, [0] * 16000)

    called = []

    def fake_run(cmd, **kwargs):
        called.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = transcribe_wav(wav, model="small", language="auto")
    assert result == []
    assert called == [], "whisper-cli must not be invoked on silent tracks"


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
    monkeypatch.setattr("listenerd.transcribe._model_exists", lambda p: True)

    with pytest.raises(TranscribeError, match="boom"):
        transcribe_wav(wav, model="small", language="auto")
