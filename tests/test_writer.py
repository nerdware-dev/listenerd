from datetime import datetime
from listenerd.merge import TaggedSegment
from listenerd.writer import MeetingDoc, render_markdown


def test_render_includes_frontmatter():
    doc = MeetingDoc(
        started_at=datetime(2026, 5, 26, 14, 30, 0),
        duration_seconds=2538,  # 42:18
        whisper_model="small",
        ollama_model="llama3.1:8b",
        summary="A quick sync.",
        action_items=["Follow up with Anna"],
        segments=[],
    )
    md = render_markdown(doc)
    assert "---" in md
    assert "date: 2026-05-26T14:30:00" in md
    assert "duration: 00:42:18" in md
    assert "source: listenerd" in md
    assert "whisper_model: small" in md


def test_render_includes_summary_and_action_items():
    doc = MeetingDoc(
        started_at=datetime(2026, 5, 26, 14, 30, 0),
        duration_seconds=60,
        whisper_model="small",
        ollama_model="llama3.1:8b",
        summary="A quick sync about Q3.",
        action_items=["Send slides to Bob", "Schedule next review"],
        segments=[],
    )
    md = render_markdown(doc)
    assert "## Summary" in md
    assert "A quick sync about Q3." in md
    assert "## Action Items" in md
    assert "- [ ] Send slides to Bob" in md
    assert "- [ ] Schedule next review" in md


def test_render_action_items_none_marker_when_empty():
    doc = MeetingDoc(
        started_at=datetime(2026, 5, 26, 14, 30, 0),
        duration_seconds=60,
        whisper_model="small",
        ollama_model="llama3.1:8b",
        summary="Chat.",
        action_items=[],
        segments=[],
    )
    md = render_markdown(doc)
    assert "## Action Items" in md
    assert "(none)" in md


def test_render_summary_failure_marker():
    doc = MeetingDoc(
        started_at=datetime(2026, 5, 26, 14, 30, 0),
        duration_seconds=60,
        whisper_model="small",
        ollama_model="llama3.1:8b",
        summary=None,  # Ollama failed
        action_items=[],
        segments=[],
    )
    md = render_markdown(doc)
    assert "[summary failed]" in md


def test_render_transcript_formats_speaker_and_timestamp():
    doc = MeetingDoc(
        started_at=datetime(2026, 5, 26, 14, 30, 0),
        duration_seconds=60,
        whisper_model="small",
        ollama_model="llama3.1:8b",
        summary="x",
        action_items=[],
        segments=[
            TaggedSegment(12_000, 17_000, "Hallo zusammen", "Me"),
            TaggedSegment(18_000, 22_000, "Hi Lukas", "Others"),
            TaggedSegment(3_725_000, 3_730_000, "Bis bald", "Me"),
        ],
    )
    md = render_markdown(doc)
    assert "**Me** (00:00:12): Hallo zusammen" in md
    assert "**Others** (00:00:18): Hi Lukas" in md
    assert "**Me** (01:02:05): Bis bald" in md
