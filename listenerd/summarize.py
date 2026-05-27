"""Generate summary + action items via local Ollama."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from listenerd.merge import TaggedSegment

# The local Ollama HTTP API. We use this instead of the `ollama run` CLI
# because the CLI wraps output at the terminal width and overwrites with
# ANSI cursor codes — the wrapping injects line breaks mid-word that
# survive even after stripping the escape codes ("Mod\nModell"). The HTTP
# API returns clean, unwrapped text.
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_GENERATE_TIMEOUT_S = 300


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


def _call_ollama(model: str, prompt: str) -> tuple[str | None, str | None]:
    """POST to /api/generate. Returns (response_text, error)."""
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_GENERATE_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return None, f"ollama HTTP error: {e}"
    except (OSError, json.JSONDecodeError) as e:
        return None, f"ollama response error: {e}"

    text = data.get("response")
    if not isinstance(text, str):
        return None, "ollama returned no 'response' field"
    return text, None


def summarize(segments: list[TaggedSegment], *, model: str) -> SummaryResult:
    prompt = PROMPT_TEMPLATE.format(transcript=format_transcript_for_prompt(segments))
    response, err = _call_ollama(model, prompt)
    if err is not None:
        return SummaryResult(summary=None, action_items=[], error=err)

    return parse_ollama_response(_strip_ansi(response))
