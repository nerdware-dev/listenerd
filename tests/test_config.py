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
    assert cfg.meetings_dir == (Path.home() / "CustomMeetings").resolve()
    assert cfg.meetings_dir.is_absolute()
