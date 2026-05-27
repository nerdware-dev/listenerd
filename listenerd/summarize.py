"""Generate summary + action items via local Ollama."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from listenerd.merge import TaggedSegment


PROMPT_TEMPLATE = """\
You are a meeting note-taker. Two speakers are present in the transcript:
"Me" (the user) and "Others" (everyone else).

Rules:
- Detect the dominant language of the transcript and write the entire output
  in that same language (German if German dominates, English if English).
- Be concrete. Quote decisions, numbers, names, deadlines verbatim. Skip
  small talk and filler.
- Action items must name the owner ("Me" or "Others") and what concretely to
  do. If unclear, omit — do not invent.
- If the transcript is too short or empty to summarize, say so in one line
  and write "(none)" for action items. Do not fabricate.

Output in this exact format (do not translate the section headers):

SUMMARY:
<3-5 sentences, in the transcript's dominant language>

ACTION_ITEMS:
- <owner>: <what>
- ...

If there are no action items, write "(none)" on the line after ACTION_ITEMS:.

Transcript:
{transcript}
"""


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07")


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences. Ollama leaks cursor/progress codes even
    without a TTY in some versions."""
    return _ANSI_RE.sub("", text)


@dataclass(frozen=True)
class SummaryResult:
    summary: Optional[str]              # None if Ollama failed
    action_items: list[str] = field(default_factory=list)
    error: Optional[str] = None


def format_transcript_for_prompt(segments: list[TaggedSegment]) -> str:
    return "\n".join(f"{seg.speaker}: {seg.text}" for seg in segments)


def parse_ollama_response(response: str) -> SummaryResult:
    summary_match = re.search(
        r"SUMMARY:\s*(.+?)(?:\n\s*ACTION_ITEMS:|$)",
        response,
        re.DOTALL,
    )
    actions_match = re.search(r"ACTION_ITEMS:\s*(.+?)$", response, re.DOTALL)

    summary = summary_match.group(1).strip() if summary_match else None

    action_items: list[str] = []
    if actions_match:
        for line in actions_match.group(1).splitlines():
            line = line.strip()
            if not line or line == "(none)":
                continue
            if line.startswith("- "):
                action_items.append(line[2:].strip())
            elif line.startswith("-"):
                action_items.append(line[1:].strip())

    return SummaryResult(
        summary=summary,
        action_items=action_items,
        error=None if summary is not None else "could not parse Ollama response",
    )


def summarize(segments: list[TaggedSegment], *, model: str) -> SummaryResult:
    prompt = PROMPT_TEMPLATE.format(transcript=format_transcript_for_prompt(segments))

    result = subprocess.run(
        ["ollama", "run", model],
        input=prompt,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return SummaryResult(
            summary=None,
            action_items=[],
            error=result.stderr.strip() or "ollama exited non-zero",
        )

    parsed = parse_ollama_response(_strip_ansi(result.stdout))
    return parsed
