import os
import re
import time
import numpy as np
import torch
import threading
from collections import deque

os.environ.setdefault('HF_HUB_DISABLE_XET', '1')

from .config_loader import cfg
from .logger import log_message

VAD_SAMPLE_RATE = 16000
VAD_CHUNK_SAMPLES = 512

_vad_model = None
_asr_model = None
_vad_lock = threading.Lock()
_asr_lock = threading.Lock()

_TRANSCRIBE_REPO = "handy-computer/gigaam-v3-e2e-rnnt-gguf"
_TRANSCRIBE_FILE = "gigaam-v3-e2e-rnnt-Q8_0.gguf"


# ─── ЛЕНИВЫЙ ИМПОРТ TRANSCRIBE.CPP ASR ──────────────────────────────────────
# transcribe.cpp работает отдельным нативным процессом (ggml), модель GGUF
# (~274 МБ Q8_0) грузится только при первом распознавании, а не при старте.


def _get_vad():
    global _vad_model
    with _vad_lock:
        if _vad_model is None:
            try:
                model, _ = torch.hub.load(
                    repo_or_dir='snakers4/silero-vad',
                    model='silero_vad',
                    onnx=True,
                    force_onnx_cpu=True,
                    force_reload=False,
                    trust_repo=True,
                )
                if model is not None:
                    _vad_model = model
            except Exception as e:
                log_message(f"VAD ONNX не загрузился: {e}", "stt.py")
            if _vad_model is None:
                try:
                    log_message("VAD: фолбэк на JIT", "stt.py")
                    _vad_model, _ = torch.hub.load(
                        repo_or_dir='snakers4/silero-vad',
                        model='silero_vad',
                        force_reload=False,
                        trust_repo=True,
                    )
                    _vad_model.to(torch.device('cpu'))
                except Exception as e:
                    log_message(f"VAD JIT тоже не загрузился: {e}", "stt.py")
                    raise RuntimeError("Не удалось загрузить модель VAD") from e
        return _vad_model


def _get_asr():
    global _asr_model
    with _asr_lock:
        if _asr_model is None:
            import transcribe_cpp
            from huggingface_hub import hf_hub_download
            path = hf_hub_download(_TRANSCRIBE_REPO, _TRANSCRIBE_FILE)
            _asr_model = transcribe_cpp.Model(path)
            import gc
            gc.freeze()
        return _asr_model


_resample_cache = {}


