"""Merge two whisper transcripts (mic + system) into a chronological
Me/Others-tagged stream."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Speaker = Literal["Me", "Others"]

# whisper.cpp emits these meta-tokens on silent or non-speech audio. They
# clutter the transcript and confuse downstream summarizers, so drop them.
_NOISE_TOKEN_RE = re.compile(
    r"^\s*[\[\(](?:BLANK_AUDIO|silence|inaudible|music|applause|laughter)[\]\)]\s*$",
    re.IGNORECASE,
)

# Canonical hallucinations whisper-cpp produces on silent audio (e.g. when
# the system track captures nothing because Multi-Output Device isn't set
# up). Conservative list: only filter when the text matches one of these
# *exactly* — to avoid swallowing real "Thank you" lines in actual speech.
_HALLUCINATION_TEXTS = frozenset({
    "Thank you.",
    "Thanks for watching.",
    "Thank you for watching.",
    "Thanks for watching!",
    ".",
})


def _is_noise(text: str) -> bool:
    text = text.strip()
    if _NOISE_TOKEN_RE.match(text):
        return True
    if text in _HALLUCINATION_TEXTS:
        return True
    return False


@dataclass(frozen=True)
class Segment:
    """Whisper segment with millisecond offsets from recording start."""
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class TaggedSegment:
    start_ms: int
    end_ms: int
    text: str
    speaker: Speaker


def merge_segments(mic: list[Segment], system: list[Segment]) -> list[TaggedSegment]:
    """Merge mic and system segments chronologically.

    - mic segments are tagged "Me", system as "Others".
    - Ties on start_ms break with Me first (mic comes from this user).
    - Empty, whitespace-only, or whisper noise-token segments are dropped.
    """
    tagged: list[TaggedSegment] = []
    for seg in mic:
        text = seg.text.strip()
        if text and not _is_noise(text):
            tagged.append(TaggedSegment(seg.start_ms, seg.end_ms, text, "Me"))
    for seg in system:
        text = seg.text.strip()
        if text and not _is_noise(text):
            tagged.append(TaggedSegment(seg.start_ms, seg.end_ms, text, "Others"))

    # Stable sort: (start_ms, 0 for Me / 1 for Others) gives Me-first ties.
    tagged.sort(key=lambda s: (s.start_ms, 0 if s.speaker == "Me" else 1))
    return tagged
