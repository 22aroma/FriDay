import wave
import threading
import pyaudio
from .constants import AUDIO_CHUNK
from .logger import log_message

_pyaudio_instance = None
_pyaudio_lock = threading.Lock()

def _get_pyaudio():
    global _pyaudio_instance
    if _pyaudio_instance is None:
        with _pyaudio_lock:
            if _pyaudio_instance is None:
                _pyaudio_instance = pyaudio.PyAudio()
    return _pyaudio_instance

def cleanup_pyaudio():
    global _pyaudio_instance
    if not _pyaudio_lock.acquire(blocking=False):
        return
    try:
        if _pyaudio_instance is not None:
            try:
                _pyaudio_instance.terminate()
            except Exception as e:
                log_message(f"Ошибка при завершении PyAudio: {e}", "FriDay_say.py")
            _pyaudio_instance = None
    finally:
        _pyaudio_lock.release()

def FriDay_say_(directory):
    """Воспроизводит WAV-файл через PyAudio."""
    try:
        with wave.open(directory, 'rb') as wf:
            p = _get_pyaudio()
            stream = p.open(
                format=p.get_format_from_width(wf.getsampwidth()),
                channels=wf.getnchannels(),
                rate=wf.getframerate(),
                output=True
            )
            try:
                while len(data := wf.readframes(AUDIO_CHUNK)):
                    stream.write(data)
            finally:
                stream.close()
    except Exception as e:
        log_message(f"Ошибка воспроизведения: {e}", "FriDay_say.py")