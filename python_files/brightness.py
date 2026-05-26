import subprocess
import re
from .logger import log_message

STANDARD_BRIGHTNESS = 1.2
GAMMA = "0.85:0.85:0.85"

MONITOR_ALIASES = {
    "лев": "DP-0",
    "прав": "HDMI-0",
}


def get_monitors():
    try:
        result = subprocess.run(['xrandr', '--query'], capture_output=True, text=True, timeout=5)
        return [line.split()[0] for line in result.stdout.split('\n') if ' connected ' in line]
    except Exception as e:
        log_message(f"Ошибка получения списка мониторов: {e}", "brightness.py")
        return []


def _get_current_brightness(output_name):
    try:
        result = subprocess.run(['xrandr', '--verbose', '--query'], capture_output=True, text=True, timeout=5)
        lines = result.stdout.split('\n')
        in_section = False
        for line in lines:
            if line.startswith(output_name):
                in_section = True
            elif in_section and 'Brightness:' in line:
                return float(line.split()[-1])
            elif in_section and ' connected ' in line and not line.startswith(output_name):
                in_section = False
    except Exception as e:
        log_message(f"Ошибка получения яркости для {output_name}: {e}", "brightness.py")
    return STANDARD_BRIGHTNESS


def _set_brightness(output_name, brightness):
    brightness = round(max(0.1, min(2.0, brightness)), 2)
    try:
        subprocess.run(
            ['xrandr', '--output', output_name, '--gamma', GAMMA, '--brightness', str(brightness)],
            check=True, timeout=5
        )
        return True
    except Exception as e:
        log_message(f"Ошибка установки яркости для {output_name}: {e}", "brightness.py")
        return False


def _resolve_targets(monitor_hint):
    if not monitor_hint:
        return get_monitors()
    for key, output in MONITOR_ALIASES.items():
        if key in monitor_hint.lower():
            return [output]
    return get_monitors()


def adjust_brightness(monitor_hint, delta):
    targets = _resolve_targets(monitor_hint)
    for t in targets:
        current = _get_current_brightness(t)
        _set_brightness(t, current + delta)


def reset_brightness(monitor_hint=""):
    targets = _resolve_targets(monitor_hint)
    for t in targets:
        _set_brightness(t, STANDARD_BRIGHTNESS)


def set_absolute_brightness(monitor_hint, value):
    targets = _resolve_targets(monitor_hint)
    for t in targets:
        _set_brightness(t, value)


_NUM_WORDS = {
    "ноль": 0, "нуль": 0,
    "один": 1, "одна": 1, "одно": 1, "единица": 1,
    "два": 2, "две": 2, "двое": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
    "десять": 10,
}


def _word_to_number(word):
    return _NUM_WORDS.get(word.strip(".,!?;"))


def extract_brightness_value(query):
    q = query.lower()

    m = re.search(r'на\s+(\d+(?:[.,]\d+)?)', q)
    if m:
        val = float(m.group(1).replace(',', '.'))
        if '.' in m.group(1):
            return val
        return val / 10.0

    m = re.search(r'на\s+(\w+)', q)
    if m:
        n = _word_to_number(m.group(1))
        if n is not None:
            return n / 10.0

    m = re.search(r'\b(\d+(?:[.,]\d+)?)\b', q)
    if m:
        return float(m.group(1).replace(',', '.'))

    for word in q.split():
        n = _word_to_number(word)
        if n is not None:
            return float(n)

    return None
