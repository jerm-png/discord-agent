import os
import re
import tempfile

import numpy as np
import sounddevice as sd
import soundfile as sf
import whisper

SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SECONDS = 3.0
MAX_DURATION = 120.0
WAKE_WORD = "your move"

_model = None


def _get_model() -> whisper.Whisper:
    global _model
    if _model is None:
        _model = whisper.load_model("base")
    return _model


def _transcribe_chunk(audio_chunk: np.ndarray) -> str:
    """Writes a single chunk to a temp file, transcribes it, cleans up."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        sf.write(tmp_path, audio_chunk, SAMPLE_RATE)
        result = _get_model().transcribe(tmp_path)
        return result["text"].strip()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def listen_and_transcribe() -> str:
    """
    Records in CHUNK_SECONDS chunks, transcribing each with Whisper.
    Accumulates text across chunks and stops when the wake word
    "your move" is detected or MAX_DURATION seconds have elapsed.
    Returns all accumulated text with the wake word stripped out.
    """
    chunk_frames = int(SAMPLE_RATE * CHUNK_SECONDS)
    max_chunks = int(MAX_DURATION / CHUNK_SECONDS)

    accumulated = []
    print("Recording... say 'your move' when done")

    with sd.InputStream(
        samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32"
    ) as stream:
        for _ in range(max_chunks):
            chunk, _ = stream.read(chunk_frames)
            chunk_text = _transcribe_chunk(chunk.copy())

            if WAKE_WORD in chunk_text.lower():
                clean = re.sub(
                    r"your\s+move[.,!?]*", "", chunk_text, flags=re.IGNORECASE
                ).strip()
                if clean:
                    accumulated.append(clean)
                break

            if chunk_text:
                accumulated.append(chunk_text)

    return " ".join(accumulated).strip()


def test_voice_input() -> None:
    """Records using wake word detection and prints the transcription."""
    print("Voice input test — speak freely, then say 'your move' when finished.")
    text = listen_and_transcribe()
    print(f"Transcription: {text!r}")


if __name__ == "__main__":
    test_voice_input()
