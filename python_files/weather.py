import re
import requests
from num2words import num2words

from python_files.config_loader import cfg
from python_files.logger import log_message

API_KEY = (cfg.weather.api_key or "").strip()
BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
DEFAULT_CITY = cfg.weather.default_city
MAX_ATTEMPTS = 10

_WEATHER_DESC = {
    "Clear": "ясно",
    "Clouds": "пасмурно",
    "Rain": "дождь",
    "Drizzle": "морось",
    "Snow": "снег",
    "Thunderstorm": "гроза",
    "Mist": "туман",
    "Fog": "туман",
    "Haze": "дымка",
    "Smoke": "дымка",
    "Dust": "пыль",
    "Sand": "пыль",
    "Ash": "пепел",
    "Squall": "шквал",
    "Tornado": "торнадо",
}

# Не города, а короткие разговорные названия (без списка всех городов)
_NICKNAME_ALIASES = {
    "питер": "санкт-петербург",
    "спб": "санкт-петербург",
}


def _normalize_text(text):
    text = re.sub(r"[^а-яёa-z\s-]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def _clean_word(word):
    """Очистка слова: убираем лишние символы и применяем разговорные названия."""
    word = word.strip(" -").lower()
    if len(word) < 2:
        return None
    return _NICKNAME_ALIASES.get(word, word)


def extract_city(query):
    """Извлекаем город из фразы вида 'погода в сочи', 'в городе москва' и т.п."""
    text = _normalize_text(query)
    if not text:
        return None

    m = re.search(r"\bв\s+городе\s+([а-яё-]+)", text)
    if not m:
        m = re.search(
            r"(?:погод\w*|температур\w*|градус\w*|дождь|холод\w*|жар\w*|"
            r"мороз\w*|тепл\w*|ветр\w*|на\s+улице|за\s+окном)\b"
            r".{0,40}?\bв\s+([а-яё-]+)",
            text,
        )
    if not m:
        return None
    return _clean_word(m.group(1))


def _nominative_candidates(word):
    """Вероятные формы именительного падежа для слова, сказанного в другом падеже."""
    candidates = [word]
    # задвоение гласной на конце — ошибка ASR: "москваа" -> "москва"
    # (кроме "ии"/"ее" — это правильные окончания: "грузии", "музее")
    if (len(word) >= 3 and word[-1] in "аеёиоуыэюя"
            and word[-1] == word[-2] and word[-2:] not in ("ии", "ее")):
        candidates.append(word[:-1])

    for suffix in ("ах", "ях", "ом", "ой", "ии", "е", "ие", "и"):
        if not word.endswith(suffix) or len(word) - len(suffix) < 2:
            continue
        # "-ии" из "-ия": "грузии"->"грузи", "турции"->"турци"
        stem = word[:-1] if suffix == "ии" else word[:-len(suffix)]
        if stem[-1] in "аеёиоуыэюя":
            # корень с гласной: "дуба"->"дубай", "кита"->"китай", "грузи"->"грузия"
            candidates += [stem + "я", stem + "й", stem + "а",
                           stem + "и", stem + "ы", stem + "ь", stem]
        else:
            # корень с согласной: "рим"->"рим", "казан"->"казань", "египт"->"египет"
            candidates += [stem + "ь", stem + "а", stem + "я", stem,
                           stem + "ы", stem + "й"]
            if len(stem) >= 2:
                candidates += [stem[:-1] + "е" + stem[-1], stem[:-1] + "о" + stem[-1]]
            candidates += [stem + "ый", stem + "ой", stem + "ий"]
        break

    result = []
    for cand in candidates:
        cand = _NICKNAME_ALIASES.get(cand, cand)
        if cand not in result:
            result.append(cand)
    return result


def _fetch_weather(city):
    params = {
        'q': city,
        'appid': API_KEY,
        'units': 'metric',
        'lang': 'ru',
    }
    try:
        response = requests.get(BASE_URL, params=params, timeout=cfg.weather.timeout)
    except Exception as e:
        log_message(f"Погода: {e}", "weather.py")
        return "error", None
    if response.status_code == 200:
        try:
            return "ok", response.json()
        except Exception as e:
            log_message(f"Погода: парсинг: {e}", "weather.py")
            return "error", None
    if response.status_code == 404:
        return "notfound", None
    log_message(f"Погода: статус {response.status_code} для '{city}'", "weather.py")
    return "error", None


def _num_to_words(val):
    try:
        return num2words(int(round(float(val))), lang='ru')
    except (ValueError, TypeError):
        return None


def get_weather(query=""):
    if not API_KEY:
        log_message("Погода: не задан weather.api_key", "weather.py")
        return "Не задан ключ OpenWeatherMap. Добавьте weather.api_key в files/config.yml"

    word = extract_city(query)

    if word is None:
        candidates = [DEFAULT_CITY]
    else:
        candidates = _nominative_candidates(word)

    data = None
    matched = None
    for city in candidates[:MAX_ATTEMPTS]:
        status, data = _fetch_weather(city)
        if status == "ok":
            matched = city
            break
        if status == "error":
            return "Не удалось получить данные"

    if data is None:
        log_message(f"Погода: не найден город '{word}'", "weather.py")
        return "Не нашла город. Попробуйте сказать название города в именительном падеже"

    try:
        main = data["main"]
        weather = (data.get("weather") or [{}])[0]
    except (KeyError, IndexError, TypeError) as e:
        log_message(f"Погода: ошибка парсинга: {e}", "weather.py")
        return "Не удалось получить данные"

    temp_words = _num_to_words(main.get("temp"))
    feels_words = _num_to_words(main.get("feels_like"))
    desc = _WEATHER_DESC.get(weather.get("main"), weather.get("main") or "")

    parts = []
    if temp_words:
        parts.append(f"Сейчас {temp_words} градусов")
    if feels_words:
        parts.append(f"ощущается как {feels_words}")
    if desc:
        parts.append(desc)

    text = ", ".join(parts)
    if matched and matched.lower() != DEFAULT_CITY.lower():
        text = f"{matched.title()}: {text}"
    return text
