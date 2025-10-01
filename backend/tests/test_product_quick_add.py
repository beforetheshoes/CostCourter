"""Coverage-focused tests for product quick add helpers."""

from __future__ import annotations

from app.models import Store
from app.services.product_quick_add import (
    _auto_detect_strategy_fields,
    _build_scrape_strategy,
    _build_store_domains,
    _coerce_price,
    _derive_store_name,
    _derive_store_slug,
    _extract_price_currency_from_ld_json,
    _merge_store_domains,
    _parse_scraper_payload,
)


def test_store_slug_and_domain_helpers_normalize_hosts() -> None:
    assert _derive_store_slug("www.Example-Shop.com") == "example-shop-com"
    assert _derive_store_name("www.Example-Shop.com") == "Example Shop"

    domains = _build_store_domains("Example-Shop.com")
    assert [entry.domain for entry in domains] == [
        "example-shop.com",
        "www.example-shop.com",
    ]

    store = Store(
        user_id=1,
        name="Example",
        slug="example",
        domains=[{"domain": "example-shop.com"}],
    )
    changed = _merge_store_domains(store, "shop.example-shop.com")
    assert changed is True
    assert any(entry["domain"] == "shop.example-shop.com" for entry in store.domains)


def test_auto_detect_strategy_fields_prefers_selectors() -> None:
    html = """
    <html>
        <head>
            <meta property=\"og:title\" content=\"Sample Gadget\" />
            <meta property=\"product:price:amount\" content=\"249.99\" />
            <meta property=\"og:image\" content=\"https://example.com/gadget.png\" />
        </head>
        <body>
            <span class=\"price\">$249.99</span>
        </body>
    </html>
    """
    detected = _auto_detect_strategy_fields(html)
    assert set(detected) == {"title", "price", "image"}
    assert detected["title"].type == "css"
    assert detected["price"].data == "249.99"
    image_data = detected["image"].data
    assert isinstance(image_data, str)
    assert image_data.endswith("gadget.png")


def test_build_scrape_strategy_uses_payload_and_fallbacks() -> None:
    metadata = {
        "title": "Widget",
        "price": "199.99",
        "raw_html": "",
    }
    strategy = _build_scrape_strategy(metadata, fallback_title="Widget Fallback")
    assert strategy["title"].data == "Widget"
    assert strategy["price"].type == "scrape_api"
    assert strategy["image"].type == "fallback"
    assert strategy["image"].data is None


def test_coerce_price_parses_decimal_strings() -> None:
    assert _coerce_price("1,299.00") == 1299.0


def test_parse_scraper_payload_combines_sources() -> None:
    payload = {
        "title": "Sample Product",
        "excerpt": "Short description",
        "lang": "en_US",
        "meta": {
            "og:image": "//cdn.example.com/image.jpg",
            "product:price:amount": "129.99",
            "product:price:currency": "usd",
        },
        "content": "<span class='price__value'>$129.99</span>",
    }
    result = _parse_scraper_payload("https://example.com/item", payload)
    assert result["title"] == "Sample Product"
    assert result["description"] == "Short description"
    image = result.get("image")
    assert isinstance(image, str)
    assert image.startswith("https://")
    assert result["price"] == "129.99"
    assert result["currency"] == "USD"
    assert result["locale"] == "en_US"


def test_extract_price_currency_from_ld_json_handles_nested_offers() -> None:
    html = """
    <html>
        <head>
            <script type=\"application/ld+json\">
            {
                \"@context\": \"https://schema.org\",
                \"offers\": {
                    \"price\": \"499.95\",
                    \"priceCurrency\": \"eur\"
                }
            }
            </script>
        </head>
    </html>
    """
    price, currency = _extract_price_currency_from_ld_json(html)
    assert price == "499.95"
    assert currency == "EUR"
