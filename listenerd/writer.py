"""Render a meeting document to Markdown."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from listenerd.merge import TaggedSegment


@dataclass(frozen=True)
class MeetingDoc:
    started_at: datetime
    duration_seconds: int
    whisper_model: str
    ollama_model: str
    summary: Optional[str]            # None = Ollama failed
    action_items: list[str]
    segments: list[TaggedSegment]


def _format_hms(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def render_markdown(doc: MeetingDoc) -> str:
    lines: list[str] = []

    # Frontmatter
    lines.append("---")
    lines.append(f"date: {doc.started_at.isoformat(timespec='seconds')}")
    lines.append(f"duration: {_format_hms(doc.duration_seconds)}")
    lines.append("source: listenerd")
    lines.append(f"whisper_model: {doc.whisper_model}")
    lines.append(f"ollama_model: {doc.ollama_model}")
    lines.append("---")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    if doc.summary is None:
        lines.append("[summary failed]")
    else:
        lines.append(doc.summary.strip())
    lines.append("")

    # Action items
    lines.append("## Action Items")
    lines.append("")
    if not doc.action_items:
        lines.append("(none)")
    else:
        for item in doc.action_items:
            lines.append(f"- [ ] {item}")
    lines.append("")

    # Transcript
    lines.append("## Transcript")
    lines.append("")
    for seg in doc.segments:
        ts = _format_hms(seg.start_ms // 1000)
        lines.append(f"**{seg.speaker}** ({ts}): {seg.text}")

    return "\n".join(lines) + "\n"
