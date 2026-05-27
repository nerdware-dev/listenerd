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


def test_parse_ollama_response_sets_error_on_malformed():
    result = parse_ollama_response("complete garbage with no markers")
    assert result.summary is None
    assert result.error == "could not parse Ollama response"
