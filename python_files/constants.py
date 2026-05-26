"""
Общие константы для всего приложения.
"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES_DIR = os.path.join(BASE_DIR, 'files')
ICON_PATH = os.path.join(FILES_DIR, 'icon.png')
FRI_DAY_SAY_FOLDER = os.path.join(BASE_DIR, 'FriDay_say')
LOG_PATH = os.path.join(BASE_DIR, 'log.txt')

SAMPLE_RATE = 16000
CHUNK = 4000
AUDIO_CHUNK = 1024

TTS_LANGUAGE = 'ru'
TTS_MODEL_ID = 'v5_4_ru'
TTS_SAMPLE_RATE = 48000
TTS_SPEAKER = 'baya'
