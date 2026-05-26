import re
from num2words import num2words

_DIRECT_REPLACEMENTS = [
    ("и т. д.", "и так далее"),
    ("и т. п.", "и тому подобное"),
    ("и т.д.", "и так далее"),
    ("и т.п.", "и тому подобное"),
    ("в т. ч.", "в том числе"),
    ("т. е.", "то есть"),
    ("т.е.", "то есть"),
    ("т. д.", "так далее"),
    ("т.д.", "так далее"),
    ("т. п.", "тому подобное"),
    ("т.п.", "тому подобное"),
    ("т. к.", "так как"),
    ("т.к.", "так как"),
    ("т. н.", "так называемый"),
    ("т.н.", "так называемый"),
    ("т. о.", "таким образом"),
    ("т.о.", "таким образом"),
    ("и др.", "и другие"),
    ("и пр.", "и прочие"),
    ("кв. км", "квадратных километров"),
    ("кв. м", "квадратных метров"),
    ("напр.", "например"),
    ("ок.", "около"),
    ("тел.", "телефон"),
    ("ул.", "улица"),
    ("руб.", "рублей"),
    ("стр.", "страница"),
    ("пл.", "площадь"),
    ("г.", "год"),
    ("гг.", "годы"),
    ("см.", "смотрите"),
    ("пр.", "прочие"),
    ("др.", "другие"),
]

_UNITS = [
    ("км/ч", ("километр в час", "километра в час", "километров в час")),
    ("м/с", ("метр в секунду", "метра в секунду", "метров в секунду")),
    ("км", ("километр", "километра", "километров")),
    ("м", ("метр", "метра", "метров")),
    ("см", ("сантиметр", "сантиметра", "сантиметров")),
    ("мм", ("миллиметр", "миллиметра", "миллиметров")),
    ("кг", ("килограмм", "килограмма", "килограммов")),
    ("г", ("грамм", "грамма", "граммов")),
    ("л", ("литр", "литра", "литров")),
    ("га", ("гектар", "гектара", "гектаров")),
    ("%", ("процент", "процента", "процентов")),
]

_CASE_PREPOSITIONS = {
    "genitive": [
        "до", "от", "для", "без", "из", "у",
        "около", "возле",
        "более", "больше", "менее", "меньше", "свыше", "порядка",
        "против", "вместо", "кроме", "среди", "ради",
    ],
    "dative": ["к", "ко", "по"],
    "instrumental": ["над", "под", "перед", "между"],
    "prepositional": ["о", "об", "при"],
}

_CASE_PATTERNS: list[tuple[re.Pattern, str]] = []
for _case, _preps in _CASE_PREPOSITIONS.items():
    _joined = "|".join(re.escape(p) for p in _preps)
    pattern = re.compile(rf"\b(?:(?P<prep>{_joined}))\s+(?P<num>\d+)\b", re.IGNORECASE)
    _CASE_PATTERNS.append((pattern, _case))


def _get_unit_form(num: int, forms: tuple[str, str, str]) -> str:
    if num % 10 == 1 and num % 100 != 11:
        return forms[0]
    if num % 10 in (2, 3, 4) and num % 100 not in (12, 13, 14):
        return forms[1]
    return forms[2]


def normalize_text(text: str) -> str:
    if not text:
        return text

    for old, new in _DIRECT_REPLACEMENTS:
        text = text.replace(old, new)

    for abbr, forms in _UNITS:
        esc = re.escape(abbr)
        text = re.sub(
            rf"(\d+)\s*{esc}(?:\b|(?=/|$|\s|[.,!?;]))",
            lambda m, forms=forms: f"{m.group(1)} {_get_unit_form(int(m.group(1)), forms)}",
            text,
        )
        text = re.sub(rf"\b{esc}(?:\b|(?=/|$|\s|[.,!?;]))", forms[2], text)

    for pattern, case in _CASE_PATTERNS:
        text = pattern.sub(
            lambda m, c=case: f"{m.group('prep')} {num2words(int(m.group('num')), lang='ru', case=c)}",
            text,
        )

    text = re.sub(r"\b(\d+)\b", lambda m: num2words(int(m.group()), lang="ru"), text)

    return text.strip()
