import re
from num2words import num2words
from python_files.logger import log_message
from python_files.tts import speak


def preprocess_query(query):
    q = query.lower().strip()

    for fw in ['посчитай', 'сколько будет', 'сколько', 'калькулятор']:
        q = q.replace(fw, '')
    q = q.strip()

    m = re.search(r'корень\s+из\s+(\d+(?:\.\d+)?)', q)
    if m:
        q = q.replace(m.group(0), f'({m.group(1)}**0.5)')
    else:
        m = re.search(r'корень\s+(\d+(?:\.\d+)?)', q)
        if m:
            q = q.replace(m.group(0), f'({m.group(1)}**0.5)')

    m = re.search(r'квадрат\s+(\d+(?:\.\d+)?)', q)
    if m:
        q = q.replace(m.group(0), f'({m.group(1)}**2)')
    else:
        m = re.search(r'(\d+(?:\.\d+)?)\s+в\s+квадрате', q)
        if m:
            q = q.replace(m.group(0), f'({m.group(1)}**2)')
        else:
            m = re.search(r'(\d+(?:\.\d+)?)\s+квадрат', q)
            if m:
                q = q.replace(m.group(0), f'({m.group(1)}**2)')

    replacements = [
        ('скобка открывается', '('),
        ('скобка закрывается', ')'),
        ('нацело разделить на', '//'),
        ('остаток от деления на', '%'),
        ('умножить на', '*'),
        ('разделить на', '/'),
        ('нацело разделить', '//'),
        ('остаток от деления', '%'),
        ('в степени', '**'),
        ('делить на', '/'),
        ('умножить', '*'),
        ('разделить', '/'),
        ('нацело', '//'),
        ('остаток от', '%'),
        ('остаток', '%'),
        ('делить', '/'),
        ('дел', '/'),
        ('умнож', '*'),
        ('плюс', '+'),
        ('минус', '-'),
    ]
    for old, new in replacements:
        q = q.replace(old, new)

    q = q.replace(',', '.')
    if q and q[0] == '-':
        q = '0' + q
    q = q.replace('(-', '(0-')
    q = q.rstrip('?!.').strip()

    return q


def tokenize(expr):
    tokens = []
    i = 0
    n = len(expr)
    while i < n:
        if expr[i] == ' ':
            i += 1
            continue
        if expr[i] in '()':
            tokens.append(expr[i])
            i += 1
            continue
        if i + 1 < n and expr[i:i+2] in ('**', '//'):
            tokens.append(expr[i:i+2])
            i += 2
            continue
        if expr[i] in '+-*/%':
            tokens.append(expr[i])
            i += 1
            continue
        m = re.match(r'\d+(?:\.\d+)?', expr[i:])
        if m:
            tokens.append(('num', float(m.group())))
            i += m.end()
            continue
        i += 1
    return tokens


def evaluate_expression(expr):
    tokens = tokenize(expr)
    if not tokens:
        return None

    precedence = {'+': 1, '-': 1, '*': 2, '/': 2, '//': 2, '%': 2, '**': 3}
    right_assoc = {'**'}

    output = []
    op_stack = []

    for tok in tokens:
        if tok[0] == 'num':
            output.append(tok)
        elif tok == '(':
            op_stack.append(tok)
        elif tok == ')':
            while op_stack and op_stack[-1] != '(':
                output.append(op_stack.pop())
            if op_stack and op_stack[-1] == '(':
                op_stack.pop()
        else:
            while (op_stack and op_stack[-1] != '(' and
                   (precedence[op_stack[-1]] > precedence[tok] or
                    (precedence[op_stack[-1]] == precedence[tok] and tok not in right_assoc))):
                output.append(op_stack.pop())
            op_stack.append(tok)

    while op_stack:
        output.append(op_stack.pop())

    stack = []
    for tok in output:
        if tok[0] == 'num':
            stack.append(tok[1])
        else:
            if len(stack) < 2:
                return None
            b = stack.pop()
            a = stack.pop()
            if tok == '+':
                stack.append(a + b)
            elif tok == '-':
                stack.append(a - b)
            elif tok == '*':
                stack.append(a * b)
            elif tok == '/':
                if b == 0:
                    return None
                stack.append(a / b)
            elif tok == '//':
                if b == 0:
                    return None
                stack.append(a // b)
            elif tok == '%':
                if b == 0:
                    return None
                stack.append(a % b)
            elif tok == '**':
                stack.append(a ** b)

    return stack[0] if stack else None


def calc_command(query):
    log_message(f"Обработка калькулятора: {query}", "commands.py")

    q_orig = query.lower().strip()
    expr = preprocess_query(query)

    if not expr:
        speak("Не понял, что посчитать")
        return None

    try:
        result = evaluate_expression(expr)
    except Exception as e:
        log_message(f"Ошибка вычисления выражения '{expr}': {e}", "calc.py")
        speak("Не получилось посчитать")
        return None

    if result is None:
        speak("Не получилось посчитать")
        return None

    res_int = int(result) if isinstance(result, float) and result.is_integer() else result

    display = q_orig
    for fw in ['посчитай', 'сколько будет', 'сколько', 'калькулятор']:
        display = display.replace(fw, '')
    display = display.strip().rstrip('?!.')

    ans = f"{display} будет {res_int}"
    log_message(f"Калькулятор: {ans}", "commands.py")
    speak(num2words(res_int, lang='ru'))
    return ans
