import os
os.environ['TORCH_HUB_NO_INTERACTION'] = '1'

import sounddevice as sd
import torch
import time
import threading
from .constants import TTS_LANGUAGE, TTS_MODEL_ID, TTS_SAMPLE_RATE, TTS_SPEAKER
from .logger import log_message

# Глобальная переменная для модели (ленивая загрузка)
_model = None
_model_loading = False

# Флаг для отслеживания текущего воспроизведения
_playing = False
_play_thread = None

def _load_model():
    """Загружает TTS модель при первом использовании (ленивая загрузка)."""
    global _model, _model_loading
    
    if _model is not None:
        return _model
    
    if _model_loading:
        # Если модель уже загружается, ждем
        while _model_loading:
            time.sleep(0.1)
        return _model
    
    _model_loading = True
    try:
        # Ограничиваем использование потоков для экономии памяти
        torch.set_num_threads(1)
        
        # Для Silero TTS torch.hub.load возвращает кортеж (model, sample_rate)
        result = torch.hub.load(
            repo_or_dir='snakers4/silero-models',
            model='silero_tts',
            language=TTS_LANGUAGE,
            speaker=TTS_MODEL_ID,
            trust_repo=True
        )
        
        # Извлекаем модель из кортежа
        if isinstance(result, tuple):
            model = result[0]
        else:
            model = result
        
        if model is None or not hasattr(model, 'apply_tts'):
            log_message(f"Ошибка: модель не загружена или не имеет метода apply_tts", "tts.py")
            _model = None
        else:
            # Перемещаем модель на CPU
            try:
                moved_model = model.to(torch.device('cpu'))
                # Если model.to() вернул None (модель уже на CPU), используем оригинальную модель
                _model = moved_model if moved_model is not None else model
                # Освобождаем память
                if hasattr(model, 'cpu'):
                    del model
                import gc
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception as e:
                log_message(f"Ошибка при перемещении модели на CPU: {e}", "tts.py")
                _model = model
    except Exception as e:
        log_message(f"Ошибка загрузки TTS модели: {e}", "tts.py")
        _model = None
    finally:
        _model_loading = False
    
    return _model

def _play_audio(audio, sample_rate):
    """Воспроизводит аудио в отдельном потоке."""
    global _playing
    _playing = True
    try:
        sd.play(audio, sample_rate)
        sd.wait()  # Ждём окончания воспроизведения
    except Exception as e:
        log_message(f"Ошибка воспроизведения аудио: {e}", "tts.py")
    finally:
        _playing = False

def speak(text: str) -> None:
    """Озвучивает переданный текст с помощью Silero TTS (неблокирующий)."""
    global _play_thread, _playing
    
    try:
        model = _load_model()
        if model is None:
            return
        
        with torch.inference_mode():
            audio = model.apply_tts(
                text=text,
                speaker=TTS_SPEAKER,
                sample_rate=TTS_SAMPLE_RATE,
                put_accent=True,
                put_yo=True,
                put_stress_homo=True,
                put_yo_homo=True
            )
        
        # Если предыдущее воспроизведение ещё идёт, прерываем его
        if _playing and _play_thread and _play_thread.is_alive():
            sd.stop()
            _play_thread.join(timeout=0.1)
        
        # Запускаем воспроизведение в отдельном потоке
        _play_thread = threading.Thread(target=_play_audio, args=(audio, TTS_SAMPLE_RATE))
        _play_thread.daemon = True
        _play_thread.start()
        
    except Exception as e:
        log_message(f"Ошибка синтеза речи: {e}", "tts.py")

def wait_for_speech():
    """Ожидает окончания воспроизведения (если нужно)."""
    global _playing, _play_thread
    if _playing and _play_thread and _play_thread.is_alive():
        _play_thread.join()