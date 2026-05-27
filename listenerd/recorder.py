"""Dual-stream audio recorder. Writes mic + system to two WAV files."""
from __future__ import annotations

import logging
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

log = logging.getLogger("listenerd.recorder")


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
        if self._mic_stream is not None or self._system_stream is not None:
            raise RuntimeError("Recorder already started; call stop() first")

        self.paths.session_dir.mkdir(parents=True, exist_ok=True)
        self._mic_writer = _WavWriter(self.paths.mic, self.sample_rate)
        self._system_writer = _WavWriter(self.paths.system, self.sample_rate)

        def mic_cb(indata, frames, t, status):
            if status:
                log.warning("mic stream status: %s", status)
            self._mic_writer.write(indata.copy())

        def system_cb(indata, frames, t, status):
            if status:
                log.warning("system stream status: %s", status)
            self._system_writer.write(indata.copy())

        try:
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
        except Exception:
            # Roll back any partial state so the recorder is usable again.
            for stream in (self._mic_stream, self._system_stream):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
            for writer in (self._mic_writer, self._system_writer):
                if writer is not None:
                    try:
                        writer.close()
                    except Exception:
                        pass
            self._mic_stream = self._system_stream = None
            self._mic_writer = self._system_writer = None
            raise

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
