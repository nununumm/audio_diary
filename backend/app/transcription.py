"""Speech-to-text: turn recorded audio into a verbatim transcript.

The provider is pluggable (chosen via DIARY_TRANSCRIBER):
  - "gemini"     : Gemini multimodal audio input (only needs GEMINI_API_KEY)
  - "google_stt" : Google Cloud Speech-to-Text (needs google-cloud-speech +
                   GOOGLE_APPLICATION_CREDENTIALS)

If no credentials are configured, a Mock transcriber is used so the app runs
end-to-end during development.
"""
from __future__ import annotations

from typing import Protocol

from .config import Settings, get_settings

# Ask for a faithful, verbatim transcript. Cleanup happens in a separate step
# (cleanup.py) so we keep both the raw and the polished versions.
_TRANSCRIBE_PROMPT = (
    "あなたは日本語の文字起こしエンジンです。"
    "この音声を、話された通りに正確に文字起こししてください。"
    "「えー」「あのー」などのフィラーや言い直しもそのまま残してください。"
    "推測で内容を補ったり要約したりしないでください。"
    "文字起こしの本文のみを出力してください。"
)


class Transcriber(Protocol):
    def transcribe(self, audio: bytes, mime_type: str) -> str: ...


class MockTranscriber:
    """Fallback used when no provider is configured. Lets the app run."""

    def transcribe(self, audio: bytes, mime_type: str) -> str:  # noqa: ARG002
        return (
            "（文字起こし未設定のためのサンプルです。GEMINI_API_KEY を設定すると"
            "実際の音声が文字起こしされます。）"
        )


class GeminiTranscriber:
    def __init__(self, settings: Settings) -> None:
        from google import genai  # imported lazily so the dep is optional

        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model

    def transcribe(self, audio: bytes, mime_type: str) -> str:
        from google.genai import types

        from .audio import to_gemini_audio

        data, mime = to_gemini_audio(audio, mime_type)
        response = self._client.models.generate_content(
            model=self._model,
            contents=[
                _TRANSCRIBE_PROMPT,
                types.Part.from_bytes(data=data, mime_type=mime),
            ],
        )
        return (response.text or "").strip()


class GoogleSttTranscriber:
    def __init__(self, settings: Settings) -> None:
        from google.cloud import speech  # optional dependency

        self._speech = speech
        self._client = speech.SpeechClient()
        self._language = settings.stt_language

    def transcribe(self, audio: bytes, mime_type: str) -> str:  # noqa: ARG002
        speech = self._speech
        config = speech.RecognitionConfig(
            # WEBM_OPUS covers what browser MediaRecorder produces by default.
            encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
            language_code=self._language,
            enable_automatic_punctuation=True,
        )
        audio_msg = speech.RecognitionAudio(content=audio)
        result = self._client.recognize(config=config, audio=audio_msg)
        return " ".join(
            r.alternatives[0].transcript for r in result.results if r.alternatives
        ).strip()


_transcriber: Transcriber | None = None


def _build_transcriber() -> Transcriber:
    settings = get_settings()
    try:
        if settings.transcriber == "google_stt":
            return GoogleSttTranscriber(settings)
        if settings.transcriber == "gemini" and settings.gemini_api_key:
            return GeminiTranscriber(settings)
    except Exception as exc:  # pragma: no cover - defensive fallback
        print(f"[transcription] provider init failed ({exc}); using mock.")
    return MockTranscriber()


def get_transcriber() -> Transcriber:
    global _transcriber
    if _transcriber is None:
        _transcriber = _build_transcriber()
    return _transcriber
