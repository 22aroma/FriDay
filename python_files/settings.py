import sys
import time
import threading

from .constants import BASE_DIR, SAMPLE_RATE, CHUNK
from .logger import log_message

_pyaudio = None
_listener = None
_listener_lock = threading.Lock()

_p = None
_stream = None


def _import_pyaudio():
    global _pyaudio
    if _pyaudio is None:
        import pyaudio
        _pyaudio = pyaudio
    return _pyaudio


def get_speech_listener():
    """Возвращает (лениво загружая) экземпляр SpeechListener."""
    global _listener
    with _listener_lock:
        if _listener is None:
            from .stt import SpeechListener
            log_message("Инициализация SpeechListener (VAD + KairosASR)...", "settings.py")
            _listener = SpeechListener(
                sample_rate=SAMPLE_RATE,
                silence_threshold_ms=400,
                min_speech_duration_ms=150,
                pre_recording_buffer_ms=200
            )
            log_message("SpeechListener инициализирован", "settings.py")
    return _listener


def get_settings():
    """Инициализирует и возвращает все необходимые компоненты для работы с аудио."""
    log_message("get_settings(): старт инициализации аудио", "settings.py")

    pyaudio = _import_pyaudio()

    global _p, _stream
    _p = pyaudio.PyAudio()

    stream_params = {
        'format': pyaudio.paInt16,
        'channels': 1,
        'rate': SAMPLE_RATE,
        'input': True,
        'frames_per_buffer': CHUNK,
    }

    _stream = None
    for attempt in range(3):
        try:
            _stream = _p.open(**stream_params)
            log_message("get_settings(): аудио-поток успешно открыт", "settings.py")
            break
        except Exception as e:
            log_message(f"get_settings(): попытка {attempt+1} открыть поток не удалась: {e}", "settings.py")
            if attempt < 2:
                time.sleep(1)
            else:
                raise

    if _stream is None:
        raise RuntimeError("Не удалось открыть аудио-поток после 3 попыток")

    listener = get_speech_listener()

    log_message("get_settings(): инициализация завершена, возвращаем объекты", "settings.py")
    return CHUNK, SAMPLE_RATE, listener, _p, _stream


def cleanup():
    global _p, _stream
    try:
        if _stream is not None:
            _stream.stop_stream()
            _stream.close()
    except Exception as e:
        log_message(f"Ошибка закрытия аудио-потока: {e}", "settings.py")
    try:
        if _p is not None:
            _p.terminate()
    except Exception as e:
        log_message(f"Ошибка завершения PyAudio: {e}", "settings.py")
    _p = None
    _stream = None
