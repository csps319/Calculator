"""Unit tests for the arithmetic engine."""

import pytest

from calculator import CalculationError, calculate


@pytest.mark.parametrize("expression, expected", [
    ("1 + 2", "3"),
    ("10 - 4", "6"),
    ("6 * 7", "42"),
    ("8 / 2", "4"),
    ("7 / 2", "3.5"),
    ("  1+2  ", "3"),
    ("1\t+\n2", "3"),
])
def test_basic_operations(expression, expected):
    assert calculate(expression) == expected


@pytest.mark.parametrize("expression, expected", [
    ("2 + 3 * 4", "14"),             # * before +
    ("2 * 3 + 4 * 5", "26"),
    ("1 + 2 * 3 - 4 / 2", "5"),
    ("10 - 2 - 3", "5"),             # left to right, not 10 - (2 - 3)
    ("100 / 10 / 2", "5"),
])
def test_operator_precedence_and_associativity(expression, expected):
    assert calculate(expression) == expected


@pytest.mark.parametrize("expression, expected", [
    ("0.1 + 0.2", "0.3"),            # 0.30000000000000004 with floats
    ("0.1 + 0.7", "0.8"),            # 0.7999999999999999 with floats
    ("0.1 * 3", "0.3"),
    ("1 - 0.9", "0.1"),
    ("1.5 * 2", "3"),                # trailing zeros removed
    (".5 + .5", "1"),                # leading dot
    ("5. + 1", "6"),                 # trailing dot
    ("1 / 3", "0.3333333333"),       # rounded to 10 places
    ("2 / 3", "0.6666666667"),       # rounded half up
    ("1 / 3 * 3", "1"),
    ("123456789.123456789 + 0.000000001", "123456789.12345679"),
])
def test_decimals_and_precision(expression, expected):
    assert calculate(expression) == expected


@pytest.mark.parametrize("expression, expected", [
    ("-5 + 3", "-2"),
    ("3 - 5", "-2"),
    ("5 - -3", "8"),
    ("5 * -2", "-10"),
    ("-6 / -3", "2"),
    ("-2 * -3 + -4", "2"),
    ("-0", "0"),                     # never show "-0"
    ("0 * -5", "0"),
])
def test_negative_numbers(expression, expected):
    assert calculate(expression) == expected


@pytest.mark.parametrize("expression, expected", [
    ("999999999999999 + 1", "1000000000000000"),   # exactly at the limit is allowed
    ("1000000 * 1000000000", "1000000000000000"),
    ("0.00000000005", "0.0000000001"),             # rounds half up at 10 places
    ("0.00000000004", "0"),
])
def test_limits_and_rounding_edges(expression, expected):
    assert calculate(expression) == expected


@pytest.mark.parametrize("expression, message", [
    # Division by zero
    ("5 / 0", "divide by zero"),
    ("0 / 0", "divide by zero"),
    ("1 / 0.0", "divide by zero"),
    ("2 + 3 / 0 * 4", "divide by zero"),
    # Empty / incomplete
    ("", "empty"),
    ("   ", "empty"),
    ("5 +", "incomplete"),
    ("-", "incomplete"),
    # Repeated or misplaced operators
    ("5 + * 3", "Unexpected operator"),
    ("5 ++ 3", "Unexpected operator"),
    ("* 5", "Unexpected operator"),
    ("5 - - - 3", "Unexpected operator"),
    ("2 3", "Missing operator"),
    # Malformed numbers
    ("1.2.3", "Malformed number"),
    ("5..2", "Malformed number"),
    (".", "Malformed number"),
    # Invalid characters, including attempts to sneak in code
    ("2 ^ 3", "Invalid character"),
    ("1e5", "Invalid character"),
    ("abc", "Invalid character"),
    ("Infinity", "Invalid character"),
    ("__import__('os')", "Invalid character"),
    ("²", "Invalid character"),
    # Very large numbers
    ("999999999999999 + 2", "too large"),
    ("10000000000 * 10000000000", "too large"),
    ("-1000000000000001", "too large"),
])
def test_invalid_expressions_raise_clear_errors(expression, message):
    with pytest.raises(CalculationError, match=message):
        calculate(expression)


def test_expression_too_long():
    with pytest.raises(CalculationError, match="too long"):
        calculate("1" * 201)


@pytest.mark.parametrize("value", [None, 5, ["1 + 1"]])
def test_non_string_expression(value):
    with pytest.raises(CalculationError, match="must be text"):
        calculate(value)