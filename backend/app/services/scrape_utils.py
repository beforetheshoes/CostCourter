"""Helpers for evaluating store scrape strategies from HTML documents."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup, Tag


def parse_strategy_selector(raw: str) -> tuple[str, str | None]:
    candidate = raw.strip()
    if not candidate:
        return "", None
    if "::attr(" in candidate:
        css, attr_fragment = candidate.split("::attr(", 1)
        return css.strip(), attr_fragment.rstrip(")").strip() or None
    if "|" in candidate:
        css, attr = candidate.split("|", 1)
        return css.strip(), attr.strip() or None
    return candidate, None


def extract_element_value(element: Tag, attr: str | None) -> str | None:
    if attr:
        value = element.get(attr)
        if isinstance(value, list):
            value = value[0] if value else None
        if value is None:
            return None
        return str(value).strip()
    text = element.get_text(strip=True)
    return text or None


def normalize_price_string(value: str) -> str | None:
    cleaned = value.strip().replace("\xa0", " ")
    if not cleaned:
        return None
    match = re.search(r"[-+]?\d[\d.,]*", cleaned)
    if match is None:
        return None
    numeric = match.group(0)
    decimal_separator: str | None = None
    if "," in numeric and "." in numeric:
        decimal_separator = "," if numeric.rfind(",") > numeric.rfind(".") else "."
    elif "," in numeric:
        decimal_separator = ","
    elif "." in numeric:
        decimal_separator = "."

    if decimal_separator == ",":
        normalized = numeric.replace(".", "").replace(",", ".")
    else:
        normalized = numeric.replace(",", "")
    normalized = normalized.strip()
    try:
        Decimal(normalized)
    except InvalidOperation:
        return None
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".") or "0"
    return normalized


def normalize_strategy_data(field: str, raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    value = raw_value.strip()
    if not value:
        return None
    if field == "price":
        return normalize_price_string(value)
    return value


def extract_with_css(
    html: str, selector: str, attr: str | None, field: str
) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select(selector):
        if not isinstance(node, Tag):
            continue
        extracted = extract_element_value(node, attr)
        normalized = normalize_strategy_data(field, extracted)
        if normalized is not None:
            return normalized
    return None


def extract_with_regex(html: str, pattern: str, field: str) -> str | None:
    try:
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
    except re.error:
        return None
    if not match:
        return None
    extracted = match.group(1)
    return normalize_strategy_data(field, extracted)


__all__ = [
    "extract_element_value",
    "extract_with_css",
    "extract_with_regex",
    "normalize_strategy_data",
    "parse_strategy_selector",
]
