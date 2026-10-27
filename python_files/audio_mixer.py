import threading
import time
from collections import deque

import numpy as np
import sounddevice as sd

# Если callback не вызывался дольше этого времени — считаем
# устройство вывода недоступным (смена динамиков/наушников,
# отключение мониторов) и пересоздаём поток.
_STREAM_DEAD_TIMEOUT = 3.0


def _resample(audio, orig_sr, target_sr):
    if orig_sr == target_sr:
        return audio
    import torch
    import torchaudio.functional as F
    t = torch.from_numpy(audio).float()
    return F.resample(t, orig_sr, target_sr).cpu().numpy()


class AudioMixer:
    SAMPLE_RATE = 48000

    def __init__(self):
        self._lock = threading.Lock()
        self._music_chunks = deque()
        self._music_offset = 0
        self._music_volume = 1.0
        self._tts_chunks = deque()
        self._tts_offset = 0
        self._stream = None
        self._stream_broken = False
        self._last_callback_time = time.time()
        self._watchdog = None
        self._closed = False

    def _log(self, message):
        from .logger import log_message
        log_message(message, "audio_mixer.py")

    def _open_stream(self):
        """Открываем поток вывода. В случае ошибки оставляем _stream = None."""
        try:
            stream = sd.OutputStream(
                samplerate=self.SAMPLE_RATE,
                channels=1,
                callback=self._callback,
                blocksize=1024,
            )
            stream.start()
            self._stream = stream
            self._stream_broken = False
            self._last_callback_time = time.time()
            self._log("Поток вывода открыт заново")
            return True
        except Exception as e:
            self._stream = None
            self._log(f"Ошибка потока вывода: {e}")
            return False

    def _ensure_stream(self):
        if self._stream is None and not self._closed:
            return self._open_stream()
        return self._stream is not None

    def _mark_broken(self):
        """Закрываем сломанный поток, чтобы его можно было пересоздать."""
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            self._stream_broken = True

    def _watchdog_loop(self):
        """Периодически проверяем, что поток вывода жив.

        Если callback давно не вызывался (устройство сменилось или
        мониторы отключились), закрываем старый поток и открываем новый.
        """
        while not self._closed:
            time.sleep(1.0)
            with self._lock:
                if self._closed:
                    return
                alive = (
                    self._stream is not None
                    and not self._stream_broken
                    and (time.time() - self._last_callback_time) < _STREAM_DEAD_TIMEOUT
                )
                need_reopen = self._stream is None or not alive
                # Есть ли что играть — чтобы не пересоздавать поток впустую
                has_audio = bool(self._music_chunks) or bool(self._tts_chunks)
            if need_reopen and has_audio:
                self._mark_broken()
                self._ensure_stream()

    def _ensure_watchdog(self):
        if self._watchdog is None or not self._watchdog.is_alive():
            self._watchdog = threading.Thread(target=self._watchdog_loop, daemon=True)
            self._watchdog.start()

    def _fill_buffer(self, chunks, offset, output, frames):
        """Копируем данные из буфера чанков в выходной массив."""
        written = 0
        while written < frames and chunks:
            chunk = chunks[0]
            available = len(chunk) - offset
            take = min(frames - written, available)
            output[written:written + take] = chunk[offset:offset + take]
            written += take
            offset += take
            if offset >= len(chunk):
                chunks.popleft()
                offset = 0
        return offset

    def _callback(self, outdata, frames, _time_info, status):
        with self._lock:
            self._last_callback_time = time.time()
            # Признак нестабильности устройства вывода (ошибка/остановка)
            if status and (status.output_underflow or status.input_overflow):
                self._stream_broken = True

        output = np.zeros(frames, dtype=np.float32)
        with self._lock:
            # Музыка с приглушением во время TTS
            volume = 0.15 if self._tts_chunks else self._music_volume
            if self._music_chunks:
                self._music_offset = self._fill_buffer(
                    self._music_chunks, self._music_offset, output, frames
                )
                output *= volume

            # TTS поверх музыки
            if self._tts_chunks:
                tts_buf = np.zeros(frames, dtype=np.float32)
                self._tts_offset = self._fill_buffer(
                    self._tts_chunks, self._tts_offset, tts_buf, frames
                )
                output += tts_buf

        outdata[:, 0] = output

    def play_music(self, audio, rate):
        self._ensure_stream()
        self._ensure_watchdog()
        audio = _resample(audio, rate, self.SAMPLE_RATE).astype(np.float32)
        with self._lock:
            self._music_chunks.clear()
            self._music_chunks.append(audio)
            self._music_offset = 0

    def append_music(self, audio, rate):
        audio = _resample(audio, rate, self.SAMPLE_RATE).astype(np.float32)
        with self._lock:
            self._music_chunks.append(audio)

    def play_tts(self, audio, rate):
        self._ensure_stream()
        self._ensure_watchdog()
        audio = _resample(audio, rate, self.SAMPLE_RATE).astype(np.float32)
        with self._lock:
            self._tts_chunks.clear()
            self._tts_chunks.append(audio)
            self._tts_offset = 0

    def stop_music(self):
        with self._lock:
            self._music_chunks.clear()
            self._music_offset = 0

    @property
    def music_playing(self):
        with self._lock:
            return bool(self._music_chunks)

    @property
    def tts_playing(self):
        with self._lock:
            return bool(self._tts_chunks)

    @property
    def music_volume(self):
        with self._lock:
            return self._music_volume

    @music_volume.setter
    def music_volume(self, vol):
        with self._lock:
            self._music_volume = max(0.0, min(1.0, vol))

    def close(self):
        self._closed = True
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
        self._stream = None


_mixer = AudioMixer()
