import re
import string

# Словарь чисел: слово -> число (0-59 + десятки)
NUM_WORDS = {
    "ноль": 0, "нуль": 0,
    "один": 1, "одна": 1, "одно": 1, "единица": 1,
    "два": 2, "две": 2, "двое": 2,
    "три": 3, "трое": 3,
    "четыре": 4, "четверо": 4,
    "пять": 5, "шесть": 6, "семь": 7,
    "восемь": 8, "девять": 9, "десять": 10,
    "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13,
    "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16,
    "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19,
    "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50,
}

# Десятки для составных чисел
TENS = {20: "двадцать", 30: "тридцать", 40: "сорок", 50: "пятьдесят"}
TENS_REVERSE = {v: k for k, v in TENS.items()}

STRIP_CHARS = string.punctuation + "\u00ab\u00bb\u201c\u201d\"'"

DIGITS_RE = re.compile(r'\b\d+\b')
TIME_DIGITS_RE = re.compile(r'\b(\d{1,2}):(\d{1,2})\b')


def _word_to_number(word):
    return NUM_WORDS.get(word.strip(STRIP_CHARS))


def _compound_to_number(words):
    """Превращаем список слов в число (например, 'двадцать пять' -> 25)."""
    total = 0
    found = False
    for w in words:
        w = w.strip(STRIP_CHARS)
        if not w:
            continue
        if w in TENS_REVERSE:
            total += TENS_REVERSE[w]
            found = True
        elif w in NUM_WORDS:
            total += NUM_WORDS[w]
            found = True
        else:
            return None
    return total if found else None


def plural_form(n, one, few, many):
    """Русское склонение: plural_form(1, 'час', 'часа', 'часов') -> 'час'."""
    n = abs(n)
    mod10 = n % 10
    mod100 = n % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if mod10 in (2, 3, 4) and mod100 not in (12, 13, 14):
        return few
    return many


def get_hour_word(hours):
    if hours is None:
        return "часов"
    return plural_form(hours, "час", "часа", "часов")


def get_minute_word(minutes):
    if minutes is None:
        return "минут"
    return plural_form(minutes, "минуту", "минуты", "минут")


def extract_number_from_query(query):
    """Извлекаем первое число из фразы. Понимает цифры, слова и составные числа."""
    query_lower = query.lower()

    # Сначала пробуем цифры
    digits = DIGITS_RE.findall(query_lower)
    if digits:
        return int(digits[0])

    words = query_lower.split()

    # Пробуем составные числа (пара слов)
    for i in range(len(words) - 1):
        n = _compound_to_number(words[i:i + 2])
        if n is not None:
            return n

    # Пробуем одиночные слова
    for word in words:
        n = _word_to_number(word)
        if n is not None:
            return n

    return None


# Идиомы: "полдень" -> (12, 0), "полночь" -> (0, 0)
IDIOMS = {
    "полдень": (12, 0),
    "полночь": (0, 0),
}

# "полтретьего" = 2:30, "полчетвертого" = 3:30 и т.д.
HALF_HOUR_MAP = {
    "полвторого": (1, 30), "полтретьего": (2, 30), "полчетвертого": (3, 30),
    "полпятого": (4, 30), "полшестого": (5, 30), "полседьмого": (6, 30),
    "полвосьмого": (7, 30), "полдевятого": (8, 30), "полдесятого": (9, 30),
    "полодиннадцатого": (10, 30), "полдвенадцатого": (11, 30), "полпервого": (12, 30),
}


# "без пяти/десяти/двадцати ..." — родительный падеж чисел-идиом
_GENITIVE_OFFSETS = {
    "пяти": 5, "шести": 6, "семи": 7, "восьми": 8, "девяти": 9,
    "десяти": 10, "пятнадцати": 15, "двадцати": 20, "тридцати": 30,
}


def _is_hour_marker(word):
    return word.strip(STRIP_CHARS).startswith("час")


def _is_minute_marker(word):
    return word.strip(STRIP_CHARS).startswith("минут")


def _extract_bare_hours(phrase):
    """Извлекаем часы из фразы ('семь' -> 7, 'двадцать три' -> 23)."""
    phrase = phrase.strip(STRIP_CHARS)
    if phrase.isdigit():
        return int(phrase)

    n = _word_to_number(phrase)
    if n is not None and 1 <= n <= 23:
        return n

    words = phrase.split()
    if len(words) >= 2:
        cand = _compound_to_number(words[:2])
        if cand is not None and 1 <= cand <= 23:
            return cand

    return None


