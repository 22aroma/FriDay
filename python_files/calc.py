import ast
import re
import operator as _op

from num2words import num2words
from python_files.logger import log_message

FILLER_WORDS = (
    "посчитай", "подсчитай", "сколько будет", "сколько получится",
    "вычисли", "реши пример", "чему равен", "чему равна", "чему равно",
    "калькулятор", "пожалуйста",
)

# ─── Русские слова → числа ──────────────────────────────────────────────────
_NUM_WORDS = {
    "ноль": 0, "нуль": 0,
    "один": 1, "одна": 1, "одно": 1,
    "два": 2, "две": 2,
    "три": 3, "четыре": 4, "пять": 5,
    "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
    "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13,
    "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16,
    "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19,
    "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50,
    "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80, "девяносто": 90,
    "сто": 100, "двести": 200, "триста": 300, "четыреста": 400,
    "пятьсот": 500, "шестьсот": 600, "семьсот": 700, "восемьсот": 800,
    "девятьсот": 900,
    "тысяча": 1000, "тысячи": 1000, "тысяч": 1000,
    "миллион": 10 ** 6, "миллиона": 10 ** 6, "миллионов": 10 ** 6,
    # Склонённые формы (для 'корень из пяти', 'вычесть из шести' и т.п.)
    "шестнадцати": 16, "пятнадцати": 15, "четырнадцати": 14,
    "тринадцати": 13, "двенадцати": 12, "одиннадцати": 11,
    "пяти": 5, "пятью": 5, "шести": 6, "шестью": 6, "семи": 7,
    "семью": 7, "восьми": 8, "восемью": 8, "девяти": 9, "десяти": 10,
    "двадцати": 20, "тридцати": 30, "сорока": 40, "пятидесяти": 50,
    "шестидесяти": 60, "семидесяти": 70, "восьмидесяти": 80,
    "девяноста": 90, "ста": 100, "двухсот": 200, "двумстам": 200,
    "двумястами": 200, "трёхсот": 300, "трехсот": 300, "тремстам": 300,
    "тремястами": 300, "четырехсот": 400,
    "четырёхсот": 400, "четыремстам": 400, "четырьмястами": 400,
    "пятисот": 500, "шестисот": 600, "семисот": 700, "восьмисот": 800,
    "девятисот": 900, "тысяче": 1000, "тысячью": 1000,
    "миллионе": 10 ** 6, "миллионом": 10 ** 6, "миллионам": 10 ** 6,
}

_NUM_WORD_RE = re.compile(
    r"(?:\b(?:%s)\s*)+" % "|".join(sorted(_NUM_WORDS, key=len, reverse=True)))

_DIGIT_RE = re.compile(r"\d+")


def _digits_to_words(text):
    """Заменяем цифры на слова ('222' → 'двести двадцать два')."""
    def repl(match):
        try:
            return num2words(int(match.group()), lang="ru")
        except Exception:
            return match.group()
    return _DIGIT_RE.sub(repl, text)


_OPS_WORDS = (
    ("умножить на", "*"), ("помножить на", "*"), ("разделить на", "/"),
    ("поделить на", "/"), ("делить на", "/"),
    ("нацело разделить на", "//"), ("остаток от деления на", "%"),
    ("скобка открывается", "("), ("скобка закрывается", ")"),
    ("умножить", "*"), ("разделить", "/"), ("поделить", "/"),
    ("нацело", "//"), ("остаток от деления", "%"),
    ("прибавить", "+"), ("прибавь", "+"), ("сложить", "+"),
    ("сложи", "+"), ("добавить", "+"), ("плюс", "+"),
    ("вычесть", "-"), ("вычти", "-"), ("отнять", "-"), ("отними", "-"),
    ("минус", "-"), ("умнож", "*"), ("делить", "/"), ("раздели", "/"),
)

_EVAL_OPS = {
    ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul,
    ast.Div: _op.truediv, ast.FloorDiv: _op.floordiv,
    ast.Mod: _op.mod, ast.Pow: _op.pow,
    ast.UAdd: _op.pos, ast.USub: _op.neg,
}


