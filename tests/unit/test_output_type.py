"""A balance the caller has to parse out of "$1250.75" is a weaker contract than a number.

The live model declared savings_balance as a string. It is right that the model chooses, and
right that an obviously-wrong choice is corrected from what the run actually saw.
"""

from __future__ import annotations

from glovebox.agent.output_type import inferred_output_type


def test_should_read_a_currency_amount_as_a_number() -> None:
    assert inferred_output_type("string", "$1250.75") == "number"


def test_should_read_a_thousands_separated_amount_as_a_number() -> None:
    assert inferred_output_type("string", "18,930.00") == "number"


def test_should_read_a_plain_two_decimal_value_as_a_number() -> None:
    assert inferred_output_type("string", "0.00") == "number"


def test_should_leave_an_identifier_alone_even_though_it_is_all_digits() -> None:
    """A member number is not a quantity: typing it numeric drops leading zeros."""
    assert inferred_output_type("string", "100234") == "string"
    assert inferred_output_type("string", "007") == "string"


def test_should_leave_ordinary_text_alone() -> None:
    for value in ("Doe, Jane", "Active", "S01 Regular Savings", ""):
        assert inferred_output_type("string", value) == "string", value


def test_should_not_override_a_type_the_model_chose_deliberately() -> None:
    """Only a default "string" is second-guessed; an explicit choice is the model's to make."""
    assert inferred_output_type("integer", "1250.75") == "integer"
    assert inferred_output_type("number", "Doe, Jane") == "number"
    assert inferred_output_type("boolean", "$1.00") == "boolean"


def test_should_handle_a_negative_or_bracketed_amount() -> None:
    assert inferred_output_type("string", "-$40.00") == "number"
    assert inferred_output_type("string", "($40.00)") == "number"


def test_should_type_from_the_captured_group_not_the_surrounding_text() -> None:
    """A regex exists to strip the wrapper; the caller receives what it captured."""
    from glovebox.replay.extraction import extracted_value

    text = "S01 Regular Savings $1250.75"
    captured = extracted_value(text, r"\$([\d,.]+)")
    assert captured == "1250.75"
    assert inferred_output_type("string", captured) == "number"
    assert inferred_output_type("string", text) == "string", "the whole row is not an amount"
