"""Normalize recorded audio into a format the transcription provider accepts.

Browser MediaRecorder usually produces WebM/Opus (Chrome/Android) or MP4/AAC
(Safari). Gemini accepts wav/mp3/aac/ogg/flac but not WebM, so we remux/transcode
to OGG/Opus using ffmpeg when needed. If ffmpeg is not installed, we pass the
audio through unchanged (best effort) rather than failing.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

# MIME types Gemini can ingest directly (no conversion needed).
GEMINI_SUPPORTED = {
    "audio/wav",
    "audio/x-wav",
    "audio/mp3",
    "audio/mpeg",
    "audio/aiff",
    "audio/aac",
    "audio/ogg",
    "audio/flac",
}


def _base_mime(mime: str) -> str:
    return (mime or "").split(";")[0].strip().lower()


def _ffmpeg_to_ogg(data: bytes) -> bytes | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in"
        dst = Path(tmp) / "out.ogg"
        src.write_bytes(data)
        try:
            subprocess.run(
                [ffmpeg, "-y", "-i", str(src), "-vn", "-c:a", "libopus", str(dst)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
        except subprocess.CalledProcessError:
            return None
        return dst.read_bytes() if dst.exists() else None


def to_gemini_audio(data: bytes, mime: str) -> tuple[bytes, str]:
    """Return (bytes, mime_type) suitable for Gemini audio input."""
    base = _base_mime(mime)
    if base in GEMINI_SUPPORTED:
        return data, base
    converted = _ffmpeg_to_ogg(data)
    if converted is not None:
        return converted, "audio/ogg"
    # Fallback: send as-is with a best-guess mime. May fail if ffmpeg is
    # missing and the browser produced WebM; README documents installing ffmpeg.
    return data, base or "audio/ogg"