def _resample(audio, orig_sr, target_sr):
    from scipy.signal import resample_poly
    key = (orig_sr, target_sr)
    if key not in _resample_cache:
        g = np.gcd(orig_sr, target_sr)
        _resample_cache[key] = (target_sr // g, orig_sr // g)
    up, down = _resample_cache[key]
    return resample_poly(audio, up, down, axis=0).astype(np.float32)


def _normalize_russian(text):
    if not text:
        return text
    return re.sub(r'\bstop\b', 'стоп', text.lower())


class SpeechListener:
    SPEECH_TIMEOUT_SEC = 8

    def __init__(self, sample_rate=16000, silence_threshold_ms=800,
                 min_speech_duration_ms=200, pre_recording_buffer_ms=300,
                 noise_gate_enabled=True, noise_gate_factor=2.5):

        self.sample_rate = sample_rate
        self.silence_threshold_ms = silence_threshold_ms
        self.min_speech_duration_ms = min_speech_duration_ms

        self.vad = _get_vad()
        self.asr = None  # лениво: грузим только при первом распознавании

        # Шумовой гейт: не пускаем в VAD тихий фон/музыку с колонок
        self.noise_gate_enabled = noise_gate_enabled
        self.noise_gate_factor = noise_gate_factor
        self.noise_floor_rms = 0.01
        self._noise_history = deque(maxlen=100)

        # Размер одного VAD-чанка в миллисекундах
        self.vad_chunk_ms = (VAD_CHUNK_SAMPLES * 1000) // VAD_SAMPLE_RATE
        self.silence_chunks_needed = int(silence_threshold_ms / self.vad_chunk_ms)

        # Буфер до начала речи (чтобы не терять начало фразы)
        pre_chunks = int(pre_recording_buffer_ms / self.vad_chunk_ms) + 1
        self.pre_buffer = deque(maxlen=pre_chunks)

        # Состояние распознавания
        self.speech_buffer = []
        self.silence_chunks = 0
        self.in_speech = False
        self.leftover_audio = np.array([], dtype=np.float32)

        # Периодический сброс VAD (каждые 30 сек)
        self._last_vad_reset = time.time()
        self._vad_reset_interval = 30
        self._speech_start_time = 0.0

        self._warmup_vad()

    def _warmup_vad(self):
        warmup = torch.zeros(VAD_CHUNK_SAMPLES, dtype=torch.float32)
        with torch.no_grad():
            for _ in range(3):
                self.vad(warmup, VAD_SAMPLE_RATE)
        self.vad.reset_states()

    def _reset_vad_state(self):
        with _vad_lock:
            self.vad.reset_states()
        self._last_vad_reset = time.time()

    def _reset_speech_state(self):
        self.speech_buffer = []
        self.silence_chunks = 0
        self.in_speech = False
        self._speech_start_time = 0.0

    # ─── шумовой гейт ──────────────────────────────────────────────────

    @staticmethod
    def _rms(chunk):
        return float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2) + 1e-12))

    def _update_noise_floor(self, rms):
        """Скользящий 10-й процентиль как оценка шумового фона."""
        self._noise_history.append(rms)
        if len(self._noise_history) >= 30:
            self.noise_floor_rms = max(
                float(np.percentile(self._noise_history, 10)),
                1e-6,
            )

    def _gate_passes(self, chunk):
        """True — чанк достаточно громкий, чтобы обрабатывать через VAD."""
        if not self.noise_gate_enabled:
            return True
        rms = self._rms(chunk)
        self._update_noise_floor(rms)
        return rms > self.noise_floor_rms * self.noise_gate_factor

    def _get_vad_prob(self, audio_chunk):
        if len(audio_chunk) != VAD_CHUNK_SAMPLES:
            return 0.0
        tensor = torch.from_numpy(audio_chunk).float()
        with _vad_lock:
            with torch.no_grad():
                prob = self.vad(tensor, VAD_SAMPLE_RATE).item()
        return prob

    def process_chunk(self, audio_chunk):
        """Обрабатываем кусок аудио. Возвращает (finalized, text)."""
        if len(audio_chunk) < 32:
            return False, None

        # Конвертируем в float
        if audio_chunk.dtype == np.int16:
            audio_float = audio_chunk.astype(np.float32) / 32767.0
        else:
            audio_float = audio_chunk.copy()

        # Ресемплинг если нужно
        if self.sample_rate != VAD_SAMPLE_RATE:
            audio_float = _resample(audio_float, self.sample_rate, VAD_SAMPLE_RATE)

        # Добавляем "хвост" с прошлого раза
        all_audio = np.concatenate([self.leftover_audio, audio_float])

        # Разбиваем на VAD-чанки
        num_chunks = len(all_audio) // VAD_CHUNK_SAMPLES
        leftover_idx = num_chunks * VAD_CHUNK_SAMPLES
        self.leftover_audio = all_audio[leftover_idx:].copy()

        finalized_text = None
        now = time.time()

        # Проверяем таймаут речи (если говорят слишком долго)
        if self.in_speech and self._speech_start_time > 0:
            if now - self._speech_start_time > self.SPEECH_TIMEOUT_SEC:
                log_message("VAD: таймаут речи, сброс", "stt.py")
                self._reset_speech_state()
                self._reset_vad_state()
                return False, None

        # Периодический сброс VAD
        if now - self._last_vad_reset > self._vad_reset_interval:
            self._reset_vad_state()

        # Обрабатываем каждый VAD-чанк
        for i in range(num_chunks):
            start = i * VAD_CHUNK_SAMPLES
            end = start + VAD_CHUNK_SAMPLES
            vad_chunk = all_audio[start:end]

            if self._gate_passes(vad_chunk):
                prob = self._get_vad_prob(vad_chunk)
                threshold = cfg.speech.vad_threshold_speech if self.in_speech else cfg.speech.vad_threshold_silence
                is_speech = prob > threshold
            else:
                is_speech = False

            if is_speech:
                self._handle_speech(vad_chunk)
            else:
                result = self._handle_silence(vad_chunk)
                if result is not None:
                    finalized_text = result

        if finalized_text is not None:
            return True, finalized_text
        return False, None

    def _handle_speech(self, chunk):
        """Обработка момента, когда есть речь."""
        if not self.in_speech:
            # Начало новой фразы — берём аудио из буфера
            self.in_speech = True
            self.speech_buffer = list(self.pre_buffer)
            self.silence_chunks = 0
            self._speech_start_time = time.time()

        self.speech_buffer.append(chunk.copy())
        self.silence_chunks = 0

        # Защита от переполнения буфера
        if len(self.speech_buffer) > 500:
            log_message("VAD: переполнение буфера, сброс", "stt.py")
            self._reset_speech_state()
            self._reset_vad_state()

    def _handle_silence(self, chunk):
        """Обработка момента тишины. Возвращает текст если фраза закончилась."""
        if not self.in_speech:
            self.pre_buffer.append(chunk.copy())
            return None

        # Тишина во время речи — считаем тишину
        self.silence_chunks += 1
        self.speech_buffer.append(chunk.copy())

        # Достаточно тишины — фраза закончилась
        if self.silence_chunks >= self.silence_chunks_needed:
            text = self._recognize()
            self._reset_speech_state()
            self._reset_vad_state()
            return text

        return None

    def _recognize(self):
        """Отправляем накопленное аудио на распознавание."""
        if len(self.speech_buffer) < 3:
            return None

        all_audio = np.concatenate(self.speech_buffer)
        duration_ms = len(all_audio) * 1000 / VAD_SAMPLE_RATE
        if duration_ms < self.min_speech_duration_ms:
            return None

        try:
            if self.asr is None:
                self.asr = _get_asr()
            t0 = time.time()
            with _asr_lock:
                with self.asr.session() as session:
                    result = session.run(all_audio, timestamps="none")
            elapsed = time.time() - t0
            if elapsed > 0.1:
                pass #невероятно сильно засоряет логи
                #log_message(f"ASR: {duration_ms:.0f} мс аудио распознано за {elapsed:.2f} с", "stt.py")
            text = result.text.strip() if result and result.text else None
            if text:
                return _normalize_russian(text)
            return None
        except Exception as e:
            log_message(f"Ошибка распознавания: {e}", "stt.py")
            return None

    def reset(self):
        self._reset_speech_state()
        self.pre_buffer.clear()
        self.leftover_audio = np.array([], dtype=np.float32)
        try:
            with _vad_lock:
                self.vad.reset_states()
            self._last_vad_reset = time.time()
        except Exception as e:
            log_message(f"Ошибка сброса VAD: {e}", "stt.py")
