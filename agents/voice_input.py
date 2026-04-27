import asyncio
import os
import re
import tempfile
import threading
import time

import numpy as np
import scipy.signal
import soundfile as sf
import whisper
import discord.ext.voice_recv as voice_recv

# Discord decodes Opus to 48 kHz stereo int16; Whisper wants 16 kHz mono float32
DISCORD_SAMPLE_RATE = 48000
DISCORD_CHANNELS = 2
WHISPER_SAMPLE_RATE = 16000

# Seconds of no incoming packets = end of utterance (Discord's client-side VAD
# means packets only arrive while the user is actively speaking)
SILENCE_TIMEOUT = 1.0

# Hard cap: abandon and return whatever was captured after this many seconds
MAX_UTTERANCE_SECONDS = 120.0

WAKE_WORD = "your move"

_model = None


def _get_model() -> whisper.Whisper:
    global _model
    if _model is None:
        _model = whisper.load_model("small")
    return _model


def _pcm_to_float_mono(pcm_bytes: bytes) -> np.ndarray:
    """Discord PCM (48 kHz stereo int16) -> Whisper float32 16 kHz mono."""
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    audio = audio.reshape(-1, DISCORD_CHANNELS).mean(axis=1)
    return scipy.signal.resample_poly(audio, 1, 3).astype(np.float32)


def _transcribe(audio: np.ndarray) -> str:
    """Writes float32 16 kHz mono to a temp wav and returns Whisper's transcription."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        sf.write(tmp_path, audio, WHISPER_SAMPLE_RATE)
        result = _get_model().transcribe(tmp_path)
        return result["text"].strip()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


class WhisperSink(voice_recv.AudioSink):
    """
    Buffers raw PCM from a single Discord user (the owner).
    write() is called from the audio-receive thread, so all buffer
    access is guarded by a lock.
    """

    def __init__(self, owner_id: int):
        super().__init__()
        self._owner_id = owner_id
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._last_packet: float = 0.0

    def wants_opus(self) -> bool:
        return False

    def write(self, user, data: voice_recv.VoiceData) -> None:
        if user is None or user.id != self._owner_id:
            return
        with self._lock:
            self._buffer.extend(data.pcm)
        self._last_packet = time.monotonic()

    def cleanup(self) -> None:
        with self._lock:
            self._buffer.clear()

    def flush(self) -> bytes:
        """Returns all buffered PCM and resets state ready for the next utterance."""
        with self._lock:
            pcm = bytes(self._buffer)
            self._buffer.clear()
            self._last_packet = 0.0
        return pcm

    @property
    def last_packet(self) -> float:
        return self._last_packet

    @property
    def has_audio(self) -> bool:
        with self._lock:
            return bool(self._buffer)


async def transcribe_utterance(sink: WhisperSink) -> str:
    """
    Waits until the owner speaks, then waits for them to stop
    (SILENCE_TIMEOUT seconds with no incoming packets), then
    transcribes the whole utterance in one Whisper pass.

    Discord's client-side VAD means packets only arrive while the
    user is actively speaking — packet gaps are real silence, not
    custom thresholds.

    Strips the wake word if present. Returns empty string on timeout
    with no audio captured.
    """
    deadline = time.monotonic() + MAX_UTTERANCE_SECONDS

    # Wait for the owner to start speaking
    while sink.last_packet == 0.0:
        if time.monotonic() > deadline:
            return ""
        await asyncio.sleep(0.05)

    # Collect until SILENCE_TIMEOUT with no new packets, or hard deadline
    while True:
        if time.monotonic() > deadline:
            break
        await asyncio.sleep(0.1)
        if sink.has_audio and time.monotonic() - sink.last_packet >= SILENCE_TIMEOUT:
            break

    raw_pcm = sink.flush()
    if not raw_pcm:
        return ""

    loop = asyncio.get_running_loop()
    audio = _pcm_to_float_mono(raw_pcm)
    text = await loop.run_in_executor(None, _transcribe, audio)

    if WAKE_WORD in text.lower():
        text = re.sub(r"your\s+move[.,!?]*", "", text, flags=re.IGNORECASE).strip()

    return text
