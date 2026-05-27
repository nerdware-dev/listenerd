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

    whisper-cli writes <wav_path>.json next to the input when --output-json is set.
    """
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
