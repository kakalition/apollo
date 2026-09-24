"""Voice in (STT) and out (TTS), both optional and config-gated.

Default STT is local ``faster-whisper`` (opt-in extra). If it is not installed we
reply that voice is unsupported rather than failing. TTS is best-effort and used
only when ``/settings briefing=voice|both``.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from apollo.observability import get_logger
from apollo.telegram.api import TelegramAPI

log = get_logger("apollo.telegram.voice")


@lru_cache(maxsize=1)
def stt_available() -> bool:
    try:
        import faster_whisper  # noqa: F401  # pyright: ignore[reportMissingImports]
    except Exception:
        return False
    return True


@lru_cache(maxsize=1)
def _whisper_model() -> Any | None:
    if not stt_available():
        return None
    from faster_whisper import WhisperModel  # pyright: ignore[reportMissingImports]

    return WhisperModel("base", device="cpu", compute_type="int8")


def transcribe_bytes(audio: bytes, *, suffix: str = ".oga") -> str | None:
    model = _whisper_model()
    if model is None:
        return None
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(audio)
        path = Path(handle.name)
    try:
        segments, _info = model.transcribe(str(path))
        return " ".join(segment.text.strip() for segment in segments).strip()
    finally:
        path.unlink(missing_ok=True)


async def transcribe_voice(api: TelegramAPI, file_id: str) -> str | None:
    if not stt_available():
        return None
    file = await api.get_file(file_id)
    if not file.file_path:
        return None
    audio = await api.download_file(file.file_path)
    return transcribe_bytes(audio)


def tts_available() -> bool:
    return shutil.which("say") is not None and shutil.which("ffmpeg") is not None


def synthesize_ogg(text: str) -> bytes | None:
    """macOS ``say`` + ffmpeg → OGG/Opus. Returns None when unavailable."""
    if not tts_available():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        aiff = Path(tmp) / "speech.aiff"
        ogg = Path(tmp) / "speech.ogg"
        try:
            subprocess.run(["say", "-o", str(aiff), text], check=True, capture_output=True)
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(aiff), "-c:a", "libopus", "-b:a", "32k", str(ogg)],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:  # pragma: no cover - host specific
            log.warning("voice.tts_failed", error=str(exc))
            return None
        return ogg.read_bytes()