def _apply_ampm(query_lower, hours, minutes):
    """Сдвигаем часы при наличии указателя половины дня (вечера/дневного времени)."""
    if hours is None:
        return hours, minutes
    pm_markers = ("вечера", "вечер", "pm", "пм")
    if any(marker in query_lower for marker in pm_markers):
        if 1 <= hours <= 11:
            hours += 12
    elif any(marker in query_lower for marker in ("ночи", "ночь")):
        if 6 <= hours <= 11:
            hours += 12
        elif hours == 12:
            hours = 0
    if "дня" in query_lower.split() and 1 <= hours <= 4:
        hours += 12
    return hours, minutes


def extract_time_from_query(query):
    """Возвращает (hours, minutes) из голосового запроса."""
    query_lower = query.lower()

    # 1. Идиомы ("полдень", "полночь")
    for phrase, hm in IDIOMS.items():
        if phrase in query_lower:
            return hm

    # 1a. "полтретьего", "половина второго" и т.д.
    for phrase, hm in HALF_HOUR_MAP.items():
        if phrase in query_lower:
            return hm

    half_hour_words = (
        "второго|третьего|четвертого|пятого|шестого|седьмого|"
        "восьмого|девятого|десятого|одиннадцатого|двенадцатого|первого"
    )
    m = re.search(rf'(?:половина|половину)\s+({half_hour_words})', query_lower)
    if m:
        mapping = {
            "второго": (1, 30), "третьего": (2, 30), "четвертого": (3, 30),
            "пятого": (4, 30), "шестого": (5, 30), "седьмого": (6, 30),
            "восьмого": (7, 30), "девятого": (8, 30), "десятого": (9, 30),
            "одиннадцатого": (10, 30), "двенадцатого": (11, 30), "первого": (12, 30),
        }
        return mapping[m.group(1)]

    # 1b. "без четверти восемь", "без десяти девять" и т.д.
    m = re.search(r'без\s+(\w+)\s+(.*)', query_lower)
    if m:
        num_part = m.group(1)
        hour_part = m.group(2).strip()
        offset = None

        if num_part in NUM_WORDS and NUM_WORDS[num_part] <= 30:
            offset = NUM_WORDS[num_part]
        elif num_part in _GENITIVE_OFFSETS:
            offset = _GENITIVE_OFFSETS[num_part]
        elif num_part == "четверти":
            offset = 15
        elif num_part == "половины":
            offset = 30

        if offset is not None:
            h = _extract_bare_hours(hour_part)
            if h is not None:
                minutes = (60 - offset) % 60
                hours = (h - 1) % 24 if offset > 0 else h
                return _apply_ampm(query_lower, hours, minutes)

    # 2. Цифровое время ("7:30")
    m = TIME_DIGITS_RE.search(query_lower)
    if m:
        hours, minutes = int(m.group(1)), int(m.group(2))
        if 0 <= hours <= 23 and 0 <= minutes <= 59:
            return _apply_ampm(query_lower, hours, minutes)

    words = query_lower.split()
    hours = None
    minutes = 0

    # 3. Часы по маркеру "час*" ("семь часов", "двадцать три часа")
    for i, word in enumerate(words):
        if _is_hour_marker(word) and i > 0:
            if i >= 2:
                cand = _compound_to_number(words[i - 2:i])
                if cand is not None:
                    hours = cand
                    continue
            prev = words[i - 1].strip(STRIP_CHARS)
            if prev.isdigit():
                hours = int(prev)
            elif _word_to_number(prev) is not None:
                hours = _word_to_number(prev)
            elif hours is None and word == "час":
                hours = 1

    # 4. Часы после предлога "в"/"на" ("разбуди в восемь", "на девять")
    if hours is None:
        for i, word in enumerate(words):
            w = word.strip(STRIP_CHARS)
            if w in ("в", "на", "во") and i + 1 < len(words):
                if i + 2 < len(words):
                    cand = _compound_to_number(words[i + 1:i + 3])
                    if cand is not None and 1 <= cand <= 23:
                        hours = cand
                        break
                nxt = words[i + 1].strip(STRIP_CHARS)
                n = _word_to_number(nxt)
                if n is not None and 1 <= n <= 23:
                    hours = n
                    break

    # 5. Минуты по маркеру "минут*" ("пять минут тридцать")
    for i, word in enumerate(words):
        if _is_minute_marker(word) and i > 0:
            if i >= 2:
                cand = _compound_to_number(words[i - 2:i])
                if cand is not None:
                    minutes = cand
                    continue
            prev = words[i - 1].strip(STRIP_CHARS)
            if prev.isdigit():
                minutes = int(prev)
            elif _word_to_number(prev) is not None:
                minutes = _word_to_number(prev)

    if hours is None:
        return None, 0
    return _apply_ampm(query_lower, hours, minutes)
