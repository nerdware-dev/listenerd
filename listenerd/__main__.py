"""listenerd daemon: detect calls, record, transcribe, summarize, write."""
from __future__ import annotations

import argparse
import logging
import shutil
import signal
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


def process_session(
    session_dir: Path,
    started_at: datetime,
    duration_s: int,
    cfg: Config,
    *,
    enforce_min_duration: bool = True,
) -> None:
    """Run the full post-recording pipeline on a finished session."""
    paths = RecordingPaths(session_dir=session_dir)

    if enforce_min_duration and duration_s < cfg.min_duration_seconds:
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


def record_once(cfg: Config) -> None:
    """Record one session immediately. Stops on SIGINT (Ctrl-C) or SIGTERM,
    then runs the full post-processing pipeline."""
    sessions_root = cfg.meetings_dir / ".sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)

    session_started_at = datetime.now()
    session_dir = sessions_root / session_started_at.strftime("%Y-%m-%dT%H%M%S")
    paths = RecordingPaths(session_dir=session_dir)
    recorder = Recorder(
        paths=paths,
        mic_device=None if cfg.mic_device == "default" else cfg.mic_device,
        system_device=cfg.system_device,
        sample_rate=cfg.sample_rate,
    )

    try:
        recorder.start()
    except Exception as e:
        log.error("Failed to start recording: %s", e)
        shutil.rmtree(session_dir, ignore_errors=True)
        raise

    log.info("Recording session %s. Press Ctrl-C (or send SIGTERM) to stop.",
             session_dir.name)
    start_mono = time.monotonic()

    def _on_term(signum, frame):
        raise KeyboardInterrupt
    prev_term = signal.signal(signal.SIGTERM, _on_term)

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        # Once we're shutting down, ignore further SIGINT/SIGTERM. A second
        # signal during post-processing (e.g. SwiftBar refreshes "recording"
        # for ~3s after Stop and a frustrated user clicks Stop again) would
        # otherwise kill the python process mid-transcription, leaving the
        # session unfinished. The signals do still terminate whisper-cli
        # subprocesses via the process group, so we don't get stuck.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        recorder.stop()
        duration_s = int(time.monotonic() - start_mono)
        log.info("Stopped after %ds. Processing…", duration_s)
        process_session(
            session_dir, session_started_at, duration_s, cfg,
            enforce_min_duration=False,
        )
        signal.signal(signal.SIGTERM, prev_term)


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
                try:
                    recorder.start()
                    log.info("Recording session %s", session_dir.name)
                except Exception as e:
                    log.error("Failed to start recording: %s. Skipping session.", e)
                    # Clean up partial session dir if it was created
                    shutil.rmtree(session_dir, ignore_errors=True)
                    recorder = None
                    session_dir = None
                    session_started_at = None

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
        help="Enable debug-level logging.",
    )
    parser.add_argument(
        "command", nargs="?", default="watch",
        choices=("watch", "record"),
        help="watch (default): auto-detect calls via mic activity. "
             "record: start recording now, stop with Ctrl-C.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config(args.config)
    log.debug("Config: %s", cfg)

    try:
        if args.command == "record":
            record_once(cfg)
        else:
            daemon_loop(cfg)
    except Exception as e:
        log.exception("Fatal: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
