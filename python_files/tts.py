import torch
import threading
import numpy as np
from .config_loader import cfg
from .logger import log_message
from .audio_mixer import _mixer

_model = None
_lock = threading.Lock()


def _load_model():
    global _model
    if _model is not None:
        return _model
    if _model is None:
        with _lock:
            if _model is None:
                try:
                    result = torch.hub.load(
                        repo_or_dir='snakers4/silero-models',
                        model='silero_tts',
                        language=cfg.tts.language,
                        speaker=cfg.tts.model_id,
                        trust_repo=True,
                    )
                    _model = result[0] if isinstance(result, tuple) else result
                    if _model is None or not hasattr(_model, 'apply_tts'):
                        log_message("Модель не загружена", "tts.py")
                        _model = None
                    else:
                        _model.to(torch.device('cpu'))
                except Exception as e:
                    log_message(f"Ошибка загрузки TTS: {e}", "tts.py")
                    _model = None
    return _model


def speak(text):
    log_message(f"Говорю: {text}", "tts.py")
    try:
        model = _load_model()
        if model is None:
            return

        # Собираем параметры, поддерживаемые моделью
        import inspect
        sig = inspect.signature(model.apply_tts)
        supported_params = {}
        for param_name in ('put_accent', 'put_yo', 'put_stress_homo', 'put_yo_homo'):
            if param_name in sig.parameters:
                supported_params[param_name] = True

        kwargs = {"speaker": cfg.tts.speaker, "sample_rate": cfg.tts.sample_rate}
        kwargs.update(supported_params)

        with torch.inference_mode():
            audio = model.apply_tts(text=text, **kwargs)
            if isinstance(audio, list):
                audio = np.asarray(audio[0]) if audio else np.array([], dtype=np.float32)
            elif isinstance(audio, torch.Tensor):
                audio = audio.cpu().numpy()

        _mixer.play_tts(audio, cfg.tts.sample_rate)
    except Exception as e:
        log_message(f"Ошибка синтеза: {e}", "tts.py")