def _parse_num_text(words):
    """Собираем число из слов: 'двадцать пять тысяч триста' → 25300."""
    result = 0
    current = 0
    for word in words:
        value = _NUM_WORDS[word]
        if value >= 1000:
            if current == 0:
                current = 1
            result += current * value
            current = 0
        else:
            current += value
    return result + current


def _replace_numbers(query):
    """Заменяем русские числа цифрами: 'пять' → '5'."""
    def replace(match):
        return str(_parse_num_text(match.group(0).split()))
    return _NUM_WORD_RE.sub(replace, query)


def _handle_functions(query):
    """Корень, квадрат и степень."""
    query = re.sub(r"корень\s*из\s*(\d+(?:\.\d+)?)", r"(\1**0.5)", query)
    query = re.sub(r"корень\s*(\d+(?:\.\d+)?)", r"(\1**0.5)", query)
    query = re.sub(r"(\d+(?:\.\d+)?)\s*в\s*квадрате", r"(\1**2)", query)
    query = re.sub(r"квадрат\s*(\d+(?:\.\d+)?)", r"(\1**2)", query)
    query = re.sub(
        r"(\d+(?:\.\d+)?)\s*в\s*степени\s*(\d+(?:\.\d+)?)",
        r"(\1**\2)", query)
    return query


def _replace_ops(query):
    for word, sign in sorted(_OPS_WORDS, key=lambda x: len(x[0]), reverse=True):
        query = query.replace(word, sign)
    return query


def to_expression(query):
    """Превращаем голос или текст в математическое выражение."""
    q = query.lower().strip()
    for filler in FILLER_WORDS:
        q = q.replace(filler, "")
    q = _replace_numbers(q)
    q = _handle_functions(q)
    q = _replace_ops(q)
    q = q.replace(",", ".").replace("×", "*").replace("÷", "/")
    q = q.rstrip("?!.").strip()
    return q


def evaluate(expr):
    """Безопасно вычисляем выражение (только числа и операторы)."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            return node.value if isinstance(node.value, (int, float)) else None
        if isinstance(node, ast.BinOp) and type(node.op) in _EVAL_OPS:
            left, right = walk(node.left), walk(node.right)
            if left is None or right is None:
                return None
            try:
                return _EVAL_OPS[type(node.op)](left, right)
            except (ZeroDivisionError, OverflowError, ValueError):
                return None
        if isinstance(node, ast.UnaryOp) and type(node.op) in _EVAL_OPS:
            value = walk(node.operand)
            if value is None:
                return None
            try:
                return _EVAL_OPS[type(node.op)](value)
            except (OverflowError, ValueError):
                return None
        return None

    try:
        result = walk(tree)
    except Exception:
        return None

    if isinstance(result, complex):
        return None
    if isinstance(result, float) and (result != result or result in
                                    (float("inf"), float("-inf"))):
        return None
    return result


def _number_words(n):
    """Число словами (целое или дробное) для озвучки и текста ответа."""
    if n < 0:
        return "минус " + _number_words(abs(n))

    whole = int(n)
    frac = round((n - whole) * 10)

    try:
        if frac == 0:
            return num2words(whole, lang="ru")

        whole_words = num2words(whole, lang="ru", gender="f") if whole else "ноль"
        unit = "целая" if whole == 1 else "целых"

        if frac == 1:
            frac_words = "одна десятая"
        elif frac == 2:
            frac_words = "две десятых"
        else:
            frac_words = num2words(frac, lang="ru") + " десятых"

        return f"{whole_words} {unit} {frac_words}"
    except Exception:
        return str(n)


def _speak_number(n):
    """Озвучиваем число (целое или дробное)."""
    from python_files.tts import speak
    speak(_number_words(n))


def calc_command(query):
    """Главная функция калькулятора."""
    from python_files.tts import speak
    log_message(f"Калькулятор: {query}", "calc.py")

    expr = to_expression(query)
    result = evaluate(expr)

    if result is None:
        log_message(f"Не удалось посчитать: '{expr}'", "calc.py")
        speak("Не получилось посчитать")
        return None

    if isinstance(result, float) and result.is_integer():
        result = int(result)

    display = _digits_to_words(query.strip().rstrip("?!."))
    answer = f"{display} будет {_number_words(result)}"
    log_message(f"Калькулятор: {answer}", "calc.py")
    _speak_number(result)
    return answer