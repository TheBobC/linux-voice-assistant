"""
Filter out Whisper hallucinations before sending transcripts to Jarvis.
No-speech prob is not available at this layer, so we use pattern matching
and repetition detection.
"""

import re
from typing import Optional, Tuple

# Common Whisper hallucination phrases triggered by ambient noise / TV
HALLUCINATION_PATTERNS = [
    r"^thanks? for watching",
    r"^thank you for watching",
    r"^please subscribe",
    r"^don'?t forget to like",
    r"^this is the first time i'?ve ever",
    r"^i'?ve never seen (anything|this) like",
    r"^wow,?\s+that'?s",
    r"^\[.*\]$",           # [Music], [Applause], [Laughter], etc.
    r"^\.+$",              # Just ellipsis/periods
    r"^the end\.?$",
    r"^bye[- ]?bye",
    r"^see you next time",
    r"^subtitles? by",
    r"^captioned? by",
    r"^amara\.org",
    r"^www\.",
    r"^http",
    r"^\(.*\)$",           # (inaudible), (music), etc.
]

_compiled = [re.compile(p, re.IGNORECASE) for p in HALLUCINATION_PATTERNS]

MIN_WORDS = 2


def is_hallucination(transcript: str) -> Tuple[bool, str]:
    """
    Returns (True, reason) if the transcript looks like a Whisper hallucination.
    """
    text = transcript.strip()

    if not text:
        return True, "empty"

    words = text.split()
    if len(words) < MIN_WORDS:
        return True, f"too short ({len(words)} word)"

    for pattern in _compiled:
        if pattern.search(text):
            return True, "hallucination pattern"

    # Repetition check: first half == second half (Whisper looping)
    if len(words) >= 8:
        half = len(words) // 2
        if " ".join(words[:half]) == " ".join(words[half : half * 2]):
            return True, "repetitive content"

    return False, "ok"


def filter_transcript(transcript: str, log_prefix: str = "[TRANSCRIPT_FILTER]") -> Optional[str]:
    """
    Returns the transcript unchanged if valid, or None if it should be discarded.
    """
    bad, reason = is_hallucination(transcript)
    if bad:
        print(f"{log_prefix} Discarding: '{transcript[:60]}' — {reason}")
        return None
    return transcript
