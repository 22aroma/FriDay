import os
import wave
import tempfile
import numpy as np
import torch
import threading
from collections import deque

from .logger import log_message

VAD_SAMPLE_RATE = 16000
VAD_CHUNK_SAMPLES = 512

_silero_vad = None
_kairos_asr = None
_vad_lock = threading.Lock()
_asr_lock = threading.Lock()


def _normalize_russian(text: str) -> str:
    if not text:
        return text
    
    text = text.lower()
    text = text.replace('stop', 'стоп')
    return text


def _get_vad():
    global _silero_vad
    with _vad_lock:
        if _silero_vad is None:
            log_message("Загружаем Silero VAD...", "stt.py")
            _silero_vad, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                trust_repo=True
            )
            _silero_vad.to(torch.device('cpu'))
            log_message("Silero VAD загружен", "stt.py")
        return _silero_vad


def _get_asr():
    global _kairos_asr
    with _asr_lock:
        if _kairos_asr is None:
            log_message("Загружаем Kairos ASR...", "stt.py")
            from kairos_asr import KairosASR
            _kairos_asr = KairosASR(device='cpu')
            log_message("Kairos ASR загружен", "stt.py")
        return _kairos_asr


def preload_models():
    _get_vad()
    _get_asr()


def _resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    import torchaudio
    
    audio_torch = torch.from_numpy(audio).float()
    if audio_torch.ndim == 1:
        audio_torch = audio_torch.unsqueeze(0)
    
    resampler = torchaudio.transforms.Resample(orig_freq=orig_sr, new_freq=target_sr)
    resampled = resampler(audio_torch)
    
    return resampled.squeeze().numpy()


class SpeechListener:
    def __init__(self, 
                 sample_rate: int = 16000,
                 silence_threshold_ms: int = 800,
                 min_speech_duration_ms: int = 200,
                 pre_recording_buffer_ms: int = 300):
        
        self.sample_rate = sample_rate
        self.silence_threshold_ms = silence_threshold_ms
        self.min_speech_duration_ms = min_speech_duration_ms
        
        self.vad = _get_vad()
        self.asr = _get_asr()
        
        self.vad_chunk_ms = (VAD_CHUNK_SAMPLES * 1000) // VAD_SAMPLE_RATE
        self.silence_chunks_threshold = int(silence_threshold_ms / self.vad_chunk_ms)
        
        pre_chunks = int(pre_recording_buffer_ms / self.vad_chunk_ms) + 1
        self.pre_buffer = deque(maxlen=pre_chunks)
        
        self.speech_buffer = []
        self.silence_chunks = 0
        self.in_speech = False
        
        self.leftover_audio = np.array([], dtype=np.float32)
        
        self._warmup_vad()
    
    def _warmup_vad(self):
        warmup_audio = np.zeros(VAD_CHUNK_SAMPLES, dtype=np.float32)
        warmup_tensor = torch.from_numpy(warmup_audio).float()
        with torch.no_grad():
            for _ in range(3):
                self.vad(warmup_tensor, VAD_SAMPLE_RATE)
        self.vad.reset_states()
    
    def _get_vad_prob(self, audio_float: np.ndarray) -> float:
        if len(audio_float) != VAD_CHUNK_SAMPLES:
            return 0.0
        
        audio_tensor = torch.from_numpy(audio_float).float()
        
        with torch.no_grad():
            prob = self.vad(audio_tensor, VAD_SAMPLE_RATE).item()
        
        return prob
    
    def process_chunk(self, audio_chunk: np.ndarray) -> tuple[bool, str | None]:
        if len(audio_chunk) < 32:
            return False, None
        
        if audio_chunk.dtype == np.int16:
            audio_float = audio_chunk.astype(np.float32) / 32768.0
        else:
            audio_float = audio_chunk.copy()
        
        if self.sample_rate != VAD_SAMPLE_RATE:
            audio_float = _resample(audio_float, self.sample_rate, VAD_SAMPLE_RATE)
        
        all_audio = np.concatenate([self.leftover_audio, audio_float])
        
        num_chunks = len(all_audio) // VAD_CHUNK_SAMPLES
        leftover_idx = num_chunks * VAD_CHUNK_SAMPLES
        self.leftover_audio = all_audio[leftover_idx:].copy()
        
        finalized_result = None
        
        for i in range(num_chunks):
            chunk_start = i * VAD_CHUNK_SAMPLES
            chunk_end = chunk_start + VAD_CHUNK_SAMPLES
            vad_chunk = all_audio[chunk_start:chunk_end]
            
            vad_prob = self._get_vad_prob(vad_chunk)
            
            if self.in_speech:
                is_speech_now = vad_prob > 0.3
            else:
                is_speech_now = vad_prob > 0.5
            
            if is_speech_now:
                if not self.in_speech:
                    self.in_speech = True
                    self.speech_buffer = list(self.pre_buffer)
                    self.silence_chunks = 0
                
                self.speech_buffer.append(vad_chunk.copy())
                self.silence_chunks = 0
            else:
                if self.in_speech:
                    self.silence_chunks += 1
                    self.speech_buffer.append(vad_chunk.copy())
                    
                    if self.silence_chunks >= self.silence_chunks_threshold:
                        text = self._finalize_and_recognize()
                        self.in_speech = False
                        self.speech_buffer = []
                        self.silence_chunks = 0
                        self.vad.reset_states()
                        
                        if text:
                            finalized_result = text.lower()
                else:
                    self.pre_buffer.append(vad_chunk.copy())
        
        return (True, finalized_result) if finalized_result is not None else (False, None)
    
    def _finalize_and_recognize(self) -> str | None:
        if len(self.speech_buffer) < 3:
            return None
        
        all_audio = np.concatenate(self.speech_buffer)
        
        duration_ms = len(all_audio) * 1000 / VAD_SAMPLE_RATE
        if duration_ms < self.min_speech_duration_ms:
            return None
        
        try:
            audio_int16 = (all_audio * 32767).astype(np.int16)
            
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp_path = tmp.name
            
            with wave.open(tmp_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(VAD_SAMPLE_RATE)
                wf.writeframes(audio_int16.tobytes())
            
            result = self.asr.transcribe(tmp_path)
            
            try:
                os.unlink(tmp_path)
            except Exception as e:
                log_message(f"Не удалось удалить временный файл {tmp_path}: {e}", "stt.py")

            text = result.full_text.strip() if result and result.full_text else None
            
            if text:
                text = _normalize_russian(text)
                return text
            
            return None
            
        except Exception as e:
            log_message(f"Ошибка распознавания: {e}", "stt.py")
            return None
    
    def reset(self):
        self.speech_buffer = []
        self.pre_buffer.clear()
        self.silence_chunks = 0
        self.in_speech = False
        self.leftover_audio = np.array([], dtype=np.float32)
        try:
            self.vad.reset_states()
        except Exception as e:
            log_message(f"Ошибка сброса VAD: {e}", "stt.py")
