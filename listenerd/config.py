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
    meetings_dir: Path = field(default_factory=lambda: (Path.home() / "Meetings").resolve())
    keep_audio: bool = False


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()

    with path.open("rb") as f:
        data = tomllib.load(f)

    defaults = Config()
    whisper = data.get("whisper", {})
    ollama = data.get("ollama", {})
    audio = data.get("audio", {})
    session = data.get("session", {})
    output = data.get("output", {})

    raw_meetings_dir = output.get("meetings_dir")
    meetings_dir = (
        Path(raw_meetings_dir).expanduser().resolve()
        if raw_meetings_dir is not None
        else defaults.meetings_dir
    )

    return Config(
        whisper_model=whisper.get("model", defaults.whisper_model),
        whisper_language=whisper.get("language", defaults.whisper_language),
        ollama_model=ollama.get("model", defaults.ollama_model),
        ollama_summary_prompt=ollama.get("summary_prompt", defaults.ollama_summary_prompt),
        mic_device=audio.get("mic_device", defaults.mic_device),
        system_device=audio.get("system_device", defaults.system_device),
        sample_rate=audio.get("sample_rate", defaults.sample_rate),
        cooldown_seconds=session.get("cooldown_seconds", defaults.cooldown_seconds),
        min_duration_seconds=session.get("min_duration_seconds", defaults.min_duration_seconds),
        meetings_dir=meetings_dir,
        keep_audio=output.get("keep_audio", defaults.keep_audio),
    )
