"""
voice/processors/response.py — TTS response shaper.

Transforms LangGraph/SupportRuntime text responses into voice-appropriate text
BEFORE they reach TTS. Applies:
  - Strip markdown (bullets, headers, bold/italic)
  - Trim to 1-2 sentences for voice
  - Remove email sign-offs
  - Normalize whitespace

This runs BEFORE TTS so voice output is always concise and natural.
The chat channel is unaffected — shaping only happens here, in the voice path.
"""
from __future__ import annotations

import re
from typing import Optional


# Patterns to strip from voice output
_MARKDOWN_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MARKDOWN_ITALIC = re.compile(r"\*(.+?)\*")
_MARKDOWN_CODE = re.compile(r"`(.+?)`")
_MARKDOWN_HEADER = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MARKDOWN_BULLETS = re.compile(r"^\s*[-*•]\s+", re.MULTILINE)
_MARKDOWN_NUMBERED = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)

_EMAIL_SIGNOFFS = (
    "best regards",
    "regards,",
    "warm regards",
    "sincerely,",
    "thank you for your understanding",
    "thanks for your patience",
    "kind regards",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def shape_for_voice(text: str, max_sentences: int = 2) -> str:
    """
    Shape text for voice/TTS output.

    Args:
        text: Raw text from SupportRuntime / LangGraph.
        max_sentences: Maximum number of sentences to keep (default 2).

    Returns:
        Voice-appropriate text: concise, no markdown, no sign-offs.
    """
    if not text:
        return ""

    # Strip markdown formatting (keep content)
    text = _MARKDOWN_HEADER.sub("", text)
    text = _MARKDOWN_BOLD.sub(r"\1", text)
    text = _MARKDOWN_ITALIC.sub(r"\1", text)
    text = _MARKDOWN_CODE.sub(r"\1", text)

    # Convert bullet/numbered lists to sentences
    text = _MARKDOWN_BULLETS.sub("", text)
    text = _MARKDOWN_NUMBERED.sub("", text)

    # Split into lines, drop sign-offs
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    lines = [
        ln for ln in lines
        if not any(ln.lower().startswith(s) for s in _EMAIL_SIGNOFFS)
    ]
    text = " ".join(lines)

    # Also strip trailing sign-off sentences (e.g. "Sure. Best regards, team.")
    # Split by sentence boundary and drop sign-off sentences
    sentences_raw = _SENTENCE_SPLIT.split(text)
    sentences_raw = [
        s for s in sentences_raw
        if not any(s.strip().lower().startswith(sig) for sig in _EMAIL_SIGNOFFS)
    ]
    text = " ".join(sentences_raw)

    # Trim to max_sentences
    sentences = _SENTENCE_SPLIT.split(text)
    if len(sentences) > max_sentences:
        text = " ".join(sentences[:max_sentences])
        # Ensure ends with punctuation
        if text and text[-1] not in ".!?":
            text = text + "."

    return text.strip()


def is_voice_appropriate(text: str, max_chars: int = 500) -> bool:
    """Check if text is within acceptable length for voice output."""
    return bool(text) and len(text) <= max_chars
