# shellmind/voice/stt.py
import os
import tempfile
import logging
import numpy as np
import sounddevice as sd
import soundfile as sf
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

# Global model to avoid reloading
_model = None

def get_whisper_model():
    """Load Whisper model (base.en) once and reuse."""
    global _model
    if _model is None:
        logger.info("Loading Whisper model (this may take a few seconds)...")
        _model = WhisperModel("base.en", device="cpu", compute_type="int8")
    return _model

def record_audio_until_enter():
    """
    Record audio from microphone until user presses Enter.
    Returns path to temporary WAV file.
    """
    logger.info("Listening for audio input...")
    
    sample_rate = 16000  # Whisper expects 16kHz
    recording = []

    def audio_callback(indata, frames, time_info, status):
        if status:
            logger.warning(f"Audio warning: {status}")
        recording.append(indata.copy())

    # Start streaming input
    try:
        with sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            callback=audio_callback,
            blocksize=1024
        ):
            input()  # Wait for Enter keypress
    except KeyboardInterrupt:
        logger.info("Recording interrupted by user.")
        return None
    except Exception as e:
        logger.error(f"Error during recording: {e}")
        return None

    if not recording:
        logger.warning("No audio recorded.")
        return None

    # Combine chunks
    audio_data = np.concatenate(recording, axis=0)

    # Save to temp file
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
        sf.write(tmp_file.name, audio_data, sample_rate)
        logger.debug(f"Audio saved to temporary file: {tmp_file.name}")
        return tmp_file.name

def transcribe_from_microphone():
    """
    Record audio until Enter is pressed, then transcribe.
    Returns transcribed text or None on error.
    """
    try:
        # Record
        audio_path = record_audio_until_enter()
        if not audio_path:
            return None

        # Transcribe
        model = get_whisper_model()
        segments, _ = model.transcribe(audio_path, beam_size=5)
        text = "".join([segment.text for segment in segments]).strip()

        # Cleanup
        try:
            os.unlink(audio_path)
        except Exception as cleanup_error:
            logger.warning(f"Failed to clean up audio file: {cleanup_error}")

        if not text:
            logger.warning("No speech detected during transcription.")
            return None

        logger.info(f"Transcribed: \"{text}\"")
        return text

    except Exception as e:
        logger.error(f"Voice transcription failed: {e}")
        return None