import json
from unittest.mock import MagicMock

import pytest

from listenerd.merge import TaggedSegment
from listenerd.summarize import (
    SummaryResult,
    format_transcript_for_prompt,
    parse_ollama_response,
    summarize,
)


def _fake_urlopen(response_text: str, *, status: int = 200, raise_url_error: bool = False):
    """Return a fake urlopen callable that yields the given Ollama response."""
    def _impl(req, timeout=None):
        if raise_url_error:
            import urllib.error
            raise urllib.error.URLError("connection refused")
        body = json.dumps({"response": response_text, "model": "test"}).encode()
        class _Resp:
            def __enter__(self_): return self_
            def __exit__(self_, *_): pass
            def read(self_): return body
        return _Resp()
    return _impl


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

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        body = json.dumps({"response": "SUMMARY:\nTest.\n\nACTION_ITEMS:\n(none)\n"}).encode()
        class _Resp:
            def __enter__(self_): return self_
            def __exit__(self_, *_): pass
            def read(self_): return body
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = summarize(segments, model="llama3.1:8b")

    assert captured["url"].endswith("/api/generate")
    assert captured["body"]["model"] == "llama3.1:8b"
    assert "Me: Hello" in captured["body"]["prompt"]
    assert captured["body"]["stream"] is False
    assert result.summary.strip() == "Test."
    assert result.action_items == []


def test_summarize_returns_none_summary_on_ollama_failure(monkeypatch):
    segments = [TaggedSegment(0, 1000, "Hello", "Me")]
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen("", raise_url_error=True),
    )
    result = summarize(segments, model="llama3.1:8b")
    assert result.summary is None
    assert result.action_items == []
    assert "connection refused" in result.error


def test_parse_ollama_response_sets_error_on_malformed():
    result = parse_ollama_response("complete garbage with no markers")
    assert result.summary is None
    assert result.error == "could not parse Ollama response"
