import os
import tempfile

import numpy as np
import sounddevice as sd
import soundfile as sf
import whisper

SAMPLE_RATE = 16000
CHANNELS = 1
MAX_DURATION = 10.0
SILENCE_DURATION = 1.5
SILENCE_THRESHOLD = 0.01  # RMS amplitude — tune up if mic is noisy
CHUNK_SECONDS = 0.1
MIN_RECORD_SECONDS = 1.0  # don't trigger silence cutoff before this

_model = None


def _get_model() -> whisper.Whisper:
    global _model
    if _model is None:
        _model = whisper.load_model("base")
    return _model


def listen_and_transcribe() -> str:
    """
    Records from the default microphone and returns Whisper's transcription.
    Stops early after SILENCE_DURATION seconds of audio below SILENCE_THRESHOLD,
    but records at least MIN_RECORD_SECONDS before the silence check activates.
    """
    chunk_frames = int(SAMPLE_RATE * CHUNK_SECONDS)
    max_chunks = int(MAX_DURATION / CHUNK_SECONDS)
    silence_chunks_needed = int(SILENCE_DURATION / CHUNK_SECONDS)
    min_chunks = int(MIN_RECORD_SECONDS / CHUNK_SECONDS)

    recorded = []
    silence_count = 0

    print("Listening... (speak now)")

    with sd.InputStream(
        samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32"
    ) as stream:
        for i in range(max_chunks):
            chunk, _ = stream.read(chunk_frames)
            recorded.append(chunk.copy())

            if i >= min_chunks:
                rms = float(np.sqrt(np.mean(chunk ** 2)))
                if rms < SILENCE_THRESHOLD:
                    silence_count += 1
                    if silence_count >= silence_chunks_needed:
                        break
                else:
                    silence_count = 0

    audio = np.concatenate(recorded, axis=0)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        sf.write(tmp_path, audio, SAMPLE_RATE)
        result = _get_model().transcribe(tmp_path)
        return result["text"].strip()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_voice_input() -> None:
    """Records once and prints the transcription."""
    print("Voice input test — recording once.")
    text = listen_and_transcribe()
    print(f"Transcription: {text!r}")


if __name__ == "__main__":
    test_voice_input()
