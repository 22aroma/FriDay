import os
from .config_loader import cfg, BASE_DIR

FILES_DIR = os.path.join(BASE_DIR, 'files')
ICON_PATH = os.path.join(FILES_DIR, 'icon.ico')
LOG_PATH = os.path.join(FILES_DIR, 'log.txt')

SAMPLE_RATE = cfg.audio.sample_rate
CHUNK = cfg.audio.chunk
