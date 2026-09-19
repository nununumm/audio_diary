"""Text cleanup: turn a raw transcript into a readable diary entry.

Removes fillers ("えー", "あのー" ...) and rewrites vague / mumbled phrasing
into natural Japanese while preserving the speaker's intent and *without*
adding new information. Uses Gemini. Falls back to returning the raw text if
Gemini is not configured, so the app always works.
"""
from __future__ import annotations

from .config import Settings, get_settings

_CLEANUP_PROMPT = (
    "以下は音声日記の文字起こしです。次の方針で、読みやすい日記本文に整えてください。\n"
    "1. 「えー」「あのー」「まあ」などのフィラーや言い直しを取り除く。\n"
    "2. 曖昧・言葉足らずな表現は、話し手の意図を保ったまま自然な日本語に整える。\n"
    "3. 事実や内容を新しく足さない。書かれていないことを創作しない。\n"
    "4. 一人称の日記としてふさわしい、落ち着いた文体にする。\n"
    "整えた本文のみを出力してください（前置きや説明は不要）。\n\n"
    "--- 文字起こし ---\n{raw}"
)


class TextCleaner:
    """Cleans transcripts with Gemini, with a graceful no-op fallback."""

    def __init__(self, settings: Settings) -> None:
        self._client = None
        self._model = settings.gemini_model
        if settings.gemini_api_key:
            try:
                from google import genai

                self._client = genai.Client(api_key=settings.gemini_api_key)
            except Exception as exc:  # pragma: no cover
                print(f"[cleanup] Gemini init failed ({exc}); cleanup disabled.")

    def clean(self, raw_text: str) -> str:
        if not raw_text.strip():
            return ""
        if self._client is None:
            return raw_text  # no API key: keep raw text as the body
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=_CLEANUP_PROMPT.format(raw=raw_text),
            )
            cleaned = (response.text or "").strip()
            return cleaned or raw_text
        except Exception as exc:  # pragma: no cover - never lose the entry
            print(f"[cleanup] generation failed ({exc}); returning raw text.")
            return raw_text


_cleaner: TextCleaner | None = None


def get_cleaner() -> TextCleaner:
    global _cleaner
    if _cleaner is None:
        _cleaner = TextCleaner(get_settings())
    return _cleaner
