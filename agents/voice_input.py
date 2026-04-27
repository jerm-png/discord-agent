import os
import tempfile

from faster_whisper import WhisperModel

_model = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel("small", device="cpu", compute_type="int8")
    return _model


def transcribe_attachment(audio_bytes: bytes, suffix: str = ".ogg") -> str:
    """
    Saves raw audio bytes to a temp file, transcribes with faster-whisper small,
    and returns the full transcription. Cleans up the temp file on exit.
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        segments, _ = _get_model().transcribe(tmp_path)
        return "".join(segment.text for segment in segments).strip()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
