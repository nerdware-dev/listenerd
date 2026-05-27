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
