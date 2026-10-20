import pytest

from arl.llm.pricing import Price, cost_usd, load_models, price_for
from arl.llm.types import Usage

PRICE = Price(input=0.10, cached_input=0.01, output=0.50)


def test_cost_of_one_million_each():
    assert cost_usd(Usage(input_tokens=1_000_000, output_tokens=1_000_000), PRICE) == (
        pytest.approx(0.60)
    )


def test_cached_tokens_are_billed_at_the_cached_rate():
    usage = Usage(input_tokens=1000, cached_input_tokens=800, output_tokens=0)
    assert cost_usd(usage, PRICE) == pytest.approx((200 * 0.10 + 800 * 0.01) / 1_000_000)


def test_reasoning_tokens_are_not_billed_twice():
    with_reasoning = Usage(input_tokens=0, output_tokens=500, reasoning_tokens=300)
    assert cost_usd(with_reasoning, PRICE) == pytest.approx(500 * 0.50 / 1_000_000)


def test_zero_usage_costs_nothing():
    assert cost_usd(Usage(), PRICE) == 0


def test_usage_adds_field_by_field():
    assert Usage(10, 2, 5, 1) + Usage(1, 1, 1, 1) == Usage(11, 3, 6, 2)


def test_default_model_has_a_price():
    config = load_models()
    assert price_for(config["default"]).input > 0


def test_unknown_model_is_an_error():
    with pytest.raises(KeyError):
        price_for("no-such-model")


def test_cache_writes_are_billed_at_the_write_rate():
    price = Price(input=0.10, cached_input=0.01, output=0.50, cache_write=0.125)
    usage = Usage(input_tokens=1000, cached_input_tokens=600, cache_write_tokens=300)
    assert cost_usd(usage, price) == pytest.approx((100 * 0.10 + 600 * 0.01 + 300 * 0.125) / 1e6)


def test_without_a_write_price_cache_writes_cost_the_input_price():
    usage = Usage(input_tokens=1000, cache_write_tokens=1000)
    assert cost_usd(usage, PRICE) == pytest.approx(1000 * 0.10 / 1e6)
