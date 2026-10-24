"""
Arithmetic engine for the calculator.

The frontend sends an expression string such as "12.5 + -3 * 4".
We split it into tokens, then evaluate it with a small recursive-descent
parser that respects operator precedence (* and / before + and -).

We deliberately do NOT use Python's eval(): it would execute any Python
code a user sends us, which is a remote-code-execution vulnerability.
"""

import re
from decimal import ROUND_HALF_UP, Decimal, localcontext

MAX_EXPRESSION_LENGTH = 200
MAX_ABS_RESULT = Decimal("1e15")   # results limited to +/- one quadrillion
RESULT_PLACES = Decimal("1e-10")   # results are rounded to 10 decimal places
WORKING_PRECISION = 28             # significant digits used during arithmetic

DIGITS = "0123456789"
OPERATORS = "+-*/"
VALID_NUMBER = re.compile(r"[0-9]+\.?[0-9]*|\.[0-9]+")  # "12", "12.", "12.5", ".5"


class CalculationError(ValueError):
    """Raised when an expression can't be evaluated. The message is safe to show to users."""


def tokenize(expression):
    """Split an expression into Decimal numbers and operator strings.

    "12.5 + -3"  ->  [Decimal("12.5"), "+", "-", Decimal("3")]
    """
    tokens = []
    position = 0
    while position < len(expression):
        char = expression[position]

        if char.isspace():
            position += 1
        elif char in OPERATORS:
            tokens.append(char)
            position += 1
        elif char in DIGITS or char == ".":
            # Grab the whole run of digits and dots, then check it is one valid number.
            start = position
            while position < len(expression) and (expression[position] in DIGITS or expression[position] == "."):
                position += 1
            text = expression[start:position]
            if not VALID_NUMBER.fullmatch(text):
                raise CalculationError(f"Malformed number: '{text}'")
            tokens.append(Decimal(text))
        else:
            raise CalculationError(f"Invalid character: '{char}'")
    return tokens


class _Parser:
    """Evaluates a token list using this grammar (lowest precedence first):

        expression := term (("+" | "-") term)*
        term       := factor (("*" | "/") factor)*
        factor     := ["-"] number

    Each grammar rule is one method. Because expression() calls term(),
    multiplication and division always happen before addition and subtraction.
    A single optional "-" in factor() is what allows negative numbers.
    """

    def __init__(self, tokens):
        self.tokens = tokens
        self.position = 0

    def peek(self):
        """Return the next token without consuming it (None when there are no more)."""
        if self.position < len(self.tokens):
            return self.tokens[self.position]
        return None

    def take(self):
        """Return the next token and move past it."""
        token = self.peek()
        self.position += 1
        return token

    def parse(self):
        result = self.expression()
        if self.peek() is not None:
            # expression() only stops at a token that is not an operator,
            # so a leftover token is always a second number, e.g. "2 3".
            raise CalculationError("Missing operator between numbers")
        return result

    def expression(self):
        result = self.term()
        while self.peek() in ("+", "-"):
            operator = self.take()
            right = self.term()
            if operator == "+":
                result = result + right
            else:
                result = result - right
        return result

    def term(self):
        result = self.factor()
        while self.peek() in ("*", "/"):
            operator = self.take()
            right = self.factor()
            if operator == "*":
                result = result * right
            elif right == 0:
                raise CalculationError("Cannot divide by zero")
            else:
                result = result / right
        return result

    def factor(self):
        is_negative = False
        if self.peek() == "-":
            self.take()
            is_negative = True

        token = self.take()
        if token is None:
            raise CalculationError("Expression is incomplete: it ends with an operator")
        if not isinstance(token, Decimal):
            raise CalculationError(f"Unexpected operator '{token}': expected a number")
        return -token if is_negative else token


def format_result(value):
    """Turn a Decimal into a plain string: no exponent, no trailing zeros, never '-0'."""
    if value == 0:
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def calculate(expression):
    """Evaluate an arithmetic expression and return the result as a string.

    Returning a string (not a float) keeps the exact decimal digits all the
    way to the browser, so 0.1 + 0.2 is shown as "0.3".
    """
    if not isinstance(expression, str):
        raise CalculationError("Expression must be text")
    expression = expression.strip()
    if not expression:
        raise CalculationError("Expression is empty")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise CalculationError(f"Expression is too long (max {MAX_EXPRESSION_LENGTH} characters)")

    with localcontext() as context:
        context.prec = WORKING_PRECISION
        tokens = tokenize(expression)
        result = _Parser(tokens).parse()

        # Check the size BEFORE rounding: a number up to 1e15 with 10 decimal
        # places fits in 26 digits, inside our 28-digit working precision.
        if abs(result) > MAX_ABS_RESULT:
            raise CalculationError("Result is too large: the limit is ±1,000,000,000,000,000")
        result = result.quantize(RESULT_PLACES, rounding=ROUND_HALF_UP)

    return format_result(result)