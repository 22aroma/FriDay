import re
import time
import threading
import os

from num2words import num2words

from python_files.logger import log_message
from python_files.number_utils import extract_number_from_query, extract_time_from_query, get_hour_word, get_minute_word, plural_form
from python_files.calc import calc_command
from python_files.weather import get_weather
from python_files.tts import speak
from python_files.music import _player as music_player
from python_files import presets as presets_mod
from python_files import wallpaper
from python_files.config_loader import cfg

shutdown_event = threading.Event()
alarm_time = None
timer_end_time = None
memory_buffer = None
_last_answer = None


def _normalize(text):
    """Нижний регистр, без пунктуации, одиночные пробелы."""
    text = re.sub(r"[^а-яёa-z0-9\s+\-*/%().,]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _any_in(text, words):
    """Проверяем, есть ли хотя бы одно слово из списка в тексте."""
    for word in words:
        if word in text:
            return True
    return False


# ─── ПРАВИЛА РАСПОЗНАВАНИЯ НАМЕРЕНИЙ ────────────────────────────────────────
# Каждое правило: (название_намерения, функция_проверки)
# Порядок важен! Первое совпадение побеждает.

_RULES = [
    ("wallpaper", lambda t: "обои" in t and _any_in(t, (
        "смени", "сменить", "поменяй", "поменя", "новые",
        "установи", "поставь"))),

    ("timer_stop", lambda t: "таймер" in t and _any_in(t, (
        "стоп", "отмени", "выключи", "убери", "отбой", "сброс"))),

    ("music_stop", lambda t: _any_in(t, (
        "стоп", "стоп музык", "выключи музык", "останови музык",
        "хватит", "музыка стоп", "музыка хватит"))),

    ("music_next", lambda t: _any_in(t, (
        "следующий трек", "следующая", "следующее", "следующий",
        "дальше", "далее", "пропусти", "переключи", "следующ",
        "вперёд", "вперед", "смени", "другую", "другой трек",
        "не то", "skip"))),

    ("music_play", lambda t: (
        _any_in(t, ("включи музык", "музыку включи", "поставь музык", "вруби музык"))
        or (re.search(r'\bвключи\b', t) and re.search(r'\bмузык', t))
    )),

    ("timer_set", lambda t: _any_in(t, (
        "таймер", "засек", "отсчита", "напомни через", "обратный отсчет"))),

    ("alarm", lambda t: _any_in(t, (
        "будильник", "разбуд", "побудк", "встань", "встать",
        "напоминание на", "подними"))),

    ("calc", lambda t: (_any_in(t, (
        "плюс", "минус", "умнож", "раздел", "корень", "степен",
        "синус", "косинус", "процент", "прибав", "слож", "калькулятор",
        "посчитай", "вычисли", "чему равен", "реши пример",
        "сколько будет", "сколько получится", "умножить", "разделить")) or
        re.search(r"\d\s*[+\-*/%]\s*\d", t))),

    ("weather", lambda t: _any_in(t, (
        "погод", "градус", "температур", "дождь", "холодн", "жар",
        "мороз", "зонт", "тепло", "на улице", "за окном", "ветер"))),

    ("repeat", lambda t: _any_in(t, (
        "повтор", "ещё раз", "еще раз", "не расслышал", "что ты сказал",
        "что ты сказала", "скажи ещё раз", "скажи еще раз"))),

    ("shutdown_app", lambda t: _any_in(t, (
        "выключись", "остановись", "отключай", "заверши", "заткнись",
        "замолкни", "спи", "пока", "до свидания", "иди в фон"))),
]


def classify_query(query):
    """Определяем намерение по тексту. Возвращает название или None."""
    text = _normalize(query)
    if not text:
        return None
    for intent, check in _RULES:
        if check(text):
            return intent
    return None


# ─── БУФЕР ПАМЯТИ (для отложенных вопросов без ключевого слова) ──────────────

class MemoryBuffer:
    def __init__(self, ttl=120):
        self.phrase = None
        self.timestamp = 0
        self.deferred = None
        self.deferred_ts = 0
        self.ttl = ttl

    def update(self, text):
        self.phrase = text
        self.timestamp = time.time()

    def mark_deferred(self):
        if self.phrase is not None:
            self.deferred = self.phrase
            self.deferred_ts = self.timestamp

    def get_deferred(self):
        if self.deferred is not None and time.time() - self.deferred_ts <= self.ttl:
            return self.deferred
        return None

    def clear(self):
        self.phrase = None
        self.timestamp = 0
        self.deferred = None
        self.deferred_ts = 0


def init_memory_buffer(ttl=120):
    global memory_buffer
    memory_buffer = MemoryBuffer(ttl)


# ─── ОБРАБОТЧИКИ КОМАНД ──────────────────────────────────────────────────────

def _handle_repeat(query):
    global _last_answer
    log_message("Повтори", "commands.py")
    if _last_answer:
        speak(_last_answer)
    else:
        speak("Я ещё ничего не говорила")


def _handle_shutdown_app(query):
    log_message("Завершение", "commands.py")
    shutdown_event.set()


def _handle_alarm(query):
    global _last_answer, alarm_time
    log_message(f"Будильник: {query}", "commands.py")

    hours, minutes = extract_time_from_query(query)

    if hours is not None and 0 <= hours <= 23 and 0 <= minutes <= 59:
        now = time.localtime()
        alarm = time.mktime((
            now.tm_year, now.tm_mon, now.tm_mday,
            hours, minutes, 0, 0, 0, -1
        ))
        if alarm <= time.time():
            alarm += 24 * 3600
        alarm_time = alarm

        hours_words = num2words(hours, lang='ru')
        hour_word = get_hour_word(hours)
        if minutes == 0:
            _last_answer = f"Будильник установлен на {hours_words} {hour_word}"
        else:
            minutes_words = num2words(minutes, lang='ru')
            minute_word = get_minute_word(minutes)
            _last_answer = f"Будильник установлен на {hours_words} {hour_word} {minutes_words} {minute_word}"
        speak(_last_answer)
    else:
        _last_answer = "Скажите полностью, например: будильник на пять часов тридцать минут"
        speak(_last_answer)


def _handle_timer_set(query):
    global _last_answer, timer_end_time
    log_message(f"Таймер: {query}", "commands.py")

    try:
        ql = query.lower()
        use_seconds = "секунд" in ql or "сек" in ql
        number = extract_number_from_query(query)

        if number is None:
            _last_answer = "Не удалось распознать время для таймера"
            speak(_last_answer)
            return

        if use_seconds:
            timer_end_time = time.time() + number
            words = num2words(number, lang='ru')
            unit = plural_form(number, "секунду", "секунды", "секунд")
            _last_answer = f"Таймер установлен на {words} {unit}"
        else:
            timer_end_time = time.time() + number * 60
            words = num2words(number, lang='ru')
            minute_word = get_minute_word(number)
            _last_answer = f"Таймер установлен на {words} {minute_word}"
        speak(_last_answer)
    except Exception as e:
        log_message(f"Ошибка таймера: {e}", "commands.py")
        _last_answer = "Не удалось распознать время для таймера"
        speak(_last_answer)


def _handle_timer_stop(query):
    global timer_end_time
    log_message("Таймер стоп", "commands.py")
    if timer_end_time is not None:
        timer_end_time = None
        speak("Таймер остановлен")
    else:
        speak("Таймер не запущен")


def _handle_wallpaper(query):
    global _last_answer
    log_message(f"Обои: {query}", "commands.py")
    path = cfg.wallpaper.path
    if not path:
        _last_answer = "Путь к обоям не задан. Укажите его в настройках"
        speak(_last_answer)
        return
    if not os.path.exists(path):
        _last_answer = f"Папка с обоями не найдена: {path}"
        speak(_last_answer)
        return
    err = wallpaper.set_all_desktop_wallpapers(path)
    if err:
        _last_answer = f"Не удалось сменить обои: {err}"
    else:
        _last_answer = "Обои сменены на всех рабочих столах"
    speak(_last_answer)


def _handle_calc(query):
    global _last_answer
    log_message(f"Калькулятор: {query}", "commands.py")
    _last_answer = calc_command(query)


def _handle_weather(query):
    global _last_answer
    log_message(f"Погода: {query}", "commands.py")
    result = get_weather(query)
    if result:
        _last_answer = result
        speak(_last_answer)
    else:
        _last_answer = "Не удалось получить данные"
        speak(_last_answer)


def _handle_music_play(query):
    global _last_answer
    log_message(f"Музыка: {query}", "commands.py")
    term = _extract_music_query(query)
    if music_player.is_playing:
        music_player.stop()
        time.sleep(0.5)
    speak("Ищу, подождите")
    ok = music_player.play(query=term) if term else music_player.play()
    _last_answer = "Музыка играет" if ok else "Не удалось найти музыку"
    if not ok:
        speak(_last_answer)


def _handle_music_next(query):
    log_message("Следующий трек", "commands.py")
    music_player.next()


def _handle_music_stop(query):
    log_message("Стоп музыка", "commands.py")
    music_player.stop()


def _extract_music_query(query):
    """Извлекаем запрос из фразы 'включи музыку'."""
    q = query.lower()
    m = re.search(r'включи\s+(.+?)\s+музык', q)
    if m:
        return m.group(1).strip()
    m = re.search(r'включи\s+музык[уа]?\s+(.+)', q)
    if m:
        return m.group(1).strip()
    return None


# ─── СПИСОК ОБРАБОТЧИКОВ ─────────────────────────────────────────────────────
# Все обработчики принимают аргумент query для единообразия.

_HANDLERS = {
    "repeat": _handle_repeat,
    "shutdown_app": _handle_shutdown_app,
    "alarm": _handle_alarm,
    "timer_set": _handle_timer_set,
    "timer_stop": _handle_timer_stop,
    "calc": _handle_calc,
    "weather": _handle_weather,
    "music_play": _handle_music_play,
    "music_next": _handle_music_next,
    "music_stop": _handle_music_stop,
    "wallpaper": _handle_wallpaper,
}


def command_handler(query):
    """Главный обработчик команд. Возвращает True если команда распознана."""
    global _last_answer

    intent = classify_query(query)

    # Если намерение не найдено — пробуем найти пресет
    if intent is None:
        preset_name = presets_mod.match(_normalize(query))
        if preset_name:
            log_message(f"Запуск пресета: '{preset_name}'", "commands.py")
            presets_mod.launch(preset_name)
            _last_answer = f"Запускаю {preset_name}"
            speak(_last_answer)
            return True
        log_message(f"Не распознано: '{query}'", "commands.py")
        return None

    log_message(f"Намерение: {intent}", "commands.py")

    handler = _HANDLERS.get(intent)
    if handler:
        handler(query)
        return True
    return None
