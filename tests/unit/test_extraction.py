"""A recorded regex asserts the value's shape; replay must not report a mismatch as success."""

from __future__ import annotations

from glovebox.replay.extraction import extracted_value


def test_should_return_the_text_unchanged_when_no_regex_was_recorded() -> None:
    assert extracted_value("1,250.75", None) == "1,250.75"


def test_should_return_the_first_capture_group_when_the_regex_has_one() -> None:
    assert extracted_value("S01 Regular Savings $1250.75", r"\$([\d,.]+)") == "1250.75"


def test_should_return_the_whole_match_when_the_regex_has_no_group() -> None:
    assert extracted_value("balance 1250.75 USD", r"[\d.]+") == "1250.75"


def test_should_return_none_when_the_recorded_shape_is_absent() -> None:
    """The failed capability read a member number where a balance was promised."""
    assert extracted_value("100234", r"S01 Regular Savings \$([\d,.]+)") is None


def test_should_refuse_to_record_an_extraction_whose_regex_misses_the_element() -> None:
    """The model anchored on 'Member No.' and wrote a balance regex; catch it at record time."""
    from types import SimpleNamespace

    import pytest

    from glovebox.agent.loop import DiscoveryAgent

    agent = object.__new__(DiscoveryAgent)
    agent._el = lambda ref: SimpleNamespace(text="100234", value=None)  # type: ignore[method-assign,assignment,return-value]
    with pytest.raises(ValueError, match="does not match"):
        DiscoveryAgent._t_extract(
            agent, "e1", "savings_balance", "balance", "string", r"S01 Regular Savings \$([\d,.]+)"
        )
