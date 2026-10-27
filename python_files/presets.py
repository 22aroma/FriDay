import json
import os
import subprocess
import threading

from .constants import FILES_DIR

PRESETS_PATH = os.path.join(FILES_DIR, 'presets.json')
_lock = threading.Lock()


def _load():
    """Загружаем пресеты из файла."""
    if not os.path.exists(PRESETS_PATH):
        return []
    try:
        with open(PRESETS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(presets):
    """Сохраняем пресеты в файл."""
    with open(PRESETS_PATH, 'w', encoding='utf-8') as f:
        json.dump(presets, f, ensure_ascii=False, indent=2)


def get_all():
    with _lock:
        return _load()


def get(name):
    for p in get_all():
        if p['name'].lower() == name.lower():
            return p
    return None


def add(name, apps):
    with _lock:
        presets = _load()
        presets.append({'name': name, 'apps': list(apps)})
        _save(presets)


def update(old_name, new_name, apps):
    with _lock:
        presets = _load()
        for p in presets:
            if p['name'] == old_name:
                p['name'] = new_name
                p['apps'] = list(apps)
                break
        _save(presets)


def delete(name):
    with _lock:
        presets = _load()
        presets = [p for p in presets if p['name'] != name]
        _save(presets)


def names():
    return [p['name'] for p in get_all()]


def match(query):
    """Ищем пресет по голосовому запросу."""
    q = query.lower().strip()
    all_names = names()

    # Точное совпадение
    for name in all_names:
        if q == name.lower():
            return name

    # Совпадение с префиксами ("запусти", "открой", "включи")
    for prefix in ('запусти ', 'открой ', 'включи '):
        if q.startswith(prefix):
            stripped = q[len(prefix):]
            for name in all_names:
                nl = name.lower()
                if stripped == nl:
                    return name
                # Нечёткое совпадение (последний символ может отличаться)
                if len(stripped) >= 2 and len(nl) >= 2:
                    if stripped[:-1] == nl[:-1]:
                        return name
    return None


def launch(name):
    """Запускаем все приложения из пресета."""
    preset = get(name)
    if not preset or not preset.get('apps'):
        return False
    for app_path in preset['apps']:
        try:
            subprocess.Popen([app_path])
        except Exception:
            try:
                subprocess.Popen(app_path, shell=True)
            except Exception:
                pass
    return True
