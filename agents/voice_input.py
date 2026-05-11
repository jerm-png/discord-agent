import asyncio
import os
import shutil
import tempfile
from dotenv import load_dotenv
load_dotenv()

import discord
from elevenlabs import ElevenLabs
from faster_whisper import WhisperModel

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

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


def check_ffmpeg() -> None:
    """Checks whether FFmpeg is on the system PATH at startup."""
    path = shutil.which("ffmpeg")
    if path:
        print(f"[FFmpeg] Found at {path}")
    else:
        print(
            "[FFmpeg] WARNING: ffmpeg not found on PATH — "
            "TTS voice output will silently fail until FFmpeg "
            "is installed and added to PATH."
        )


async def speak_response(
    text: str, guild, channel=None, bot=None
) -> None:
    """
    Converts text to speech via ElevenLabs and plays it in
    the General voice channel. Requires FFmpeg on PATH.
    Silently skips if API keys are missing.
    """
    if not ELEVENLABS_API_KEY or not ELEVENLABS_VOICE_ID:
        return

    voice_channel = discord.utils.get(
        guild.voice_channels, name="General"
    )
    if not voice_channel:
        return

    tmp_path = None
    voice_client = None
    try:
        el_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        audio_iter = el_client.text_to_speech.convert(
            voice_id=ELEVENLABS_VOICE_ID,
            text=text,
            model_id="eleven_monolingual_v1",
        )
        with tempfile.NamedTemporaryFile(
            suffix=".mp3", delete=False
        ) as tmp:
            for chunk in audio_iter:
                tmp.write(chunk)
            tmp_path = tmp.name

        voice_client = discord.utils.get(
            bot.voice_clients, guild=guild
        ) if bot else None
        if voice_client is None:
            voice_client = await voice_channel.connect()
        elif voice_client.channel != voice_channel:
            await voice_client.move_to(voice_channel)

        source = discord.FFmpegPCMAudio(tmp_path)
        done = asyncio.Event()
        voice_client.play(source, after=lambda _: done.set())
        await done.wait()

    except Exception as e:
        if channel:
            await channel.send(
                "Voice response failed — "
                "text response above is complete."
            )
    finally:
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()
        # Fix temp file leak — always clean up the mp3
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
