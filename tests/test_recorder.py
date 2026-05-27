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


def test_recorder_rejects_double_start(tmp_path, monkeypatch):
    """Calling start() twice without stop() in between must raise."""
    import sounddevice as sd

    class _FakeStream:
        def __init__(self, *a, **kw): pass
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(sd, "InputStream", _FakeStream)

    paths = RecordingPaths(session_dir=tmp_path)
    rec = Recorder(
        paths=paths,
        mic_device=None,
        system_device=None,
        sample_rate=16000,
    )
    rec.start()
    try:
        with pytest.raises(RuntimeError, match="already started"):
            rec.start()
    finally:
        rec.stop()


def test_recorder_rolls_back_on_second_stream_failure(tmp_path, monkeypatch):
    """If the system InputStream fails to construct, no resources leak and the
    recorder is usable again afterwards."""
    import sounddevice as sd

    calls = {"n": 0}

    class _FlakyStream:
        def __init__(self, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom")
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(sd, "InputStream", _FlakyStream)

    paths = RecordingPaths(session_dir=tmp_path)
    rec = Recorder(
        paths=paths,
        mic_device=None,
        system_device=None,
        sample_rate=16000,
    )
    with pytest.raises(RuntimeError, match="boom"):
        rec.start()

    # Recorder must be in a clean state after the failure
    assert rec._mic_stream is None
    assert rec._system_stream is None
    assert rec._mic_writer is None
    assert rec._system_writer is None

    # Should be able to start again with a non-flaky stream
    calls["n"] = 0
    class _OkStream:
        def __init__(self, *a, **kw): pass
        def start(self): pass
        def stop(self): pass
        def close(self): pass
    monkeypatch.setattr(sd, "InputStream", _OkStream)
    rec.start()
    rec.stop()
