import sys
from datetime import datetime
from .constants import LOG_PATH

_file = None

def _get_file():
    global _file
    if _file is None:
        try:
            _file = open(LOG_PATH, "a", encoding="utf-8")
        except Exception as e:
            print(f"[LOGGER ERROR] Не удалось открыть лог-файл: {e}", file=sys.stderr)
            return None
    return _file

def log_message(message: str, module_name: str):
    f = _get_file()
    if f is None:
        return
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{ts}] [{module_name}] {message}\n")
        f.flush()
    except Exception as e:
        print(f"[LOGGER ERROR] {e}", file=sys.stderr)

def close_log():
    global _file
    if _file is not None:
        try:
            _file.close()
        except Exception:
            pass
        _file = None
