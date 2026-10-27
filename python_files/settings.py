import time
import threading
import sounddevice as sd

from .constants import SAMPLE_RATE, CHUNK
from .config_loader import cfg
from .logger import log_message

_listener = None
_listener_lock = threading.Lock()

_stream = None
_stream_lock = threading.Lock()


def _open_stream():
    """Пытаемся открыть аудио-поток, 3 попытки."""
    for attempt in range(3):
        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype='int16',
                blocksize=CHUNK,
            )
            stream.start()
            log_message(f"Аудио-поток открыт (попытка {attempt + 1})", "settings.py")
            return stream
        except Exception as e:
            log_message(f"Попытка {attempt + 1} не удалась: {e}", "settings.py")
            if attempt < 2:
                time.sleep(1)
    return None


def get_speech_listener():
    global _listener
    with _listener_lock:
        if _listener is not None:
            return _listener
        from .stt import SpeechListener
        log_message("Инициализация SpeechListener...", "settings.py")
        _listener = SpeechListener(
            sample_rate=SAMPLE_RATE,
            silence_threshold_ms=cfg.speech.silence_threshold_ms,
            min_speech_duration_ms=cfg.speech.min_speech_duration_ms,
            pre_recording_buffer_ms=cfg.speech.pre_recording_buffer_ms,
            noise_gate_enabled=cfg.speech.noise_gate_enabled,
            noise_gate_factor=cfg.speech.noise_gate_factor,
        )
        log_message("SpeechListener готов", "settings.py")
        return _listener


def get_settings():
    global _stream
    log_message("Инициализация аудио...", "settings.py")

    with _stream_lock:
        if _stream is None:
            _stream = _open_stream()
        if _stream is None:
            raise RuntimeError("Не удалось открыть аудио-поток")

    listener = get_speech_listener()
    log_message("Инициализация завершена", "settings.py")
    return {"chunk": CHUNK, "sample_rate": SAMPLE_RATE, "listener": listener, "stream": _stream}


def cleanup():
    global _stream
    with _stream_lock:
        if _stream is not None:
            try:
                _stream.stop()
                _stream.close()
            except Exception as e:
                log_message(f"Ошибка закрытия потока: {e}", "settings.py")
        _stream = None


def safe_read(stream, chunk):
    """Читаем данные из потока. Если ошибка — пересоздаём поток.

    Принимает текущий объект потока, но в случае сбоя пересоздаёт
    поток внутри settings и возвращает новые данные вместе с флагом
    того, что поток был пересоздан (для повторного чтения).
    """
    global _stream
    for attempt in range(2):
        if stream is None:
            raise RuntimeError("Аудио-поток не инициализирован")
        try:
            data, overflowed = stream.read(chunk)
            return data, overflowed
        except Exception as e:
            log_message(f"Ошибка чтения (попытка {attempt + 1}): {e}", "settings.py")
            _recreate_stream()
            # Читаем данные уже из нового потока
            with _stream_lock:
                stream = _stream
            if stream is None:
                raise
            time.sleep(0.1)
    raise RuntimeError("Не удалось прочитать аудио после пересоздания потока")


def _recreate_stream():
    global _stream
    with _stream_lock:
        if _stream is not None:
            try:
                _stream.stop()
                _stream.close()
            except Exception:
                pass
        _stream = _open_stream()
