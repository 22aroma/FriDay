import os
import sys
from omegaconf import OmegaConf

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES_DIR = os.path.join(BASE_DIR, 'files')
CONFIG_PATH = os.path.join(FILES_DIR, 'config.yml')

DEFAULT_CONFIG = {
    "audio": {"sample_rate": 16000, "chunk": 4000},
    "speech": {
        "silence_threshold_ms": 300,
        "min_speech_duration_ms": 100,
        "pre_recording_buffer_ms": 300,
        "vad_threshold_speech": 0.2,
        "vad_threshold_silence": 0.3,
        "noise_gate_enabled": True,
        "noise_gate_factor": 2.5,
    },
    "tts": {
        "language": "ru",
        "model_id": "v5_4_ru",
        "sample_rate": 48000,
        "speaker": "baya",
    },
    "wake_word": "пятница",
    "listening_duration": 15,
    "detection_cooldown": 1,
    "memory_ttl": 60,
    "weather": {"default_city": "Москва", "timeout": 5, "api_key": ""},
    "music": {"default_genre": ""},
    "wallpaper": {"path": ""},
}


def _load_config():
    base = OmegaConf.create(DEFAULT_CONFIG)
    if not os.path.exists(CONFIG_PATH):
        print("[config] config.yml не найден, используются стандартные настройки", file=sys.stderr)
        return base
    try:
        user = OmegaConf.load(CONFIG_PATH)
        return OmegaConf.merge(base, user)
    except Exception as e:
        print(f"[config] Ошибка загрузки config.yml: {e}", file=sys.stderr)
        return base


cfg = _load_config()
