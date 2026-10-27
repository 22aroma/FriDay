import os
import sys
import threading
from datetime import datetime
from .constants import FILES_DIR, LOG_PATH

_file = None
_lock = threading.Lock()


def _get_file():
    global _file
    if _file is not None:
        return _file
    try:
        os.makedirs(FILES_DIR, exist_ok=True)
        _file = open(LOG_PATH, "a", encoding="utf-8")
    except Exception as e:
        print(f"[LOGGER] Не удалось открыть файл: {e}", file=sys.stderr)
        return None
    return _file


def log_message(message, module_name):
    f = _get_file()
    if f is None:
        return
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        f.write(f"[{ts}] [{module_name}] {message}\n")
        f.flush()


def close_log():
    global _file
    with _lock:
        if _file is not None:
            try:
                _file.close()
            except Exception:
                pass
            _file = None
