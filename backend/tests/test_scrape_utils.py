"""Unit tests for scrape utility helpers."""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.scrape_utils import (
    extract_element_value,
    extract_with_css,
    extract_with_regex,
    normalize_price_string,
    normalize_strategy_data,
    parse_strategy_selector,
)


def test_parse_strategy_selector_exposes_attribute() -> None:
    selector, attr = parse_strategy_selector("div.price::attr(data-price)")
    assert selector == "div.price"
    assert attr == "data-price"

    selector, attr = parse_strategy_selector("h1.title | text")
    assert selector == "h1.title"
    assert attr == "text"

    selector, attr = parse_strategy_selector("span.name")
    assert selector == "span.name"
    assert attr is None


def test_extract_element_value_prefers_attribute() -> None:
    html = '<span class="price" data-amount="15.99">$15.99</span>'
    element = BeautifulSoup(html, "html.parser").select_one("span.price")
    assert element is not None
    assert extract_element_value(element, "data-amount") == "15.99"
    assert extract_element_value(element, None) == "$15.99"


def test_normalize_price_string_handles_locale_variants() -> None:
    assert normalize_price_string("€ 1.234,50") == "1234.5"
    assert normalize_price_string("$19.00") == "19"
    assert normalize_price_string("invalid") is None


def test_normalize_strategy_data_returns_trimmed_value() -> None:
    assert normalize_strategy_data("title", "  Sample Product  ") == "Sample Product"
    assert normalize_strategy_data("price", "£ 1,299.00") == "1299"
    assert normalize_strategy_data("price", None) is None


def test_extract_with_css_returns_first_valid_match() -> None:
    html = """
    <main>
        <div class="product">
            <span class="price" data-amount="1099">$10.99</span>
            <img class="image" src="https://example.com/a.png" />
        </div>
    </main>
    """
    value = extract_with_css(html, "span.price", "data-amount", "price")
    assert value == "1099"

    image = extract_with_css(html, "img.image", "src", "image")
    assert image == "https://example.com/a.png"

    missing = extract_with_css(html, "span.missing", "data-amount", "price")
    assert missing is None


def test_extract_with_regex_handles_invalid_patterns() -> None:
    html = '<span class="price">Price: $42.99</span>'
    assert extract_with_regex(html, r"Price: \$(\d+\.\d+)", "price") == "42.99"
    assert extract_with_regex(html, r"Price: \\$(\\d+", "price") is None
