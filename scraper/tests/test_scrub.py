from app.main import scrub_response


def test_scrub_response_trims_fields() -> None:
    raw = {
        "title": "",
        "excerpt": "  ",
        "lang": "",
        "meta": {"foo": "bar"},
        "content": "<html></html>",
        "fullContent": "<html></html>",
        "source": "https://example.com",
    }
    cleaned = scrub_response(raw, full_content=False)
    assert cleaned["title"] == ""
    assert cleaned["excerpt"] == ""
    assert "lang" not in cleaned
    assert cleaned["fullContent"] is None
    assert cleaned["content"] == "<html></html>"


def test_scrub_response_keeps_lang() -> None:
    raw = {
        "title": "Product",
        "excerpt": "Great product",
        "lang": "en-US",
        "meta": {},
        "content": "<html></html>",
        "fullContent": "<html></html>",
        "source": "https://example.com",
    }
    cleaned = scrub_response(raw, full_content=True)
    assert cleaned["lang"] == "en-US"
    assert cleaned["fullContent"] == "<html></html>"
