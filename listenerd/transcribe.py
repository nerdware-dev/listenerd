"""Wrap whisper.cpp's whisper-cli for transcription."""
from __future__ import annotations

import json
import logging
import os
import shutil
import struct
import subprocess
import wave
from pathlib import Path

from listenerd.merge import Segment


log = logging.getLogger("listenerd.transcribe")


class TranscribeError(RuntimeError):
    pass


# Peak absolute sample value below which a 16-bit PCM WAV is considered
# silent. 64 = ~ -54 dBFS — well below any real speech, while tolerant of
# slight DC offset or codec dither. Tracks that fail this check are skipped
# entirely: whisper-cpp would otherwise spend several minutes generating
# canonical hallucinations ("Thank you.", "Thanks for watching.") on the
# silent audio.
_SILENCE_PEAK_THRESHOLD = 64


def is_silent_wav(wav_path: Path) -> bool:
    """Return True if the WAV's loudest sample is below the silence threshold.

    Reads the whole file (cheap at 16 kHz mono int16). Returns False if the
    file can't be opened or read — let whisper itself surface that error.
    """
    try:
        with wave.open(str(wav_path)) as w:
            n = w.getnframes()
            if n == 0:
                return True
            # Read in chunks to bound memory on long files.
            chunk = max(1, w.getframerate() * 60)  # ~60s windows
            peak = 0
            while True:
                frames = w.readframes(chunk)
                if not frames:
                    break
                # int16: each pair of bytes is one sample. Find the max
                # absolute value across the chunk without numpy.
                count = len(frames) // 2
                samples = struct.unpack(f"<{count}h", frames)
                chunk_peak = max(abs(s) for s in samples) if samples else 0
                if chunk_peak > peak:
                    peak = chunk_peak
                if peak >= _SILENCE_PEAK_THRESHOLD:
                    return False
        return peak < _SILENCE_PEAK_THRESHOLD
    except (wave.Error, OSError, EOFError, struct.error):
        return False


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


def _model_exists(path: Path) -> bool:
    """Return True if the model file exists. Extracted for testability."""
    return path.exists()


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

    Short-circuits to an empty list for silent files — saves minutes of CPU
    and avoids whisper's silence-hallucination output.

    whisper-cli writes <wav_path>.json next to the input when --output-json is set.
    """
    if is_silent_wav(wav_path):
        log.info("Skipping %s (silent track)", wav_path.name)
        return []

    binary = find_whisper_binary()
    model_path = Path.home() / "models" / f"ggml-{model}.bin"
    if not _model_exists(model_path):
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
        "--output-file", str(wav_path),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, env=_metal_env()
    )
    if result.returncode != 0:
        raise TranscribeError(result.stderr or "whisper-cli failed")

    if not json_out.exists():
        raise TranscribeError(f"Expected JSON output not found: {json_out}")

    return parse_whisper_json(json_out.read_text())
